# AIRPAD Browser Availability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add manual, read-only availability collection for the four AIRPAD venues through the public Doinsport iframe.

**Architecture:** Keep AIRPAD on a dedicated source manifest, connector, collector function, and CLI command; do not generalize all platforms into a registry. Reuse the existing browser session lifecycle, `BrowserSlotObservation`, UTC normalization, SQLite persistence, and stale snapshot behavior. Drive only visible labels and DOM in the public `airpad.doinsport.club` iframe.

**Tech Stack:** Python 3.12+, standard library, Playwright already installed in the browser tool group, SQLite, pytest, Ruff, Pyright.

## Global Constraints

- The default collection window is 14 local days in `Europe/Zurich`.
- Use one Chromium process per collection invocation and a fresh context/page per venue.
- Read only visible DOM, visible attributes, accessibility state, and visible iframe content.
- Do not use login, credentials, cookies, local storage, hidden application state, network interception, private APIs, or CAPTCHA bypass.
- A loaded grid with visible court rows and no slot cards is a valid zero-slot state.
- A source/browser error is saved for that venue and does not stop other AIRPAD venues.
- Failed or unavailable runs preserve the previous successful slots as stale.
- `cherpines` is out of scope for this first AIRPAD activation.
- No new dependency is required.

---

## File Map

- Create `data/airpad_sources.json`: the exact four-row AIRPAD source manifest.
- Create `src/padel_availability/connectors/airpad.py`: AIRPAD source model, label mapping, manifest loader, and source errors.
- Create `src/padel_availability/connectors/airpad_browser.py`: public iframe navigation, visible DOM payload script, AIRPAD parser, and connector lifecycle.
- Modify `src/padel_availability/connectors/playtomic_browser.py`: expose the existing default browser factory for the dedicated connector without changing Playtomic behavior.
- Modify `src/padel_availability/connectors/__init__.py`: export AIRPAD public types and functions.
- Modify `src/padel_availability/collector.py`: add the dedicated `collect_airpad()` orchestration and four-location selection.
- Modify `src/padel_availability/cli.py`: add `collect-airpad` with the existing runtime preflight and output format.
- Modify `README.md`: document AIRPAD setup and manual collection.
- Create `tests/test_airpad.py`: manifest and source contract tests.
- Create `tests/test_airpad_browser.py`: DOM payload, parsing, date, state, and connector lifecycle tests.
- Modify `tests/test_collector.py`: AIRPAD persistence, continuation, stale, and lifecycle tests.
- Modify `tests/test_cli_availability.py`: AIRPAD CLI and runtime error tests.
- Create `tests/fixtures/airpad/dom/`: sanitized public DOM fixtures for home, activity selection, empty grid, available slots, blocked page, and malformed states.

## Task 1: Add AIRPAD Source Contract

**Files:**
- Create: `data/airpad_sources.json`
- Create: `src/padel_availability/connectors/airpad.py`
- Create: `tests/test_airpad.py`
- Modify: `src/padel_availability/connectors/__init__.py`

**Interfaces:**
- `AIRPAD_LOCATION_IDS: frozenset[str]` contains exactly `airpad-les-acacias`, `airpad-la-praille`, `airpad-meyrin`, and `airpad-plan-les-ouates`.
- `AIRPAD_LOCATION_LABELS: Mapping[str, str]` maps those IDs to `LES ACACIAS`, `LA PRAILLE`, `MEYRIN`, and `PLAN-LES-OUATES`.
- `AirpadStatus = Literal["public", "unavailable"]`.
- `AirpadSource` is a frozen slots dataclass with `location_id: str`, `booking_url: str`, `checked_at: str`, and `status: AirpadStatus`.
- `load_airpad_sources(path: Path) -> tuple[AirpadSource, ...]` validates exact manifest fields, exact four IDs, public URL, UTC timestamp, and duplicate rejection.
- `AirpadSourceError` is the bounded `ValueError` used by the source loader and connector.

- [ ] **Step 1: Write failing manifest tests.**

Add tests named `test_load_airpad_sources_accepts_exact_four_rows`, `test_load_airpad_sources_rejects_missing_or_extra_location`, `test_load_airpad_sources_rejects_duplicate_rows`, and `test_airpad_location_labels_are_explicit`. Use `tmp_path` JSON files and assert the common URL is `https://www.airpad.ch/reserve`.

- [ ] **Step 2: Run the focused tests to verify they fail.**

Run:

```bash
uv run pytest tests/test_airpad.py -q
```

Expected: collection/import failures because the AIRPAD module and manifest do not exist yet.

- [ ] **Step 3: Implement the source model and manifest.**

Mirror the validation style of `PlaytomicSource` and `load_playtomic_sources`, but do not reuse Playtomic's exact-five validation. Every manifest row must contain only `location_id`, `booking_url`, `checked_at`, and `status`; public rows use the common AIRPAD URL.

- [ ] **Step 4: Export the public AIRPAD contract.**

Export `AirpadSource`, `AirpadSourceError`, `AIRPAD_LOCATION_IDS`, `AIRPAD_LOCATION_LABELS`, and `load_airpad_sources` from `connectors/__init__.py`.

- [ ] **Step 5: Run the focused tests to verify they pass.**

Run:

```bash
uv run pytest tests/test_airpad.py -q
```

Expected: all source-contract tests pass.

- [ ] **Step 6: Commit the source contract.**

```bash
git add data/airpad_sources.json src/padel_availability/connectors/airpad.py src/padel_availability/connectors/__init__.py tests/test_airpad.py
git commit -m "feat: add AIRPAD source contract"
```

## Task 2: Implement Visible AIRPAD DOM Parsing

**Files:**
- Create: `src/padel_availability/connectors/airpad_browser.py`
- Create: `tests/fixtures/airpad/dom/home.html`
- Create: `tests/fixtures/airpad/dom/activity-selection.html`
- Create: `tests/fixtures/airpad/dom/booking-empty.html`
- Create: `tests/fixtures/airpad/dom/booking-available.html`
- Create: `tests/fixtures/airpad/dom/booking-blocked.html`
- Create: `tests/fixtures/airpad/dom/booking-malformed.html`
- Create: `tests/test_airpad_browser.py`
- Modify: `src/padel_availability/connectors/playtomic_browser.py`

**Interfaces:**
- `parse_airpad_dom(payload: object, requested_date: date) -> tuple[BrowserSlotObservation, ...]` validates a visible AIRPAD booking payload and returns normalized local observations.
- `parse_airpad_observations(observations: Sequence[BrowserSlotObservation], *, location_id: str, run_id: str, window_start: date, window_end: date) -> tuple[AvailabilitySlot, ...]` delegates the existing deterministic hash, DST, UTC, duplicate, and window rules.
- `_AIRPAD_VISIBLE_DOM_SCRIPT` returns `view`, `date`, `slots`, `empty_grid`, and `visible_text` from visible iframe DOM only.
- The payload maps each visible `.playground-slot` to its `.section-title` court label, visible `Start HH:MM` time, visible duration labels such as `60 min`, optional external ID, disabled state, and whether `.empty_playground` is present.
- `default_browser_factory() -> BrowserFactory` is added to `playtomic_browser.py` as a public wrapper around the existing `_PlaywrightBrowserSession`; existing Playtomic behavior and tests remain unchanged.

- [ ] **Step 1: Add sanitized DOM fixtures and failing parser tests.**

Fixtures must preserve only visible structure observed in the public iframe: `.calendar-block`, `.date-slot`, `.playground-slot`, `.section-title`, `.info-playground`, `.empty_playground`, and available duration cards. Do not copy scripts, hidden state, cookies, or network data.

Add tests named `test_airpad_available_dom_extracts_each_duration`, `test_airpad_empty_playground_is_zero_slots`, `test_airpad_blocked_dom_is_bounded_error`, `test_airpad_unknown_booking_dom_is_error`, `test_airpad_missing_id_uses_existing_hash`, `test_airpad_24_hour_times_use_zurich_and_utc`, and `test_airpad_changed_date_rejects_unchanged_dom`.

- [ ] **Step 2: Run the parser tests to verify they fail.**

Run:

```bash
uv run pytest tests/test_airpad_browser.py -q
```

Expected: import or assertion failures because the AIRPAD payload script and parser do not exist.

- [ ] **Step 3: Implement the visible payload script.**

Use visible element checks equivalent to the Playtomic extractor. Identify the booking view from `.calendar-block` and visible `.date-slot` buttons. Read the active date from the visible date button's `aria-label` (for example `September 22, 2026`) and normalize it to an ISO date in the browser script. Inspect only visible `.playground-slot` containers. Mark `empty_grid` true only when at least one visible court row exists and no visible slot duration card exists; `.empty_playground` is retained as explicit per-row evidence when present.

- [ ] **Step 4: Implement the parser and shared normalization call.**

Parse `HH:MM` values as Europe/Zurich local time, parse each visible `N min` duration, create one `BrowserSlotObservation` per visible duration, and use `None` for missing external IDs. Preserve `available`, `unavailable`, and `unknown` states from visible classes/disabled attributes. Delegate final `AvailabilitySlot` construction to `parse_browser_observations` so slot hashing and UTC/DST behavior stay identical.

- [ ] **Step 5: Expose the browser factory wrapper and run parser tests.**

Run:

```bash
uv run pytest tests/test_airpad_browser.py -q
```

Expected: all AIRPAD parser and fixture tests pass.

- [ ] **Step 6: Commit the parser.**

```bash
git add src/padel_availability/connectors/airpad_browser.py src/padel_availability/connectors/playtomic_browser.py tests/fixtures/airpad/dom tests/test_airpad_browser.py
git commit -m "feat: parse AIRPAD booking DOM"
```

## Task 3: Add AIRPAD Browser Navigation And Lifecycle

**Files:**
- Modify: `src/padel_availability/connectors/airpad_browser.py`
- Modify: `tests/test_airpad_browser.py`

**Interfaces:**
- `AirpadBrowserConnector(sources: Sequence[AirpadSource], *, browser_factory: BrowserFactory = default_browser_factory, timeout_ms: int = 15_000)`.
- `AirpadBrowserConnectorFactory = Callable[[Sequence[AirpadSource]], AirpadBrowserConnector]`.
- `AirpadBrowserConnector.open() -> None` starts one shared browser session lazily/idempotently.
- `AirpadBrowserConnector.close() -> None` closes the shared browser session and is safe when no session was opened.
- `AirpadBrowserConnector.collect(location: LocationRecord, *, run_id: str, window_start: date, window_end: date, collected_at: str) -> AvailabilityResult` returns a success/unavailable result or raises a documented source/browser error.

- [ ] **Step 1: Add failing fake-browser lifecycle tests.**

Add tests named `test_airpad_connector_selects_visible_site_and_closes_context`, `test_airpad_connector_collects_all_time_ranges_without_duplicates`, `test_airpad_connector_accepts_loaded_empty_playground`, `test_airpad_connector_continues_after_date_refresh`, and `test_airpad_programming_errors_propagate_and_cleanup`. Assert one `browser_enter`/`browser_exit`, one fresh context per location, visible frame URL selection, and page/context cleanup.

- [ ] **Step 2: Run the lifecycle tests to verify they fail.**

Run:

```bash
uv run pytest tests/test_airpad_browser.py -k connector -q
```

Expected: failures because `AirpadBrowserConnector` has no navigation or lifecycle implementation.

- [ ] **Step 3: Implement the public navigation flow.**

From the common booking URL, wait for a frame whose URL starts with `https://airpad.doinsport.club/`. In that frame, click visible `.item-title` text `1.Terrains`, then the `.activity-card` matching `AIRPAD_LOCATION_LABELS[location_id]`. Reject missing or divergent selection states.

- [ ] **Step 4: Implement visible date and time-range iteration.**

For each local date, open the visible `.btn-date-calendar`, click `button.days-btn[aria-label="<Month DD, YYYY>"]`, wait for the active date to match, then read the visible `.playground-slot` cards. Walk `.btn-arrow-right` through the visible time ranges, recording `.select-time-range` labels and stopping when the label repeats; cap the loop at eight ranges to prevent an external UI loop. Deduplicate observations through the existing slot hash.

- [ ] **Step 5: Implement lifecycle and bounded errors.**

Use a fresh context and page per venue, close page/context in nested `finally` blocks, and map only Playwright/runtime failures to the AIRPAD source error. Let programming errors propagate. Treat visible `Sign in`, `Login`, CAPTCHA, missing frame, and malformed booking DOM as bounded errors without attempting authentication.

- [ ] **Step 6: Run the lifecycle tests to verify they pass.**

Run:

```bash
uv run pytest tests/test_airpad_browser.py -q
```

Expected: all parser and connector tests pass.

- [ ] **Step 7: Commit the connector.**

```bash
git add src/padel_availability/connectors/airpad_browser.py tests/test_airpad_browser.py
git commit -m "feat: collect AIRPAD browser availability"
```

## Task 4: Integrate AIRPAD Collector And CLI

**Files:**
- Modify: `src/padel_availability/collector.py`
- Modify: `src/padel_availability/cli.py`
- Modify: `src/padel_availability/connectors/__init__.py`
- Modify: `tests/test_collector.py`
- Modify: `tests/test_cli_availability.py`

**Interfaces:**
- `_AIRPAD_LOCATION_IDS: frozenset[str]` in `collector.py` contains the four AIRPAD IDs.
- `collect_airpad(connection: sqlite3.Connection, locations: Sequence[LocationRecord], sources: Sequence[AirpadSource], *, now: datetime | None = None, horizon_days: int = 14, location_id: str | None = None, browser_connector_factory: AirpadBrowserConnectorFactory | None = None) -> tuple[CollectionOutcome, ...]`.
- CLI command `collect-airpad` accepts `--database`, `--sources` defaulting to `data/airpad_sources.json`, `--location-id`, and `--days`.

- [ ] **Step 1: Add failing collector tests.**

Add tests named `test_airpad_collection_runs_all_four_sites`, `test_airpad_collection_selects_one_site_and_uses_zurich_window`, `test_airpad_error_is_persisted_and_other_sites_continue`, `test_airpad_failed_run_keeps_previous_snapshot_stale`, and `test_airpad_browser_opens_once_and_closes_after_collection`. Use a fake `AirpadBrowserConnector`, assert immediate save counts, sorted outcomes, and exact four-location validation.

- [ ] **Step 2: Run collector tests to verify they fail.**

Run:

```bash
uv run pytest tests/test_collector.py -k airpad -q
```

Expected: import or missing-function failures because `collect_airpad` does not exist.

- [ ] **Step 3: Implement dedicated AIRPAD collection orchestration.**

Mirror the proven Playtomic collector semantics without adding AIRPAD IDs to the Playtomic exact-five manifest. Select all four AIRPAD locations by default, validate `--location-id`, open one browser session, save each result immediately, continue after documented errors, and close the connector in `finally`.

- [ ] **Step 4: Add the CLI command and output.**

Reuse `_check_playwright_runtime`, the existing database connection lifecycle, snapshot status rendering, and the `CollectionOutcome` output format. Keep `collect-playtomic` behavior unchanged.

- [ ] **Step 5: Add offline CLI tests and run the focused suite.**

Add `test_collect_airpad_reports_outcomes`, `test_collect_airpad_rejects_non_positive_days`, and `test_collect_airpad_reports_missing_playwright_with_setup_guidance`, then run:

```bash
uv run pytest tests/test_airpad.py tests/test_airpad_browser.py tests/test_collector.py tests/test_cli_availability.py -q
```

Expected: all focused AIRPAD, collector, and CLI tests pass.

- [ ] **Step 6: Commit the integration.**

```bash
git add src/padel_availability/collector.py src/padel_availability/cli.py src/padel_availability/connectors/__init__.py tests/test_collector.py tests/test_cli_availability.py
git commit -m "feat: add AIRPAD collection command"
```

## Task 5: Document And Verify AIRPAD End To End

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-09-22-airpad-browser-design.md` only if verification evidence changes an explicit acceptance note.

- [ ] **Step 1: Document installation and manual collection.**

Add the AIRPAD command beside the Playtomic command, state that it opens a public Doinsport iframe, remains sequential/read-only, uses ephemeral browser state, and excludes `cherpines` from this activation.

- [ ] **Step 2: Run the complete offline verification.**

Run:

```bash
LD_LIBRARY_PATH="/tmp/opencode/playwright-libs/usr/lib/x86_64-linux-gnu:/tmp/opencode/playwright-libs/lib/x86_64-linux-gnu" \
FONTCONFIG_FILE="tests/fixtures/fontconfig.conf" \
uv run pytest -q
uv run ruff check src/padel_availability/connectors/airpad.py src/padel_availability/connectors/airpad_browser.py src/padel_availability/collector.py src/padel_availability/cli.py tests/test_airpad.py tests/test_airpad_browser.py tests/test_collector.py tests/test_cli_availability.py
uv run pyright src/padel_availability/connectors/airpad.py src/padel_availability/connectors/airpad_browser.py src/padel_availability/collector.py src/padel_availability/cli.py
git diff --check
```

Expected: the full suite passes; targeted AIRPAD files have no new Ruff or Pyright errors; `git diff --check` is clean.

- [ ] **Step 3: Prepare a disposable catalog database for live smoke.**

Run the documented `init-db`, `import-candidates`, and `build-catalog` commands against `/tmp/opencode/airpad-smoke.sqlite3`, then run:

```bash
uv run padel-availability collect-airpad \
  --database /tmp/opencode/airpad-smoke.sqlite3 \
  --sources data/airpad_sources.json \
  --days 2
```

Expected: four outcome lines, one per AIRPAD ID, with bounded errors only if the public portal visibly blocks or lacks a booking contract. No credentials, profile, cache, or generated database is committed.

- [ ] **Step 4: Inspect final changes and commit documentation.**

```bash
git status --short --branch
git diff --check
git diff -- README.md
git log --oneline -10
git add README.md
git commit -m "docs: document AIRPAD availability collection"
```

- [ ] **Step 5: Final review.**

Review all commits from the AIRPAD branch range, confirm the four source rows, public iframe-only boundary, stale behavior, and live smoke output. Leave the working tree clean.
