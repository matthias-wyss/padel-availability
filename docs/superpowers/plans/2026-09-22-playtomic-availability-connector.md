# Playtomic Availability Connector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collect public Playtomic padel slots for the five catalog locations, normalize them into SQLite snapshots, and expose a manual CLI command without authentication or browser automation.

**Architecture:** Typed availability models and timezone helpers stay in `availability.py`. SQLite persistence owns run/slot history and derives stale views without deleting successful snapshots. A focused Playtomic adapter consumes a verified public JSON URL template through an injectable standard-library transport; a collector runs the five sites independently and the CLI persists and summarizes each outcome.

**Tech Stack:** Python 3.12, `sqlite3`, `json`, `dataclasses`, `datetime`, `zoneinfo`, `urllib.request`, `urllib.error`, `pytest`, Ruff, Pyright, and `uv`. No runtime dependency is added.

## Global Constraints

- Keep the connector read-only: no reservation, payment, cancellation, or remote mutation.
- Use only public Playtomic pages/JSON; never use credentials, cookies, private tokens, or persistent sessions.
- Do not bypass CAPTCHA, rate limits, anti-bot controls, or authentication.
- Do not add browser automation, a scheduler, a daemon, or a web UI in this slice.
- Cover exactly `padel-station`, `gva-palexpo`, `padel-parc-etoy`, `padel-parc-preverenges`, and `vaudoise-arena`.
- Default to a half-open 14-calendar-day window `[today, today + 14 days)` in `Europe/Zurich`; allow a positive CLI override.
- Store all collection timestamps and normalized instants as UTC ISO-8601 strings ending in `Z`.
- Preserve every observed slot state as `available`, `unavailable`, or `unknown`; never infer that a club is closed or fully booked from an empty or inaccessible response.
- A site failure must create an explicit `error` or `unavailable` run and must not delete its last successful snapshot.
- Collect sites independently and sequentially with bounded timeouts and no automatic retries in the first slice.
- Keep default tests offline and deterministic; live source checks are explicit and never part of the default suite.
- Keep `reports/inventory.md` as the static catalog report; this slice does not add availability to that report.
- Do not commit generated SQLite files, caches, credentials, or local runtime state.

---

## File Map

Create these files:

- `src/padel_availability/availability.py`: immutable run/slot/snapshot models and timezone/window validation.
- `src/padel_availability/connectors/__init__.py`: connector package marker and public exports.
- `src/padel_availability/connectors/playtomic.py`: source manifest model, public HTTP transport, payload parser, and single-location adapter.
- `src/padel_availability/collector.py`: multi-location orchestration and per-site outcomes.
- `data/playtomic_sources.json`: checked public Playtomic source templates for the five catalog locations.
- `tests/test_availability.py`: model and timezone tests.
- `tests/test_playtomic.py`: manifest, fixture parser, URL-window substitution, and transport error tests.
- `tests/test_collector.py`: multi-site success/error/stale behavior and horizon tests.

Modify these files:

- `src/padel_availability/database.py`: availability tables, persistence, history queries, and stale snapshot projection.
- `src/padel_availability/cli.py`: `collect-playtomic` command and deterministic console summary.
- `tests/test_database.py`: availability schema, round-trip, cascade, and stale projection tests.
- `tests/test_report.py`: CLI/database integration only if shared fixtures need an update; do not change static report semantics.
- `README.md`: manual collection command and freshness/error boundaries.

Do not modify the existing catalog JSON schema, existing location identities, or connector-independent report output.

## Interfaces Between Tasks

Task 1 produces the types consumed by Tasks 2-5:

```python
from datetime import date, datetime
from typing import Literal

AvailabilityRunStatus = Literal["success", "error", "unavailable"]
SlotStatus = Literal["available", "unavailable", "unknown"]
SnapshotStatus = Literal["success", "stale", "error", "unavailable"]

@dataclass(frozen=True, slots=True)
class AvailabilityRun:
    run_id: str
    location_id: str
    connector: str
    source_url: str
    window_start: str
    window_end: str
    horizon_days: int
    collected_at: str
    status: AvailabilityRunStatus
    error: str | None

@dataclass(frozen=True, slots=True)
class AvailabilitySlot:
    run_id: str
    location_id: str
    slot_key: str
    external_id: str | None
    court_label: str | None
    starts_at: str
    ends_at: str
    timezone: str
    status: SlotStatus

@dataclass(frozen=True, slots=True)
class AvailabilityResult:
    run: AvailabilityRun
    slots: tuple[AvailabilitySlot, ...]

@dataclass(frozen=True, slots=True)
class AvailabilitySnapshot:
    location_id: str
    latest_run: AvailabilityRun
    slots: tuple[AvailabilitySlot, ...]
    status: SnapshotStatus
    last_success_at: str | None
```

Task 2 produces these database functions:

```python
def save_availability_result(
    connection: sqlite3.Connection,
    result: AvailabilityResult,
    *,
    commit: bool = True,
) -> None: ...

def list_availability_runs(
    connection: sqlite3.Connection,
    location_id: str | None = None,
) -> tuple[AvailabilityRun, ...]: ...

def list_availability_slots(
    connection: sqlite3.Connection,
    run_id: str,
) -> tuple[AvailabilitySlot, ...]: ...

def get_availability_snapshot(
    connection: sqlite3.Connection,
    location_id: str,
) -> AvailabilitySnapshot | None: ...
```

Task 3 produces these connector functions:

```python
def load_playtomic_sources(path: Path) -> tuple[PlaytomicSource, ...]: ...

def parse_playtomic_slots(
    payload: object,
    *,
    location_id: str,
    run_id: str,
    window_start: date,
    window_end: date,
) -> tuple[AvailabilitySlot, ...]: ...

class PlaytomicConnector:
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

Task 4 produces:

```python
@dataclass(frozen=True, slots=True)
class CollectionOutcome:
    location_id: str
    run_id: str
    status: AvailabilityRunStatus
    slot_count: int
    window_start: str
    window_end: str
    error: str | None

def collect_playtomic(
    connection: sqlite3.Connection,
    locations: Sequence[LocationRecord],
    sources: Sequence[PlaytomicSource],
    *,
    now: datetime | None = None,
    horizon_days: int = 14,
    location_id: str | None = None,
    fetch_json: JsonFetcher = fetch_public_json,
) -> tuple[CollectionOutcome, ...]: ...
```

### Task 1: Add Availability Models And Time Helpers

**Files:**
- Create: `src/padel_availability/availability.py`
- Create: `tests/test_availability.py`

**Interfaces:** Use the exact model types from the interface block above. Reuse existing model validation conventions: raise `ModelError`, validate absolute HTTP(S) URLs, and require UTC timestamps to end in `Z`.

- [ ] **Step 1: Write failing model and time tests**

```python
from datetime import date, datetime, timezone

import pytest

from padel_availability.availability import (
    AvailabilityRun,
    AvailabilitySlot,
    ModelError,
    local_window,
    local_to_utc,
)


def test_local_window_is_half_open_and_uses_zurich_date() -> None:
    now = datetime(2026, 9, 22, 23, 30, tzinfo=timezone.utc)

    assert local_window(now, 14) == (date(2026, 9, 23), date(2026, 10, 7))


def test_local_time_is_normalized_to_utc() -> None:
    assert local_to_utc("2026-09-23T20:00:00+02:00") == "2026-09-23T18:00:00Z"


def test_slot_rejects_non_increasing_utc_interval() -> None:
    with pytest.raises(ModelError, match="ends_at"):
        AvailabilitySlot(
            "run-1", "padel-station", "slot-1", None, None,
            "2026-09-23T18:00:00Z", "2026-09-23T18:00:00Z",
            "Europe/Zurich", "available",
        )
```

- [ ] **Step 2: Run the focused tests and verify the expected failure**

Run: `uv run pytest tests/test_availability.py -q`

Expected: FAIL because `availability.py` and its types do not exist yet.

- [ ] **Step 3: Implement the minimal immutable models and helpers**

Implement `_utc_timestamp`, date validation, `local_window`, and `local_to_utc`
using `datetime`, `zoneinfo.ZoneInfo("Europe/Zurich")`, and no third-party
package. Use a half-open date window: `window_end = window_start +
timedelta(days=horizon_days)`. Reject non-positive horizons, reversed dates,
unknown statuses, blank IDs, invalid URLs, and intervals where `ends_at <=
starts_at`. Require `AvailabilityRun.error` for `error`/`unavailable` statuses
and require it to be null for `success`.

- [ ] **Step 4: Run the focused tests and the existing model suite**

Run: `uv run pytest tests/test_availability.py tests/test_models.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the model slice**

```bash
git add src/padel_availability/availability.py tests/test_availability.py
git commit -m "feat: add availability snapshot models"
```

### Task 2: Persist Availability Runs And Slots

**Files:**
- Modify: `src/padel_availability/database.py:26-124`
- Modify: `tests/test_database.py`

**Interfaces:** Consume `AvailabilityRun`, `AvailabilitySlot`, `AvailabilityResult`, and `AvailabilitySnapshot` from Task 1. Produce the four exact database functions in the interface block.

- [ ] **Step 1: Add failing schema and round-trip tests**

Add tests that initialize a temporary database, insert one catalog location,
save a success result with one available and one unavailable slot, reopen the
database, and assert exact run/slot values. Also add:

```python
def test_failed_latest_run_exposes_previous_success_as_stale(tmp_path: Path) -> None:
    connection = ready_database(tmp_path)
    save_availability_result(connection, successful_result())
    save_availability_result(connection, failed_result())

    snapshot = get_availability_snapshot(connection, "padel-station")

    assert snapshot is not None
    assert snapshot.status == "stale"
    assert snapshot.slots[0].status == "available"
    assert snapshot.latest_run.status == "error"
    assert snapshot.last_success_at == "2026-09-22T08:00:00Z"
```

Test that deleting a catalog location cascades its availability rows, that a
duplicate `(run_id, slot_key)` is rejected or updated deterministically, and
that a failed result with no prior success returns status `error` or
`unavailable` with an empty slot tuple.

- [ ] **Step 2: Run the focused database tests and verify failure**

Run: `uv run pytest tests/test_database.py -q`

Expected: FAIL because the availability tables and repository functions do not exist.

- [ ] **Step 3: Add the two SQLite tables**

Extend `initialize` with these constraints:

```sql
CREATE TABLE IF NOT EXISTS availability_runs (
    run_id TEXT PRIMARY KEY,
    location_id TEXT NOT NULL REFERENCES locations(location_id) ON DELETE CASCADE,
    connector TEXT NOT NULL,
    source_url TEXT NOT NULL,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    horizon_days INTEGER NOT NULL CHECK (horizon_days > 0),
    collected_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('success', 'error', 'unavailable')),
    error TEXT
);

CREATE TABLE IF NOT EXISTS availability_slots (
    run_id TEXT NOT NULL REFERENCES availability_runs(run_id) ON DELETE CASCADE,
    location_id TEXT NOT NULL REFERENCES locations(location_id) ON DELETE CASCADE,
    slot_key TEXT NOT NULL,
    external_id TEXT,
    court_label TEXT,
    starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    timezone TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('available', 'unavailable', 'unknown')),
    PRIMARY KEY (run_id, slot_key)
);
```

Enable foreign keys as the existing database code does. Store each result in a
single transaction; do not delete runs or slots during a new save.

- [ ] **Step 4: Implement save, list, and stale projection functions**

`save_availability_result` inserts the run and all slots atomically. The list
functions return deterministic ordering by `collected_at`, `run_id`, and
`slot_key`. `get_availability_snapshot` selects the latest run for the
location, then the latest successful run. Return current slots for a successful
latest run; otherwise return the last successful slots with `status="stale"`
when one exists, or empty slots with the latest error/unavailable status.

- [ ] **Step 5: Run the database and inventory suites**

Run: `uv run pytest tests/test_database.py tests/test_inventory.py -q`

Expected: PASS.

- [ ] **Step 6: Commit the persistence slice**

```bash
git add src/padel_availability/database.py tests/test_database.py
git commit -m "feat: persist availability snapshots"
```

### Task 3: Verify Public Playtomic Sources And Parse Fixtures

**Files:**
- Create: `src/padel_availability/connectors/__init__.py`
- Create: `src/padel_availability/connectors/playtomic.py`
- Create: `data/playtomic_sources.json`
- Create: `tests/fixtures/playtomic/padel-station.json`
- Create: `tests/fixtures/playtomic/gva-palexpo.json`
- Create: `tests/fixtures/playtomic/padel-parc-etoy.json`
- Create: `tests/fixtures/playtomic/padel-parc-preverenges.json`
- Create: `tests/fixtures/playtomic/vaudoise-arena.json`
- Create: `tests/test_playtomic.py`

**Interfaces:** Consume `AvailabilityResult`, `AvailabilityRun`, and
`AvailabilitySlot` from Task 1. The adapter uses a callable transport:

```python
JsonFetcher = Callable[[str], object]

@dataclass(frozen=True, slots=True)
class PlaytomicSource:
    location_id: str
    booking_url: str
    availability_url_template: str | None
    checked_at: str
    status: Literal["public", "unavailable"]
```

- [ ] **Step 1: Verify the five public booking pages and record source metadata**

Check the current booking URL already stored for each of the five location IDs.
Use only the public page and requests it makes without credentials. Record one
manifest row per location with:

```json
{
  "format_version": 1,
  "sources": [
    {
      "location_id": "padel-station",
      "booking_url": "https://playtomic.com/fr/clubs/padel-station1",
      "availability_url_template": "https://public.example/slots?from={window_start}&to={window_end}",
      "checked_at": "2026-09-22T00:00:00Z",
      "status": "public"
    }
  ]
}
```

Replace the example URL with the exact public JSON URL template observed for
the location. The template must contain `{window_start}` and `{window_end}`.
If no public JSON feed is available without a credential or browser session,
set `availability_url_template` to `null` and `status` to `unavailable`; do
not invent a private endpoint. Every one of the five location IDs must appear
exactly once.

- [ ] **Step 2: Freeze redacted public JSON fixtures and write failing parser tests**

Save one representative response per location under `tests/fixtures/playtomic`.
Remove cookies, tokens, personal data, and unrelated payload fields while
keeping the exact slot array/path, external IDs, court labels, local timestamps,
and available/unavailable values needed by the parser. Add tests that assert a
fixture produces `AvailabilitySlot` values with `Europe/Zurich`, UTC `Z`
timestamps, and stable `slot_key` values. Add an invalid-payload test that
raises `PlaytomicSourceError` rather than returning an empty success.

- [ ] **Step 3: Run parser tests and verify the expected failure**

Run: `uv run pytest tests/test_playtomic.py -q`

Expected: FAIL because the source manifest loader, transport, and parser do not exist.

- [ ] **Step 4: Implement manifest validation and public transport**

Implement `load_playtomic_sources` with strict top-level/version/field checks,
exact five-location coverage, URL validation, UTC `checked_at`, and the
placeholder requirement for public URL templates. Implement:

```python
def fetch_public_json(url: str, *, timeout: float = 10.0) -> object:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "padel-availability/0.1"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)
```

Do not add cookies, authorization headers, retries, or browser code. Wrap HTTP,
JSON, and schema failures in `PlaytomicSourceError` with bounded public error
messages.

- [ ] **Step 5: Implement the parser and single-location connector**

`parse_playtomic_slots` must follow the exact fixture payload shape captured in
Step 2, reject missing slot arrays/required fields, preserve explicit state,
filter only slots outside the requested half-open date window, and deduplicate
by external ID or a deterministic hash of location, court, start, and end.
Convert offset-aware local timestamps with `local_to_utc`; reject naive or
ambiguous values instead of guessing. `PlaytomicConnector.collect` formats the
manifest template with the requested dates, returns a `success` result on a
valid response (including zero slots), and returns `unavailable` when the
manifest says no public feed exists.

- [ ] **Step 6: Run parser tests, model tests, and JSON validation**

Run:

```bash
uv run pytest tests/test_playtomic.py tests/test_availability.py -q
python3 -m json.tool data/playtomic_sources.json
```

Expected: PASS with no network request made by the tests.

- [ ] **Step 7: Commit the source adapter slice**

```bash
git add src/padel_availability/connectors data/playtomic_sources.json tests/fixtures/playtomic tests/test_playtomic.py
git commit -m "feat: add public Playtomic source adapter"
```

### Task 4: Orchestrate Independent Site Collection

**Files:**
- Create: `src/padel_availability/collector.py`
- Create: `tests/test_collector.py`

**Interfaces:** Consume `LocationRecord` from the catalog, `PlaytomicSource`/
`PlaytomicConnector` from Task 3, and `save_availability_result` from Task 2.
Produce `CollectionOutcome` and `collect_playtomic` exactly as defined above.

- [ ] **Step 1: Write failing orchestration tests**

Use a fixture-backed `fetch_json(url)` callable, fixed `now`, and temporary
SQLite catalog. Test:

```python
def test_collection_runs_all_selected_sites_independently(tmp_path: Path) -> None:
    outcomes = collect_playtomic(
        connection,
        five_playtomic_locations,
        sources,
        now=datetime(2026, 9, 22, 9, 0, tzinfo=ZoneInfo("Europe/Zurich")),
        horizon_days=14,
        fetch_json=fixture_fetch_json,
    )

    assert [outcome.location_id for outcome in outcomes] == [
        "gva-palexpo",
        "padel-parc-etoy",
        "padel-parc-preverenges",
        "padel-station",
        "vaudoise-arena",
    ]
    assert all(outcome.status in {"success", "error", "unavailable"} for outcome in outcomes)
```

Add a test where one fixture raises `PlaytomicSourceError`; assert the other
four runs are saved and the failed location has an explicit error run. Add a
second collection with the failed source after a successful first run and
assert `get_availability_snapshot` returns the previous slots as `stale`.

- [ ] **Step 2: Run collector tests and verify failure**

Run: `uv run pytest tests/test_collector.py -q`

Expected: FAIL because the collector module does not exist.

- [ ] **Step 3: Implement date windows and independent persistence**

Resolve `now` in `Europe/Zurich`, convert an aware UTC `now` to that zone,
derive the half-open dates, validate `horizon_days > 0`, and select either all
five Playtomic locations or the requested `location_id`. Use one collected UTC
timestamp for the command invocation and a run ID containing the location ID
and timestamp.

For each location, call the connector and immediately save its result in its
own transaction. Catch only expected `PlaytomicSourceError`, `OSError`,
`TimeoutError`, and JSON/schema errors; convert them to an `error` or
`unavailable` result and continue to the next location. Do not catch
`BaseException` or hide programming errors. Sort outcomes by `location_id`.

- [ ] **Step 4: Run the collector, database, and offline catalog suites**

Run: `uv run pytest tests/test_collector.py tests/test_database.py tests/test_inventory.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the collection service**

```bash
git add src/padel_availability/collector.py tests/test_collector.py
git commit -m "feat: collect Playtomic availability snapshots"
```

### Task 5: Add The Manual CLI Command And Documentation

**Files:**
- Modify: `src/padel_availability/cli.py:14-113`
- Modify: `tests/test_report.py` or create `tests/test_cli_availability.py`
- Modify: `README.md`

**Interfaces:** Consume `load_locations`, `load_playtomic_sources`, and
`collect_playtomic`. Keep all existing `init-db`, `import-candidates`,
`build-catalog`, and `report` behavior unchanged.

- [ ] **Step 1: Write failing CLI tests**

Add tests for parser behavior and validation:

```python
def test_collect_playtomic_rejects_non_positive_days(tmp_path: Path) -> None:
    assert main([
        "collect-playtomic",
        "--database", str(tmp_path / "catalog.sqlite3"),
        "--days", "0",
    ]) == 2
```

Add a CLI integration test with a monkeypatched fixture fetcher or direct
collector invocation that asserts the summary contains all selected location
IDs, statuses, and slot counts. Do not make the test call the real network.

- [ ] **Step 2: Run the focused CLI tests and verify failure**

Run: `uv run pytest tests/test_cli_availability.py -q` (or the named test module created in Step 1).

Expected: FAIL because `collect-playtomic` is not registered.

- [ ] **Step 3: Register the command and validate arguments**

Add a parser subcommand with:

```text
collect-playtomic
  --database PATH      required
  --sources PATH       default data/playtomic_sources.json
  --location-id ID     optional
  --days INTEGER       default 14, must be positive
```

Load the existing SQLite catalog and source manifest, call `collect_playtomic`,
and print one deterministic line per outcome containing location ID, status,
slot count, window, and bounded error text. Return `0` after every selected
site has a persisted outcome, even when an outcome is `error` or `unavailable`;
return `2` for invalid arguments, missing catalog data, validation errors, or
database errors through the existing `main` error handling.

- [ ] **Step 4: Document manual collection and freshness rules**

Add this command to README:

```bash
uv run padel-availability collect-playtomic \
  --database var/catalog.sqlite3 \
  --sources data/playtomic_sources.json \
  --days 14
```

Document that it is read-only, public-source-only, manual, sequential, and
that `error`/`unavailable` keeps the previous successful snapshot as stale.
Document that the static inventory report is not yet an availability report.

- [ ] **Step 5: Run the CLI, report, and complete offline suites**

Run:

```bash
uv run pytest tests/test_cli_availability.py tests/test_report.py -q
uv run ruff format --check .
uv run ruff check .
uv run pyright
```

Expected: PASS without network requests in tests.

- [ ] **Step 6: Commit the CLI slice**

```bash
git add src/padel_availability/cli.py tests/test_cli_availability.py README.md
git commit -m "feat: add manual Playtomic collection command"
```

### Task 6: Final Verification And Reviewable Artifacts

**Files:**
- Modify: `reports/research-notes.md` only if the source manifest research changes a current booking-source note.
- Create: no generated database or cache files.

- [ ] **Step 1: Run the complete offline suite**

Run:

```bash
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest
```

Expected: all commands pass without network access, credentials, or generated
SQLite files appearing in `git status`.

- [ ] **Step 2: Validate source coverage and data boundaries**

Run a Python assertion harness that loads `data/verified_locations.json` and
`data/playtomic_sources.json`, asserts the five exact location IDs, checks all
source timestamps end in `Z`, and confirms no source row contains credentials,
cookies, authorization headers, or private URLs. Run the fixture-backed
collector and assert each selected location has exactly one persisted outcome.

- [ ] **Step 3: Inspect deterministic CLI behavior**

Run:

```bash
uv run padel-availability collect-playtomic --help
uv run padel-availability collect-playtomic --database var/catalog.sqlite3 --days 14
git status --short
git diff --check
git diff --stat
```

The real collection command may report source-specific `error` or
`unavailable` outcomes; it must not create reservations or require credentials.
Do not commit the generated database.

- [ ] **Step 4: Request final code review**

Review the full diff for public-only access, stale snapshot preservation,
timezone correctness, per-site isolation, deterministic persistence, and
absence of browser/authentication code before considering the connector slice
complete.
