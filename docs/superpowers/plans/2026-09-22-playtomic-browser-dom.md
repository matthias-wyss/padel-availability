# Playtomic Browser DOM Transport Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a public Playwright/Chromium DOM transport that collects visible Playtomic slots when no public JSON feed exists.

**Architecture:** Keep the existing standard-library JSON connector and add a browser transport selected by each manifest row. The browser transport owns temporary Playwright contexts and emits transport-neutral slot observations; the existing availability models, SQLite persistence, collector, stale projection, and CLI summary remain the canonical downstream path.

**Tech Stack:** Python 3.12, Playwright Python sync API, Chromium, `sqlite3`, `datetime`, `zoneinfo`, `json`, `html.parser`, pytest fixtures, Ruff, Pyright, and `uv`. Playwright is optional for the static catalog and installed only through a browser dependency group.

## Global Constraints

- No account, login, payment, reservation, cancellation, or remote mutation.
- No persistent cookies, storage state, private tokens, or authorization headers; destroy the temporary browser context after each site.
- No CAPTCHA interaction, anti-bot bypass, rate-limit evasion, proxy rotation, fingerprint spoofing, or stealth plugin.
- No scheduler, daemon, web UI, or external headless-browser service.
- No live network request in the default test suite.
- A login page, CAPTCHA, access block, missing browser executable, timeout, or unknown DOM shape produces an explicit `error` or `unavailable` run.
- Cover exactly `padel-station`, `gva-palexpo`, `padel-parc-etoy`, `padel-parc-preverenges`, and `vaudoise-arena`.
- Preserve `Europe/Zurich` local dates, UTC `Z` persisted instants, explicit `available`/`unavailable`/`unknown` states, stale snapshots, and deterministic CLI output.
- Keep the standard-library JSON transport working for future verified public JSON sources.
- Do not commit generated SQLite files, browser profiles, caches, credentials, or Playwright downloads.

---

## File Map

Create:

- `src/padel_availability/connectors/playtomic_browser.py`: browser lifecycle, public-page navigation, DOM observation extraction, and observation normalization.
- `tests/fixtures/playtomic/dom/padel-station.html`: sanitized DOM fixture.
- `tests/fixtures/playtomic/dom/gva-palexpo.html`: sanitized DOM fixture.
- `tests/fixtures/playtomic/dom/padel-parc-etoy.html`: sanitized DOM fixture.
- `tests/fixtures/playtomic/dom/padel-parc-preverenges.html`: sanitized DOM fixture.
- `tests/fixtures/playtomic/dom/vaudoise-arena.html`: sanitized DOM fixture.
- `tests/test_playtomic_browser.py`: offline DOM extraction, normalization, and browser failure tests.

Modify:

- `pyproject.toml`: add the optional `browser` dependency group containing `playwright>=1.45,<2`.
- `src/padel_availability/connectors/playtomic.py`: add source `transport` validation and keep JSON transport behavior explicit.
- `src/padel_availability/connectors/__init__.py`: export the browser connector API.
- `data/playtomic_sources.json`: mark the five current rows as `transport: "browser_dom"` and `status: "public"` with their booking URLs.
- `src/padel_availability/collector.py`: select JSON or browser transport per source while preserving per-site transactions and errors.
- `tests/test_playtomic.py`: update manifest fixtures and JSON transport assertions.
- `tests/test_collector.py`: add injected browser-transport success/error/stale cases.
- `src/padel_availability/cli.py`: keep `collect-playtomic` behavior and improve the missing-browser error text only if needed.
- `tests/test_cli_availability.py`: cover browser transport selection without launching Chromium.
- `README.md`: document optional installation, Chromium installation, and the explicit live smoke command.

## Interfaces Between Tasks

Task 1 produces the manifest and observation contract:

```python
TransportKind = Literal["json", "browser_dom"]

@dataclass(frozen=True, slots=True)
class PlaytomicSource:
    location_id: str
    booking_url: str
    transport: TransportKind
    availability_url_template: str | None
    checked_at: str
    status: Literal["public", "unavailable"]

@dataclass(frozen=True, slots=True)
class BrowserSlotObservation:
    external_id: str | None
    court_label: str | None
    starts_at: str
    ends_at: str
    status: Literal["available", "unavailable", "unknown"]

def parse_browser_observations(
    observations: Sequence[BrowserSlotObservation],
    *,
    location_id: str,
    run_id: str,
    window_start: date,
    window_end: date,
) -> tuple[AvailabilitySlot, ...]: ...
```

Task 2 produces the browser connector:

```python
class PlaytomicBrowserConnector:
    def collect(
        self,
        location: LocationRecord,
        source: PlaytomicSource,
        *,
        run_id: str,
        window_start: date,
        window_end: date,
        collected_at: str,
    ) -> AvailabilityResult: ...
```

The connector accepts an injected browser factory or page driver in tests so
the default suite never imports or launches Chromium.

### Task 1: Add Browser Source Metadata And Offline Observation Contract

**Files:**

- Modify: `pyproject.toml`
- Modify: `src/padel_availability/connectors/playtomic.py`
- Modify: `data/playtomic_sources.json`
- Modify: `tests/test_playtomic.py`
- Create: `tests/test_playtomic_browser.py`

- [ ] **Step 1: Write failing manifest and observation tests**

Add tests for the new source shape and immutable observation:

```python
def test_browser_source_requires_no_json_url() -> None:
    source = PlaytomicSource(
        "padel-station",
        "https://playtomic.com/fr/clubs/padel-station1",
        "browser_dom",
        None,
        "2026-09-22T00:00:00Z",
        "public",
    )

    assert source.transport == "browser_dom"
    assert source.availability_url_template is None


def test_browser_observation_rejects_blank_times() -> None:
    with pytest.raises(ModelError, match="starts_at"):
        BrowserSlotObservation(None, "Court 1", "", "2026-09-22T19:00:00+02:00", "available")
```

Update the manifest coverage test to require `transport == "browser_dom"` for
the five checked public rows. Keep a JSON source test with a URL template so
the existing transport remains valid.

- [ ] **Step 2: Run the focused tests and verify the expected failure**

Run:

```bash
uv run pytest tests/test_playtomic.py tests/test_playtomic_browser.py -q
```

Expected: FAIL because the transport field and browser observation type do not
exist yet.

- [ ] **Step 3: Add the optional browser dependency and source validation**

Add this dependency group without changing runtime dependencies:

```toml
[dependency-groups]
browser = [
    "playwright>=1.45,<2",
]
```

Extend `PlaytomicSource` with `transport: Literal["json", "browser_dom"]` in
the exact field order shown in the interface block above.
Validate these relationships:

- `json` + `public` requires exactly one `{window_start}` and one
  `{window_end}` in `availability_url_template`;
- `browser_dom` + `public` requires a null `availability_url_template`;
- `unavailable` requires a null template for either transport;
- unknown fields, transports, statuses, URLs, and timestamps remain rejected.

Use the existing manifest field order and update every checked row with
`transport: "browser_dom"` and `status: "public"`.

- [ ] **Step 4: Implement the immutable observation and pure normalizer**

Create `BrowserSlotObservation` with the same non-blank optional ID/label and
offset-aware timestamp validation used by the availability models. Implement
`parse_browser_observations` by converting observations to
`AvailabilitySlot` values through `local_to_utc`, filtering the half-open local
date window, using external IDs or the existing deterministic hash, and
rejecting conflicting duplicate IDs. Keep explicit states and sort by UTC
start, UTC end, court label, and slot key.

- [ ] **Step 5: Run the focused offline tests and commit**

Run:

```bash
uv run pytest tests/test_playtomic.py tests/test_playtomic_browser.py -q
uv run ruff check src/padel_availability/connectors tests/test_playtomic*.py
```

Expected: PASS without Chromium or network access.

```bash
git add pyproject.toml src/padel_availability/connectors/playtomic.py data/playtomic_sources.json tests/test_playtomic.py tests/test_playtomic_browser.py
git commit -m "feat: add browser Playtomic source metadata"
```

### Task 2: Implement Public DOM Extraction And Browser Lifecycle

**Files:**

- Create: `src/padel_availability/connectors/playtomic_browser.py`
- Create: five `tests/fixtures/playtomic/dom/*.html` files
- Modify: `tests/test_playtomic_browser.py`
- Modify: `src/padel_availability/connectors/__init__.py`

- [ ] **Step 1: Inspect the public pages with a temporary browser and freeze sanitized DOM fixtures**

Install the optional runtime outside the repository:

```bash
uv sync --group browser
uv run playwright install chromium
```

Open each checked booking URL in a new incognito context, without login or
storage state. Capture only the minimal visible DOM needed for the date control,
slot card, court label, time range, external ID, and explicit state. Remove
personal data, cookies, tokens, hidden application state, and unrelated HTML.
The five checked-in fixtures must contain the actual attributes and text used
by the extractor, not a guessed schema.

- [ ] **Step 2: Write failing extractor tests from the captured fixtures**

For every fixture, assert that the extractor returns at least one observation
when the fixture contains a visible slot, preserves the court and state, and
returns an empty tuple for an explicit no-slots page. Add malformed DOM,
ambiguous time, disabled-slot, and login/CAPTCHA marker tests.

Run:

```bash
uv run pytest tests/test_playtomic_browser.py -q
```

Expected: FAIL because the browser connector and extractor do not exist.

- [ ] **Step 3: Implement the browser page driver with bounded public navigation**

Implement a synchronous Playwright driver that:

1. lazily imports `sync_playwright`;
2. launches Chromium headless with no user-data directory;
3. creates a fresh context for one location;
4. navigates only to the manifest `booking_url`;
5. waits for the visible public booking view with a finite timeout;
6. selects each requested date through the observed visible date control or
   public URL state;
7. evaluates only visible DOM and accessibility attributes to produce
   `BrowserSlotObservation` values;
8. closes the page/context even when extraction fails.

The extractor must not read script tags, local storage, cookies, network
responses, authorization state, or hidden React/application state. Use the
captured DOM contract, explicit English/French availability labels, and
offsets derived from `Europe/Zurich` for the requested local date. If a visible
time range, date control, or state cannot be parsed unambiguously, raise
`PlaytomicBrowserError`; do not infer a duration or availability.

- [ ] **Step 4: Map browser outcomes to availability results**

Return `success` with normalized slots for a valid page, including zero slots
when the page explicitly shows no slots. Return `unavailable` only for an
explicit public unavailable state. Convert browser launch/navigation/DOM
errors to bounded `PlaytomicSourceError` text so the collector persists an
`error` run. Never catch `BaseException` or silently turn an unknown page into
success zero.

- [ ] **Step 5: Run browser tests without a live page and commit**

Run:

```bash
uv run pytest tests/test_playtomic_browser.py -q
uv run ruff format --check src/padel_availability/connectors tests/test_playtomic_browser.py
uv run pyright src/padel_availability/connectors/playtomic_browser.py
```

Expected: PASS using sanitized fixtures and injected page/browser fakes; no
network request is made by the tests.

```bash
git add src/padel_availability/connectors/playtomic_browser.py src/padel_availability/connectors/__init__.py tests/fixtures/playtomic/dom tests/test_playtomic_browser.py
git commit -m "feat: scrape public Playtomic DOM"
```

### Task 3: Integrate Browser Transport With Sequential Collection

**Files:**

- Modify: `src/padel_availability/collector.py`
- Modify: `tests/test_collector.py`
- Modify: `src/padel_availability/connectors/__init__.py`

- [ ] **Step 1: Add failing injected-browser collector tests**

Add a fake browser connector that returns two normalized slots for one source,
an explicit unavailable result for another, and a browser error for a third.
Assert that `collect_playtomic` selects the browser transport from the source
row, saves each run immediately, continues to the remaining sites, sorts
outcomes by location ID, and exposes the previous success as stale after a
second browser error.

- [ ] **Step 2: Run collector tests and verify the expected failure**

Run: `uv run pytest tests/test_collector.py -q`

Expected: FAIL because the collector currently always constructs the JSON
connector and does not accept browser transport injection.

- [ ] **Step 3: Implement transport selection without changing the public API**

Keep `collect_playtomic`'s existing arguments and add one optional injected
browser factory used only by tests. Create the browser connector once when a
selected source uses `browser_dom`; keep JSON sources on the existing
`PlaytomicConnector`. For each location, call the selected connector and
immediately call `save_availability_result`. Catch only the documented browser
and source errors, continue sequentially, and preserve the existing run ID,
window, outcome sorting, and stale semantics.

- [ ] **Step 4: Run collector, database, and inventory suites and commit**

Run:

```bash
uv run pytest tests/test_collector.py tests/test_database.py tests/test_inventory.py -q
```

Expected: PASS with no browser launch in the default suite.

```bash
git add src/padel_availability/collector.py tests/test_collector.py src/padel_availability/connectors/__init__.py
git commit -m "feat: collect browser Playtomic snapshots"
```

### Task 4: Wire CLI, Documentation, And Offline Acceptance Tests

**Files:**

- Modify: `src/padel_availability/cli.py`
- Modify: `tests/test_cli_availability.py`
- Modify: `README.md`

- [ ] **Step 1: Add failing CLI tests**

Add tests that monkeypatch the collector/browser boundary and assert the
existing command prints deterministic `status`, `slots`, `window`, `error`, and
`last_success` fields for browser success, error, unavailable, and stale cases.
Add a missing-Playwright error test that returns exit code 2 with installation
guidance. Do not launch Chromium or call the network.

- [ ] **Step 2: Implement the smallest CLI/documentation changes**

Keep `collect-playtomic --database`, `--sources`, `--location-id`, and `--days`
unchanged. The command reads the manifest transport, persists results through
the existing collector, and prints the already-defined freshness field. Add
README instructions:

```bash
uv sync --group browser
uv run playwright install chromium
uv run padel-availability collect-playtomic \
  --database var/catalog.sqlite3 \
  --sources data/playtomic_sources.json \
  --days 14
```

Document that collection is public/read-only/manual/sequential, browser state
is ephemeral, CAPTCHA/login pages become explicit errors, and the static
inventory report remains separate.

- [ ] **Step 3: Run CLI/report suites and commit**

Run:

```bash
uv run pytest tests/test_cli_availability.py tests/test_report.py -q
uv run ruff check .
uv run pyright
```

Expected: PASS without browser launch or network requests.

```bash
git add src/padel_availability/cli.py tests/test_cli_availability.py README.md
git commit -m "docs: document browser Playtomic collection"
```

### Task 5: Live Smoke Verification And Final Review

**Files:**

- Modify: `reports/research-notes.md` only if the live public-page result changes source notes.
- Create: no generated database, browser profile, cache, or credential file.

- [ ] **Step 1: Run complete offline verification**

Run:

```bash
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest
git diff --check
```

Expected: all offline checks pass and no generated runtime artifacts appear in
`git status`.

- [ ] **Step 2: Run an explicit public smoke test one location at a time**

After installing Chromium, run:

```bash
uv run padel-availability collect-playtomic \
  --database /tmp/padel-availability-smoke.sqlite3 \
  --sources data/playtomic_sources.json \
  --location-id padel-station \
  --days 2
```

Repeat for the other four IDs. Inspect only the CLI outcome and persisted
normalized slots; do not save the browser profile or commit the temporary
database. If a page blocks access or exposes no parseable public DOM, preserve
the explicit error/unavailable result rather than bypassing it.

- [ ] **Step 3: Review the full diff and push**

Review public-only access, ephemeral browser state, no CAPTCHA bypass, DOM
truthfulness, timezone correctness, stale preservation, deterministic output,
and absence of generated artifacts. Then inspect `git status`, `git diff`, and
`git log --oneline -10`, stage only intended files, commit any remaining
changes, and push the current branch to its configured remote.
