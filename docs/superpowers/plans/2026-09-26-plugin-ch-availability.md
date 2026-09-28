# Plugin.ch Availability Connector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a public, visible-DOM Plugin.ch collector for eight catalogued padel sites without login, booking, private APIs, or new dependencies.

**Architecture:** Add a strict `PluginSource` manifest loader, a single browser connector that emits the same `BrowserSlotObservation` values as the existing connectors, and a collector/CLI entry point following the established Everness, Padel First, and Matchpoint flows. Tenant URLs identify the source; the parser validates the visible Plugin diary, selected date, `Padel` activity, courts, slot times, and conservative states before reusing the existing UTC normalization and persistence pipeline.

**Tech Stack:** Python >=3.12, Playwright already declared in the `browser` dependency group, standard-library JSON/dataclasses/zoneinfo, pytest, Ruff, and Pyright.

## Global Constraints

- Read only visible public Plugin.ch booking DOM; do not log in, activate membership, book, pay, call private APIs, solve CAPTCHAs, or collect participant data.
- Cover exactly these eight location IDs: `fraisiers`, `csu-champel`, `drizia-miremont`, `cologny`, `collonge-bellerive`, `mies-tannay`, `crans-vd`, and `gland`.
- Use the checked public routes from the spec and set new manifest evidence timestamps to `2026-09-26T00:00:00Z`.
- Reuse `BrowserSlotObservation`, `parse_browser_observations`, `AvailabilityResult`, `local_window`, and `save_availability_result`; do not add a generic framework or dependency.
- Treat Europe/Zurich wall times as local input and normalize to UTC through the existing pipeline.
- Fail closed for loading, authentication, CAPTCHA, wrong date, wrong activity, malformed courts/slots, duplicate slots, partial matrices at any visible interval, or an absent/unrecognized raw availability state. Only explicitly recognized ambiguous visual labels may normalize to `unknown`.
- An explicit visible no-availability marker is a successful empty result; missing availability state is an error.
- Close page, context, and browser resources on every success and failure path.
- Preserve catalog membership/access/account facts; public diary visibility does not imply anonymous booking permission.

## File Map

**Create:**

- `src/padel_availability/connectors/plugin.py` — `PluginSource`, constants, and strict manifest loader.
- `src/padel_availability/connectors/plugin_browser.py` — visible DOM script, parser, date navigation, and browser connector.
- `data/plugin_sources.json` — eight exact source rows.
- `tests/test_plugin.py` — manifest and source-model tests.
- `tests/test_plugin_browser.py` — parser, fixture, and browser lifecycle tests.
- `tests/fixtures/plugin/dom/plugin-diary.html` — sanitized common Plugin diary fixture.
- `tests/fixtures/plugin/dom/plugin-weekly-diary.html` — sanitized weekly-scheduler fixture observed on five tenants.

**Modify:**

- `src/padel_availability/connectors/__init__.py` — export Plugin symbols.
- `src/padel_availability/collector.py` — add Plugin source IDs, error result, and `collect_plugin`.
- `src/padel_availability/cli.py` — add `collect-plugin` parser and dispatch.
- `tests/test_collector.py` — eight-location Plugin collector coverage.
- `tests/test_cli_availability.py` — CLI dispatch and browser-runtime checks for Plugin.
- `data/verified_locations.json` — exact Plugin booking URL/platform evidence for eight records.
- `tests/test_inventory.py` — assert the eight current Plugin booking routes and evidence.
- `reports/research-notes.md` — record the eight public Plugin routes and account caveats.
- `reports/inventory.md` — regenerate from the updated catalog.
- `README.md` — document `collect-plugin` and its public/read-only boundaries.

---

### Task 1: Add the strict Plugin source manifest

**Files:**
- Create: `src/padel_availability/connectors/plugin.py`
- Create: `data/plugin_sources.json`
- Create: `tests/test_plugin.py`
- Modify: `src/padel_availability/connectors/__init__.py`

**Interfaces:**
- Produces `PluginSource`, `PluginSourceError`, `PLUGIN_BOOKING_URLS`, `PLUGIN_LOCATION_IDS`, and `load_plugin_sources(path: Path) -> tuple[PluginSource, ...]`.
- The browser and collector tasks consume the exact constants and source tuple produced here.

- [ ] **Step 1: Write the failing manifest tests**

Add `tests/test_plugin.py` with a `_row(location_id, booking_url=None)` helper and tests for:

```python
PLUGIN_URLS = {
    "cologny": "https://reservation.cs-cologny.ch/diary",
    "collonge-bellerive": "https://reservation.tccb.ch/diary",
    "crans-vd": "https://tccrans.plugin.ch/user/diary",
    "csu-champel": "https://unige.plugin.ch/",
    "drizia-miremont": "https://tcdrizia.plugin.ch/",
    "fraisiers": "https://tcfraisiers.plugin.ch/?sport=301",
    "gland": "https://tcgland.plugin.ch/user/diary",
    "mies-tannay": "https://tcmt.plugin.ch/user/diary",
}
```

Test exact eight-row loading and sorted IDs, exact URLs, `public` status, and
`2026-09-26T00:00:00Z` timestamps. Add rejection cases for empty, missing,
duplicate, extra, unsupported-URL, malformed JSON, invalid timestamp, invalid
status, wrong top-level keys, and extra row fields.

- [ ] **Step 2: Run the manifest tests and verify the expected failure**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_plugin.py
```

Expected: collection fails because `padel_availability.connectors.plugin` and
`data/plugin_sources.json` do not exist yet.

- [ ] **Step 3: Implement the source model and loader**

Use the existing `PadelFirstSource`/`load_padelfirst_sources` validation pattern
with exact URL mapping rather than a hostname-only check, because two tenants
use custom reservation domains:

```python
PluginStatus = Literal["public", "unavailable"]

PLUGIN_BOOKING_URLS = {
    "cologny": "https://reservation.cs-cologny.ch/diary",
    "collonge-bellerive": "https://reservation.tccb.ch/diary",
    "crans-vd": "https://tccrans.plugin.ch/user/diary",
    "csu-champel": "https://unige.plugin.ch/",
    "drizia-miremont": "https://tcdrizia.plugin.ch/",
    "fraisiers": "https://tcfraisiers.plugin.ch/?sport=301",
    "gland": "https://tcgland.plugin.ch/user/diary",
    "mies-tannay": "https://tcmt.plugin.ch/user/diary",
}
PLUGIN_LOCATION_IDS = frozenset(PLUGIN_BOOKING_URLS)
```

Define a frozen slotted `PluginSource` with `location_id`, `booking_url`,
`checked_at`, and `status`. Validate text, URL, UTC timestamp, status, exact
manifest keys, exact row count, exact URL mapping, unique IDs, and exact
coverage. Return rows sorted by `location_id`; bound all source errors to 160
characters.

Create `data/plugin_sources.json` with `format_version: 1` and the eight rows
from the spec, all `public` and checked at `2026-09-26T00:00:00Z`.

Export the constants, source class/error, and loader from
`connectors/__init__.py` following the existing connector exports.

- [ ] **Step 4: Run the manifest tests and verify they pass**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_plugin.py
```

Expected: all Plugin manifest tests pass.

- [ ] **Step 5: Commit the source contract**

```bash
git add src/padel_availability/connectors/plugin.py data/plugin_sources.json tests/test_plugin.py src/padel_availability/connectors/__init__.py
git commit -m "feat: add Plugin.ch source manifest"
```

### Task 2: Define and parse the visible Plugin diary payload

**Files:**
- Create: `src/padel_availability/connectors/plugin_browser.py`
- Create: `tests/test_plugin_browser.py`
- Create: `tests/fixtures/plugin/dom/plugin-diary.html`

**Interfaces:**
- Produces `PluginBrowserError`, `_PLUGIN_VISIBLE_DOM_SCRIPT`, and `parse_plugin_dom(payload, requested_date, *, expected_activity="Padel")`.
- The browser connector task consumes the parser and DOM script; the collector task consumes the connector’s `PluginBrowserConnector`.

- [ ] **Step 1: Write parser tests against the sanitized payload contract**

In `tests/test_plugin_browser.py`, define `_payload` with this exact shape:

```python
{
    "view": "booking",
    "date": "2026-09-26",
    "activity": "Padel",
    "courts": ["Court 1", "Court 2"],
    "slots": [
        {"court": "Court 1", "start": "09:00", "end": "10:30", "state": "available"},
        {"court": "Court 2", "start": "09:00", "end": "10:30", "state": "booked"},
    ],
    "loading": False,
    "authentication_visible": False,
    "empty_grid": False,
}
```

Add tests that assert variable durations, `available`/`unavailable`/`unknown`
mapping, Europe/Zurich local timestamps, explicit empty results, both table and
weekly fixture extraction, per-interval court coverage, and rejection of
loading, authentication, CAPTCHA text, wrong view, wrong date, wrong activity,
missing courts, partial matrices at one interval, duplicate slots, malformed
times, invalid duration, participant fields, and an unmarked empty grid.

- [ ] **Step 2: Run the parser tests and verify the expected failure**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_plugin_browser.py
```

Expected: collection fails because `plugin_browser.py` and
`parse_plugin_dom` do not exist yet.

- [ ] **Step 3: Inspect the live visible Plugin DOM before choosing selectors**

Run a read-only Playwright inspection for all eight manifest URLs. For each
page, record visible `table`, `select`, `button`, date-label, activity-label,
and cell class/attribute shapes from `document.body.innerText` and the visible
DOM. Do not call `fetch`, inspect hidden inputs, or submit any form. Confirm
which tenants share the common diary layouts and add sanitized fixtures for both
observed layouts under `tests/fixtures/plugin/dom/plugin-diary.html` and
`tests/fixtures/plugin/dom/plugin-weekly-diary.html`.

The fixture must contain a visible `Padel` activity, selected date
`2026-09-26`, two visible courts, at least one free cell, one occupied cell,
one unknown-state cell, and the visible date-navigation control used by the
connector. Remove names, account identifiers, booking URLs, and tenant data not
needed by the parser test.

- [ ] **Step 4: Implement the visible DOM script and parser**

Implement `_PLUGIN_VISIBLE_DOM_SCRIPT` to return only the payload keys defined
in Step 1. Use the existing visible-element checks from the browser connectors:
hidden, zero-size, `display:none`, `visibility:hidden`, `opacity:0`, and
`aria-hidden=true` content must not contribute data. Read only the visible
selected activity/date, visible court headings, and visible diary cells for
both the reservation-table and weekly-scheduler layouts. Never infer a blank or
unrecognized cell as available/booked; emit a recognized state or fail closed.

Implement:

```python
def parse_plugin_dom(
    payload: object,
    requested_date: date,
    *,
    expected_activity: str = "Padel",
) -> tuple[BrowserSlotObservation, ...]: ...
```

Require `view == "booking"`, an ISO selected date equal to `requested_date`,
`activity == expected_activity`, boolean loading/auth flags, nonempty unique
courts, exact slot fields, valid `HH:MM` times, positive Europe/Zurich
durations, unique `(court, start, end)` keys, and one observation for every
visible court at every visible interval when the grid is nonempty. Map only explicitly known ambiguous
visual labels to `unknown`; reject an absent or unrecognized raw state. The
connector calls the shared `parse_browser_observations` helper and translates
its `PlaytomicSourceError` into `PluginBrowserError` as the other browser
connectors do.

- [ ] **Step 5: Run parser and fixture tests**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_plugin_browser.py
```

Expected: all payload, fixture, and parser tests pass.

- [ ] **Step 6: Commit the parser contract**

```bash
git add src/padel_availability/connectors/plugin_browser.py tests/test_plugin_browser.py tests/fixtures/plugin/dom/plugin-diary.html tests/fixtures/plugin/dom/plugin-weekly-diary.html
git commit -m "feat: parse public Plugin.ch diaries"
```

### Task 3: Add the Plugin browser connector and date navigation

**Files:**
- Modify: `src/padel_availability/connectors/plugin_browser.py`
- Modify: `tests/test_plugin_browser.py`

**Interfaces:**
- Produces `PluginBrowserConnector`, `PluginBrowserConnectorFactory`, and `PluginBrowserError` with the same `open`, `close`, and `collect(location, *, run_id, window_start, window_end, collected_at)` lifecycle as the existing browser connectors. The connector passes observations directly to the shared `parse_browser_observations` helper.

- [ ] **Step 1: Add fake-page lifecycle tests before connector code**

Extend `tests/test_plugin_browser.py` with fake page/context/browser classes and
tests named:

- `test_plugin_connector_uses_public_diary_and_visible_next_day_navigation`
- `test_plugin_connector_rejects_authentication_and_closes_resources`
- `test_plugin_connector_rejects_wrong_activity_and_closes_resources`
- `test_plugin_connector_declines_optional_cookies_only_when_visible`
- `test_plugin_connector_persists_variable_dates_and_slot_states`

Assert the exact source URL is passed to `goto`, the date navigation control is
clicked only between requested dates, page/context/browser are closed on parser
errors, and no booking-cell selector is clicked.

- [ ] **Step 2: Run connector tests and verify the expected failure**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_plugin_browser.py -k connector
```

Expected: the new connector tests fail because `PluginBrowserConnector` is not
implemented.

- [ ] **Step 3: Implement the connector lifecycle**

Follow `MatchpointBrowserConnector`/`PadelFirstBrowserConnector` without copying
their site-specific parsers:

```python
class PluginBrowserConnector:
    def __init__(
        self,
        sources: Sequence[PluginSource],
        *,
        browser_factory: BrowserFactory = default_browser_factory,
        timeout_ms: int = _PLUGIN_TIMEOUT_MS,
    ) -> None: ...

    def open(self) -> None: ...
    def close(self) -> None: ...
    def collect(
        self,
        location: LocationRecord,
        *,
        run_id: str,
        window_start: date,
        window_end: date,
        collected_at: str,
    ) -> AvailabilityResult: ...
```

Implement `_wait_for_plugin_date` using repeated visible DOM evaluation until
the court/slot matrix is ready. Implement visible optional-cookie decline and
visible date-next navigation only. Never select a booking cell. On an explicit
empty diary, return a successful empty observation set; on auth/loading/DOM
drift, raise `PluginBrowserError`.

Use `PluginSource.booking_url` as the run source URL and preserve the existing
run window, `collected_at`, and slot normalization behavior.

- [ ] **Step 4: Run all browser tests**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_plugin_browser.py
```

Expected: all parser, fixture, lifecycle, cleanup, and date-navigation tests
pass.

- [ ] **Step 5: Commit the browser connector**

```bash
git add src/padel_availability/connectors/plugin_browser.py tests/test_plugin_browser.py
git commit -m "feat: add Plugin.ch browser connector"
```

### Task 4: Wire Plugin.ch into the collector and CLI

**Files:**
- Modify: `src/padel_availability/collector.py`
- Modify: `src/padel_availability/cli.py`
- Modify: `src/padel_availability/connectors/__init__.py`
- Modify: `tests/test_collector.py`
- Modify: `tests/test_cli_availability.py`

**Interfaces:**
- Produces `collect_plugin(connection, locations, sources, *, now=None, horizon_days=14, location_id=None, browser_connector_factory=None) -> tuple[CollectionOutcome, ...]`.
- Produces CLI command `collect-plugin --database PATH --sources PATH --location-id ID --days N` with the same defaults and output format as the other browser collectors.

- [ ] **Step 1: Add failing collector and CLI tests**

Add Plugin test helpers in `tests/test_collector.py`:

- `plugin_locations()` returning the eight catalog records in sorted ID order;
- `plugin_sources()` loading `data/plugin_sources.json`;
- `ready_plugin_database(tmp_path)` inserting only the eight candidates/locations;
- `_plugin_result(...)` returning an `AvailabilityResult` with source `plugin_browser`.

Add tests that assert all eight locations use the Europe/Zurich window,
received sources equal the manifest, outcomes are sorted, one selected
`location_id` works, missing catalog locations and unknown IDs raise the same
style of `ValueError`, browser startup errors persist eight error runs and
still call `close`, and source status `unavailable` avoids browser startup.

Add CLI tests asserting `collect-plugin` accepts its default
`data/plugin_sources.json`, calls `_check_playwright_runtime` for a public
source, and dispatches to `collect_plugin` with `--days` and `--location-id`.

- [ ] **Step 2: Run the new integration tests and verify the expected failure**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_collector.py -k plugin tests/test_cli_availability.py -k plugin
```

Expected: collection or assertions fail because the Plugin collector and CLI
command do not exist.

- [ ] **Step 3: Implement collector wiring**

In `collector.py`, add Plugin imports/constants, `_plugin_error_result`, and a
`collect_plugin` function shaped like `collect_padelfirst`:

- validate the selected ID against `PLUGIN_LOCATION_IDS`;
- validate all eight catalog locations when collecting without a filter;
- build `plugin-{location_id}-{collected_at}` run IDs;
- open one browser session for selected public sources;
- persist one error result per affected location if startup fails;
- catch `PluginSourceError`, `OSError`, `TimeoutError`, and
  `json.JSONDecodeError`, plus documented browser errors;
- always close the connector and return outcomes sorted by location ID.

In `cli.py`, add the parser block:

```python
plugin_command = commands.add_parser(
    "collect-plugin", help="collect public Plugin.ch availability manually"
)
plugin_command.add_argument("--database", required=True, type=Path)
plugin_command.add_argument("--sources", type=Path, default=Path("data/plugin_sources.json"))
plugin_command.add_argument("--location-id")
plugin_command.add_argument("--days", type=_positive_days, default=14)
```

Dispatch it alongside the other browser collectors, run the Playwright runtime
check for any selected public source, print `status`, `slots`, `window`,
`error`, and `last_success`, and preserve stale snapshots on errors.

Export the Plugin browser/source symbols from `connectors/__init__.py`.

- [ ] **Step 4: Run integration tests**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_collector.py -k plugin tests/test_cli_availability.py -k plugin
```

Expected: all Plugin collector and CLI tests pass.

- [ ] **Step 5: Commit the integration wiring**

```bash
git add src/padel_availability/collector.py src/padel_availability/cli.py src/padel_availability/connectors/__init__.py tests/test_collector.py tests/test_cli_availability.py
git commit -m "feat: wire Plugin.ch collection"
```

### Task 5: Update catalog evidence, reports, and user documentation

**Files:**
- Modify: `data/verified_locations.json`
- Modify: `tests/test_inventory.py`
- Modify: `reports/research-notes.md`
- Modify: `reports/inventory.md`
- Modify: `README.md`

**Interfaces:**
- The eight catalog records expose their checked booking URL and `Plugin.ch` platform without changing unrelated facts.
- The README documents `collect-plugin` as sequential, public, read-only collection.

- [ ] **Step 1: Add failing catalog assertions**

Extend `test_matchpoint_locations_have_current_booking_evidence` into a
platform-specific assertion or add `test_plugin_locations_have_current_booking_evidence` with:

```python
expected = {
    "cologny": ("https://reservation.cs-cologny.ch/diary", "Plugin.ch"),
    "collonge-bellerive": ("https://reservation.tccb.ch/diary", "Plugin.ch"),
    "crans-vd": ("https://tccrans.plugin.ch/user/diary", "Plugin.ch"),
    "csu-champel": ("https://unige.plugin.ch/", "Plugin.ch"),
    "drizia-miremont": ("https://tcdrizia.plugin.ch/", "Plugin.ch"),
    "fraisiers": ("https://tcfraisiers.plugin.ch/?sport=301", "Plugin.ch"),
    "gland": ("https://tcgland.plugin.ch/user/diary", "Plugin.ch"),
    "mies-tannay": ("https://tcmt.plugin.ch/user/diary", "Plugin.ch"),
}
```

Assert matching `location.booking_url`, `location.booking_platform`, and both
supporting fact keys in evidence. Run the focused inventory test and confirm it
fails before the catalog is updated.

- [ ] **Step 2: Add exact catalog evidence**

For each record, add the exact route and `Plugin.ch` platform fields and two
checked evidence records dated `2026-09-26T00:00:00Z` for
`location.booking_url` and `location.booking_platform`. Preserve current
verification status and all unrelated evidence, including the account and
membership caveats.

- [ ] **Step 3: Update research notes and README**

Add a Plugin.ch section to `reports/research-notes.md` documenting the eight
routes, public diary visibility, and the fact that public availability does
not imply anonymous booking. Add a README section with:

```bash
uv run padel-availability collect-plugin \
  --database var/catalog.sqlite3 \
  --sources data/plugin_sources.json \
  --days 14
```

State that the command is manual, sequential, public/read-only, does not log
in or reserve, and persists errors as stale outcomes.

- [ ] **Step 4: Regenerate the tracked inventory report**

Build and render the catalog through the existing CLI entry point using a
temporary ignored database. In this checkout, invoke `cli.main` directly
because `cli.py` has no module `__main__` block:

```bash
.venv/bin/python -c "from padel_availability.cli import main; raise SystemExit(main(['build-catalog', '--database', '/tmp/padel-availability-plugin.sqlite3', '--candidates', 'data/candidates.json', '--verified', 'data/verified_locations.json', '--run-id', 'inventory-2026-09-26']))"
.venv/bin/python -c "from padel_availability.cli import main; raise SystemExit(main(['report', '--database', '/tmp/padel-availability-plugin.sqlite3', '--output', 'reports/inventory.md']))"
```

Verify that all eight Plugin URLs and platform evidence appear in the report.

- [ ] **Step 5: Run documentation/catalog tests**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_inventory.py
```

Expected: the complete inventory test file passes.

- [ ] **Step 6: Commit catalog and docs**

```bash
git add data/verified_locations.json tests/test_inventory.py reports/research-notes.md reports/inventory.md README.md
git commit -m "docs: record Plugin.ch availability sources"
```

### Task 6: Run full verification and all eight live smoke checks

**Files:**
- No source changes expected; only fix files from Tasks 1–5 if a verification failure identifies a real defect.

- [ ] **Step 1: Run the complete offline suite and static checks**

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/pyright --pythonpath .venv/bin/python
```

Expected: all tests pass, Ruff reports no violations or formatting changes, and
Pyright reports zero errors, warnings, or information messages.

- [ ] **Step 2: Run the read-only eight-route smoke test**

Use Playwright with the eight manifest URLs and today's Europe/Zurich date. For
each source, call the visible DOM script, wait for the selected date, parse with
`expected_activity="Padel"`, and print only location ID, court count, slot
count, available count, and parser status. Do not click any booking cell or
submit any form. A successful smoke requires each route to either produce a
validated grid or an explicit validated empty result; authentication or
unrecognized DOM is a reported failure, not a coerced success.

- [ ] **Step 3: Inspect final diff and status**

```bash
git diff --check
git status --short --branch
git log --oneline -10
```

Confirm only intended Plugin commits were created and do not revert or stage
the pre-existing dirty changes in the checkout.

- [ ] **Step 4: Commit any final test-only correction**

If a correction is required, stage only the corrected Plugin files and use:

```bash
git commit -m "fix: harden Plugin.ch availability parsing"
```
