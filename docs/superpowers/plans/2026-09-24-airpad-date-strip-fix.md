# AIRPAD Live Doinsport DOM Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore live AIRPAD collection against the current public Doinsport date-strip and slot-option markup.

**Architecture:** Preserve the existing public date-picker click using its full visible accessible name and preserve ISO extraction when available. Otherwise, verify the active visible date-strip label against the requested date. Extract one observation per visible duration offer nested inside a `.slot-container`; treat explicit `.empty_playground` rows as empty. Read only the public visible DOM.

**Tech Stack:** Python 3.12+, Playwright, pytest, Ruff, Pyright, SQLite.

## Global Constraints

- Keep navigation and extraction limited to visible public DOM, visible attributes, and accessibility labels.
- Do not use private endpoints, hidden application state, network interception, login, or booking actions.
- Keep the existing ISO date extraction when a visible `aria-label` provides one.
- After clicking the visible full-date picker entry, accept the selected date only when either the existing ISO value equals the requested date or the normalized active label matches the requested date's English weekday, day, and month.
- The full-year date picker label is the year-bearing selection; use the requested full ISO date only after the active strip confirms it.
- Treat a matching active date-strip label as visible date-transition evidence. If the requested date was already active, accept an unchanged grid without waiting for an artificial refresh. If changing dates, an unchanged previous date label remains stale and must not be accepted.
- Allow generic `Sign in` and `Login or register` navigation links in the page chrome. Continue to reject explicit CAPTCHA, access-denied, sign-in-required, or visible password/dialog challenges; never interact with login controls.
- For the current booking grid, emit one available observation per visible duration option inside each `.slot-container`, using its visible start time, court title, and `ion-label` duration. Do not click offers or persist prices.
- Treat a row with visible `.empty_playground` content and no offers as an explicit empty row. A row with neither a valid offer nor an explicit empty-state marker remains a bounded error.
- Keep source error and stale snapshot behavior unchanged.
- No dependency, CLI, manifest, or persistence schema changes.
- No automatic collection scheduling or booking behavior; do not change Playtomic, Everness, or Padel First semantics.
- Leave project edits uncommitted unless the user explicitly requests integration.

---

## File Map

- Modify `src/padel_availability/connectors/airpad_browser.py`: expose the active visible date label and reconcile it with the requested date after a visible date-picker click.
- Modify `src/padel_availability/connectors/airpad_browser.py`: also read the current visible `.slot-container`/duration-option structure and distinguish generic login navigation from explicit challenges.
- Modify `tests/test_airpad_browser.py`: cover the no-`aria-label` date strip, date matching, duration offers, empty rows, login navigation, and authentication errors.
- Create `tests/fixtures/airpad/dom/booking-date-strip-no-aria.html`: sanitized visible calendar/date-strip HTML with no scripts or network data.
- Create `tests/fixtures/airpad/dom/booking-slot-containers.html`: sanitized visible slot containers and nested duration options, no scripts or network data.
- Create `tests/fixtures/airpad/dom/booking-auth.html`: a visible authentication dialog fixture, no scripts or network data.
- No other connector, collector, CLI, manifest, dependency, or schema files should change.

## Task 1: Capture the Visible Active Date Label

**Files:** `tests/fixtures/airpad/dom/booking-date-strip-no-aria.html`, `tests/test_airpad_browser.py`, `src/padel_availability/connectors/airpad_browser.py`.

**Interfaces:**
- `_AIRPAD_VISIBLE_DOM_SCRIPT` continues to return `date` and adds `active_date_label`, the text of the visible selected `.date-slot`.
- `parse_airpad_dom()` continues to require a resolved ISO date; the connector resolves the requested date only after checking the label.

- [ ] **Step 1: Add a sanitized live-shape fixture.**

Create `tests/fixtures/airpad/dom/booking-date-strip-no-aria.html` with only visible `.calendar-block`, `.date-slot` buttons, one `.date-slot.active`, and a minimal visible `.playground-slot`. The selected button text is `Thu 24 Sep`; none of the date buttons has `aria-label`, `data-date`, or inline script content.

```html
<main class="calendar-block">
  <nav>
    <button class="date-slot">Wed 23 Sep</button>
    <button class="date-slot active">Thu 24 Sep</button>
    <button class="date-slot after-active">Fri 25 Sep</button>
  </nav>
  <div class="playground-slot">
    <div class="section-title">TERRAIN 1 - LA PRAILLE</div>
    <div class="info-playground">No slot available</div>
  </div>
</main>
```

- [ ] **Step 2: Add a failing visible-DOM extraction test.**

In `tests/test_airpad_browser.py`, load the fixture through `_browser_payload()` and assert the visible booking view is found, the legacy `date` is empty, and `active_date_label == "Thu 24 Sep"`.

```python
def test_airpad_visible_script_extracts_active_date_without_aria_label(
    fixture_browser: Any,
) -> None:
    payload = _browser_payload(fixture_browser, "booking-date-strip-no-aria")

    assert payload["view"] == "booking"
    assert payload["date"] == ""
    assert payload["active_date_label"] == "Thu 24 Sep"
```

- [ ] **Step 3: Run the test and verify the expected failure.**

Run:

```bash
uv run --group browser --group dev pytest tests/test_airpad_browser.py::test_airpad_visible_script_extracts_active_date_without_aria_label -q
```

Expected: the assertion fails because the payload currently omits `active_date_label`.

- [ ] **Step 4: Return the active date-strip text from the visible script.**

In `_AIRPAD_VISIBLE_DOM_SCRIPT`, derive the label from the already-selected visible date element with the existing `text()` helper and return it as `active_date_label`. Keep `dateFromLabel()` and the existing ISO `date` behavior unchanged.

```javascript
const activeDateLabel = activeDate ? text(activeDate) : '';
```

- [ ] **Step 5: Run focused extraction tests.**

Run:

```bash
uv run --group browser --group dev pytest tests/test_airpad_browser.py -q
```

Expected: all existing AIRPAD browser tests plus the new fixture test pass.

## Task 2: Match the Active Label to the Requested Date

**Files:** `src/padel_availability/connectors/airpad_browser.py`, `tests/test_airpad_browser.py`.

**Interfaces:**
- Add `_airpad_active_date_matches(label: object, requested_date: date) -> bool`.
- Extend `_airpad_payload_date(payload: object, requested_date: date | None = None) -> str | None` to use a visible label only when it matches the supplied requested date.
- `_select_airpad_date()` continues to click the visible picker control and exact full-date `button.days-btn[aria-label="..."]` before applying the strip fallback.

- [ ] **Step 1: Add failing connector tests for the no-aria date strip.**

Use the public `AirpadBrowserConnector` with `_FakeAirpadFrame` payloads whose `date` is empty and whose `active_date_label` is visible text. Test `Thu\n24\nSep` for `date(2026, 9, 24)`, `Fri 1 Jan` for `date(2027, 1, 1)`, and a mismatched weekday/day that must time out. Include two consecutive dates with identical empty grids but distinct active labels; the changed visible label must count as date-transition evidence. Do not import the private matcher into the test.

- [ ] **Step 2: Run the matching tests and verify they fail.**

Run:

```bash
uv run pytest tests/test_airpad_browser.py -k active_date_strip -q
```

Expected: the new connector tests fail with `timed out waiting for the requested AIRPAD date` because the payload has no ISO `date`.

- [ ] **Step 3: Implement the small visible-label matcher.**

Add `_AIRPAD_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")` beside `_AIRPAD_MONTHS`. Normalize whitespace, require an English weekday/day/month label, and compare all three tokens against that fixed weekday tuple, the requested day number, and the first three letters of the requested English month. Return `False` for malformed values.

```python
def _airpad_active_date_matches(label: object, requested_date: date) -> bool:
    if not isinstance(label, str):
        return False
    parts = " ".join(label.split()).replace(",", "").split()
    expected = (
        _AIRPAD_WEEKDAYS[requested_date.weekday()],
        str(requested_date.day),
        _AIRPAD_MONTHS[requested_date.month - 1][:3],
    )
    return len(parts) == 3 and tuple(part.casefold() for part in parts) == tuple(
        part.casefold() for part in expected
    )
```

- [ ] **Step 4: Use visible date confirmation in date waits.**

Let `_airpad_payload_date(payload, requested_date)` return the existing ISO `date` when present; otherwise return `requested_date.isoformat()` only if `active_date_label` matches. In `_select_airpad_date()`, use this same resolver for `previous_date` so an already-active requested day does not require a fake refresh. In `_wait_for_airpad_date()`, resolve the current payload the same way and treat a matching visible active label as date-transition evidence; keep the existing loading and grid comparison checks for stale content whose active label does not match.

- [ ] **Step 5: Add a connector regression for the current AIRPAD date strip.**

Use the fake frame to return `date: ""` and active labels for the selected days, request September 24–25, 2026, and assert collection succeeds with both resolved ISO dates even when both grids are empty. Add a case where the active label remains on the previous day and assert it is not accepted as the requested date.

- [ ] **Step 6: Run targeted tests and static checks.**

Run:

```bash
uv run --group browser --group dev pytest tests/test_airpad_browser.py -q
uv run ruff check src/padel_availability/connectors/airpad_browser.py tests/test_airpad_browser.py
uv run pyright src/padel_availability/connectors/airpad_browser.py tests/test_airpad_browser.py
```

Expected: tests pass; Ruff and Pyright report zero findings for changed files.

## Task 3: Parse the Current Slot-Container Structure

**Files:** `src/padel_availability/connectors/airpad_browser.py`, `tests/test_airpad_browser.py`, `tests/fixtures/airpad/dom/booking-slot-containers.html`, `tests/fixtures/airpad/dom/booking-auth.html`.

**Interfaces:**
- `_AIRPAD_VISIBLE_DOM_SCRIPT` returns one payload row per visible `.playground-slot`, with `court`, `slots`, and an explicit `empty_playground` state.
- Each extracted offer has `external_id`, `court`, `time`, `duration`, `class`, and `disabled`, compatible with `_parse_airpad_slot()`.
- A visible `ion-item` duration option produces one observation; no price is stored and no option is clicked.

- [ ] **Step 1: Add sanitized fixtures for current live markup.**

Create `booking-slot-containers.html` with a visible `.calendar-block`, a selected `.date-slot` with `aria-label="September 24, 2026"`, generic `Sign in`/`Login or register` navigation text, one court row containing `.slot-container > .start-time .time` and two `.slot-price-list ion-item` duration options (`60 min` and `120 min`), plus a second court row with `.empty_playground`. Create `booking-auth.html` with the same booking shell and a visible password field inside a visible authentication dialog.

- [ ] **Step 2: Add failing DOM and parser assertions.**

Use `_browser_payload()` to parse `booking-slot-containers.html`; assert its payload contains two offers, their start time is `09:00`, durations are `60 min` and `120 min`, the empty row identifies `Court 2`, and generic login navigation remains visible but does not block `parse_airpad_dom()`. Assert the parser yields two `available` observations with ends at 10:00 and 11:00. Load `booking-auth.html` and assert the script reports `authentication_visible` and the parser raises a bounded blocked-page error.

- [ ] **Step 3: Run the new tests and verify the expected failures.**

Run:

```bash
uv run --group browser --group dev pytest tests/test_airpad_browser.py -k "slot_container or authentication_dialog" -q
```

Expected: the slot payload has no extracted offers, generic login text is misclassified as blocked, and the authentication visibility field is absent.

- [ ] **Step 4: Extract each visible duration offer without interacting with it.**

In `_AIRPAD_VISIBLE_DOM_SCRIPT`, keep the existing `.info-playground > *` path for old fixtures. When a row contains `.slot-container`, read the visible `.start-time .time` and each visible `.slot-price-list ion-item`'s `ion-label`; emit one payload slot per duration option. Use the option's visible `disabled`/`aria-disabled` state and explicit unavailable classes; otherwise mark the visible offer `available`. Use only the option's visible slot ID if present, otherwise leave `external_id` null for the existing deterministic hash.

- [ ] **Step 5: Require each visible court row and time range to be complete.**

Keep a row's court label from visible `.section-title`. A row with one or more valid duration offers is populated; a row with a visible `.empty_playground` and no offers is explicitly empty; a row with neither is invalid. Set `empty_grid` only when all visible rows are valid and explicitly empty. In `parse_airpad_dom()`, reject `invalid_rows` before returning any observations so one malformed court cannot be silently dropped. After a time-range label changes, keep polling until the visible rows satisfy the same complete-grid rule; do not parse a label-only intermediate state.

- [ ] **Step 6: Allow public login navigation while rejecting explicit challenges.**

Remove generic `sign in` and `login` substrings from `_AIRPAD_BLOCK_MARKERS`. Retain CAPTCHA, access-denied, sign-in-required, and authentication-required phrases. Add `authentication_visible` from visible password inputs and visible authentication dialogs, and make `parse_airpad_dom()` reject that flag. Do not interact with or submit authentication controls.

- [ ] **Step 7: Run all AIRPAD browser tests and targeted static checks.**

Run:

```bash
uv run --group browser --group dev pytest tests/test_airpad_browser.py -q
uv run ruff check src/padel_availability/connectors/airpad_browser.py tests/test_airpad_browser.py
uv run pyright src/padel_availability/connectors/airpad_browser.py tests/test_airpad_browser.py
```

Expected: AIRPAD browser tests pass and Ruff/Pyright report zero findings.

## Task 4: Verify All Sources Live and Run the Full Suite

**Files:** no further source changes; use a new disposable SQLite database under `/tmp/opencode`.

- [ ] **Step 1: Build a fresh disposable catalog.**

Run this block from the project root. It generates a unique database path and refuses to initialize an existing file:

```bash
DB="/tmp/opencode/all-sources-airpad-$(date +%Y%m%d%H%M%S).sqlite3"
test ! -e "$DB"
uv run padel-availability init-db --database "$DB"
uv run padel-availability import-candidates --database "$DB" --input data/candidates.json
uv run padel-availability build-catalog --database "$DB" --candidates data/candidates.json --verified data/verified_locations.json --run-id airpad-date-strip-smoke
```

- [ ] **Step 2: Run the two-day AIRPAD collection without runtime overrides.**

Run:

```bash
env -u LD_LIBRARY_PATH -u FONTCONFIG_FILE uv run padel-availability collect-airpad --database "$DB" --sources data/airpad_sources.json --days 2
```

Expected: one persisted outcome per AIRPAD site; each is either `success` with its observed slots or an explicit source error if the public portal itself is currently blocked.

- [ ] **Step 3: Run and inspect the all-source smoke.**

Run the same two-day window for the other connectors:

```bash
env -u LD_LIBRARY_PATH -u FONTCONFIG_FILE uv run padel-availability collect-playtomic --database "$DB" --sources data/playtomic_sources.json --days 2
env -u LD_LIBRARY_PATH -u FONTCONFIG_FILE uv run padel-availability collect-everness --database "$DB" --sources data/everness_sources.json --days 2
env -u LD_LIBRARY_PATH -u FONTCONFIG_FILE uv run padel-availability collect-padelfirst --database "$DB" --sources data/padelfirst_sources.json --location-id vernier --days 2
```

Inspect latest runs and slots through `list_availability_runs()`, `list_availability_slots()`, and `get_availability_snapshot()`. Verify all eleven configured location IDs appear, and for each successful run check source URL, two-day window, slot count, UTC timestamps, `Europe/Zurich` timezone, unique slot keys, and slot status. Record errors exactly when a public source fails; on this fresh database there is no earlier successful snapshot to preserve.

Run this read-only inspection against the database created in Step 1:

```bash
uv run python -c '
import sys
from pathlib import Path
from datetime import datetime
from padel_availability.database import connect, list_availability_runs, list_availability_slots

expected = {
    "padel-station", "gva-palexpo", "padel-parc-etoy", "padel-parc-preverenges",
    "vaudoise-arena", "airpad-les-acacias", "airpad-la-praille", "airpad-meyrin",
    "airpad-plan-les-ouates", "everness", "vernier",
}
connection = connect(Path(sys.argv[1]))
latest = {run.location_id: run for run in list_availability_runs(connection)}
assert set(latest) == expected
for location_id, run in sorted(latest.items()):
    slots = list_availability_slots(connection, run.run_id)
    assert run.horizon_days == 2
    assert run.window_start < run.window_end
    assert len({slot.slot_key for slot in slots}) == len(slots)
    for slot in slots:
        assert slot.location_id == location_id
        assert slot.timezone == "Europe/Zurich"
        assert datetime.fromisoformat(slot.starts_at.replace("Z", "+00:00")) < datetime.fromisoformat(slot.ends_at.replace("Z", "+00:00"))
    print(location_id, run.connector, run.status, len(slots), run.error or "none")
connection.close()
' "$DB"
```

- [ ] **Step 4: Run repository-wide verification.**

Run:

```bash
uv run ruff format --check .
uv run ruff check .
uv run pyright
env -u LD_LIBRARY_PATH -u FONTCONFIG_FILE uv run --group dev --group browser pytest -q
git diff --check
```

Expected: all checks pass, with no environment overrides required for browser tests.
