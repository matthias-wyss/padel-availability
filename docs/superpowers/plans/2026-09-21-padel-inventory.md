# Padel Inventory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first working slice of the Geneva-to-Lausanne padel catalog: import all supplied candidates, verify public facts and sources, detect duplicates conservatively, persist the result in SQLite, and generate a readable inventory report.

**Architecture:** A small Python package owns typed inventory records, SQLite persistence, conservative candidate matching, provenance, and report generation. A tracked JSON file contains the verified public catalog; SQLite is generated for local reads and later availability data. Real availability connectors and the web UI are separate slices and are not implemented by this plan.

**Tech Stack:** Python 3.12, `sqlite3`, `json`, `dataclasses`, `pytest`, Ruff, Pyright, and `uv`. No runtime dependency is required for the inventory slice.

## Global Constraints

- Keep the project isolated at `/home/agentops/workspace/projects/padel-availability`.
- Keep all default tests offline and deterministic.
- Use one canonical record per physical site; AIRPAD's four sites remain separate records.
- Preserve original candidate names and aliases; never discard an input entry during deduplication.
- Represent missing facts as `unknown`, never as `no`.
- Require source URL, verification date, evidence note, and confidence for recorded external facts.
- Do not use personal credentials, cookies, sessions, or private account data in this slice.
- Do not automate reservations, payments, CAPTCHA solving, authentication bypass, or rate-limit bypass.
- Do not infer that a site is fully booked from an incomplete or inaccessible source.
- Store all verification timestamps as timezone-aware UTC timestamps; preserve source-local opening hours as text until availability normalization exists.
- Do not commit generated databases, caches, credentials, or local runtime state; the tracked JSON catalog and Markdown report are the reviewable data artifacts.
- Do not commit implementation changes automatically unless the user explicitly requests a commit.

---

## File Map

Create the following files:

- `pyproject.toml`: package metadata, console script, and development tooling.
- `.gitignore`: virtual environments, caches, local databases, secrets, and generated runtime files.
- `README.md`: setup, inventory build commands, data rules, and current limitations.
- `src/padel_availability/__init__.py`: package version.
- `src/padel_availability/models.py`: frozen dataclasses and constrained literal values.
- `src/padel_availability/database.py`: SQLite schema, connection setup, and repository writes/reads.
- `src/padel_availability/canonicalize.py`: text normalization and duplicate suggestions without automatic merges.
- `src/padel_availability/inventory.py`: JSON loading, validation, and catalog build orchestration.
- `src/padel_availability/report.py`: deterministic Markdown and JSON report rendering.
- `src/padel_availability/cli.py`: initial command help, then `init-db`, `import-candidates`, `build-catalog`, and `report` commands.
- `data/candidates.json`: the original 29 candidate entries exactly as supplied, including source wording.
- `data/verified_locations.json`: the verified canonical facts and provenance collected from public sources.
- `reports/research-notes.md`: per-candidate source and duplicate decisions from the manual research pass.
- `reports/inventory.md`: generated review report for the current verification run.
- `tests/test_models.py`: model validation tests.
- `tests/test_database.py`: schema and persistence tests.
- `tests/test_canonicalize.py`: normalization and conservative duplicate suggestion tests.
- `tests/test_inventory.py`: candidate and verified-catalog validation tests.
- `tests/test_report.py`: deterministic report tests.

Do not create scraper, browser automation, authentication, or frontend files in this slice.

## Task 1: Create the Python project foundation

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `README.md`
- Create: `src/padel_availability/__init__.py`
- Create: `src/padel_availability/cli.py`
- Create: `tests/test_models.py`

**Interfaces:**
- Produces the installable package `padel_availability` and console command `padel-availability`.
- Produces a clean test command: `uv run pytest`.

- [ ] **Step 1: Write the failing package smoke test**

```python
from padel_availability import __version__


def test_package_exposes_version() -> None:
    assert __version__ == "0.1.0"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_models.py -q`

Expected: FAIL because the package and project environment do not exist yet.

- [ ] **Step 3: Add the minimum project files**

Use this project configuration:

```toml
[build-system]
requires = ["hatchling>=1.25,<2"]
build-backend = "hatchling.build"

[project]
name = "padel-availability"
version = "0.1.0"
description = "Verified padel club catalog for the Geneva to Lausanne region"
requires-python = ">=3.12"
dependencies = []

[project.scripts]
padel-availability = "padel_availability.cli:main"

[dependency-groups]
dev = [
    "pyright>=1.1,<2",
    "pytest>=8.3,<9",
    "ruff>=0.6,<1",
]

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.ruff]
line-length = 100
src = ["src"]

[tool.pyright]
include = ["src", "tests"]
typeCheckingMode = "strict"
```

Set `src/padel_availability/__init__.py` to:

```python
__version__ = "0.1.0"
```

Set `src/padel_availability/cli.py` to this installable foundation; later tasks add subcommands without changing the entry point:

```python
import argparse


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="padel-availability",
        description="Build and inspect the verified padel inventory.",
    )
    parser.parse_args()
    parser.print_help()
```

Use this `.gitignore` content:

```gitignore
.venv/
__pycache__/
.pytest_cache/
.ruff_cache/
.pyright/
.worktrees/
var/
*.sqlite3
*.sqlite3-*
.env
.env.*
!.env.example
```

The README must state that this slice is an inventory catalog, not an automatic booking service, and show:

```bash
uv sync --dev
uv run pytest
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv sync --dev && uv run pytest tests/test_models.py -q`

Expected: PASS.

- [ ] **Step 5: Run the static checks**

Run: `uv run ruff format --check . && uv run ruff check . && uv run pyright`

Expected: all checks pass, with no source or test file excluded from the configured paths.

## Task 2: Define inventory models and the SQLite schema

**Files:**
- Create: `src/padel_availability/models.py`
- Create: `src/padel_availability/database.py`
- Create: `tests/test_models.py`
- Create: `tests/test_database.py`

**Interfaces:**
- `models.py` produces `CandidateEntry`, `CourtGroup`, `SourceEvidence`, `LocationRecord`, `CandidateMatch`, and `VerificationRun`.
- `database.py` produces `connect(path: Path) -> sqlite3.Connection`, `initialize(connection: sqlite3.Connection) -> None`, `insert_candidates(connection: sqlite3.Connection, entries: Sequence[CandidateEntry]) -> None`, `upsert_location(connection: sqlite3.Connection, location: LocationRecord) -> None`, `insert_evidence(connection: sqlite3.Connection, location_id: str, evidence: SourceEvidence) -> None`, `record_candidate_match(connection: sqlite3.Connection, match: CandidateMatch) -> None`, `list_locations(connection: sqlite3.Connection) -> tuple[LocationRecord, ...]`, `list_candidate_matches(connection: sqlite3.Connection) -> tuple[CandidateMatch, ...]`, and `create_verification_run(connection: sqlite3.Connection, run: VerificationRun) -> None`.

- [ ] **Step 1: Write model validation tests**

Test the exact allowed values and required fields:

```python
import pytest

from padel_availability.models import LocationRecord, ModelError


def test_unknown_is_valid_but_other_tri_state_values_are_rejected() -> None:
    record = LocationRecord(
        location_id="example-geneve",
        canonical_name="Example Padel",
        municipality="Geneva",
        candidate_ids=("example",),
        access_kind="public",
        membership_required="unknown",
        public_booking="unknown",
        racket_rental="unknown",
        locker_rooms="unknown",
        booking_account_required="unknown",
        verification_status="to_verify",
        court_groups=(),
        aliases=(),
        evidence=(),
        notes="",
    )
    assert record.membership_required == "unknown"

    with pytest.raises(ModelError):
        LocationRecord.from_mapping({**record.to_mapping(), "public_booking": "maybe"})
```

Test that a confirmed or probable location needs at least one evidence record and that a court group count is positive.

- [ ] **Step 2: Run the model tests to verify they fail**

Run: `uv run pytest tests/test_models.py -q`

Expected: FAIL because the model module does not exist.

- [ ] **Step 3: Implement frozen dataclasses and validation**

Use these stable values:

```python
class ModelError(ValueError):
    pass


TriState = Literal["yes", "no", "unknown"]
AccessKind = Literal["public", "members", "university", "conditions", "unknown"]
CoverStatus = Literal["indoor", "outdoor", "partially_covered", "seasonal", "unknown"]
VerificationStatus = Literal["confirmed", "probable", "to_verify", "not_confirmed", "closed"]
EvidenceRelation = Literal["supports", "contradicts", "discovery"]
Confidence = Literal["confirmed", "probable", "to_verify"]
```

Implement:

```python
@dataclass(frozen=True, slots=True)
class CandidateEntry:
    candidate_id: str
    raw_name: str
    municipality: str
    courts_text: str | None
    type_text: str | None
    access_text: str | None


@dataclass(frozen=True, slots=True)
class CourtGroup:
    label: str
    count: int
    format: str | None
    cover_status: CoverStatus


@dataclass(frozen=True, slots=True)
class SourceEvidence:
    url: str
    source_type: str
    title: str
    checked_at: str
    fact_key: str
    relation: EvidenceRelation
    evidence: str
    confidence: Confidence


@dataclass(frozen=True, slots=True)
class LocationRecord:
    location_id: str
    canonical_name: str
    municipality: str
    candidate_ids: tuple[str, ...]
    access_kind: AccessKind
    membership_required: TriState
    public_booking: TriState
    racket_rental: TriState
    locker_rooms: TriState
    booking_account_required: TriState
    verification_status: VerificationStatus
    court_groups: tuple[CourtGroup, ...]
    aliases: tuple[str, ...]
    evidence: tuple[SourceEvidence, ...]
    notes: str
    brand: str | None = None
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    overall_cover_status: CoverStatus = "unknown"
    official_url: str | None = None
    booking_url: str | None = None
    booking_platform: str | None = None


@dataclass(frozen=True, slots=True)
class CandidateMatch:
    candidate_id: str
    location_id: str | None
    status: Literal["matched", "duplicate", "not_confirmed", "unresolved"]
    note: str


@dataclass(frozen=True, slots=True)
class VerificationRun:
    run_id: str
    started_at: str
    ended_at: str
    candidate_count: int
    error_count: int
    summary: str
```

`LocationRecord.from_mapping()` must reject missing required keys, invalid literals, non-positive court counts, malformed URLs, non-UTC timestamps, and `confirmed`/`probable` records with no evidence. `to_mapping()` must use stable JSON-compatible values. `SourceEvidence.checked_at` and `VerificationRun.started_at`/`ended_at` use ISO 8601 UTC strings ending in `Z`.

- [ ] **Step 4: Write SQLite schema tests**

The tests must create a temporary database, call `initialize`, insert one candidate and one location, close and reopen the database, and assert that values and evidence round-trip. Also assert that SQLite rejects `public_booking = 'maybe'` and a court count of zero.

- [ ] **Step 5: Run schema tests to verify they fail**

Run: `uv run pytest tests/test_database.py -q`

Expected: FAIL because the repository functions and schema do not exist.

- [ ] **Step 6: Implement the schema and repository**

`initialize` must create these tables with foreign keys enabled:

- `locations`: canonical site fields, tri-state access fields, URLs, status, dates, and notes;
- `court_groups`: one-to-many court descriptions with positive `count`;
- `location_aliases`: aliases linked to locations;
- `sources`: unique URL, source type, title, and checked timestamp;
- `location_evidence`: location/source relation, fact key, evidence, confidence;
- `candidate_entries`: original input values and optional matched location;
- `candidate_matches`: candidate status `matched`, `duplicate`, `not_confirmed`, or `unresolved`, with a note;
- `verification_runs`: run ID, UTC start/end, candidate count, error count, and summary.

`connect` must set `row_factory = sqlite3.Row`, enable `PRAGMA foreign_keys = ON`, and create parent directories before opening a non-memory path. All writes must use one transaction and parameterized SQL. `list_locations` must order by municipality and canonical name.

- [ ] **Step 7: Run model and schema tests**

Run: `uv run pytest tests/test_models.py tests/test_database.py -q`

Expected: PASS.

## Task 3: Add and import the 29 supplied candidate entries

**Files:**
- Create: `data/candidates.json`
- Create: `src/padel_availability/inventory.py`
- Modify: `src/padel_availability/database.py`
- Create: `tests/test_inventory.py`

**Interfaces:**
- `load_candidates(path: Path) -> tuple[CandidateEntry, ...]`.
- `import_candidates(connection: sqlite3.Connection, entries: Sequence[CandidateEntry]) -> None`.
- `validate_candidate_set(entries: Sequence[CandidateEntry]) -> None`.

- [ ] **Step 1: Write failing import tests**

Test that the fixture has exactly 29 entries, preserves the slash-separated names and accents from the supplied list, and rejects duplicate `candidate_id` values or empty municipalities.

```python
def test_supplied_candidate_set_contains_29_entries() -> None:
    entries = load_candidates(Path("data/candidates.json"))
    assert len(entries) == 29
    assert entries[0].raw_name == "AIRPAD Les Acacias"
    assert any(entry.raw_name == "L'Asphalte / Pointe de la Jonction" for entry in entries)
```

- [ ] **Step 2: Run the import tests to verify they fail**

Run: `uv run pytest tests/test_inventory.py -q`

Expected: FAIL because the candidate fixture and loader do not exist.

- [ ] **Step 3: Create the exact candidate fixture**

Create one JSON object per entry with fields `candidate_id`, `raw_name`, `municipality`, `courts_text`, `type_text`, and `access_text`. Use these names and municipalities:

| Candidate ID | Name | Municipality |
|---|---|---|
| `airpad-les-acacias` | AIRPAD Les Acacias | Genève |
| `airpad-la-praille` | AIRPAD La Praille | Lancy |
| `airpad-meyrin` | AIRPAD Meyrin | Meyrin |
| `airpad-plan-les-ouates` | AIRPAD Plan-les-Ouates | Plan-les-Ouates |
| `asphalte-jonction` | L'Asphalte / Pointe de la Jonction | Genève |
| `padel-station` | Padel Station | Chêne-Bourg |
| `maisonnex` | Centre sportif de Maisonnex | Meyrin |
| `cherpines` | Centre sportif des Cherpines | Plan-les-Ouates |
| `evaux` | Padel des Evaux | Onex |
| `vernier` | Tennis, badminton et padel de Vernier | Vernier |
| `bernex` | Court de padel / TC Bernex | Bernex |
| `fraisiers` | Padel REDSPORT-LANDAGORA / TC Fraisiers | Lancy |
| `csu-champel` | CSU Champel | Genève |
| `drizia-miremont` | Drizia-Miremont / Bout-du-Monde | Genève |
| `cologny` | Centre sportif de Cologny | Cologny |
| `collonge-bellerive` | Padel de Collonge-Bellerive | Collonge-Bellerive |
| `david-lloyd-geneva` | David Lloyd Country Club Geneva | Bellevue |
| `gva-palexpo` | GVA Padel / Palexpo | Grand-Saconnex |
| `mies-tannay` | Tennis Club Mies-Tannay | Mies/Tannay |
| `crans-vd` | Tennis Padel Crans VD | Crans-près-Céligny |
| `everness` | Everness | Chavannes-de-Bogis |
| `gland` | Padel Tennis Gland | Gland |
| `padel-parc-etoy` | Padel Parc Etoy | Etoy |
| `padel-parc-preverenges` | Padel Parc Préverenges | Préverenges |
| `padel-one-echandens` | Padel One Echandens | Echandens |
| `urban-padel-lausanne` | Urban Padel Lausanne | Lausanne |
| `ehl-padel-club` | EHL Padel Club | Lausanne |
| `vaudoise-arena` | Vaudoise aréna | Prilly |
| `green-club` | Green Club | Romanel-sur-Lausanne |

Copy the supplied court counts, type text, and access wording into the raw fields, including `À vérifier` where the source list used it. Do not turn those raw claims into verified facts at import time.

- [ ] **Step 4: Implement strict JSON loading and import**

`load_candidates` must reject non-object JSON, missing fields, duplicate IDs, blank names, and blank municipalities. `import_candidates` must be idempotent by `candidate_id` and must not overwrite a non-null `matched_location_id` with null.

- [ ] **Step 5: Run import and database tests**

Run: `uv run pytest tests/test_inventory.py tests/test_database.py -q`

Expected: PASS with all 29 candidates stored and recoverable.

## Task 4: Add conservative normalization and duplicate suggestions

**Files:**
- Create: `src/padel_availability/canonicalize.py`
- Create: `tests/test_canonicalize.py`

**Interfaces:**
- `normalize_text(value: str) -> str`.
- `candidate_signature(name: str, municipality: str) -> tuple[str, str]`.
- `suggest_duplicate_pairs(entries: Sequence[CandidateEntry]) -> tuple[tuple[str, str], ...]`.

- [ ] **Step 1: Write failing normalization tests**

```python
def test_normalize_text_handles_case_accents_and_punctuation() -> None:
    assert normalize_text("Vaudoise aréna") == "vaudoise arena"
    assert normalize_text("  Padel-Station / Chêne-Bourg  ") == "padel station chene bourg"


def test_duplicate_suggestions_do_not_merge_distinct_airpad_sites() -> None:
    entries = load_candidates(Path("data/candidates.json"))
    suggestions = suggest_duplicate_pairs(entries)
    assert ("airpad-les-acacias", "airpad-la-praille") not in suggestions
```

Add a fixture with two spelling variants of the same site in the same municipality and assert that it produces a suggestion, not an automatic match.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_canonicalize.py -q`

Expected: FAIL because normalization and suggestion functions do not exist.

- [ ] **Step 3: Implement standard-library normalization**

Use `unicodedata.normalize("NFKD", value)` followed by ASCII combining-mark removal, `casefold`, replacement of punctuation with spaces, whitespace collapse, and trimming. Build signatures from normalized name and municipality. Suggest pairs only when normalized municipality matches and `difflib.SequenceMatcher` ratio is at least `0.88`; return pairs sorted by candidate ID. Never mutate, delete, or merge records here.

- [ ] **Step 4: Run canonicalization tests**

Run: `uv run pytest tests/test_canonicalize.py -q`

Expected: PASS, including the distinct AIRPAD assertion.

## Task 5: Define the verified catalog format and catalog builder

**Files:**
- Create: `data/verified_locations.json`
- Modify: `src/padel_availability/inventory.py`
- Modify: `src/padel_availability/database.py`
- Create: `tests/test_inventory.py`

**Interfaces:**
- `load_locations(path: Path) -> tuple[LocationRecord, ...]`.
- `validate_verified_catalog(candidates: Sequence[CandidateEntry], locations: Sequence[LocationRecord]) -> None`.
- `build_catalog(connection: sqlite3.Connection, candidates: Sequence[CandidateEntry], locations: Sequence[LocationRecord], run: VerificationRun) -> None`.

- [ ] **Step 1: Write failing catalog validation tests**

Cover these rules:

```python
def test_catalog_requires_each_candidate_to_be_matched_or_explicitly_unconfirmed() -> None:
    candidates = (candidate("one"), candidate("two"))
    locations = (location_with_candidate("one"),)
    with pytest.raises(ModelError, match="two"):
        validate_verified_catalog(candidates, locations)


def test_confirmed_location_requires_external_evidence() -> None:
    record = location_with_status("confirmed", evidence=())
    with pytest.raises(ModelError, match="evidence"):
        validate_verified_catalog((candidate("one"),), (record,))
```

Define the helpers in the test module with complete typed values:

```python
def candidate(candidate_id: str) -> CandidateEntry:
    return CandidateEntry(candidate_id, f"Example {candidate_id}", "Geneva", None, None, None)


def location_with_candidate(candidate_id: str) -> LocationRecord:
    return LocationRecord(
        location_id=f"location-{candidate_id}",
        canonical_name=f"Example {candidate_id}",
        municipality="Geneva",
        candidate_ids=(candidate_id,),
        access_kind="public",
        membership_required="unknown",
        public_booking="unknown",
        racket_rental="unknown",
        locker_rooms="unknown",
        booking_account_required="unknown",
        verification_status="probable",
        court_groups=(),
        aliases=(),
        evidence=(
            SourceEvidence(
                url="https://example.test/location",
                source_type="official",
                title="Example location",
                checked_at="2026-09-21T00:00:00Z",
                fact_key="location.exists",
                relation="supports",
                evidence="The official page names the location.",
                confidence="probable",
            ),
        ),
        notes="",
    )


def location_with_status(status: VerificationStatus, evidence: tuple[SourceEvidence, ...]) -> LocationRecord:
    return LocationRecord(
        location_id="location-one",
        canonical_name="Example one",
        municipality="Geneva",
        candidate_ids=("one",),
        access_kind="unknown",
        membership_required="unknown",
        public_booking="unknown",
        racket_rental="unknown",
        locker_rooms="unknown",
        booking_account_required="unknown",
        verification_status=status,
        court_groups=(),
        aliases=(),
        evidence=evidence,
        notes="",
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_inventory.py -q`

Expected: FAIL because verified catalog loading and validation do not exist.

- [ ] **Step 3: Define the JSON shape and initial verified file**

Use a top-level object with `format_version: 1`, `verified_at: "2026-09-21"`, and `locations`. Each location object contains the `LocationRecord` fields, `candidate_ids`, `court_groups`, `aliases`, and `evidence`. Use explicit `unknown` values for any fact not confirmed by a public source. Use statuses as follows:

- `confirmed` when the physical site and key access/reservation facts are supported by an official source;
- `probable` when the site is corroborated but one material fact still relies on a secondary source;
- `to_verify` when the site is plausible but official confirmation or reservation access is missing;
- `not_confirmed` when the supplied candidate cannot be confirmed after the research pass;
- `closed` only when an authoritative source explicitly says it is closed.

The file must account for all 29 candidate IDs exactly once, either through `candidate_ids` on a canonical location or through an explicit `not_confirmed` candidate record. Duplicate candidates must point to one location and appear as aliases or candidate matches, never as a second physical location.

- [ ] **Step 4: Implement loader and transactional builder**

`load_locations` must validate `format_version`, ISO dates, unique `location_id`, unique candidate assignment, and all model constraints. `validate_verified_catalog` must reject omissions, ambiguous duplicate assignments, unsupported statuses, and confirmed/probable locations without evidence. `build_catalog` must run in one transaction, insert candidates, upsert locations and court groups, attach aliases, persist sources/evidence, record candidate matches, and finish one `verification_run` with the supplied `VerificationRun.run_id`.

The builder must be rerunnable: running it twice with the same JSON produces the same location rows and does not duplicate sources or evidence rows with the same `(location_id, url, fact_key, checked_at, evidence)` identity.

- [ ] **Step 5: Run catalog tests**

Run: `uv run pytest tests/test_inventory.py tests/test_database.py -q`

Expected: PASS.

## Task 6: Perform the public-source inventory research

**Files:**
- Modify: `data/verified_locations.json`
- Create: `reports/research-notes.md`

**Interfaces:**
- The research output is the validated `data/verified_locations.json`; no credentials or live booking sessions are part of this task.

- [ ] **Step 1: Check every supplied candidate against public sources**

For each of the 29 candidates, check in this order:

1. official club, operator, venue, or commune page;
2. official reservation page;
3. Association Cantonale Padel Genève or another official regional association;
4. official platform listing;
5. regional secondary source only as corroboration or discovery.

Use the seven supplied discovery references as leads, not as automatic proof: ACPGE, AIRPAD, Ville de Genève/L'Asphalte, TC Drizia-Miremont, Torpille, PadelHike, and Les Genevois. Verify the current page for every site rather than copying a regional table wholesale.

- [ ] **Step 2: Record facts without guessing**

For every material field, record a source evidence entry with URL, page title, `checked_at: "2026-09-21T00:00:00Z"`, fact key, supporting or contradicting relation, concise evidence text, and confidence. Record `unknown` when the page does not state a fact. Preserve conflicts in evidence and explain the chosen status in `notes`.

Check specifically:

- physical address and municipality;
- number of courts and doubles/singles grouping;
- indoor, outdoor, covered, or seasonal status;
- public access, membership, university conditions, or other restrictions;
- official and booking URLs;
- booking platform and account requirement;
- published price and duration facts when available;
- racket rental and changing-room information;
- published booking opening window, if any.

- [ ] **Step 3: Resolve duplicates conservatively**

Apply these decisions to the named ambiguous entries:

- keep each AIRPAD site separate;
- inspect whether `L'Asphalte / Pointe de la Jonction` is one site and preserve both names as aliases if confirmed;
- inspect whether `Padel REDSPORT-LANDAGORA / TC Fraisiers` is one site and preserve both names if confirmed;
- inspect whether `Drizia-Miremont / Bout-du-Monde` is one site and preserve both names if confirmed;
- do not merge a venue with a brand merely because both use the same booking platform;
- do not add Tennis Club Nyon to the 29-candidate catalog without a new explicit scope decision; it was deliberately removed from the supplied current list.

- [ ] **Step 4: Write research notes and review the JSON**

`reports/research-notes.md` must list each candidate, its canonical location ID or `not_confirmed` decision, primary source, booking URL status, unresolved fields, and duplicate decision. It must not contain credentials, cookies, or private URLs.

- [ ] **Step 5: Validate the research data offline**

Run: `uv run pytest tests/test_inventory.py -q`

Expected: PASS using only the saved JSON and fixtures; no test makes a network request.

## Task 7: Generate deterministic inventory reports and CLI commands

**Files:**
- Create: `src/padel_availability/report.py`
- Modify: `src/padel_availability/cli.py`
- Create: `tests/test_report.py`
- Modify: `README.md`

**Interfaces:**
- `render_markdown_report(locations: Sequence[LocationRecord], candidate_matches: Sequence[CandidateMatch], run: VerificationRun) -> str`.
- `render_json_report(locations: Sequence[LocationRecord], candidate_matches: Sequence[CandidateMatch], run: VerificationRun) -> str`.
- CLI commands:
  - `padel-availability init-db --database PATH`;
  - `padel-availability import-candidates --database PATH --input PATH`;
  - `padel-availability build-catalog --database PATH --candidates PATH --verified PATH --run-id ID`;
  - `padel-availability report --database PATH --output PATH`.

- [ ] **Step 1: Write failing report tests**

```python
def test_markdown_report_has_stable_sections_and_unknown_values() -> None:
    report = render_markdown_report(sample_locations(), sample_matches(), sample_run())
    assert report.index("## Summary") < report.index("## Locations")
    assert "Unknown" in report
    assert "https://example.test/booking" in report
    assert render_markdown_report(sample_locations(), sample_matches(), sample_run()) == report
```

Define the report fixtures with the public model types:

```python
def sample_locations() -> tuple[LocationRecord, ...]:
    return (
        LocationRecord(
            location_id="location-one",
            canonical_name="Example Padel",
            municipality="Geneva",
            candidate_ids=("one",),
            access_kind="public",
            membership_required="unknown",
            public_booking="unknown",
            racket_rental="unknown",
            locker_rooms="unknown",
            booking_account_required="unknown",
            verification_status="probable",
            court_groups=(),
            aliases=(),
            evidence=(
                SourceEvidence(
                    url="https://example.test/booking",
                    source_type="official",
                    title="Example booking",
                    checked_at="2026-09-21T00:00:00Z",
                    fact_key="booking.url",
                    relation="supports",
                    evidence="The official page links to booking.",
                    confidence="probable",
                ),
            ),
            notes="",
        ),
    )


def sample_matches() -> tuple[CandidateMatch, ...]:
    return (CandidateMatch("one", "location-one", "matched", "Official match"),)


def sample_run() -> VerificationRun:
    return VerificationRun("run-1", "2026-09-21T08:00:00Z", "2026-09-21T08:01:00Z", 1, 0, "ok")
```

Also test that source URLs are emitted as links, contradictions appear in a warnings section, and a `not_confirmed` candidate appears in the unresolved section.

- [ ] **Step 2: Run report tests to verify they fail**

Run: `uv run pytest tests/test_report.py -q`

Expected: FAIL because the report module does not exist.

- [ ] **Step 3: Implement deterministic report rendering**

The Markdown report must contain these sections in this order:

1. Summary with verification run ID, UTC timestamps, candidate count, location count, and error count;
2. Confirmed and probable locations;
3. Locations to verify or closed;
4. Duplicate and alias decisions;
5. Missing or unknown facts;
6. Source evidence and contradictions.

Sort locations by municipality then canonical name, sources by URL, and facts by field key. Render tri-state values in French as `Oui`, `Non`, and `Inconnu`, while keeping machine values in JSON/SQLite as `yes`, `no`, and `unknown`.

- [ ] **Step 4: Implement CLI and run it against a temporary database**

Use `argparse` from the standard library. Commands must return exit code 2 for invalid arguments or validation errors, and exit code 0 after successful database/report generation. Do not make CLI commands perform network requests.

Run:

```bash
uv run padel-availability init-db --database var/catalog.sqlite3
uv run padel-availability import-candidates --database var/catalog.sqlite3 --input data/candidates.json
uv run padel-availability build-catalog --database var/catalog.sqlite3 --candidates data/candidates.json --verified data/verified_locations.json --run-id inventory-2026-09-21
uv run padel-availability report --database var/catalog.sqlite3 --output reports/inventory.md
```

- [ ] **Step 5: Run report and CLI tests**

Run: `uv run pytest tests/test_report.py tests/test_inventory.py -q`

Expected: PASS, with a report containing all 29 candidates and no credentials.

## Task 8: Finish documentation and verification

**Files:**
- Modify: `README.md`
- Modify: `reports/inventory.md`

- [ ] **Step 1: Document the first-slice workflow**

README must include the exact commands for syncing, running tests, building the catalog, regenerating the report, and inspecting unresolved facts. It must explain that the catalog is read-only, source freshness is explicit, and availability scrapers are not included yet.

- [ ] **Step 2: Generate the committed reviewable artifacts**

Run the four CLI commands from Task 7 with `var/catalog.sqlite3` as the ignored local database and `reports/inventory.md` as the tracked Markdown output. Confirm that `reports/inventory.md` contains 29 candidate decisions and that every location link points to an official or explicitly labeled secondary source.

- [ ] **Step 3: Run the complete offline verification suite**

Run:

```bash
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest
```

Expected: all commands pass without network access, credentials, or generated SQLite files in `git status`.

- [ ] **Step 4: Inspect the final worktree**

Run:

```bash
git status --short
git diff --check
git diff --stat
```

Confirm that only source code, tests, the candidate/verified JSON, the report, README, and plan/spec documents are present. Do not commit unless the user explicitly asks for it.

## Completion Gate

This plan is complete when:

- all 29 supplied candidates are represented exactly once as matched, duplicate, or explicitly not confirmed;
- the SQLite catalog can be rebuilt from the tracked JSON files;
- duplicate suggestions are conservative and no record is silently removed;
- every confirmed or probable fact has source evidence and a verification date;
- unknown and contradictory facts remain visible;
- the Markdown report is deterministic and readable on a phone-sized screen;
- the default test suite is offline and passing;
- no booking, payment, CAPTCHA bypass, personal credential, or availability scraper has been added.
