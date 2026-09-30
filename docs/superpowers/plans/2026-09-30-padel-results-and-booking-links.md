# Compact Padel Results and Booking Links Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show one compact result per exact club/time window, merge same-time court options, and link to a verified booking page for the selected day.

**Architecture:** Keep availability snapshots at court-slot granularity in SQLite and in `GET /api/availability`; group matching rows in the browser after filters are applied. Validate date navigation using only each provider's public visible controls, then use a small client-side link builder for confirmed date URLs and preserve the existing verified URL for platforms without one.

**Tech Stack:** Python 3.12, Flask/Jinja, native JavaScript and CSS, existing pytest/Playwright browser tests, Docker Compose on CT103.

## Global Constraints

- Group only records with the same location, exact start, exact end, snapshot state, and slot state; different durations and availability states remain separate.
- Use `Europe/Zurich` for displayed days and date parameters; apply existing date/time filters before grouping.
- Preserve the individual `AvailabilitySlot` rows in SQLite and the read-only API; aggregation is presentation-only.
- Validate date links through public visible date controls. Never click booking slots, log in, book, or use private APIs.
- A date-level link is sufficient; do not invent a court/time query parameter. Use a direct date URL only after verifying that provider's public route. Otherwise retain its existing booking URL.
- Keep **À vérifier**, **Données anciennes**, no-data, unavailable, and out-of-window states distinct and textually labeled.
- Preserve accessible native controls, keyboard focus, `target="_blank"`, and `rel="noopener noreferrer"`.
- Keep the existing Minimal Swiss direction; add no client framework, map, or runtime dependency.
- Before production deployment, preserve the database at `/var/lib/padel-availability/catalog.sqlite3`, verify the initial refresh and public route, and update the CT103/NPM infra docs without staging unrelated existing infra changes.

---

## File map

**Modify:**
- `src/padel_availability/static/app.js` — post-filter grouping, court labels/counts, summary, and verified date-link builder.
- `src/padel_availability/static/app.css` — compact row/card layout for desktop and mobile.
- `tests/test_web_ui.py` — grouped slot, date link, status separation, and responsive browser assertions.
- `README.md` — explain grouped result counts and which booking links preselect a date.
- `docs/superpowers/specs/2026-09-30-padel-results-and-booking-links-design.md` — record verified link behavior by source family.
- `/home/agentops/workspace/infra/containers/ct103-services.md` — verify the deployed revision and UI update after rollout.
- `/home/agentops/workspace/infra/03-network-security.md` — keep the already-created public NPM host entry current after verifying it live.

## Task 1: Group duplicate court slots in the UI

**Files:** `src/padel_availability/static/app.js`, `tests/test_web_ui.py`

**Contract:** A presentation group contains `location`, `snapshot_status`, `slot.status`, exact `starts_at`, exact `ends_at`, unique non-empty court labels, and an unidentified-entry count. Group after applying club/cover/date/time filters. Show known court names/counts separately from neutral source-entry counts; never call unlabeled rows courts.

- [x] **Step 1: Add fixture slots for duplicate and different-duration cases**

In `tests/test_web_ui.py`, give the same configured outdoor club two `available` rows with the same start/end but different court labels, plus one row with the same start and a different end. Also add two identical-window `unknown` rows, two stale rows in a separate location, and two identical-window rows with no court labels.

Assert the requested display behavior:

```python
assert page.locator("#available-results .slot-card[data-location-id='collonge-bellerive']").count() == 2
assert page.locator("#available-results").get_by_text("2 terrains libres").count() == 1
assert page.locator("#available-results").get_by_text("Court extérieur 1 · Court extérieur 2").is_visible()
assert page.locator("#unknown-results .slot-card[data-location-id='collonge-bellerive']").count() == 1
assert page.locator("#stale-results .slot-card[data-location-id='csu-champel']").count() == 1
assert page.locator("#available-results").get_by_text("2 possibilités").count() == 1
assert page.locator("#available-results").get_by_text(
    "1 terrain identifié · 1 possibilité non identifiée"
).is_visible()
```

- [x] **Step 2: Run the UI test and confirm it fails on duplicate cards**

Run `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_web_ui.py::test_evening_search_keeps_statuses_and_local_club_selection`.
Expected: the fixture's two identical windows currently render as two cards.

- [x] **Step 3: Group filtered rows before rendering**

Add a small `groupSlots(rows)` helper in `app.js`. Use a `Map` keyed by
`JSON.stringify([location_id, snapshot_status, slot.status, starts_at, ends_at])`.
Append source rows to their group and collect unique non-empty `court_label`
values. Keep the count of source entries for rows with no labels. Call this after
`matchesFilters` so grouping does not change filter results.

```javascript
function groupSlots(rows) {
  const groups = new Map();
  for (const row of rows) {
    const key = JSON.stringify([
      row.location.location_id,
      row.location.snapshot_status,
      row.slot.status,
      row.slot.starts_at,
      row.slot.ends_at,
    ]);
    const group = groups.get(key) || {
      location: row.location,
      slot: row.slot,
      slots: [],
      courtLabels: new Set(),
      unidentifiedCount: 0,
    };
    group.slots.push(row.slot);
    if (row.slot.court_label) group.courtLabels.add(row.slot.court_label);
    else group.unidentifiedCount += 1;
    groups.set(key, group);
  }
  return [...groups.values()].map((group) => ({
    ...group,
    courtLabels: [...new Set(group.slots.map((slot) => slot.court_label).filter(Boolean))],
  }));
}
```

- [x] **Step 4: Render one card per group and preserve section semantics**

Update `createSlotCard` to accept a group, render the common time range and
duration once, display the unique court labels and a `N terrains libres` label
when every source row has a court label. Use `N possibilités` when no rows have
labels; for mixed groups, show the unique labeled courts and the unlabeled
possibility count separately. Keep stale/unknown groups in their separate result
arrays.

- [x] **Step 5: Count grouped windows and court-time opportunities**

Set `#available-count` to the number of grouped available windows. Set
`#result-summary` to the grouped-window total plus the sum of each group's
available-court count (or neutral source-entry count where labels are absent);
do not count every raw row as a separate time window.

- [x] **Step 6: Run the targeted browser test**

Run the Step 2 test again. Expected: duplicate exact windows collapse to one,
different end times stay separate, and stale/unknown cards remain segregated.

## Task 2: Validate and implement date-aware booking URLs

**Files:** `src/padel_availability/static/app.js`, `tests/test_web_ui.py`,
`docs/superpowers/specs/2026-09-30-padel-results-and-booking-links-design.md`

- [x] **Step 1: Record public date-link behavior for each configured booking family**

Use the checked-in public booking URLs and a sample date of `2026-10-01`. Probe
`date=2026-10-01` and verify the visible selected date using each connector's
visible DOM shape. Where the query is ignored and a public date control exists,
use only that date control and record the URL before/after; do not click an
available court or any booking/login/payment control. Record Playtomic `.com`,
legacy Playtomic `.io`, AIRPAD, Everness, Padel First, Matchpoint, and Plugin.ch
in the spec's validation table. The current probe confirms direct-day URLs for
Playtomic `.com`, Playtomic `.io`, and Everness; the other four remain on their
existing booking URLs unless a safe visible route is verified.

- [x] **Step 2: Add failing tests for the confirmed date URL and fallback**

In the browser fixture, include: Playtomic `.com` URL
`https://playtomic.com/fr/clubs/padel-station1`; legacy `.io` URL
`https://playtomic.io/vaudoise-arena/53b5aaf2-7449-4691-96f8-a582ce37144b?q=PADEL~2025-03-17~~~`;
Everness URL `https://padel.everness.ch/`; and an unverified Matchpoint URL
`https://padelgeneva.matchpoint.com.es/Booking/Grid.aspx?id=9`. For slots whose
Europe/Zurich day is `2026-10-01`, assert the generated `date` parameter on the
Playtomic and Everness links, preserve the `.io` `q` value, and assert the
Matchpoint link remains unchanged.

- [x] **Step 3: Run the focused link test and confirm the date query is missing**

Run `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_web_ui.py::test_booking_links_open_the_verified_local_date`. Expected:
current code returns the base booking URL without a `date` query.

- [x] **Step 4: Implement the minimal per-platform URL builder**

Add `bookingUrl(location, slot)` in `app.js`. Convert `slot.starts_at` to its
Europe/Zurich date. For `playtomic.com`, `playtomic.io`, and `padel.everness.ch`,
construct a `URL` and call `searchParams.set("date", localDay)` so existing
query components are preserved and duplicate `date` keys are not created.
Return `location.booking_url` unchanged for AIRPAD, Matchpoint, Padel First, and
Plugin.ch; their sample-date probes did not verify a direct-day URL.

```javascript
function bookingUrl(location, slot) {
  const url = new URL(location.booking_url);
  const localDay = localDate(slot.starts_at);
  if (["playtomic.com", "playtomic.io", "padel.everness.ch"].includes(url.hostname)) {
    url.searchParams.set("date", localDay);
  }
  return url.href;
}
```

- [x] **Step 5: Run the link and UI tests**

Run `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_web_ui.py tests/test_web.py`.
Expected: Playtomic opens the selected local day; unverified provider URLs remain
unchanged; booking links still open safely in a new tab.

## Task 3: Replace tall repeated cards with compact chronological rows

**Files:** `src/padel_availability/static/app.js`, `src/padel_availability/static/app.css`, `tests/test_web_ui.py`

- [x] **Step 1: Add browser assertions for the compact row structure**

For one grouped card, assert the time range, club/municipality, duration,
coverage, court count/labels, update time, and reservation link remain visible.
Assert the card is one row at a 1440px viewport and stacks at 375px without
horizontal overflow; keyboard focus and 44px booking targets remain.

- [x] **Step 2: Run the layout assertions before changing CSS**

Run the focused browser test. Expected: the current tall two-column result card
does not satisfy the compact row/card class structure.

- [x] **Step 3: Apply the compact Swiss-style layout**

Update the slot-card markup and existing CSS tokens only: desktop rows place the
time range and venue first, court/count and status metadata next, and one
reservation action at the right. On mobile, stack these elements and keep the
action below the details. Remove repeated per-court layout because Task 1 now
renders one group card.

The result row's content order is:

```html
<article class="slot-row">
  <time class="slot-time">16:00 à 18:00</time>
  <div class="slot-venue">Padel Parc Préverenges · Préverenges</div>
  <div class="slot-courts">4 terrains libres · Court 1 · Court 2 · Court 3 · Court 4</div>
  <div class="slot-meta">Intérieur · 120 min · Mis à jour à 15:32</div>
  <a class="booking-link">Réserver</a>
</article>
```

- [x] **Step 4: Re-run the browser interaction and responsive checks**

Run `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_web_ui.py` and
`PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_web.py`. Expected: the
evening range still includes a 21:30 start with its full end, localStorage
selection persists, and all viewport/keyboard assertions pass.

## Task 4: Document, publish, and deploy the UI revision

**Files:** `README.md`, plan/spec, CT103 Compose deployment, infra docs.

- [x] **Step 1: Update the user guide**

Document one card per exact club/time window, how court counts/labels work,
grouped summary semantics, direct-date links by validated provider, and the
existing-link fallback when no safe date route exists.

- [x] **Step 2: Run quality checks**

Run `PYTHONPATH=src .venv/bin/python -m pytest -q`, `.venv/bin/ruff check .`,
`.venv/bin/ruff format --check src tests`, and `.venv/bin/pyright`. Expected: all
tests pass with no lint/type errors.

- [ ] **Step 3: Commit, merge, and publish the tested revision**

Inspect status, staged diff, and recent commits. Commit only the UI/URL change,
fast-forward `master`, then push the public GitHub URL without force.

- [ ] **Step 4: Pull and redeploy on CT103**

Show the server write command first; `git pull --ff-only` in
`/opt/padel-availability`, then run
`docker compose -f deploy/ct103/compose.yaml up -d --build`. Verify web health,
worker health, and the persistent database path.

- [ ] **Step 5: Verify production behavior and update infra docs**

Confirm the app returns grouped results at the public URL, check a Playtomic
date link from a card, verify grouped court counts and distinct durations, and
confirm the refresh status is no longer stuck. Update and publish only the
intended CT103/NPM infra documentation files; leave all pre-existing infra
changes untouched.
