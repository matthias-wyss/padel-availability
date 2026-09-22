# Everness Browser Availability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add safe, read-only availability collection for the public Everness reservation grid.

**Architecture:** Keep Everness in a dedicated source manifest, connector, collector function, and CLI command. Reuse `BrowserSlotObservation`, shared Europe/Zurich-to-UTC normalization, SQLite persistence, stale snapshot behavior, and the existing browser session factory. Extract only visible Everness table DOM; never parse inline JavaScript state or call private Plugin endpoints.

**Tech Stack:** Python 3.12+, standard library, Playwright already installed in the browser tool group, SQLite, pytest, Ruff, Pyright.

## Global Constraints

- The first activation covers exactly the catalog location `everness`.
- The public booking URL is exactly `https://padel.everness.ch/`.
- The default collection window remains 14 local days in `Europe/Zurich`.
- Use one Chromium process per collection invocation and a fresh context/page per venue.
- Read only visible DOM, visible attributes, accessibility state, and visible page content.
- Do not parse inline JavaScript state, hidden `num` identifiers, cookies, local storage, private endpoints, network responses, credentials, login forms, CAPTCHA, reservation, payment, or background scheduling.
- Court labels come from visible `.table_header` text; starts come from visible `.hour_slot` text; cells come from visible `.terrainTxt` elements.
- `.cursor` maps to `available`, `.notallowed` maps to `unavailable`, and an unclassified visible cell maps to `unknown`.
- Derive duration from the difference between adjacent visible start times; use the preceding visible interval for the final row.
- A stable visible grid with no selectable cells is a successful zero-slot run.
- A date change requires an observable loading transition followed by a stable grid or a changed visible grid fingerprint; unchanged stale DOM without a refresh signal is an error.
- Source/browser errors are persisted for Everness and preserve the previous successful snapshot as stale; programming errors propagate.
- No new dependency is required and existing Playtomic behavior remains unchanged.

---

## File Map

- Create `data/everness_sources.json`: the exact one-row Everness source manifest.
- Create `src/padel_availability/connectors/everness.py`: source model, source errors, ID/URL constants, and manifest loader.
- Create `src/padel_availability/connectors/everness_browser.py`: visible DOM payload script, parser, normalization adapter, and browser lifecycle.
- Modify `src/padel_availability/connectors/__init__.py`: export Everness public types and functions.
- Modify `src/padel_availability/collector.py`: add `collect_everness()` and exact-one-location selection.
- Modify `src/padel_availability/cli.py`: add `collect-everness` and reuse the existing runtime preflight/output path.
- Modify `README.md`: document Everness setup and manual collection.
- Create `tests/test_everness.py`: manifest and source contract tests.
- Create `tests/test_everness_browser.py`: sanitized visible DOM, parser, date, state, and lifecycle tests.
- Modify `tests/test_collector.py`: Everness persistence, stale, continuation, and lifecycle tests.
- Modify `tests/test_cli_availability.py`: Everness CLI and runtime error tests.
- Create `tests/fixtures/everness/dom/`: sanitized home, available, unavailable, empty, loading, hidden, and malformed table fixtures.

## Task 1: Add Everness Source Contract

**Files:**
- Create: `data/everness_sources.json`
- Create: `src/padel_availability/connectors/everness.py`
- Create: `tests/test_everness.py`
- Modify: `src/padel_availability/connectors/__init__.py`

**Interfaces:**
- `EVERNESS_LOCATION_IDS: frozenset[str]` contains exactly `everness`.
- `EVERNESS_BOOKING_URL = "https://padel.everness.ch/"`.
- `EvernessStatus = Literal["public", "unavailable"]`.
- `EvernessSource` is a frozen slots dataclass with `location_id: str`, `booking_url: str`, `checked_at: str`, and `status: EvernessStatus`.
- `load_everness_sources(path: Path) -> tuple[EvernessSource, ...]` validates exact manifest fields, exact one-location coverage, public URL, UTC timestamp, status, and duplicate rejection.
- `EvernessSourceError` is the bounded `ValueError` used by the loader and connector.

- [ ] **Step 1: Write failing manifest tests.**

Add tests named `test_load_everness_sources_accepts_exact_one_row`, `test_load_everness_sources_rejects_missing_or_extra_location`, `test_load_everness_sources_rejects_duplicate_rows`, `test_load_everness_sources_rejects_wrong_url_or_timestamp`, and `test_everness_constants_are_explicit`. Use `tmp_path` JSON files and assert `https://padel.everness.ch/` exactly.

- [ ] **Step 2: Run the focused tests to verify they fail.**

```bash
PATH="/home/agentops/.local/bin:$PATH" uv run pytest tests/test_everness.py -q
```

Expected: import failure because the Everness module and loader do not exist.

- [ ] **Step 3: Implement the source model and manifest.**

Create `data/everness_sources.json` with `format_version: 1` and one row containing only `location_id`, `booking_url`, `checked_at`, and `status`. Validate the manifest at the trust boundary and keep the public row on the exact Everness URL.

- [ ] **Step 4: Export the public contract and run tests.**

Export `EvernessSource`, `EvernessSourceError`, `EVERNESS_LOCATION_IDS`, `EVERNESS_BOOKING_URL`, `EvernessStatus`, and `load_everness_sources` from `connectors/__init__.py`, then run:

```bash
PATH="/home/agentops/.local/bin:$PATH" uv run pytest tests/test_everness.py -q
```

Expected: all source-contract tests pass.

- [ ] **Step 5: Commit the source contract.**

```bash
git add data/everness_sources.json src/padel_availability/connectors/everness.py src/padel_availability/connectors/__init__.py tests/test_everness.py
git commit -m "feat: add Everness source contract"
```

## Task 2: Implement Visible Everness DOM Parsing

**Files:**
- Create: `src/padel_availability/connectors/everness_browser.py`
- Create: `tests/fixtures/everness/dom/home.html`
- Create: `tests/fixtures/everness/dom/booking-available.html`
- Create: `tests/fixtures/everness/dom/booking-unavailable.html`
- Create: `tests/fixtures/everness/dom/booking-empty.html`
- Create: `tests/fixtures/everness/dom/booking-loading.html`
- Create: `tests/fixtures/everness/dom/booking-hidden.html`
- Create: `tests/fixtures/everness/dom/booking-malformed.html`
- Create: `tests/test_everness_browser.py`

**Interfaces:**
- `parse_everness_dom(payload: object, requested_date: date) -> tuple[BrowserSlotObservation, ...]` validates and parses a visible Everness payload.
- `parse_everness_observations(observations: Sequence[BrowserSlotObservation], *, location_id: str, run_id: str, window_start: date, window_end: date) -> tuple[AvailabilitySlot, ...]` delegates shared slot hashing, duplicate, DST, UTC, and window rules.
- `_EVERNESS_VISIBLE_DOM_SCRIPT` returns `view`, `date_label`, `courts`, `rows`, `grid_fingerprint`, `loading`, and `visible_text` from visible DOM only.
- The payload contains visible court labels, visible `HH:MM` row starts, visible cell classes/state, and no inline-script identifiers.
- `default_browser_factory()` from `playtomic_browser.py` is reused; Playtomic behavior is unchanged.

- [ ] **Step 1: Add sanitized fixtures and failing parser tests.**

Fixtures must retain only visible table structure and visible state classes. Do not copy scripts, `num` identifiers, hidden state, cookies, network data, or inline JavaScript. Add tests named `test_everness_available_dom_extracts_visible_cells`, `test_everness_ignores_hidden_cells`, `test_everness_unavailable_and_unknown_states`, `test_everness_empty_visible_grid_returns_zero_slots`, `test_everness_loading_page_is_not_final_data`, `test_everness_login_or_captcha_is_bounded_error`, `test_everness_malformed_grid_is_error`, `test_everness_derives_visible_ninety_minute_duration`, `test_everness_24_hour_times_use_zurich_and_utc`, and `test_everness_missing_ids_use_shared_hash`.

- [ ] **Step 2: Run parser tests to verify they fail.**

```bash
PATH="/home/agentops/.local/bin:$PATH" uv run pytest tests/test_everness_browser.py -q
```

Expected: import or assertion failures because the Everness payload script and parser do not exist.

- [ ] **Step 3: Implement the visible payload script.**

Use `document.querySelector`/`querySelectorAll` only on visible elements. Read `#multi-language-date`, `#table_reservation`, visible `.table_header`, visible `.hour_slot`, and visible `.terrainTxt`. Ignore hidden rows/cells. Set `loading` from visible loading text/markers and reject pages whose visible text contains login or CAPTCHA markers. Compute a stable fingerprint from visible date, court labels, row labels, and cell visible classes/styles.

- [ ] **Step 4: Implement date/time/state parsing and shared normalization.**

Parse the visible English date label such as `22 Sep 2026`, parse `HH:MM` local starts in `Europe/Zurich`, derive durations from adjacent visible row starts, and use the preceding interval for the final row. Construct one `BrowserSlotObservation` per visible cell with `external_id=None`. Map `cursor` to `available`, `notallowed` to `unavailable`, and all other visible cells to `unknown`. Reject missing labels, invalid rows, partial matrices, invalid durations, loading payloads, and date mismatches. Delegate final `AvailabilitySlot` construction to `parse_browser_observations`.

- [ ] **Step 5: Run the parser tests and static checks.**

```bash
PATH="/home/agentops/.local/bin:$PATH" uv run pytest tests/test_everness_browser.py -q
PATH="/home/agentops/.local/bin:$PATH" uv run ruff check src/padel_availability/connectors/everness_browser.py tests/test_everness_browser.py
PATH="/home/agentops/.local/bin:$PATH" uv run pyright src/padel_availability/connectors/everness_browser.py tests/test_everness_browser.py
```

Expected: all parser tests pass; Ruff and Pyright report no diagnostics for changed paths.

- [ ] **Step 6: Commit the parser.**

```bash
git add src/padel_availability/connectors/everness_browser.py tests/fixtures/everness/dom tests/test_everness_browser.py
git commit -m "feat: parse Everness booking grid"
```

## Task 3: Add Everness Browser Navigation And Lifecycle

**Files:**
- Modify: `src/padel_availability/connectors/everness_browser.py`
- Modify: `tests/test_everness_browser.py`

**Interfaces:**
- `EvernessBrowserConnector(sources: Sequence[EvernessSource], *, browser_factory: BrowserFactory = default_browser_factory, timeout_ms: int = 15_000)`.
- `EvernessBrowserConnectorFactory = Callable[[Sequence[EvernessSource]], EvernessBrowserConnector]`.
- `EvernessBrowserConnector.open() -> None` starts one shared browser session lazily and idempotently.
- `EvernessBrowserConnector.close() -> None` closes the shared browser session and is safe when unopened.
- `EvernessBrowserConnector.collect(location: LocationRecord, *, run_id: str, window_start: date, window_end: date, collected_at: str) -> AvailabilityResult` returns success/unavailable or raises a documented Everness error.

- [ ] **Step 1: Add failing fake-browser lifecycle tests.**

Add tests named `test_everness_connector_collects_grid_and_closes_context`, `test_everness_connector_selects_each_requested_date`, `test_everness_connector_rejects_stale_grid_without_refresh`, `test_everness_connector_accepts_empty_grid_after_loading`, `test_everness_connector_maps_startup_browser_error`, and `test_everness_programming_errors_propagate_and_cleanup`. Assert one browser enter/exit, one fresh context/page, visible date control use, no cell click/submission, and page/context cleanup.

- [ ] **Step 2: Run lifecycle tests to verify they fail.**

```bash
PATH="/home/agentops/.local/bin:$PATH" LD_LIBRARY_PATH="/tmp/opencode/playwright-libs/usr/lib/x86_64-linux-gnu:/tmp/opencode/playwright-libs/lib/x86_64-linux-gnu" FONTCONFIG_FILE="tests/fixtures/fontconfig.conf" uv run pytest tests/test_everness_browser.py -k connector -q
```

Expected: import or missing-behavior failures because `EvernessBrowserConnector` has no navigation/lifecycle implementation.

- [ ] **Step 3: Implement public page navigation and visible date selection.**

Open `source.booking_url` with `wait_until="commit"`, wait for visible `#table_reservation`, reject visible login/CAPTCHA/unavailable text, and use only visible elements inside `#datepicker` to select each requested date. Poll `#multi-language-date` until its parsed label equals the requested `date`. Do not call hidden date endpoints or read inline scripts.

- [ ] **Step 4: Implement stable-grid refresh and collection.**

Capture the previous visible payload before each date click. Accept the new payload only after its date matches, `loading` has transitioned to a stable state, and either the loading marker was observed or `grid_fingerprint` changed. Parse each stable payload and accumulate observations across the requested window. Stop and raise a bounded error on unchanged stale content, ambiguous controls, missing table, or malformed visible DOM.

- [ ] **Step 5: Implement lifecycle and bounded errors.**

Use a fresh context and page per venue, close page/context in nested `finally` blocks, map only Playwright/runtime failures to `EvernessSourceError`, and let programming errors propagate. Map raw documented browser startup failures to the Everness error type so the collector can persist them. Never click `.terrainTxt`, submit forms, open payment, or attempt authentication.

- [ ] **Step 6: Run browser tests and commit.**

```bash
PATH="/home/agentops/.local/bin:$PATH" LD_LIBRARY_PATH="/tmp/opencode/playwright-libs/usr/lib/x86_64-linux-gnu:/tmp/opencode/playwright-libs/lib/x86_64-linux-gnu" FONTCONFIG_FILE="tests/fixtures/fontconfig.conf" uv run pytest tests/test_everness_browser.py -q
PATH="/home/agentops/.local/bin:$PATH" uv run ruff check src/padel_availability/connectors/everness_browser.py tests/test_everness_browser.py
PATH="/home/agentops/.local/bin:$PATH" uv run pyright src/padel_availability/connectors/everness_browser.py tests/test_everness_browser.py
git diff --check
```

Expected: all Everness browser tests pass and changed paths are clean. Commit:

```bash
git add src/padel_availability/connectors/everness_browser.py tests/test_everness_browser.py
git commit -m "feat: collect Everness browser availability"
```

## Task 4: Integrate Everness Collector And CLI

**Files:**
- Modify: `src/padel_availability/collector.py`
- Modify: `src/padel_availability/cli.py`
- Modify: `src/padel_availability/connectors/__init__.py`
- Modify: `tests/test_collector.py`
- Modify: `tests/test_cli_availability.py`

**Interfaces:**
- `_EVERNESS_LOCATION_IDS: frozenset[str]` in `collector.py` contains exactly `everness`.
- `collect_everness(connection: sqlite3.Connection, locations: Sequence[LocationRecord], sources: Sequence[EvernessSource], *, now: datetime | None = None, horizon_days: int = 14, location_id: str | None = None, browser_connector_factory: EvernessBrowserConnectorFactory | None = None) -> tuple[CollectionOutcome, ...]`.
- CLI command `collect-everness` accepts `--database`, `--sources` defaulting to `data/everness_sources.json`, `--location-id`, and `--days`.

- [ ] **Step 1: Add failing collector tests.**

Add `test_everness_collection_runs_exact_location`, `test_everness_collection_uses_zurich_window`, `test_everness_error_is_persisted_and_snapshot_is_stale`, `test_everness_browser_opens_once_and_closes`, `test_everness_collection_rejects_unknown_location`, and `test_everness_collection_persists_startup_error`. Use a fake `EvernessBrowserConnector`, assert immediate save behavior, exact location validation, shared lifecycle, UTC collected timestamp, and continuation/error persistence.

- [ ] **Step 2: Run collector tests to verify they fail.**

```bash
PATH="/home/agentops/.local/bin:$PATH" uv run pytest tests/test_collector.py -k everness -q
```

Expected: import or missing-function failures because `collect_everness` does not exist.

- [ ] **Step 3: Implement dedicated Everness collection orchestration.**

Mirror AIRPAD collector semantics without changing Playtomic or AIRPAD: validate the exact one-location catalog contract, create one Everness connector, open it once for public sources, save the result immediately, convert documented errors to persisted error runs, preserve stale prior slots, and close in `finally`.

- [ ] **Step 4: Add CLI command and output.**

Reuse `_check_playwright_runtime`, the existing database lifecycle, `_positive_days`, snapshot rendering, and `CollectionOutcome` formatting. Keep `collect-playtomic` and `collect-airpad` branches unchanged.

- [ ] **Step 5: Add CLI tests and run the focused suite.**

Add `test_collect_everness_reports_outcomes`, `test_collect_everness_selects_exact_location`, `test_collect_everness_rejects_non_positive_days`, and `test_collect_everness_reports_missing_playwright_with_setup_guidance`, then run:

```bash
PATH="/home/agentops/.local/bin:$PATH" LD_LIBRARY_PATH="/tmp/opencode/playwright-libs/usr/lib/x86_64-linux-gnu:/tmp/opencode/playwright-libs/lib/x86_64-linux-gnu" FONTCONFIG_FILE="tests/fixtures/fontconfig.conf" uv run pytest tests/test_everness.py tests/test_everness_browser.py tests/test_collector.py tests/test_cli_availability.py -q
```

Expected: all Everness, collector, and CLI tests pass.

- [ ] **Step 6: Commit the integration.**

```bash
git add src/padel_availability/collector.py src/padel_availability/cli.py src/padel_availability/connectors/__init__.py tests/test_collector.py tests/test_cli_availability.py
git commit -m "feat: add Everness collection command"
```

## Task 5: Document And Verify Everness End To End

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Document Everness setup and manual collection.**

Add `collect-everness` beside the existing manual availability commands. State that it reads the public Plugin.ch grid, is sequential/read-only/manual, uses ephemeral browser state, never logs in or reserves, and that other portals without public availability remain unsupported rather than bypassed.

- [ ] **Step 2: Run complete offline verification.**

```bash
PATH="/home/agentops/.local/bin:$PATH" LD_LIBRARY_PATH="/tmp/opencode/playwright-libs/usr/lib/x86_64-linux-gnu:/tmp/opencode/playwright-libs/lib/x86_64-linux-gnu" FONTCONFIG_FILE="tests/fixtures/fontconfig.conf" uv run --group browser --group dev pytest -q
PATH="/home/agentops/.local/bin:$PATH" uv run --group dev ruff check src/padel_availability/connectors/everness.py src/padel_availability/connectors/everness_browser.py src/padel_availability/collector.py tests/test_everness.py tests/test_everness_browser.py tests/test_collector.py tests/test_cli_availability.py
PATH="/home/agentops/.local/bin:$PATH" uv run --group dev pyright src/padel_availability/connectors/everness.py src/padel_availability/connectors/everness_browser.py src/padel_availability/collector.py
git diff --check
```

Expected: the full suite passes; targeted Everness paths have no new Ruff or Pyright errors; diff check is clean.

- [ ] **Step 3: Prepare a disposable catalog database.**

If `/tmp/opencode/everness-smoke.sqlite3` does not exist, run the existing `init-db`, `import-candidates`, and `build-catalog` commands against it. If it exists, use a new `/tmp/opencode/everness-smoke-<run>.sqlite3` path; do not delete an existing artifact.

- [ ] **Step 4: Run the two-day live smoke.**

```bash
PATH="/home/agentops/.local/bin:$PATH" LD_LIBRARY_PATH="/tmp/opencode/playwright-libs/usr/lib/x86_64-linux-gnu:/tmp/opencode/playwright-libs/lib/x86_64-linux-gnu" FONTCONFIG_FILE="tests/fixtures/fontconfig.conf" uv run padel-availability collect-everness \
  --database /tmp/opencode/everness-smoke.sqlite3 \
  --sources data/everness_sources.json \
  --days 2
```

Expected: one persisted Everness outcome for the two-day window. A visible portal contract error is acceptable and must be reported; no credentials, profile, cache, generated database, or live response is committed.

- [ ] **Step 5: Inspect and commit documentation.**

```bash
git status --short --branch
git diff --check
git diff -- README.md
git log --oneline -10
git add README.md
git commit -m "docs: document Everness availability collection"
```

- [ ] **Step 6: Final review.**

Review all Everness commits, confirm exact one-location manifest, visible-DOM-only boundary, stale behavior, no reservation/login path, offline test output, and live smoke output. Leave the working tree clean.
