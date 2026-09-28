# Matchpoint Browser Availability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collect public Matchpoint court availability for Bernex through Padel Connect and Urban Padel Lausanne.

**Architecture:** Add one Matchpoint source loader/manifest and one Playwright browser connector shared by both tenant URLs. Parse only the visible SVG schedule, normalize its variable slot intervals with the existing browser observation helper, then persist through the existing collector and SQLite path.

**Tech Stack:** Python 3.12, Playwright (existing optional browser dependency), SQLite, pytest, Ruff, Pyright.

## Global Constraints

- The initial activation covers catalog locations `bernex` and `urban-padel-lausanne`.
- Read only visible DOM, visible attributes, accessibility state, and visible page content. Do not use private endpoints, network responses, inline application scripts, browser profiles, or hidden state; do not inspect or import cookies or local storage.
- If a visible cookie notice blocks date navigation, click its visible `Decline` control only to reject optional cookies in the current ephemeral context. Never accept cookies or preserve consent state between runs.
- Do not log in, create accounts, click reservation slots, submit forms, or trigger payment.
- Do not persist player names or other participant details.
- Evaux and Jonction remain out of the initial manifest until their public no-login booking grids are confirmed.
- Other uncovered platforms (Plugin.ch, Green Club, Bookinea, Padel One, and Cherpines AIRPAD) are deferred.
- Use `Europe/Zurich` for local dates/times and store UTC instants.
- Preserve immediate-save and stale-snapshot semantics; add no dependencies.
- Inspect existing diffs before editing shared files. Preserve the current dirty working tree; do not reset, stash, or overwrite its existing changes.
- Do not commit unless the user requests it.

---

## File Map

- Create `src/padel_availability/connectors/matchpoint.py` for the exact two-location source model and manifest loader.
- Create `src/padel_availability/connectors/matchpoint_browser.py` for sanitized visible-SVG extraction, parsing, browser lifecycle, and normalization.
- Create `data/matchpoint_sources.json` for the Bernex and Urban tenant URLs.
- Modify `data/verified_locations.json` only to add current booking URL/platform evidence for Bernex and Urban Padel Lausanne; leave court facts and verification classifications unchanged.
- Export the new public connector/source names through `src/padel_availability/connectors/__init__.py`.
- Add `collect_matchpoint()` and its error-result helper to `src/padel_availability/collector.py`.
- Add `collect-matchpoint` to `src/padel_availability/cli.py` and the manual usage example to `README.md`.
- Create `tests/test_matchpoint.py`, `tests/test_matchpoint_browser.py`, and sanitized HTML fixtures under `tests/fixtures/matchpoint/dom/`.
- Add focused collector tests to `tests/test_collector.py` and CLI tests to `tests/test_cli_availability.py`.
- Extend the catalog evidence assertions in `tests/test_inventory.py` to assert booking URL/platform evidence for both new sources.

## Task 1: Add strict Matchpoint source metadata

**Files:**
- Create: `src/padel_availability/connectors/matchpoint.py`
- Create: `data/matchpoint_sources.json`
- Modify: `data/verified_locations.json`
- Create: `tests/test_matchpoint.py`
- Test: `tests/test_inventory.py`

**Interfaces:**
- Produces `MatchpointSource`, `MatchpointSourceError`, `MatchpointStatus`, `MATCHPOINT_LOCATION_IDS`, `MATCHPOINT_BOOKING_URLS`, and `load_matchpoint_sources(path: Path) -> tuple[MatchpointSource, ...]`.
- The only valid IDs are `bernex` and `urban-padel-lausanne`.
- The exact booking URLs are `https://padelgeneva.matchpoint.com.es/Booking/Grid.aspx` and `https://urbanpadellausanne.matchpoint.com.es/Booking/Grid.aspx`.

- [ ] **Step 1: Add source-loader and catalog-evidence tests.** In `tests/test_matchpoint.py`, test the shipped manifest returns the two sources in location-ID order; assert both URLs, `checked_at`, and `public` status. In `tests/test_inventory.py`, assert the two location records carry the correct booking URL/platform and supporting fact keys. Add parameterized source failures for missing/extra IDs, duplicate rows, wrong URL for an ID, bad timestamp/status, extra row keys, and malformed JSON.

  ```python
  ROOT = Path(__file__).parents[1]


  def test_load_matchpoint_sources_accepts_exact_two_rows() -> None:
      sources = load_matchpoint_sources(ROOT / "data/matchpoint_sources.json")
      assert [source.location_id for source in sources] == ["bernex", "urban-padel-lausanne"]
      assert sources[0].booking_url == "https://padelgeneva.matchpoint.com.es/Booking/Grid.aspx"
      assert (
          sources[1].booking_url == "https://urbanpadellausanne.matchpoint.com.es/Booking/Grid.aspx"
      )
      assert all(source.status == "public" for source in sources)


  def test_verified_catalog_has_matchpoint_booking_evidence() -> None:
      locations = {
          location.location_id: location
          for location in load_locations(ROOT / "data/verified_locations.json")
      }
      assert locations["bernex"].booking_platform == "Padel Connect"
      assert locations["urban-padel-lausanne"].booking_platform == "Matchpoint"
      assert all(
          {"location.booking_url", "location.booking_platform"}
          <= {item.fact_key for item in locations[location_id].evidence}
          for location_id in ("bernex", "urban-padel-lausanne")
      )
  ```

- [ ] **Step 2: Run the focused tests to confirm they fail.**

  Run: `.venv/bin/pytest -q tests/test_matchpoint.py`

  Expected: collection fails because the Matchpoint source module does not exist.
- [ ] **Step 3: Implement the source model and loader.** Follow `src/padel_availability/connectors/padelfirst.py`: frozen slotted dataclass, existing text/URL/timestamp validators, exact-key manifest validation, and bounded source errors. Define a location-to-URL mapping and reject a URL that does not match its location.

  The public source contract is:

  ```python
  MatchpointStatus = Literal["public", "unavailable"]
  MATCHPOINT_LOCATION_IDS = frozenset({"bernex", "urban-padel-lausanne"})
  MATCHPOINT_BOOKING_URLS = {
      "bernex": "https://padelgeneva.matchpoint.com.es/Booking/Grid.aspx",
      "urban-padel-lausanne": "https://urbanpadellausanne.matchpoint.com.es/Booking/Grid.aspx",
  }


  @dataclass(frozen=True, slots=True)
  class MatchpointSource:
      location_id: str
      booking_url: str
      checked_at: str
      status: MatchpointStatus
  ```

  `load_matchpoint_sources()` must return sorted rows only after the manifest has exactly those two distinct IDs and each row's URL matches `MATCHPOINT_BOOKING_URLS[location_id]`.

- [ ] **Step 4: Add the exact two-row manifest.** Use `checked_at` `2026-09-25T00:00:00Z` and `status` `public` for both rows.
- [ ] **Step 5: Add fact-specific booking evidence to the two catalog rows.** For Bernex, cite the Padel Academy Bernex page and official Padel Connect/Matchpoint public portal. For Urban Padel, cite the official Urban Padel page and its Matchpoint tenant. Set `booking_url` and `booking_platform`, refresh notes that claim no booking route/domain exists, and leave both rows' `verification_status`, court count, and unknown access/account fields unchanged.
- [ ] **Step 6: Run focused tests and catalog validation.**

  Run: `.venv/bin/pytest -q tests/test_matchpoint.py tests/test_inventory.py`

  Expected: all source-manifest and verified-catalog tests pass.

## Task 2: Parse sanitized Matchpoint visible schedules

**Files:**
- Create: `src/padel_availability/connectors/matchpoint_browser.py`
- Create: `tests/test_matchpoint_browser.py`
- Create: `tests/fixtures/matchpoint/dom/padelconnect-bernex.html`
- Create: `tests/fixtures/matchpoint/dom/urban-padel.html`

**Interfaces:**
- Produces `MatchpointBrowserError`, `_MATCHPOINT_VISIBLE_DOM_SCRIPT`, and `parse_matchpoint_dom(payload: object, requested_date: date) -> tuple[BrowserSlotObservation, ...]`.
- Reuse `BrowserSlotObservation` and `parse_browser_observations()` from `playtomic_browser.py`; do not create a second availability-slot model or normalizer.

- [ ] **Step 1: Add parser tests for both tenant shapes.** Cover visible date, court labels, a Bernex explicit priced offer (`09:00-10:30`), an Urban 60-minute slot, an Urban 90-minute slot, occupied cells, open-match cells, and an unclassified state. Assert local offset-aware timestamps and `available`/`unavailable`/`unknown` statuses. Include malformed time ranges, duplicate/missing court labels, stale dates, partial grids, loading, and authentication challenges.

  Use a sanitized payload contract independent of tenant markup:

  ```python
  payload = {
      "view": "booking",
      "date": "2026-09-25",
      "courts": ["Court 1"],
      "slots": [
          {"court": "Court 1", "start": "09:00", "end": "10:30", "state": "available"},
          {"court": "Court 1", "start": "10:30", "end": "12:00", "state": "booked"},
          {"court": "Court 1", "start": "12:00", "end": "13:30", "state": "open_match"},
          {"court": "Court 1", "start": "13:30", "end": "15:00", "state": "unrecognized"},
      ],
      "loading": False,
      "authentication_visible": False,
  }
  ```

  Assert starts/ends with `+02:00` on 2026-09-25, and states `available`, `unavailable`, `unavailable`, and `unknown` respectively.

- [ ] **Step 2: Run the focused parser tests to confirm they fail.**

  Run: `.venv/bin/pytest -q tests/test_matchpoint_browser.py`

  Expected: collection fails because the Matchpoint browser module does not exist.
- [ ] **Step 3: Add sanitized visible-DOM fixtures and browser-script tests.** Keep only rendered schedule SVG, visible date controls, court/time labels, and status/price marks; remove names, hidden elements, scripts, request data, and unrelated page chrome. Verify `_MATCHPOINT_VISIBLE_DOM_SCRIPT` emits no participant text.
- [ ] **Step 4: Implement the visible-DOM script and parser.** Restrict extraction to visible `.myReservas` SVG content and visible date controls. Return only court/date/time labels, visible cell geometry/markers, and boolean loading/authentication flags; inspect page text locally for markers but do not return it. Read the visible French date field in the form `Vendredi, 25 Septembre, 2026` and parse it with an explicit French month-name table into `YYYY-MM-DD`; do not rely on JavaScript's locale-dependent date parsing. Match court columns and time rows from visible labels and geometry. Treat explicit price offers and complete visible empty button cells as available only when their dimensions align with the rendered court/time grid; treat visible booking/open-match event overlays as unavailable; retain unknown states as `unknown`. Never infer availability from missing or malformed cells.

  The sanitized script result must have this shape and contain no raw event text:

  ```python
  {
      "view": "booking",
      "date": "2026-09-25",
      "courts": ["Court 1"],
      "slots": [{"court": "Court 1", "start": "09:00", "end": "10:30", "state": "available"}],
      "loading": False,
      "authentication_visible": False,
  }
  ```

  In the parser, map the sanitized slot state explicitly:

  ```python
  status = {
      "available": "available",
      "booked": "unavailable",
      "open_match": "unavailable",
  }.get(state, "unknown")
  ```

- [ ] **Step 5: Convert displayed `HH:MM-HH:MM` ranges and grid geometry to local datetimes.** Reject invalid, zero-length, ambiguous, or out-of-day intervals; use `Europe/Zurich`; allow durations to vary by cell and tenant. Call `parse_browser_observations()` for window filtering, UTC conversion, deduplication, and slot-key generation, and wrap `PlaytomicSourceError` as `MatchpointBrowserError`.
- [ ] **Step 6: Run parser and browser-script tests.**

  Run: `.venv/bin/pytest -q tests/test_matchpoint_browser.py`

  Expected: both fixture variants parse while names and non-visible content never appear in observations.

## Task 3: Add the browser connector and safe date navigation

**Files:**
- Modify: `src/padel_availability/connectors/matchpoint_browser.py`
- Modify: `tests/test_matchpoint_browser.py`

**Interfaces:**
- Produces `MatchpointBrowserConnector(sources: Sequence[MatchpointSource], *, browser_factory: BrowserFactory = default_browser_factory, timeout_ms: int = 15_000)` with `open() -> None`, `close() -> None`, and `collect(location: LocationRecord, *, run_id: str, window_start: date, window_end: date, collected_at: str) -> AvailabilityResult`.
- Produces `MatchpointBrowserConnectorFactory = Callable[[Sequence[MatchpointSource]], MatchpointBrowserConnector]` for collector injection.

- [ ] **Step 1: Add fake-page lifecycle tests before implementation.** Assert that each source opens only its configured public grid, requested dates advance through visible date controls, the visible displayed date is verified before parsing, no booking cell is clicked, the public registration/login links are not followed, and pages/contexts/browser close after success and failure.
- [ ] **Step 2: Run lifecycle tests to confirm the connector is missing.**

  Run: `.venv/bin/pytest -q tests/test_matchpoint_browser.py -k connector`

  Expected: import/attribute failures for `MatchpointBrowserConnector`.
- [ ] **Step 3: Implement the connector using the existing browser factory.** Open one Chromium session for a collection, process the configured tenant sources sequentially, and use one fresh context/page per source. If the visible optional-cookie banner blocks controls, click only the visible `Décliner`/`Decline` choice and wait for its blocker overlay to disappear; never accept. Select dates only with visible `Aujourd'hui`/next-day/date-picker controls, and wait for both the requested date and a complete visible court grid. Never click calendar cells or account/booking controls.

  The collection loop follows this shape; `page.click()` is limited to the visible next-day control:

  ```python
  day = window_start
  while day < window_end:
      payload = _wait_for_matchpoint_date(page, day, timeout_ms)
      observations.extend(parse_matchpoint_dom(payload, day))
      if day + timedelta(days=1) < window_end:
          _visible_locator(page, "button.manyana").click()
      day += timedelta(days=1)
  ```

- [ ] **Step 4: Map only documented browser/source failures to `MatchpointBrowserError`.** Let programming errors propagate. Always close page, context, and browser session in `finally`; reuse `_is_documented_browser_error()` only for Playwright's documented runtime exceptions.
- [ ] **Step 5: Build `AvailabilityRun` with connector `matchpoint_browser`; call `parse_browser_observations()` for the requested window and return the resulting `AvailabilityResult`.
- [ ] **Step 6: Run all Matchpoint browser tests.**

  Run: `.venv/bin/pytest -q tests/test_matchpoint_browser.py`

  Expected: lifecycle, navigation, cleanup, date validation, and parser cases pass.

## Task 4: Integrate collection, CLI, and user documentation

**Files:**
- Modify: `src/padel_availability/collector.py`
- Modify: `src/padel_availability/cli.py`
- Modify: `src/padel_availability/connectors/__init__.py`
- Modify: `README.md`
- Modify: `tests/test_collector.py`
- Modify: `tests/test_cli_availability.py`

**Interfaces:**
- Produces `collect_matchpoint(connection: sqlite3.Connection, locations: Sequence[LocationRecord], sources: Sequence[MatchpointSource], *, now: datetime | None = None, horizon_days: int = 14, location_id: str | None = None, browser_connector_factory: MatchpointBrowserConnectorFactory | None = None) -> tuple[CollectionOutcome, ...]`.
- CLI command: `collect-matchpoint --database PATH [--sources PATH] [--location-id ID] [--days N]`.

- [ ] **Step 1: Add collector tests first.** Cover the exact two locations, one-location selection, Europe/Zurich window, browser startup/error persistence, immediate saves, stale-snapshot preservation, and browser cleanup.

  Define a local fake factory in `tests/test_collector.py` that creates a valid successful result without launching Playwright:

  ```python
  class FakeMatchpointConnector:
      def __init__(self, sources: Sequence[MatchpointSource]) -> None:
          self.sources = {source.location_id: source for source in sources}

      def open(self) -> None:
          pass

      def close(self) -> None:
          pass

      def collect(
          self,
          location: LocationRecord,
          *,
          run_id: str,
          window_start: date,
          window_end: date,
          collected_at: str,
      ) -> AvailabilityResult:
          source = self.sources[location.location_id]
          run = AvailabilityRun(
              run_id,
              location.location_id,
              "matchpoint_browser",
              source.booking_url,
              window_start.isoformat(),
              window_end.isoformat(),
              (window_end - window_start).days,
              collected_at,
              "success",
              None,
          )
          return AvailabilityResult(run, ())


  def fake_browser_factory(sources: Sequence[MatchpointSource]) -> FakeMatchpointConnector:
      return FakeMatchpointConnector(sources)


  outcomes = collect_matchpoint(
      connection,
      load_locations(ROOT / "data/verified_locations.json"),
      load_matchpoint_sources(ROOT / "data/matchpoint_sources.json"),
      now=datetime(2026, 9, 24, 22, 30, tzinfo=UTC),
      horizon_days=2,
      browser_connector_factory=fake_browser_factory,
  )
  assert [outcome.location_id for outcome in outcomes] == ["bernex", "urban-padel-lausanne"]
  assert outcomes[0].window_start == "2026-09-25"
  assert outcomes[0].window_end == "2026-09-27"
  ```

- [ ] **Step 2: Run the focused collector tests to confirm they fail.**

  Run: `.venv/bin/pytest -q tests/test_collector.py -k matchpoint`

  Expected: import/attribute failures for `collect_matchpoint`.
- [ ] **Step 3: Implement the collector following `collect_padelfirst()` in the existing file.** Use exact location IDs, source URL in the availability run, connector name `matchpoint_browser`, sequential collection, the existing result/error pattern, and close the connector in `finally`.
- [ ] **Step 4: Add CLI tests first.** Verify default source path, explicit source path, both location IDs, `--days`, deterministic output, missing Playwright guidance, and no browser-runtime check for an `unavailable` source.

  ```python
  def test_collect_matchpoint_defaults_and_selects_urban(tmp_path, monkeypatch):
      loaded_paths = []
      collected = []

      def fake_load(path):
          loaded_paths.append(path)
          return load_matchpoint_sources(ROOT / "data/matchpoint_sources.json")

      def fake_collect(_connection, _locations, sources, *, horizon_days, location_id):
          collected.append((horizon_days, location_id))
          assert {source.location_id for source in sources} == {"bernex", "urban-padel-lausanne"}
          return ()

      monkeypatch.setattr(cli, "load_matchpoint_sources", fake_load)
      monkeypatch.setattr(cli, "collect_matchpoint", fake_collect)
      monkeypatch.setattr(cli, "_check_playwright_runtime", lambda: None)

      assert (
          cli.main(
              [
                  "collect-matchpoint",
                  "--database",
                  str(tmp_path / "catalog.sqlite3"),
                  "--location-id",
                  "urban-padel-lausanne",
                  "--days",
                  "2",
              ]
          )
          == 0
      )
      assert loaded_paths == [Path("data/matchpoint_sources.json")]
      assert collected == [(2, "urban-padel-lausanne")]
  ```

- [ ] **Step 5: Add the `collect-matchpoint` parser and dispatch.** Follow the adjacent `collect-padelfirst` CLI pattern, including `_check_playwright_runtime()` only when a selected source is public and stale snapshot slot-count reporting.

  ```python
  matchpoint_command = commands.add_parser(
      "collect-matchpoint", help="collect public Matchpoint availability manually"
  )
  matchpoint_command.add_argument("--database", required=True, type=Path)
  matchpoint_command.add_argument(
      "--sources", type=Path, default=Path("data/matchpoint_sources.json")
  )
  matchpoint_command.add_argument("--location-id")
  matchpoint_command.add_argument("--days", type=_positive_days, default=14)
  ```

- [ ] **Step 6: Export Matchpoint source/connector names and document the manual command in `README.md`.**
- [ ] **Step 7: Run the focused integration tests.**

  Run: `.venv/bin/pytest -q tests/test_matchpoint.py tests/test_matchpoint_browser.py tests/test_collector.py tests/test_cli_availability.py tests/test_inventory.py`

  Expected: all targeted tests pass.

## Task 5: Verify the two live public tenants

**Files:**
- No new files.

- [ ] **Step 1: Run Ruff format and lint.**

  Run: `.venv/bin/ruff format --check . && .venv/bin/ruff check .`

  Expected: no formatting changes and no lint errors.
- [ ] **Step 2: Run Pyright and the full pytest suite.**

  Run: `/home/agentops/.local/bin/uv run pyright`

  Run: `env -u LD_LIBRARY_PATH -u FONTCONFIG_FILE .venv/bin/pytest -q`

  Expected: zero Pyright errors and all tests pass.
- [ ] **Step 3: Run a two-day public smoke for Bernex and Urban Padel.** Use a database under `/tmp/opencode/`, the checked-in source manifest, and no login or booking actions. Inspect each outcome and snapshot through the application database API; confirm actual observed slots remain dynamic and no participant names are present.

  ```text
  .venv/bin/padel-availability init-db --database /tmp/opencode/matchpoint-smoke-20260925.sqlite3
  .venv/bin/padel-availability build-catalog --database /tmp/opencode/matchpoint-smoke-20260925.sqlite3 --candidates data/candidates.json --verified data/verified_locations.json --run-id matchpoint-smoke-20260925
  env -u LD_LIBRARY_PATH -u FONTCONFIG_FILE .venv/bin/padel-availability collect-matchpoint --database /tmp/opencode/matchpoint-smoke-20260925.sqlite3 --sources data/matchpoint_sources.json --days 2
  ```

  Inspect snapshots through the database API without deleting the smoke database:

  ```python
  from pathlib import Path
  from padel_availability.database import connect, get_availability_snapshot

  connection = connect(Path("/tmp/opencode/matchpoint-smoke-20260925.sqlite3"))
  try:
      for location_id in ("bernex", "urban-padel-lausanne"):
          print(get_availability_snapshot(connection, location_id))
  finally:
      connection.close()
  ```

- [ ] **Step 4: Inspect `git status` and `git diff`.** Confirm the new changes are additive and pre-existing dirty files remain untouched; keep generated smoke data under `/tmp/opencode/`.
