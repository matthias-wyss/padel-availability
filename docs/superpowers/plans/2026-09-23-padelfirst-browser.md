# Padel First Browser Availability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add safe, read-only Padel First Vernier availability collection from the public visible scheduler.

**Architecture:** Keep Padel First in a dedicated source manifest, connector, collector function, and CLI command. Reuse `BrowserSlotObservation`, the shared Europe/Zurich-to-UTC normalization, SQLite persistence, stale snapshot behavior, and the existing Playwright browser factory. Extract only visible FullCalendar and scheduler DOM; never parse inline state or call private endpoints.

**Tech Stack:** Python 3.12+, standard library, existing Playwright browser group, SQLite, pytest, Ruff, Pyright.

## Global Constraints

- The first activation covers exactly the catalog location `vernier`.
- The public booking URL is exactly `https://padelfirst.ss-r.ch/court-vernier/`.
- The default collection window remains 14 local days in `Europe/Zurich`.
- The published fixed booking duration is 90 minutes.
- Use one Chromium process per collection invocation and a fresh context/page per venue.
- Read only visible DOM, visible attributes, accessibility state, and visible page content.
- Do not parse inline JavaScript, cookies, local storage, private endpoints, network responses, credentials, login forms, CAPTCHA, reservation, payment, or hidden application state.
- Generic login navigation links are allowed; visible authentication challenges, CAPTCHA, access denied, loading-only pages, and malformed booking DOM are bounded errors.
- Source/browser errors are persisted and preserve the previous successful snapshot as stale; programming errors propagate.
- No new dependency is required and existing Playtomic, AIRPAD, and Everness behavior remains unchanged.

---

## File Map

- Create `data/padelfirst_sources.json`: the exact one-row public source manifest.
- Create `src/padel_availability/connectors/padelfirst.py`: source model, constants, errors, and manifest loader.
- Create `src/padel_availability/connectors/padelfirst_browser.py`: visible DOM payload, parser, scheduler navigation, and browser lifecycle.
- Modify `src/padel_availability/connectors/__init__.py`: export Padel First types and functions.
- Modify `src/padel_availability/collector.py`: add `collect_padelfirst()` and exact-one-location selection.
- Modify `src/padel_availability/cli.py`: add `collect-padelfirst` and existing runtime preflight/output handling.
- Modify `README.md`: document Padel First setup and manual collection, replacing the broad unsupported wording for this source.
- Create `tests/test_padelfirst.py`: source and manifest contract tests.
- Create `tests/test_padelfirst_browser.py`: visible DOM parser and browser lifecycle tests.
- Modify `tests/test_collector.py`: Padel First persistence, stale, continuation, and lifecycle tests.
- Modify `tests/test_cli_availability.py`: Padel First command, selection, validation, and runtime tests.
- Create sanitized scheduler fixtures under `tests/fixtures/padelfirst/dom/` without scripts, cookies, or network data.

## Task 1: Add Padel First Source Contract

**Files:**
- Create: `data/padelfirst_sources.json`
- Create: `src/padel_availability/connectors/padelfirst.py`
- Create: `tests/test_padelfirst.py`
- Modify: `src/padel_availability/connectors/__init__.py`

**Interfaces:**
- `PADEL_FIRST_LOCATION_IDS: frozenset[str]` contains exactly `vernier`.
- `PADEL_FIRST_BOOKING_URL = "https://padelfirst.ss-r.ch/court-vernier/"`.
- `PADEL_FIRST_SLOT_MINUTES = 90`.
- `PadelFirstStatus = Literal["public", "unavailable"]`.
- `PadelFirstSource` is a frozen slots dataclass with `location_id`, `booking_url`, `checked_at`, and `status`.
- `load_padelfirst_sources(path: Path) -> tuple[PadelFirstSource, ...]` validates exact manifest fields, URL, UTC timestamp, status, duplicate rejection, and exact one-location coverage.
- `PadelFirstSourceError` is the bounded `ValueError` used by the loader and connector.

- [ ] **Step 1: Write failing manifest tests.**

Test acceptance of the one exact row and rejection of missing/extra fields,
wrong URL/timestamp/status, duplicate rows, and wrong location IDs. Assert the
constants are exact.

- [ ] **Step 2: Run the focused tests to verify failure.**

```bash
PATH="/home/agentops/.local/bin:$PATH" uv run pytest tests/test_padelfirst.py -q
```

Expected: import failure because the Padel First module does not exist.

- [ ] **Step 3: Implement the source model, loader, manifest, and exports.**

Use the strict Everness manifest pattern, with one row containing only
`location_id`, `booking_url`, `checked_at`, and `status`. Keep the source on
the exact public Vernier URL.

- [ ] **Step 4: Run tests and commit the source contract.**

```bash
PATH="/home/agentops/.local/bin:$PATH" uv run pytest tests/test_padelfirst.py -q
git add data/padelfirst_sources.json src/padel_availability/connectors/padelfirst.py src/padel_availability/connectors/__init__.py tests/test_padelfirst.py
git commit -m "feat: add Padel First source contract"
```

## Task 2: Parse the Visible Padel First Scheduler

**Files:**
- Create: `src/padel_availability/connectors/padelfirst_browser.py`
- Create: `tests/test_padelfirst_browser.py`
- Create: `tests/fixtures/padelfirst/dom/scheduler-available.html`
- Create: `tests/fixtures/padelfirst/dom/scheduler-unavailable.html`
- Create: `tests/fixtures/padelfirst/dom/scheduler-malformed.html`

**Interfaces:**
- `_PADEL_FIRST_VISIBLE_DOM_SCRIPT` returns visible calendar dates and scheduler rows only.
- `parse_padelfirst_dom(payload: object, requested_date: date) -> tuple[BrowserSlotObservation, ...]` validates and parses the visible scheduler.
- `parse_padelfirst_observations(observations: Sequence[BrowserSlotObservation], *, location_id: str, run_id: str, window_start: date, window_end: date) -> tuple[AvailabilitySlot, ...]` delegates shared normalization.
- `PadelFirstBrowserError` extends `PadelFirstSourceError` and truncates messages to 160 characters.

- [ ] **Step 1: Add sanitized HTML fixtures and failing parser tests.**

Fixtures contain only `#scheduler-table`, visible headers, times, status spans,
match blocks, and visible attributes. Tests cover two courts, available cells,
occupied/blocked cells, unknown status, 90-minute ends, DST-safe UTC output,
date mismatch, empty/incomplete tables, loading text, CAPTCHA/auth challenge,
and invalid visible attributes.

- [ ] **Step 2: Run parser tests to verify failure.**

```bash
PATH="/home/agentops/.local/bin:$PATH" uv run pytest tests/test_padelfirst_browser.py -q
```

Expected: import or assertion failures because the payload script and parser do not exist.

- [ ] **Step 3: Implement visible payload extraction.**

Use `getBoundingClientRect`, computed visibility, `textContent`, and visible
attributes. Read `#scheduler-table`, visible `th.fc-court`, the first cell of
each visible `tbody tr`, and each visible state element in court cells. Keep
generic login navigation links out of the block detector; detect only explicit
challenge text, password/form challenge containers, CAPTCHA, or access denied.

- [ ] **Step 4: Implement the parser and shared normalization adapter.**

Parse `YYYY-MM-DD` from the visible scheduler title or visible `checkin`, parse
`HH:MM` in `Europe/Zurich`, add `PADEL_FIRST_SLOT_MINUTES`, map state classes to
the three slot statuses, require a complete matrix, and delegate final slot
hashing/window/UTC handling to `parse_browser_observations`.

- [ ] **Step 5: Run parser tests and static checks.**

```bash
PATH="/home/agentops/.local/bin:$PATH" uv run pytest tests/test_padelfirst_browser.py -q
PATH="/home/agentops/.local/bin:$PATH" uv run ruff check src/padel_availability/connectors/padelfirst_browser.py tests/test_padelfirst_browser.py
PATH="/home/agentops/.local/bin:$PATH" uv run pyright src/padel_availability/connectors/padelfirst_browser.py tests/test_padelfirst_browser.py
```

- [ ] **Step 6: Commit the parser.**

```bash
git add src/padel_availability/connectors/padelfirst_browser.py tests/fixtures/padelfirst/dom tests/test_padelfirst_browser.py
git commit -m "feat: parse Padel First scheduler"
```

## Task 3: Add Visible Calendar Navigation And Browser Lifecycle

**Files:**
- Modify: `src/padel_availability/connectors/padelfirst_browser.py`
- Modify: `tests/test_padelfirst_browser.py`

**Interfaces:**
- `PadelFirstBrowserConnector(sources: Sequence[PadelFirstSource], *, browser_factory: BrowserFactory = default_browser_factory, timeout_ms: int = 15_000)`.
- `PadelFirstBrowserConnectorFactory = Callable[[Sequence[PadelFirstSource]], PadelFirstBrowserConnector]`.
- `open() -> None`, `close() -> None`, and `collect(location: LocationRecord, *, run_id: str, window_start: date, window_end: date, collected_at: str) -> AvailabilityResult` follow the existing browser connector contracts.

- [ ] **Step 1: Add failing fake-browser lifecycle tests.**

Assert one browser enter/exit, one fresh context/page, visible `.fc-event.available`
date mapping, scheduler modal date refresh, month navigation, no scheduler-cell
click, cleanup on errors, and programming-error propagation.

- [ ] **Step 2: Run lifecycle tests to verify failure.**

```bash
PATH="/home/agentops/.local/bin:$PATH" LD_LIBRARY_PATH="/tmp/opencode/playwright-libs/usr/lib/x86_64-linux-gnu:/tmp/opencode/playwright-libs/lib/x86_64-linux-gnu" FONTCONFIG_FILE="tests/fixtures/fontconfig.conf" uv run pytest tests/test_padelfirst_browser.py -k connector -q
```

- [ ] **Step 3: Implement visible calendar event mapping and month navigation.**

Wait for visible `#calendar` and its month heading, map each visible green
event's table column to its visible `fc-day-top[data-date]` header, and use only
visible previous/next month buttons. Click the green event for each requested
date; never click a scheduler state cell.

- [ ] **Step 4: Implement scheduler refresh and collection.**

After each event click, poll the visible `#scheduler-table` and modal title until
the requested date is present in visible text/attributes. Reject a stale date,
partial matrix, loading-only page, or missing scheduler as a bounded error. Add
all visible observations for each requested date and return a success result.

- [ ] **Step 5: Implement cleanup and bounded errors, then commit.**

```bash
PATH="/home/agentops/.local/bin:$PATH" LD_LIBRARY_PATH="/tmp/opencode/playwright-libs/usr/lib/x86_64-linux-gnu:/tmp/opencode/playwright-libs/lib/x86_64-linux-gnu" FONTCONFIG_FILE="tests/fixtures/fontconfig.conf" uv run pytest tests/test_padelfirst_browser.py -q
PATH="/home/agentops/.local/bin:$PATH" uv run ruff check src/padel_availability/connectors/padelfirst_browser.py tests/test_padelfirst_browser.py
PATH="/home/agentops/.local/bin:$PATH" uv run pyright src/padel_availability/connectors/padelfirst_browser.py tests/test_padelfirst_browser.py
git diff --check
git add src/padel_availability/connectors/padelfirst_browser.py tests/test_padelfirst_browser.py
git commit -m "feat: collect Padel First browser availability"
```

## Task 4: Integrate Collector And CLI

**Files:**
- Modify: `src/padel_availability/collector.py`
- Modify: `src/padel_availability/cli.py`
- Modify: `src/padel_availability/connectors/__init__.py`
- Modify: `tests/test_collector.py`
- Modify: `tests/test_cli_availability.py`

**Interfaces:**
- `_PADEL_FIRST_LOCATION_IDS: frozenset[str]` contains exactly `vernier`.
- `collect_padelfirst(connection: sqlite3.Connection, locations: Sequence[LocationRecord], sources: Sequence[PadelFirstSource], *, now: datetime | None = None, horizon_days: int = 14, location_id: str | None = None, browser_connector_factory: PadelFirstBrowserConnectorFactory | None = None) -> tuple[CollectionOutcome, ...]`.
- CLI command `collect-padelfirst` accepts `--database`, `--sources` defaulting to `data/padelfirst_sources.json`, `--location-id`, and `--days`.

- [ ] **Step 1: Add failing collector tests.**

Cover exact location selection, Europe/Zurich window, immediate persistence,
startup failure, stale previous snapshot, shared browser lifecycle, unknown
location rejection, and programming-error propagation.

- [ ] **Step 2: Implement dedicated collector orchestration.**

Mirror `collect_everness` without changing existing collectors: validate the
exact catalog contract, open one connector for public sources, save each result,
convert documented source/browser failures to `padelfirst_browser` error runs,
and close in `finally`.

- [ ] **Step 3: Add the CLI command and output tests.**

Reuse `_check_playwright_runtime`, `_positive_days`, snapshot display, and the
existing setup guidance. Add tests for the default manifest, exact location,
positive days, output, and missing Playwright.

- [ ] **Step 4: Run focused integration tests and commit.**

```bash
PATH="/home/agentops/.local/bin:$PATH" uv run pytest tests/test_padelfirst.py tests/test_padelfirst_browser.py tests/test_collector.py tests/test_cli_availability.py -q
PATH="/home/agentops/.local/bin:$PATH" uv run ruff check src/padel_availability/connectors/padelfirst.py src/padel_availability/connectors/padelfirst_browser.py src/padel_availability/collector.py src/padel_availability/cli.py tests/test_padelfirst.py tests/test_padelfirst_browser.py tests/test_collector.py tests/test_cli_availability.py
PATH="/home/agentops/.local/bin:$PATH" uv run pyright src/padel_availability/connectors/padelfirst.py src/padel_availability/connectors/padelfirst_browser.py src/padel_availability/collector.py src/padel_availability/cli.py
git diff --check
git add src/padel_availability/collector.py src/padel_availability/cli.py src/padel_availability/connectors/__init__.py tests/test_collector.py tests/test_cli_availability.py
git commit -m "feat: add Padel First collection command"
```

## Task 5: Document And Verify End To End

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Document manual Padel First collection.**

Add the exact install and `collect-padelfirst` command beside the other manual
commands. State that the source is public, sequential, read-only, ephemeral,
never logs in/reserves/pays, and that other unsupported portals remain
unsupported rather than bypassed.

- [ ] **Step 2: Run complete offline verification.**

```bash
PATH="/home/agentops/.local/bin:$PATH" LD_LIBRARY_PATH="/tmp/opencode/playwright-libs/usr/lib/x86_64-linux-gnu:/tmp/opencode/playwright-libs/lib/x86_64-linux-gnu" FONTCONFIG_FILE="tests/fixtures/fontconfig.conf" uv run --group browser --group dev pytest -q
PATH="/home/agentops/.local/bin:$PATH" uv run --group dev ruff check .
PATH="/home/agentops/.local/bin:$PATH" uv run --group dev pyright
git diff --check
```

- [ ] **Step 3: Run a disposable two-day live smoke.**

Use a new `/tmp/opencode/padelfirst-smoke-<run>.sqlite3` path, initialize the
catalog from tracked JSON, and run:

```bash
PATH="/home/agentops/.local/bin:$PATH" LD_LIBRARY_PATH="/tmp/opencode/playwright-libs/usr/lib/x86_64-linux-gnu:/tmp/opencode/playwright-libs/lib/x86_64-linux-gnu" FONTCONFIG_FILE="/home/agentops/workspace/projects/padel-availability/tests/fixtures/fontconfig.conf" uv run padel-availability collect-padelfirst \
  --database /tmp/opencode/padelfirst-smoke-20260923.sqlite3 \
  --sources data/padelfirst_sources.json \
  --location-id vernier \
  --days 2
```

Inspect the output and SQLite snapshot; do not commit generated artifacts.

- [ ] **Step 4: Commit documentation and perform final review.**

```bash
git status --short --branch
git diff -- README.md
git log --oneline -10
git add README.md
git commit -m "docs: document Padel First availability collection"
```

Review all Padel First commits for exact manifest coverage, visible-DOM-only
behavior, no reservation path, stale semantics, test output, and live smoke
result. Leave unrelated existing work untouched and the working tree clean.
