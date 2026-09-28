# Plugin date navigation and Pyright environment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Plugin collection navigate visible dates successfully, configure project-wide Pyright, and persist the maximum publicly selectable snapshot window per location.

**Architecture:** Replace the assumed next-day button with selection through the visible Plugin datepicker. Keep the existing stable-grid and parser checks as the gate before persistence. Configure Pyright for Python 3.12 and the project virtual environment in `pyproject.toml`; do not change application imports or add dependencies.

**Tech Stack:** Python 3.12, existing Playwright, pytest, Pyright, SQLite.

## Global Constraints

- Read only visible public Plugin.ch booking DOM; do not log in, activate membership, book, pay, call private APIs, solve CAPTCHAs, or collect participant data.
- Use the visible datepicker only for date navigation; never click a reservation cell.
- Fail closed unless the visible selected date and activity match the request and the grid is stable.
- Configure Pyright for Python `3.12` and the project’s existing `.venv`; add no dependencies.
- Do not bypass disabled dates; persist only each public datepicker’s selectable range in the primary checkout's `var/catalog.sqlite3`.

---

### Task 1: Navigate requested days through the visible datepicker

**Files:**
- Modify: `src/padel_availability/connectors/plugin_browser.py`
- Modify: `tests/test_plugin_browser.py`

**Interfaces:**
- Add `_select_plugin_date(page: _PluginPage, requested_date: date, timeout_ms: int) -> None`.
- Reuse `_visible_locator`, `_wait_for_plugin_date`, and `parse_plugin_dom`.

- [x] **Step 1: Add a connector regression for the missing visible next-day button**

Add `test_plugin_connector_uses_visible_datepicker_across_month_boundary` for
the requested window 2026-09-30 through
2026-10-02. Model the visible datepicker with a September/October month selector,
the 2026 year selector, and one exact October 1 day cell. Make the old next-day
script return an empty selector so the current connector fails at its current
navigation assumption. Assert after the fix that both requested dates are
selected in order, the month changes to October at the boundary, and no booking
cell is clicked.

- [x] **Step 2: Run the regression and verify it fails**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_plugin_browser.py -k month_boundary
```

Expected: test fails with `visible Plugin next-day control was not found`.

- [x] **Step 3: Implement visible calendar selection**

Implement `_select_plugin_date` to click the unique visible `#multi-language-date`,
wait for the visible `#datepicker`, set `.ui-datepicker-month` to
`str(requested_date.month - 1)` and `.ui-datepicker-year` to
`str(requested_date.year)`, and scan `td[data-handler="selectDay"]` cells for
exactly one visible cell whose `data-month`, `data-year`, and trimmed inner text
equal the requested date. Click only that cell. Raise `PluginBrowserError` if
controls or the exact day are missing or ambiguous. Extend `_PluginLocator` only
for the Playwright operations used by the helper.

In `collect`, call the helper for each later requested date, then retain
`_wait_for_plugin_date` before parsing. Remove the obsolete next-day-button
assumption and update the fake-page lifecycle test to assert datepicker selection
between days and that no booking-cell locator is clicked.

- [x] **Step 4: Verify browser tests**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_plugin_browser.py
.venv/bin/ruff check src/padel_availability/connectors/plugin_browser.py tests/test_plugin_browser.py
.venv/bin/ruff format --check src/padel_availability/connectors/plugin_browser.py tests/test_plugin_browser.py
.venv/bin/pyright src/padel_availability/connectors/plugin_browser.py
```

Expected: all focused tests pass, formatting/lint are clean, and the connector
has no Pyright diagnostics.

### Task 2: Point project Pyright at Python 3.12 and `.venv`

**Files:**
- Modify: `pyproject.toml`

**Interfaces:**
- Configure `[tool.pyright]` with `pythonVersion = "3.12"`, `venvPath = "."`, and `venv = ".venv"`.

- [x] **Step 1: Add the minimal environment configuration**

Add those three settings to the existing `[tool.pyright]` table; preserve its
`include` and strict type-checking settings.

- [x] **Step 2: Run bare project Pyright**

Run from the worktree root to check both configured paths, `src` and `tests`:

```bash
.venv/bin/pyright
```

Expected: zero errors, warnings, and informations without `--pythonpath`.

### Task 3: Verify and persist the longest visible Plugin windows

**Files:**
- No further source changes unless a regression is discovered.
- Database: primary checkout `var/catalog.sqlite3` (ignored local catalog created from tracked candidate/verified JSON).

- [x] **Step 1: Run the full offline checks**

Run:

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check src tests
.venv/bin/pyright
```

- [x] **Step 2: Run the collector within each route's visible datepicker horizon**

Run the collector once per location using its observed visible datepicker horizon:

```bash
env -u LD_LIBRARY_PATH -u FONTCONFIG_FILE PYTHONPATH=src \
  .venv/bin/padel-availability collect-plugin \
  --database /home/agentops/workspace/projects/padel-availability/var/catalog.sqlite3 \
  --sources data/plugin_sources.json \
  --location-id collonge-bellerive \
  --days 7
```

Use these exact location/window pairs: `collonge-bellerive`, `cologny`,
`csu-champel`, `drizia-miremont`, `fraisiers`, and `mies-tannay` with 7 days;
`crans-vd` with 3 days; and `gland` with 14 days. Replace the example's
`--location-id` and `--days` with each pair. All windows start on the current
Europe/Zurich date. Run from the worktree root so `PYTHONPATH=src` uses the
correct implementation.

Expected windows on 2026-09-28: the six 7-day locations end at 2026-10-05
(exclusive), Crans at 2026-10-01 (exclusive), and Gland at 2026-10-12
(exclusive).

- [x] **Step 3: Verify persisted snapshots**

Open `var/catalog.sqlite3` read-only and query `availability_runs` for the latest
Plugin row per location, then confirm each has `status='success'`, its
location-specific window above, and a persisted slot count matching the CLI
summary. Do not remove or overwrite the database.
