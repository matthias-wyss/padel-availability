# Past Slot and Duration Filters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hide slots whose start instant has passed and let users combine duration filters.

**Architecture:** Keep SQLite and `/api/availability` unchanged. Apply the current-time and duration predicates in the existing client-side `matchesFilters` path before grouping, with native duration checkboxes built from observed slot lengths. Re-render at the next visible slot start so an open page removes newly expired slots without polling.

**Tech Stack:** Existing Flask/Jinja page, native HTML/CSS/JavaScript, pytest and Playwright UI tests.

## Global Constraints

- Compare `starts_at` with the browser's current instant; a slot is past at `starts_at <= now`, including a slot already in progress.
- Use `Europe/Zurich` only for displayed dates/times; ISO timestamps already identify instants for the past-time comparison.
- Apply past and duration filters before grouping, for `available`, `unknown`, and `stale` rows alike.
- Duration options are the unique positive minute lengths present in loaded snapshots, sorted ascending and selected by default.
- Keep all source records and snapshots unchanged; add no runtime dependencies or guessed availability.
- Duration controls are native labeled checkboxes inside a `fieldset` and remain keyboard-accessible.

---

## Task 1: Add failing UI coverage for past and duration filtering

**Files:** `tests/test_web_ui.py`

- [x] Create fixture data with one past and one in-progress slot, plus future slots of 30, 60, 90, and 120 minutes. Add past `unknown` and `stale` slots as well.
- [x] Freeze `Date.now()` at 14:00 Europe/Zurich before loading the page; include earlier and in-progress starts on today itself.
- [x] Assert past and in-progress slots are absent from all result sections; future slots remain; duration checkboxes list `30`, `60`, `90`, `120` and start checked.
- [x] Uncheck 60/90/120, then assert only the 30-minute future slot remains and the result count updates. Re-enable 60 and verify both durations show.
- [x] Run `PYTHONPATH=src uv run pytest -q tests/test_web_ui.py::test_past_and_duration_filters_apply_before_grouping`; the UI fixture first failed because the duration controls were absent.

## Task 2: Implement one shared filter path and duration controls

**Files:** `src/padel_availability/templates/index.html`, `src/padel_availability/static/app.js`, `tests/test_web_ui.py`

- [x] Add a `Durées` fieldset with an empty `#duration-options` container after the time fields.
- [x] Add `slotDurationMinutes(slot)` and a French label formatter (`30 min`, `1 h`, `1 h 30`, `2 h`).
- [x] In `renderDurationFilters`, gather unique positive durations from loaded slots, sort them, and render checked native checkboxes named `duration`.
- [x] Pass a single `now = Date.now()` and the checked-duration set into `matchesFilters`; reject `Date.parse(slot.starts_at) <= now` and any unselected duration before grouping.
- [x] Keep the duration fieldset options refreshed by `loadAvailability`; delegate its `change` event to `renderAvailability`.
- [x] Run the focused UI test and verify past unknown/stale cards, future cards, multi-selection, and result summaries.

## Task 3: Remove newly expired slots while the page stays open

**Files:** `src/padel_availability/static/app.js`, `tests/test_web_ui.py`

- [x] During `renderAvailability`, find the next future start among selected clubs and matching coverage; schedule one `setTimeout` for that instant.
- [x] Clear/replace the pending timeout whenever availability is rendered; when it fires, call `renderAvailability` and schedule the next boundary.
- [x] Add a browser test with a slot starting shortly in the future; verify it is initially visible and disappears after its start time.
- [x] Run the focused timer test and ensure the timeout does not leave stale timer callbacks after a new render.

## Task 4: Document and verify the user-facing behavior

**Files:** `README.md`, `docs/superpowers/specs/2026-09-30-padel-results-and-booking-links-design.md`

- [x] Document that past-start slots are hidden and that duration checkboxes are cumulative, default to all current durations, and filter all result states.
- [x] Add acceptance bullets for the start-time boundary, current-time removal in an open tab, dynamic duration choices, and summary/group consistency.
- [x] Run `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check src tests`, and `uv run pyright` (`495 passed`, Ruff/format and Pyright clean).
