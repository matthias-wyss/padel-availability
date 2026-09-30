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

**Contract:** A presentation group contains `location`, `snapshot_status`, `slot.status`, exact `starts_at`, exact `ends_at`, unique non-empty court labels, and the number of source entries. Group after applying club/cover/date/time filters. Do not claim a court count when labels are absent; show the neutral source-entry count instead.

- [ ] **Step 1: Add fixture slots for duplicate and different-duration cases**

In `tests/test_web_ui.py`, give the same configured outdoor club two `available` rows with the same start/end but different court labels, plus one row with the same start and a different end. Also add two identical-window `unknown` rows, two stale rows in a separate location, and two identical-window rows with no court labels.

Assert the requested display behavior:

```python
assert page.locator("#available-results .slot-card[data-location-id='collonge-bellerive']").count() == 2
assert page.locator("#available-results").get_by_text("2 terrains libres").count() == 1
assert page.locator("#available-results").get_by_text("Court extérieur 1 · Court extérieur 2").is_visible()
assert page.locator("#unknown-results .slot-card[data-location-id='collonge-bellerive']").count() == 1
assert page.locator("#stale-results .slot-card[data-location-id='csu-champel']").count() == 1
assert page.locator("#available-results").get_by_text("2 possibilités").count() == 1
```

- [ ] **Step 2: Run the UI test and confirm it fails on duplicate cards**

Run `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_web_ui.py::test_evening_search_keeps_statuses_and_local_club_selection`.
Expected: the fixture's two identical windows currently render as two cards.

- [ ] **Step 3: Group filtered rows before rendering**

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
    const group = groups.get(key) || { location: row.location, slot: row.slot, slots: [] };
    group.slots.push(row.slot);
    groups.set(key, group);
  }
  return [...groups.values()].map((group) => ({
    ...group,
    courtLabels: [...new Set(group.slots.map((slot) => slot.court_label).filter(Boolean))],
  }));
}
```

- [ ] **Step 4: Render one card per group and preserve section semantics**

Update `createSlotCard` to accept a group, render the common time range and
duration once, display the unique court labels and a `N terrains libres` label
when every source row has a court label, and use `N possibilités` when labels are
missing. Keep stale/unknown groups in their separate result arrays.

- [ ] **Step 5: Count grouped windows and court-time opportunities**

Set `#available-count` to the number of grouped available windows. Set
`#result-summary` to the grouped-window total plus the sum of each group's
available-court count (or neutral source-entry count where labels are absent);
do not count every raw row as a separate time window.

- [ ] **Step 6: Run the targeted browser test**

Run the Step 2 test again. Expected: duplicate exact windows collapse to one,
different end times stay separate, and stale/unknown cards remain segregated.

## Task 2: Validate and implement date-aware booking URLs

**Files:** `src/padel_availability/static/app.js`, `tests/test_web_ui.py`,
`docs/superpowers/specs/2026-09-30-padel-results-and-booking-links-design.md`

- [ ] **Step 1: Record public date-link behavior for each configured booking family**

Use the existing checked-in booking URLs and the configured browser connector
patterns to open each public booking page. For a sample date in the supported
window, use only its visible date control and record the page URL before and
after the date changes. Cover Playtomic `.com`, legacy Playtomic `.io`, AIRPAD,
Everness, Padel First, Matchpoint, and Plugin.ch. Do not click an available slot
or any booking/login/payment control. Record whether a stable direct-day URL is
available; if it is not, note that the existing booking URL remains the fallback.

- [ ] **Step 2: Add failing tests for the confirmed date URL and fallback**

In the browser fixture, give a Playtomic `.com` location the public URL
`https://playtomic.com/fr/clubs/padel-station1` and a slot on a deterministic
Europe/Zurich date. Assert the **Réserver** link is
`https://playtomic.com/fr/clubs/padel-station1?date=2026-10-01`. Give another
provider an existing query string; assert its link stays byte-for-byte unchanged
unless Step 1 validates its date format.

- [ ] **Step 3: Run the focused link test and confirm the date query is missing**

Run `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_web_ui.py::test_booking_links_open_the_verified_local_date`. Expected:
current code returns the base booking URL without a `date` query.

- [ ] **Step 4: Implement the minimal per-platform URL builder**

Add `bookingUrl(location, slot)` in `app.js`. Convert `slot.starts_at` to its
Europe/Zurich date. For validated Playtomic `.com` club URLs, construct a `URL`
and call `searchParams.set("date", localDay)` so existing query components are
preserved and a duplicate `date` key is not created. Add other source-family
rules only when Step 1 verified them. Return `location.booking_url` unchanged
for any unsupported or unverified route.

```javascript
function bookingUrl(location, slot) {
  const url = new URL(location.booking_url);
  const localDay = localDate(slot.starts_at);
  if (url.hostname === "playtomic.com") url.searchParams.set("date", localDay);
  // Add only provider rules recorded by Step 1; otherwise keep the verified URL.
  return url.href;
}
```

- [ ] **Step 5: Run the link and UI tests**

Run `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_web_ui.py tests/test_web.py`.
Expected: Playtomic opens the selected local day; unverified provider URLs remain
unchanged; booking links still open safely in a new tab.

## Task 3: Replace tall repeated cards with compact chronological rows

**Files:** `src/padel_availability/static/app.js`, `src/padel_availability/static/app.css`, `tests/test_web_ui.py`

- [ ] **Step 1: Add browser assertions for the compact row structure**

For one grouped card, assert the time range, club/municipality, duration,
coverage, court count/labels, update time, and reservation link remain visible.
Assert the card is one row at a 1440px viewport and stacks at 375px without
horizontal overflow; keyboard focus and 44px booking targets remain.

- [ ] **Step 2: Run the layout assertions before changing CSS**

Run the focused browser test. Expected: the current tall two-column result card
does not satisfy the compact row/card class structure.

- [ ] **Step 3: Apply the compact Swiss-style layout**

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

- [ ] **Step 4: Re-run the browser interaction and responsive checks**

Run `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_web_ui.py` and
`PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_web.py`. Expected: the
evening range still includes a 21:30 start with its full end, localStorage
selection persists, and all viewport/keyboard assertions pass.

## Task 4: Document, publish, and deploy the UI revision

**Files:** `README.md`, plan/spec, CT103 Compose deployment, infra docs.

- [ ] **Step 1: Update the user guide**

Document one card per exact club/time window, how court counts/labels work,
grouped summary semantics, direct-date links by validated provider, and the
existing-link fallback when no safe date route exists.

- [ ] **Step 2: Run quality checks**

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
