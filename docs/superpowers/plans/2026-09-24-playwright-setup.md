# Playwright Runtime Setup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the optional Playwright browser runtime setup reproducible and remove workspace-specific library/font paths from project instructions and browser test fixtures.

**Architecture:** Keep Playwright optional and lazy-loaded. Document project and Chromium installation commands in the README and CLI error guidance; make browser tests use the standard installed runtime and expose a broken browser installation instead of silently skipping it.

**Tech Stack:** Python 3.12+, uv, Playwright, Chromium, pytest.

## Global Constraints

- Document the optional browser group and Chromium setup using project commands:

  ```bash
  uv sync --dev --group browser
  uv run playwright install --with-deps chromium
  ```

- Explain that Linux system dependency installation may require administrator privileges; setup must not run automatically from application startup.
- Update CLI setup guidance to give the same complete install commands.
- Remove user-facing reliance on `/tmp/opencode` paths. Browser tests should use the installed system browser libraries and fonts, and should not set a workspace-specific `FONTCONFIG_FILE`.
- Keep Playwright optional for non-browser users; do not add a new dependency or an automatic bootstrap mechanism.
- Do not install operating-system packages on CT108 without first showing the exact write command and following the cluster documentation requirements.

---

## File Map

- Modify user setup instructions: `README.md`.
- Modify runtime setup error guidance: `src/padel_availability/cli.py`.
- Update CLI guidance expectations: `tests/test_cli_availability.py`.
- Remove host-specific environment/font setup from: `tests/test_airpad_browser.py`, `tests/test_everness_browser.py`, `tests/test_playtomic_browser.py`.
- Delete obsolete host-bound fixture: `tests/fixtures/fontconfig.conf`.
- No changes to `pyproject.toml`, application browser behavior, or dependencies are planned.

## Task 1: Document the Reproducible Browser Setup

**Files:** `README.md`, `src/padel_availability/cli.py`, `tests/test_cli_availability.py`.

- [ ] **Step 1: Update manual browser installation instructions.**

In `README.md`, keep the normal `uv sync --dev` workflow optional-browser-free. In the manual availability section, replace the two browser install commands with:

```bash
uv sync --dev --group browser
uv run playwright install --with-deps chromium
```

Add one sentence that `--with-deps` may install Linux packages and can require administrator privileges. Keep Playwright setup out of application startup.

- [ ] **Step 2: Update CLI setup guidance and its tests.**

In `src/padel_availability/cli.py`, change the browser setup error guidance to name `uv sync --dev --group browser` and `uv run playwright install --with-deps chromium`. Update every assertion in `tests/test_cli_availability.py` that checks the old two commands so it checks these exact new commands.

- [ ] **Step 3: Run CLI tests and focused Ruff.**

Run:

```bash
uv run pytest tests/test_cli_availability.py -q
uv run ruff check src/padel_availability/cli.py tests/test_cli_availability.py
```

Expected: command defaults and behavior remain unchanged; missing-runtime guidance contains both documented setup commands.

## Task 2: Remove Host-Specific Browser Test Configuration

**Files:** `tests/test_airpad_browser.py`, `tests/test_everness_browser.py`, `tests/test_playtomic_browser.py`, `tests/fixtures/fontconfig.conf`.

- [ ] **Step 1: Remove custom Fontconfig environment mutation.**

In each of the three browser test modules, remove the `os` import if unused, `FONTCONFIG_FILE`/`previous_fontconfig` handling, the `/tmp/opencode/playwright-libs/usr/share/fonts` detection, and the `finally` block that restores the variable. Keep normal browser/page/context cleanup intact.

- [ ] **Step 2: Make missing and broken optional runtimes distinct.**

Keep `pytest.skip()` when importing Playwright fails, because the browser group is optional. When Playwright imports but Chromium cannot launch, use `pytest.fail()` with a message containing `uv sync --dev --group browser` and `uv run playwright install --with-deps chromium`. This ensures a full browser-group test run detects incomplete setup instead of passing with browser tests skipped.

- [ ] **Step 3: Remove the obsolete Fontconfig fixture.**

Delete `tests/fixtures/fontconfig.conf` after confirming no test references it. Do not replace it with another absolute-path configuration.

- [ ] **Step 4: Run the browser tests without workspace environment variables.**

After installing the documented runtime, run:

```bash
env -u LD_LIBRARY_PATH -u FONTCONFIG_FILE uv run --group browser --group dev pytest tests/test_airpad_browser.py tests/test_everness_browser.py tests/test_playtomic_browser.py -q
```

Expected: Playwright tests execute rather than skip, all pass, and no `/tmp/opencode` runtime path is required.

## Task 3: Verify Setup and the Padel First CLI Smoke

**Files:** no further source files; disposable artifacts only under `/tmp`.

- [ ] **Step 1: Install the project browser group and inspect the runtime.**

Run `uv sync --dev --group browser` and inspect the existing Playwright cache and Chromium executable before installing anything else. Do not run an operating-system package install without first showing its exact command. If Linux libraries are missing on CT108, stop before the system write and ask for approval; on a normal development machine, use the documented `uv run playwright install --with-deps chromium` command.

- [ ] **Step 2: Run the full test suite with the browser group.**

Run:

```bash
env -u LD_LIBRARY_PATH -u FONTCONFIG_FILE uv run --group browser --group dev pytest -q
```

Expected: all tests pass, browser tests are not skipped for runtime launch failures, and environment variables are not needed.

- [ ] **Step 3: Run and inspect a disposable Padel First collection.**

Run the documented two-day collection against a new `/tmp` database:

```bash
DB="/tmp/opencode/padelfirst-runtime-smoke-$(date +%Y%m%d%H%M%S).sqlite3"
uv run padel-availability init-db --database "$DB"
uv run padel-availability import-candidates --database "$DB" --input data/candidates.json
uv run padel-availability build-catalog --database "$DB" --candidates data/candidates.json --verified data/verified_locations.json --run-id playwright-runtime-smoke
env -u LD_LIBRARY_PATH -u FONTCONFIG_FILE uv run padel-availability collect-padelfirst --database "$DB" --sources data/padelfirst_sources.json --location-id vernier --days 2
```

Verify the persisted run and slots through the project database API:

```bash
uv run python -c 'import sys; from pathlib import Path; from padel_availability.database import connect, list_availability_runs, list_availability_slots; connection = connect(Path(sys.argv[1])); run = list_availability_runs(connection, "vernier")[-1]; slots = list_availability_slots(connection, run.run_id); assert run.status == "success" and run.source_url == "https://padelfirst.ss-r.ch/court-vernier/"; assert all(slot.timezone == "Europe/Zurich" for slot in slots); print(run); print(f"persisted slots: {len(slots)}"); connection.close()' "$DB"
```

Expected: `vernier status=success`, a two-day window, and persisted UTC slots with `Europe/Zurich` metadata.

- [ ] **Step 4: Check the user-facing docs and diff.**

Run:

```bash
git diff --check
git status --short
```

Search `README.md`, `src/padel_availability/cli.py`, and the three test modules for `/tmp/opencode`, `LD_LIBRARY_PATH`, and `FONTCONFIG_FILE`. Expected: no user-facing or test-fixture runtime dependency remains.
