# Repository Quality Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clear repository-wide Ruff formatting/lint and strict Pyright findings without adding exclusions or changing intended application behavior.

**Architecture:** First normalize formatting and apply safe Ruff fixes, then resolve remaining diagnostics by validation boundary and module. Keep runtime input validation; make decoded JSON types explicit before parsing and use public names for validators shared across modules.

**Tech Stack:** Python 3.12+, Ruff, Pyright strict mode, pytest, standard library.

## Global Constraints

- Keep the configured Ruff and Pyright checks repository-wide; do not add exclusions, relax strict mode, or suppress diagnostics just to reach a green result.
- Use Ruff formatting and safe import fixes first, reviewing the resulting diff before proceeding.
- Resolve remaining Ruff findings and Pyright diagnostics in small file-oriented batches. Preserve runtime validation at trust boundaries and existing error handling.
- Add or adjust a focused test if a correction changes behavior or fixes a demonstrable defect. Avoid tests that merely duplicate unchanged behavior.
- Do not intentionally refactor architecture or alter product behavior as part of lint/type cleanup.
- No package additions are planned.
- Do not discard or overwrite the current uncommitted Padel First work.

---

## File Map

- Format only: `docs/superpowers/plans/2026-09-21-padel-inventory.md`, `docs/superpowers/plans/2026-09-22-playtomic-availability-connector.md`, `docs/superpowers/plans/2026-09-22-playtomic-browser-dom.md`.
- Modify model and availability validation: `src/padel_availability/models.py`, `src/padel_availability/availability.py`.
- Modify candidate/catalog parsing: `src/padel_availability/inventory.py`.
- Modify availability source parsing and shared validator imports: `src/padel_availability/connectors/airpad.py`, `src/padel_availability/connectors/everness.py`, `src/padel_availability/connectors/padelfirst.py`, `src/padel_availability/connectors/playtomic.py`, `src/padel_availability/connectors/playtomic_browser.py`.
- Modify data access and report typing: `src/padel_availability/database.py`, `src/padel_availability/report.py`.
- Modify tests: `tests/test_models.py`, `tests/test_inventory.py`, `tests/test_availability.py`, `tests/test_airpad.py`, `tests/test_everness.py`, `tests/test_padelfirst.py`, `tests/test_playtomic.py`, `tests/test_database.py`, `tests/test_report.py`, `tests/test_cli_availability.py`, `tests/test_playtomic_browser.py`.
- Ruff formatting also touches: `src/padel_availability/cli.py`, `src/padel_availability/collector.py`, `src/padel_availability/connectors/airpad_browser.py`, `src/padel_availability/connectors/everness_browser.py`, `tests/test_airpad_browser.py`, `tests/test_collector.py`, `tests/test_everness_browser.py`.
- No changes to `pyproject.toml` or dependency declarations are planned.

## Task 1: Establish Baseline, Format, and Apply Safe Ruff Fixes

**Files:** the 24 paths in the file map currently reported by `ruff format --check .`, plus Ruff-fixable import/style locations in `src/` and `tests/`.

- [ ] **Step 1: Record fresh baseline output.**

Run:

```bash
uv run ruff check . --output-format concise
uv run ruff format --check .
uv run pyright
uv run --group dev --group browser pytest -q
```

Expected before remediation: Ruff reports 21 findings, formatting reports 24 files, Pyright reports 77 errors, and pytest passes. Record actual totals if they differ.

- [ ] **Step 2: Format supported source and Markdown files.**

Run `uv run ruff format .`, inspect `git diff --stat` and `git diff`, and confirm changes are formatting only. Keep unrelated existing Padel First work intact.

- [ ] **Step 3: Apply safe Ruff fixes.**

Run `uv run ruff check --fix .` without `--unsafe-fixes`. Inspect each changed import or expression, especially UTC timestamp parsing, then run `uv run ruff format --check .` and `uv run ruff check .` to list remaining diagnostics.

- [ ] **Step 4: Verify behavior after automatic edits.**

Run `uv run --group dev --group browser pytest -q`. Expected: the existing suite passes; any failure is investigated before further cleanup.

## Task 2: Resolve Remaining Ruff Findings

**Files:** `src/padel_availability/inventory.py`, `src/padel_availability/models.py`, `tests/test_availability.py`, and `tests/test_inventory.py`.

- [ ] **Step 1: Add regression assertions for invalid input types and URL ports.**

In `tests/test_inventory.py`, assert non-`CandidateEntry` values passed to `validate_candidate_set`, non-list candidate JSON, and non-object candidate rows raise `TypeError`. Use `cast(object, value)` where needed so the test itself is valid under strict Pyright.

In `tests/test_models.py`, add an invalid URL case with an empty hostname and explicit port, such as `http://:80`, and assert `ModelError`.

- [ ] **Step 2: Run the focused tests and confirm the new assertions fail.**

Run:

```bash
uv run pytest tests/test_inventory.py tests/test_models.py -q
```

Expected: failures show the current exception category and URL acceptance behavior before changes.

- [ ] **Step 3: Correct the remaining Ruff rules at their source.**

Raise `TypeError` for invalid runtime types in `validate_candidate_set()` and `load_candidates()`. Make `_url()` retain its malformed-port check while using the parsed port value in URL validation; reject a missing hostname when a port is present. In `tests/test_availability.py`, call the frozen run's `__setattr__` directly inside the existing `pytest.raises(FrozenInstanceError)` assertion rather than using `setattr()` with a constant attribute name.

- [ ] **Step 4: Verify Ruff and focused tests.**

Run:

```bash
uv run ruff check src/padel_availability/inventory.py src/padel_availability/models.py tests/test_availability.py tests/test_inventory.py
uv run pytest tests/test_availability.py tests/test_inventory.py tests/test_models.py -q
```

Expected: all six remaining Ruff findings across these files are clean and focused validation tests pass.

## Task 3: Make Model and Catalog Types Strict Without Dropping Validation

**Files:** `src/padel_availability/models.py`, `src/padel_availability/inventory.py`, `tests/test_models.py`, `tests/test_inventory.py`.

- [ ] **Step 1: Annotate decoded JSON as `object` and narrow it after shape checks.**

In `load_candidates()` and `load_locations()`, assign `json.load()` to an `object` local. After the existing list/dict checks, cast the validated outer object to `list[object]` or `dict[str, object]`; iterate rows as `object`, validate each row is a dict, then pass it to `LocationRecord.from_mapping()` as `Mapping[str, object]`.

- [ ] **Step 2: Make sequence validation accept and narrow untrusted values.**

Change `validate_candidate_set()` to accept `Sequence[object]` and retain its `isinstance(entry, CandidateEntry)` check. Change `validate_verified_catalog()` candidate/location sequences to `Sequence[object]`, retaining each existing type guard before accessing model fields. Raise `TypeError` for wrong Python object types; retain `ModelError` for invalid catalog facts and duplicate/assignment rules.

- [ ] **Step 3: Type model mapping collections and preserve constructor guards.**

In `_strings()`, narrow accepted tuple/list inputs to a typed `tuple[object, ...] | list[object]` before conversion. In `LocationRecord.from_mapping()`, cast already validated `groups` and `evidence` containers to sequences of `object` before constructing typed tuples. For Pyright's unnecessary-instance diagnostics in model `__post_init__` checks, assign externally constructible field values to `object` locals and validate those locals; do not delete the runtime guards.

- [ ] **Step 4: Update the context manager annotation.**

In `_catalog_transaction()`, import `Generator` from `collections.abc` and annotate the generator as `Generator[None, None, None]` so the `contextmanager` return type is current.

- [ ] **Step 5: Run model/catalog tests and targeted Pyright.**

Run:

```bash
uv run pytest tests/test_models.py tests/test_inventory.py -q
uv run pyright src/padel_availability/models.py src/padel_availability/inventory.py tests/test_models.py tests/test_inventory.py
```

Expected: tests pass and Pyright reports no errors in these files.

## Task 4: Publish Shared Validators and Clean Availability Types

**Files:** `src/padel_availability/models.py`, `src/padel_availability/availability.py`, `src/padel_availability/connectors/airpad.py`, `src/padel_availability/connectors/everness.py`, `src/padel_availability/connectors/padelfirst.py`, `src/padel_availability/connectors/playtomic.py`, `src/padel_availability/connectors/playtomic_browser.py`, `tests/test_availability.py`, `tests/test_airpad.py`, `tests/test_everness.py`, `tests/test_padelfirst.py`, `tests/test_playtomic.py`.

- [ ] **Step 1: Replace cross-module private validator names with public names.**

Rename shared `models.py` helpers `_text`, `_optional_text`, `_literal`, `_url`, and `_utc_timestamp` to `validate_text`, `validate_optional_text`, `validate_literal`, `validate_url`, and `validate_utc_timestamp`. Update all internal and external call sites listed above and remove only the corresponding `reportPrivateUsage` ignores. Keep `_optional_url` and `_strings` private because they are not shared outside `models.py`.

- [ ] **Step 2: Keep availability guards meaningful to strict typing.**

In `local_window()`, validate `now` and `horizon_days` through `object`-typed locals, then use the narrowed values for conversion and `timedelta`. In `AvailabilityResult` and `AvailabilitySnapshot`, validate `run`, `slots`, and each slot through `object`-typed locals and retain the ownership checks. Use `datetime.UTC` in UTC conversion and import the public shared validator names.

- [ ] **Step 3: Run source-contract and availability tests.**

Run:

```bash
uv run pytest tests/test_availability.py tests/test_airpad.py tests/test_everness.py tests/test_padelfirst.py tests/test_playtomic.py tests/test_collector.py -q
uv run pyright src/padel_availability/availability.py src/padel_availability/models.py src/padel_availability/connectors/airpad.py src/padel_availability/connectors/everness.py src/padel_availability/connectors/padelfirst.py src/padel_availability/connectors/playtomic.py src/padel_availability/connectors/playtomic_browser.py tests/test_availability.py
```

Expected: existing invalid-value cases still raise their documented errors, all caller imports are public, and targeted Pyright is clean.

## Task 5: Type Playtomic Manifest and Slot Parsing

**Files:** `src/padel_availability/connectors/playtomic.py`, `tests/test_playtomic.py`.

- [ ] **Step 1: Narrow manifest JSON at the input boundary.**

Store `json.loads()` as `object`, check for a dictionary, cast it to `dict[str, object]`, then validate `format_version` and `sources`. Cast the validated source list to `list[object]`; validate every row is a dictionary before reading fields. Preserve exact manifest fields, five-location coverage, and bounded `PlaytomicSourceError` messages.

- [ ] **Step 2: Narrow slot payload JSON before parsing.**

Validate payload as a dictionary and `slots` as a list, then cast to `dict[str, object]` and `list[object]`. Validate each slot dictionary as `dict[str, object]`; keep existing required-field, timestamp, deduplication, and window checks. After validating status membership, cast the narrowed value to `SlotStatus` for `AvailabilitySlot` construction. Compare location IDs as `frozenset[str]` against `_EXPECTED_LOCATION_IDS`.

- [ ] **Step 3: Run Playtomic regression tests and targeted Pyright.**

Run:

```bash
uv run pytest tests/test_playtomic.py tests/test_playtomic_browser.py -q
uv run pyright src/padel_availability/connectors/playtomic.py tests/test_playtomic.py
```

Expected: malformed inputs remain rejected, valid fixtures normalize identically, and the two files type-check cleanly.

## Task 6: Clean Report, Database, and Test Typing

**Files:** `src/padel_availability/database.py`, `src/padel_availability/report.py`, `tests/test_availability.py`, `tests/test_cli_availability.py`, `tests/test_playtomic_browser.py`.

- [ ] **Step 1: Fix the remaining standard-library and report annotations.**

Import `Sequence` from `collections.abc` in `database.py`. In `report.py`, declare `decisions` and `aliases` as `list[str]` before appending rendered lines.

- [ ] **Step 2: Remove private parser access from CLI default tests.**

Replace direct `cli._parser()` tests with calls to `cli.main()` while monkeypatching the public collector/source loader boundary already used by integration tests. Capture the default source path and default 14-day horizon passed to the collector; assert those values and the exit code.

- [ ] **Step 3: Type intentional invalid test values.**

In `tests/test_availability.py`, cast the intentionally invalid status string to the declared slot status type before constructing the object under `pytest.raises(ModelError)`. In `tests/test_playtomic_browser.py`, annotate `initial_payload` as `dict[str, object]` so the empty `dates` and `slots` lists do not infer `list[Unknown]`.

- [ ] **Step 4: Run focused tests and targeted Pyright.**

Run:

```bash
uv run pytest tests/test_database.py tests/test_report.py tests/test_availability.py tests/test_cli_availability.py tests/test_playtomic_browser.py -q
uv run pyright src/padel_availability/database.py src/padel_availability/report.py tests/test_availability.py tests/test_cli_availability.py tests/test_playtomic_browser.py
```

Expected: test behavior is unchanged and Pyright reports no errors in these files.

## Task 7: Whole-Repository Verification

**Files:** all repository files included in the configured Ruff, Pyright, and pytest checks.

- [ ] **Step 1: Run final static checks.**

Run:

```bash
uv run ruff format --check .
uv run ruff check .
uv run pyright
```

Expected: all three commands exit successfully with zero formatting differences, Ruff findings, and Pyright diagnostics.

- [ ] **Step 2: Run all tests and inspect the full diff.**

Run `uv run --group dev --group browser pytest -q`, then `git diff --check`, `git status --short`, and inspect `git diff`. Expected: all tests pass, no whitespace errors, only the approved quality corrections and preserved Padel First changes are present, with no dependency/config exclusions.
