# Matchpoint Evaux and Jonction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the public Padel Connect grids for Parc des Evaux and L'Asphalte / Pointe de la Jonction to the existing read-only Matchpoint collector.

**Architecture:** Extend the existing four-source Matchpoint manifest and static URL map with public `id=8` and `id=9` grid URLs. Reuse the current sequential browser connector and visible SVG parser, while adding a visible center-label check so a changed ID cannot silently collect Bernex. Update catalog evidence, tests, documentation, and run a four-location live smoke.

**Tech Stack:** Python `>=3.12`, Playwright `>=1.45,<2`, SQLite, pytest `>=8.3,<9`, Ruff `>=0.6,<1`, Pyright `>=1.1,<2`.

## Global Constraints

- Use exactly these new public URLs: `https://padelgeneva.matchpoint.com.es/Booking/Grid.aspx?id=8` for Evaux and `https://padelgeneva.matchpoint.com.es/Booking/Grid.aspx?id=9` for Jonction.
- Read only the visible public grid, visible attributes, and visible page content; do not use private endpoints, network responses, inline application state, browser profiles, cookies, local storage, credentials, or account sessions.
- The visible cookie `Decline` control may reject optional cookies in the ephemeral browser context; never accept optional cookies or persist consent.
- Do not log in, create accounts, click booking slots, reserve, pay, or persist participant names.
- Keep local calendar handling in `Europe/Zurich`, normalize stored instants to UTC, and preserve immediate persistence and stale-snapshot behavior.
- Add no dependencies and do not commit credentials, generated databases, cookies, browser profiles, or live participant data.
- Treat open matches as unavailable for full-court booking; never treat missing or malformed cells as available.

---

## File Map

- Modify `src/padel_availability/connectors/matchpoint.py` to define the four supported location IDs, exact booking URLs, and expected visible center labels.
- Modify `src/padel_availability/connectors/matchpoint_browser.py` to emit the visible center label and validate it when parsing a source result.
- Modify `data/matchpoint_sources.json` to contain exactly four public source rows.
- Modify `data/verified_locations.json` to replace the generic Evaux and Jonction booking links with the confirmed public grid URLs and add fact-specific evidence.
- Modify `tests/test_matchpoint.py` to cover exact four-source metadata and URL coverage.
- Modify `tests/test_matchpoint_browser.py` and create `tests/fixtures/matchpoint/dom/padelconnect-evaux.html` and `tests/fixtures/matchpoint/dom/padelconnect-jonction.html` for visible center and court-grid behavior.
- Modify `tests/test_collector.py` to exercise all four Matchpoint locations and the existing ordered sequential lifecycle.
- Modify `tests/test_inventory.py` to assert booking URL/platform evidence for all four Matchpoint records.
- Modify `README.md` and `reports/research-notes.md` to remove the stale “Evaux/Jonction not confirmed” wording and document the four-source manual command.
- Regenerate `reports/inventory.md` from a fresh local catalog after the catalog JSON changes; do not retain the generated SQLite database.
- No production changes are expected in `src/padel_availability/collector.py` or `src/padel_availability/cli.py`; their current set-driven source loading already handles the added IDs.

## Task 1: Expand the Strict Matchpoint Sources

**Files:**
- Modify: `src/padel_availability/connectors/matchpoint.py:19-26, 68-69, 94-96`
- Modify: `data/matchpoint_sources.json`
- Test: `tests/test_matchpoint.py:10-113`

**Interfaces:**
- Consumes: existing `MatchpointSource` and `load_matchpoint_sources(path: Path)`.
- Produces: `MATCHPOINT_LOCATION_IDS` containing `asphalte-jonction`, `bernex`, `evaux`, and `urban-padel-lausanne`; `MATCHPOINT_BOOKING_URLS` mapping each ID to its exact public URL.

- [ ] **Step 1: Extend the manifest tests before implementation.** Replace the two-source constants and helper URL map in `tests/test_matchpoint.py` with these exact values:

```python
BERNEX_URL = "https://padelgeneva.matchpoint.com.es/Booking/Grid.aspx"
EVAUX_URL = "https://padelgeneva.matchpoint.com.es/Booking/Grid.aspx?id=8"
JONCTION_URL = "https://padelgeneva.matchpoint.com.es/Booking/Grid.aspx?id=9"
URBAN_URL = "https://urbanpadellausanne.matchpoint.com.es/Booking/Grid.aspx"
```

Update the acceptance test to expect the sorted IDs `asphalte-jonction`, `bernex`, `evaux`, `urban-padel-lausanne`, four URLs, four `2026-09-26T00:00:00Z` timestamps, and four `public` statuses. Add the two new rows to the sorting and exact-coverage cases.

- [ ] **Step 2: Run the source tests and confirm the old implementation fails.**

Run: `env -u LD_LIBRARY_PATH -u FONTCONFIG_FILE .venv/bin/pytest -q tests/test_matchpoint.py`

Expected: FAIL because the current loader accepts exactly two rows and does not recognize the two new location IDs or URLs.

- [ ] **Step 3: Implement the four-source constants and strict coverage.** Change `MATCHPOINT_BOOKING_URLS` to:

```python
MATCHPOINT_BOOKING_URLS = {
    "asphalte-jonction": "https://padelgeneva.matchpoint.com.es/Booking/Grid.aspx?id=9",
    "bernex": "https://padelgeneva.matchpoint.com.es/Booking/Grid.aspx",
    "evaux": "https://padelgeneva.matchpoint.com.es/Booking/Grid.aspx?id=8",
    "urban-padel-lausanne": "https://urbanpadellausanne.matchpoint.com.es/Booking/Grid.aspx",
}
```

Keep `MATCHPOINT_LOCATION_IDS = frozenset(MATCHPOINT_BOOKING_URLS)`. Update loader error text from “exactly two rows” and “both Matchpoint locations” to four-source wording without changing validation behavior.

- [ ] **Step 4: Replace the manifest with exactly four rows.** Keep the existing Bernex and Urban rows, add Evaux and Jonction with the exact URLs above, set `checked_at` to `2026-09-26T00:00:00Z`, and set every row to `status: "public"`.

- [ ] **Step 5: Run the source tests and commit the isolated source change.**

Run: `env -u LD_LIBRARY_PATH -u FONTCONFIG_FILE .venv/bin/pytest -q tests/test_matchpoint.py`

Expected: PASS.

Commit only the source model, manifest, and source tests:

```bash
git add src/padel_availability/connectors/matchpoint.py data/matchpoint_sources.json tests/test_matchpoint.py
git commit -m "feat: add Evaux and Jonction Matchpoint sources"
```

## Task 2: Validate the Visible Center Before Parsing Slots

**Files:**
- Modify: `src/padel_availability/connectors/matchpoint.py`
- Modify: `src/padel_availability/connectors/matchpoint_browser.py:41-258, 371-429, 598-620`
- Modify: `tests/test_matchpoint_browser.py:27-167, 174-237, 280-515`
- Create: `tests/fixtures/matchpoint/dom/padelconnect-evaux.html`
- Create: `tests/fixtures/matchpoint/dom/padelconnect-jonction.html`

**Interfaces:**
- Consumes: `MatchpointSource.location_id`, `_MATCHPOINT_VISIBLE_DOM_SCRIPT`, and `parse_matchpoint_dom(payload, requested_date)`.
- Produces: `parse_matchpoint_dom(payload, requested_date, *, expected_center: str | None = None)` and a sanitized payload field `center` containing the visible `#labelCentro` text.

- [ ] **Step 1: Add failing center-validation tests.** Update `_payload()` to include a `center` field and update `_parse()` to accept an optional `expected_center`. Add these assertions:

```python
def test_matchpoint_parser_rejects_wrong_visible_center() -> None:
    with pytest.raises(ValueError, match="center"):
        _parse(
            _payload([], center="Bernex", empty_grid=True),
            REQUESTED_DATE,
            expected_center="Parc des Evaux",
        )
```

Add fixture assertions for the new public HTML files:

```python
def test_visible_evaux_grid_extracts_center_and_three_courts(browser: Browser) -> None:
    payload = _browser_payload(browser, "padelconnect-evaux.html")
    assert payload["center"] == "Parc des Evaux"
    assert payload["courts"] == ["Evaux 1", "Evaux 2", "Evaux 3"]
    assert "player_name" not in repr(payload)


def test_visible_jonction_grid_extracts_center_and_two_courts(browser: Browser) -> None:
    payload = _browser_payload(browser, "padelconnect-jonction.html")
    assert payload["center"] == "Jonction"
    assert payload["courts"] == ["Jonction 1", "Jonction 2"]
    assert "player_name" not in repr(payload)
```

The fixtures must contain only sanitized visible DOM structures, use the existing SVG classes (`.myReservas`, `.fondoCabecera`, `.celdaTxt`, `.buttonHora`, `.evento`), and include at least one available cell plus booked/open-match states and a variable duration for each new center.

- [ ] **Step 2: Run the browser tests and confirm they fail.**

Run: `env -u LD_LIBRARY_PATH -u FONTCONFIG_FILE .venv/bin/pytest -q tests/test_matchpoint_browser.py`

Expected: FAIL because the script does not yet return `center`, the fixtures do not exist, and the parser has no expected-center check.

- [ ] **Step 3: Emit only the visible center label.** In `_MATCHPOINT_VISIBLE_DOM_SCRIPT`, read `text(document.querySelector('#labelCentro'))` and add it as `center` in the returned sanitized mapping. Do not return visible body text, hidden state, participant fields, cookies, or network data.

- [ ] **Step 4: Add the expected-center contract.** Define this static mapping beside the Matchpoint source constants:

```python
MATCHPOINT_EXPECTED_CENTERS = {
    "asphalte-jonction": "Jonction",
    "bernex": "Bernex",
    "evaux": "Parc des Evaux",
    "urban-padel-lausanne": "Urban Padel Sàrl",
}
```

In `parse_matchpoint_dom`, when `expected_center` is provided, require `dom["center"]` to be exactly that string and raise `MatchpointBrowserError("visible Matchpoint center does not match requested location")` on missing or mismatched values. Keep existing callers/tests valid by making the keyword optional.

- [ ] **Step 5: Pass the expected center from the connector.** In `MatchpointBrowserConnector.collect`, look up `MATCHPOINT_EXPECTED_CENTERS[location.location_id]` and pass it to every `parse_matchpoint_dom` call. A source returning Bernex for `evaux` or `asphalte-jonction` must fail before availability slots are normalized.

- [ ] **Step 6: Update the connector test double for the new payload contract.** Make `_FakeMatchpointPage.evaluate()` include `center: "Bernex"` in every payload used by the existing connector lifecycle tests, and add a wrong-center case that returns `center: "Bernex"` for an Evaux source and expects `MatchpointBrowserError` before normalization.

- [ ] **Step 7: Add sanitized Evaux and Jonction DOM fixtures.** Base their structure on the existing Bernex fixture, but use the exact visible center labels and court labels above. Keep the fixtures offline and remove any participant or hidden application fields.

- [ ] **Step 8: Run browser tests and commit the parser guard.**

Run: `env -u LD_LIBRARY_PATH -u FONTCONFIG_FILE .venv/bin/pytest -q tests/test_matchpoint_browser.py`

Expected: PASS.

Commit only the parser, source constant, fixtures, and browser tests:

```bash
git add src/padel_availability/connectors/matchpoint.py src/padel_availability/connectors/matchpoint_browser.py tests/test_matchpoint_browser.py tests/fixtures/matchpoint/dom/padelconnect-evaux.html tests/fixtures/matchpoint/dom/padelconnect-jonction.html
git commit -m "feat: validate Matchpoint center selection"
```

## Task 3: Update Catalog Evidence and Inventory Assertions

**Files:**
- Modify: `data/verified_locations.json:138-173, 280-315`
- Modify: `tests/test_inventory.py:281-304`
- Modify: `reports/research-notes.md:18, 22`

**Interfaces:**
- Consumes: the existing `LocationRecord` evidence schema and `load_locations()` validation.
- Produces: exact booking URLs and `Padel Connect` platform evidence for `asphalte-jonction` and `evaux`.

- [ ] **Step 1: Extend the inventory assertion before editing data.** Add these entries to the `expected` mapping in `test_matchpoint_locations_have_current_booking_evidence`:

```python
"asphalte-jonction": (
    "https://padelgeneva.matchpoint.com.es/Booking/Grid.aspx?id=9",
    "Padel Connect",
),
"evaux": (
    "https://padelgeneva.matchpoint.com.es/Booking/Grid.aspx?id=8",
    "Padel Connect",
),
```

- [ ] **Step 2: Run the inventory assertion and confirm it fails.**

Run: `env -u LD_LIBRARY_PATH -u FONTCONFIG_FILE .venv/bin/pytest -q tests/test_inventory.py::test_matchpoint_locations_have_current_booking_evidence`

Expected: FAIL because Evaux still points to the generic Padel Connect site and Jonction still points to the Padel Academy homepage.

- [ ] **Step 3: Update the two catalog records without changing unrelated facts.** Set `booking_url` and `booking_platform` as follows:

| `location_id` | `booking_url` | `booking_platform` |
| --- | --- | --- |
| `asphalte-jonction` | `https://padelgeneva.matchpoint.com.es/Booking/Grid.aspx?id=9` | `Padel Connect` |
| `evaux` | `https://padelgeneva.matchpoint.com.es/Booking/Grid.aspx?id=8` | `Padel Connect` |

Add `official_platform` evidence checked at `2026-09-26T00:00:00Z` for each exact public grid, with `fact_key` values `location.booking_url` and `location.booking_platform`. Keep Evaux’s existing confirmed account-required fact and Jonction’s existing probable verification status unchanged.

- [ ] **Step 4: Refresh the two research-note booking statuses.** Record the exact public grid URLs in `reports/research-notes.md`; keep the existing source confidence and unresolved access/account facts explicit.

- [ ] **Step 5: Run inventory tests and commit the catalog slice.**

Run: `env -u LD_LIBRARY_PATH -u FONTCONFIG_FILE .venv/bin/pytest -q tests/test_inventory.py`

Expected: PASS.

Commit only the catalog, research notes, and inventory test:

```bash
git add data/verified_locations.json reports/research-notes.md tests/test_inventory.py
git commit -m "data: verify Evaux and Jonction Matchpoint grids"
```

## Task 4: Extend Collection Tests and User Documentation

**Files:**
- Modify: `tests/test_collector.py:259-340, 1234-1343`
- Modify: `README.md:116-135`
- Modify: `reports/inventory.md` by regenerating it from the catalog CLI

**Interfaces:**
- Consumes: the unchanged `collect_matchpoint()` signature and the four-source manifest.
- Produces: deterministic collection tests proving that all four locations are selected, persisted, and closed in order; documentation for the four-source manual command.

- [ ] **Step 1: Update collector fixtures and lifecycle expectations.** Change `matchpoint_locations()` to load `bernex`, `evaux`, `asphalte-jonction`, and `urban-padel-lausanne`. Update `test_matchpoint_collection_uses_exact_locations_and_zurich_window` to expect sorted collection order:

```python
[
    "open",
    "collect:asphalte-jonction",
    "collect:bernex",
    "collect:evaux",
    "collect:urban-padel-lausanne",
    "close",
]
```

Assert the four UTC-window-normalized date pairs, four successful outcomes, and four persisted availability runs. Update the startup-error test to expect four error outcomes and four persisted runs.

- [ ] **Step 2: Run collector tests and confirm the old helper fails.**

Run: `env -u LD_LIBRARY_PATH -u FONTCONFIG_FILE .venv/bin/pytest -q tests/test_collector.py -k matchpoint`

Expected: FAIL because the helper currently loads only Bernex and Urban and the source manifest still has two rows before the earlier tasks are present.

- [ ] **Step 3: Update the README command description.** Keep the existing `collect-matchpoint` command, but state that it reads Bernex, Parc des Evaux, Jonction, and Urban Padel Lausanne. Remove the stale sentence saying Evaux and Jonction need separately confirmed public grids. Keep the no-login, visible-DOM, `Decline`, open-match, stale-snapshot, and manual/sequential constraints.

- [ ] **Step 4: Regenerate the tracked inventory report without committing its database.** Use a temporary ignored database and the existing commands:

```bash
rm -f /tmp/opencode/matchpoint-evaux-jonction-catalog.sqlite3
.venv/bin/padel-availability init-db --database /tmp/opencode/matchpoint-evaux-jonction-catalog.sqlite3
.venv/bin/padel-availability build-catalog --database /tmp/opencode/matchpoint-evaux-jonction-catalog.sqlite3 --candidates data/candidates.json --verified data/verified_locations.json --run-id matchpoint-evaux-jonction-20260926
.venv/bin/padel-availability report --database /tmp/opencode/matchpoint-evaux-jonction-catalog.sqlite3 --output reports/inventory.md
```

Confirm the report contains the exact `id=8` and `id=9` booking links and no credentials, cookies, participant names, or generated database path.

- [ ] **Step 5: Run collector tests and commit documentation/test changes.**

Run: `env -u LD_LIBRARY_PATH -u FONTCONFIG_FILE .venv/bin/pytest -q tests/test_collector.py tests/test_cli_availability.py -k matchpoint`

Expected: PASS.

Commit only the collector tests, README, and regenerated report:

```bash
git add tests/test_collector.py README.md reports/inventory.md
git commit -m "docs: expose all public Matchpoint locations"
```

## Task 5: Run Full Verification and Four-Location Live Smoke

**Files:**
- Verify: all changed source, data, tests, and documentation files from Tasks 1-4.
- Do not add: `/tmp/opencode/matchpoint-evaux-jonction-live.sqlite3` or any other generated database.

**Interfaces:**
- Consumes: the four-row `data/matchpoint_sources.json` and `collect-matchpoint` CLI command.
- Produces: evidence that all four public grids succeed without login and expose the expected visible centers and court labels.

- [ ] **Step 1: Run formatting, lint, type checking, and the complete offline suite.**

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
/home/agentops/.local/bin/uv run pyright
env -u LD_LIBRARY_PATH -u FONTCONFIG_FILE .venv/bin/pytest -q
```

Expected: format check passes, Ruff reports `All checks passed!`, Pyright reports `0 errors`, and pytest reports all tests passed.

- [ ] **Step 2: Run the four-location no-login smoke.**

```bash
.venv/bin/padel-availability init-db --database /tmp/opencode/matchpoint-evaux-jonction-live.sqlite3
.venv/bin/padel-availability build-catalog --database /tmp/opencode/matchpoint-evaux-jonction-live.sqlite3 --candidates data/candidates.json --verified data/verified_locations.json --run-id matchpoint-live-20260926
env -u LD_LIBRARY_PATH -u FONTCONFIG_FILE .venv/bin/padel-availability collect-matchpoint --database /tmp/opencode/matchpoint-evaux-jonction-live.sqlite3 --sources data/matchpoint_sources.json --days 2
```

Expected: four `status=success` lines for `asphalte-jonction`, `bernex`, `evaux`, and `urban-padel-lausanne`. Inspect the persisted snapshots and confirm visible courts are:

```text
asphalte-jonction: Jonction 1, Jonction 2
bernex: Bernex Terrain Bleu, Bernex Terrain Vert
evaux: Evaux 1, Evaux 2, Evaux 3
urban-padel-lausanne: Terrain 1, Terrain 2, Terrain 3, Terrain 4
```

- [ ] **Step 3: Check the final diff and repository safety constraints.**

Run: `git diff --check`, `git status --short --branch`, and `git diff --stat HEAD~5..HEAD`.

Confirm no generated SQLite database, credentials, cookie state, participant names, or browser profile is tracked. Keep unrelated pre-existing worktree changes unstaged.

- [ ] **Step 4: Commit only a named Task 5 fix if verification required one.** If a fix was needed, inspect `git status --short`, stage only the exact source/test paths changed by that fix, and create the following commit; if no fix was needed, create no additional commit.

```bash
git commit -m "test: verify all Matchpoint public centers"
```
