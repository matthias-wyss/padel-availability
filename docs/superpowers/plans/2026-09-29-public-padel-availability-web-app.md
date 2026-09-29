# Public Padel Availability Web App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build, document, and deploy a public app that helps visitors find bookable padel slots across configured Geneva–Lausanne clubs.

**Architecture:** A Flask/Waitress web service serves one server-rendered page and a small JSON API. A single collector worker shares persistent SQLite job/cooldown state with the web service, runs scheduled and requested collections through existing collector functions, and writes snapshots to a persistent database. CT103 pulls the public GitHub repository and runs the web/worker containers behind NPM on CT100.

**Tech Stack:** Python 3.12, Flask, Waitress, existing Playwright collectors, SQLite, Jinja templates, native HTML/CSS/JavaScript, Docker Compose, Nginx Proxy Manager.

## Global Constraints

- The app is public and requires no account.
- Opening or filtering the page never starts a collection.
- The user-triggered **Actualiser** requests a collection of all 23 configured source locations; it does not book, authenticate, pay, or collect player data.
- Booking links leave the app and open the club's public booking page.
- The selector includes the 23 locations with configured public collectors; the six catalog locations without a configured source are not presented as searchable availability venues.
- With no time range, show all times. **Ce soir** fills today's date and 18:00–22:00 but is not a fixed default.
- `unknown`, stale, unavailable, no-snapshot, and out-of-window states are distinct and never masquerade as confirmed free slots.
- Do not attempt to bypass disabled public datepicker days. Persist and display each source's actual collection window.
- Schedule a complete source refresh daily every 30 minutes from 07:00 through 23:00 in `Europe/Zurich`.
- Manual and scheduled starts share one global five-minute cooldown and one active collector.
- Page reads never contact booking sites. The public refresh endpoint accepts no arbitrary URL, shell command, or user-supplied source path.
- The production SQLite database is mounted in persistent storage outside the Git checkout.
- Any real CT103/CT100 deployment change must be verified and reflected in the matching `workspace/infra/` documentation and committed/pushed there as required by the infra repository instructions.
- Implement in an ignored project worktree on a feature branch. Prefix Python test commands with `PYTHONPATH=src` so the shared `.venv` imports worktree code, not the primary checkout.

---

## File map

**Create:**
- `src/padel_availability/web.py` — Flask app factory, page/API routes, web entry point.
- `src/padel_availability/refresh.py` — persisted refresh-job state, cooldown, schedule loop, and all-source worker.
- `src/padel_availability/templates/index.html` — accessible search page.
- `src/padel_availability/static/app.css` — mobile-first Minimal Swiss layout and status tokens.
- `src/padel_availability/static/app.js` — snapshot loading, filters, local club selection, and refresh polling.
- `tests/test_web.py` — snapshot API and refresh route behavior.
- `tests/test_refresh.py` — global cooldown, single-worker, schedule, and collection horizon behavior.
- `tests/test_web_ui.py` — browser interaction and accessibility smoke using local fixture data.
- `deploy/ct103/Dockerfile` — Python/Playwright application image.
- `deploy/ct103/compose.yaml` — web and single collector-worker services sharing persistent SQLite state.
- `deploy/ct103/bootstrap-catalog.sh` — one-time catalog initialization and initial collection.
- `AGENTS.md` — project-specific contribution and deployment guidance.

**Modify:**
- `pyproject.toml`, `uv.lock` — Flask/Waitress web dependency group and web/worker console entry points.
- `src/padel_availability/database.py` — last-success lookup plus refresh-job/singleton cooldown tables and helpers.
- `README.md` — operator and user guide for CLI collectors and the public web app.
- `/home/agentops/workspace/infra/containers/ct103-services.md` — deployed app, volume, port, and runbook.
- `/home/agentops/workspace/infra/03-network-security.md` — public NPM hostname and exposure.

---

### Task 1: Expose configured snapshots through a read-only web API

**Files:**
- Create: `src/padel_availability/web.py`
- Test: `tests/test_web.py`
- Modify: `src/padel_availability/database.py`, `pyproject.toml`, `uv.lock`

**Interfaces:**
- `create_app(database_path: Path, data_directory: Path) -> Flask`
- `get_latest_successful_availability_run(connection: sqlite3.Connection, location_id: str) -> AvailabilityRun | None`
- `GET /healthz` returns `200` with a minimal health response.
- `GET /api/availability` returns JSON containing `generated_at` and a `locations` object keyed by `location_id`. Each value contains `canonical_name`, `municipality`, `overall_cover_status`, `booking_url`, `snapshot_status`, `window_start`, `window_end`, `last_success_at`, and `slots` (`court_label`, `starts_at`, `ends_at`, `status`).

- [ ] **Step 1: Declare the web dependency group**

Add a `web` dependency group with `Flask>=3.1,<4` and `waitress>=3,<4`, then
update `uv.lock` with `uv lock`. Keep Playwright in the existing `browser` group.
If `uv` is missing, install it only in the ignored `.venv` with
`.venv/bin/python -m pip install uv`; then run
`.venv/bin/uv sync --dev --group browser --group web`.

- [ ] **Step 2: Write failing snapshot API tests**

Create a temporary initialized catalog with a configured location having one
available slot, a stale location whose latest failed run follows an earlier
success, an explicit empty success, and a configured location with no run. Call
the Flask test client at `GET /api/availability` and assert:

```python
assert response.status_code == 200
assert locations["cologny"]["snapshot_status"] == "success"
assert locations["collonge-bellerive"]["snapshot_status"] == "stale"
assert locations["crans-vd"]["snapshot_status"] == "no_data"
assert locations["cologny"]["slots"][0]["status"] == "available"
assert locations["collonge-bellerive"]["window_end"] == "2026-10-05"
```

At the start of the test function, assert
`importlib.util.find_spec("padel_availability.web") is not None`, then import
`create_app` inside the function. Also assert that only configured source IDs
appear, the stale window comes from the last successful run (not the latest
failed run), and GET does not insert an availability run. The initial failure is
an assertion, not a test-collection error.

- [ ] **Step 3: Run the API tests and verify the expected failure**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_web.py
```

Expected: the API test fails its module-presence assertion because the web app
is not implemented yet.

- [ ] **Step 4: Implement the read-only snapshot endpoint**

Add the Flask app factory and `GET /api/availability`. Load the 23 configured
source IDs from the six checked-in manifests, location metadata from the
initialized catalog, and data through `get_availability_snapshot`. For a stale
snapshot, query its last successful `AvailabilityRun` so `window_start` and
`window_end` match the returned slots. Return `snapshot_status="no_data"` when
no run exists. Do not copy raw exception details or expose database paths.

- [ ] **Step 5: Verify snapshot API tests and typing**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_web.py
.venv/bin/ruff check src/padel_availability/web.py tests/test_web.py
.venv/bin/pyright src/padel_availability/web.py tests/test_web.py
```

Expected: all status/window/API assertions pass; GET creates no availability
runs.

### Task 2: Persist one refresh job and run all collectors safely

**Files:**
- Create: `src/padel_availability/refresh.py`
- Test: `tests/test_refresh.py`
- Modify: `src/padel_availability/database.py`, `src/padel_availability/web.py`, `pyproject.toml`

**Interfaces:**
- `RefreshStatus` contains `job_id: str | None`, `trigger: Literal["manual", "scheduled"] | None`, `status: Literal["idle", "queued", "running", "success", "partial", "error"]`, request/start/finish timestamps, completed/total location counts, `next_allowed_at: str | None`, and bounded error text.
- `RefreshCoordinator(database_path: Path, data_directory: Path, runner: RefreshRunner | None = None)` exposes `request_manual(now: datetime | None = None) -> tuple[RefreshStatus, int]`, `status() -> RefreshStatus`, `enqueue_scheduled(now: datetime) -> bool`, `run_pending_once(now: datetime) -> bool`, and `run_forever(stop_event: threading.Event) -> None`.
- `RefreshRunner = Callable[[sqlite3.Connection, Path, datetime, Callable[[CollectionOutcome], None]], tuple[CollectionOutcome, ...]]`.
- `run_all_sources(connection: sqlite3.Connection, data_directory: Path, now: datetime, on_outcome: Callable[[CollectionOutcome], None]) -> tuple[CollectionOutcome, ...]` calls the six existing `collect_*` functions sequentially.
- Add `padel-availability-web = "padel_availability.web:main"` and `padel-availability-worker = "padel_availability.refresh:main"` to `[project.scripts]`; update `uv.lock`.

- [ ] **Step 1: Write failing refresh state and cooldown tests**

At the start of each test, assert
`importlib.util.find_spec("padel_availability.refresh") is not None`, then import
`RefreshCoordinator` inside the test. With a temporary database and a fake
`RefreshRunner`, assert that the first manual request returns HTTP status 202
and creates one queued job; a request while a job is active returns 409 with its
status; a request within the
five-minute global cooldown returns 429 and `next_allowed_at`; and a request
after cooldown returns 202. Assert that scheduled triggers use the same
cooldown/active-job state and skip blocked ticks instead of queueing them.

Also test `run_all_sources` with fake collector callables and the real source
manifests. Assert the five non-Plugin collector families receive
`horizon_days=14` and Plugin receives these `(location_id, horizon_days)` pairs:
`collonge-bellerive`, `cologny`, `csu-champel`, `drizia-miremont`, `fraisiers`,
and `mies-tannay` at 7 days; `crans-vd` at 3 days; and `gland` at 14 days.

- [ ] **Step 2: Run the refresh tests and verify the expected failure**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_refresh.py
```

Expected: the refresh tests fail their module-presence assertion because the
refresh-state table/coordinator are not implemented yet.

- [ ] **Step 3: Add persisted refresh state and transaction helpers**

Extend `database.initialize` with `availability_refresh_jobs` and a singleton
`availability_refresh_control`. Store trigger type, job status (`queued`,
`running`, `success`, `partial`, `error`), request/start/finish timestamps,
progress, bounded error, and the shared `last_started_at`. Use an SQLite
`BEGIN IMMEDIATE` transaction to accept at most one active job and enforce the
five-minute global start cooldown. Expose helpers to enqueue, claim, update, and
read status; add database tests for cooldown and one-active-job behavior.

- [ ] **Step 4: Implement the all-source runner and source horizons**

Call `collect_playtomic`, `collect_airpad`, `collect_everness`,
`collect_padelfirst`, `collect_matchpoint`, and `collect_plugin` with the checked
source manifests, the catalog locations, and one shared timezone-aware `now`.
Use 14 days for the existing non-Plugin collectors. For Plugin, call once per
configured location using the verified rolling horizons: seven days for
`collonge-bellerive`, `cologny`, `csu-champel`, `drizia-miremont`, `fraisiers`,
and `mies-tannay`; three days for `crans-vd`; fourteen days for `gland`. Update
job progress after each `CollectionOutcome`. Preserve previous successful data
as stale on errors; never fabricate slots beyond a source's selectable window.

- [ ] **Step 5: Implement the 07:00–23:00 Europe/Zurich worker schedule**

Add one single-replica worker process. Check due half-hour ticks using
`ZoneInfo("Europe/Zurich")`; queue a scheduled full refresh only when the global
cooldown and single-worker state permit it. Skip a blocked tick instead of
backfilling missed runs. Provide a `padel-availability-worker` entry point and a
stop event so container shutdown stops the scheduler loop cleanly.

- [ ] **Step 6: Add manual refresh and status routes**

Add `POST /api/refresh` to request only the fixed all-source job; return 202 when
queued, 409 with current status when a job is active, and 429 with `Retry-After`
when the five-minute cooldown is active. Add `GET /api/refresh/status` for the
job and next scheduled time. Do not accept source IDs, arbitrary URLs, shell
commands, or user-supplied paths from the request.

The web process only enqueues refresh jobs; the worker process claims and runs
them. Page GET routes only read state and never start browser activity.

- [ ] **Step 7: Run refresh/API tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_refresh.py tests/test_web.py
.venv/bin/ruff check src/padel_availability/refresh.py src/padel_availability/database.py tests/test_refresh.py
.venv/bin/pyright src/padel_availability/refresh.py src/padel_availability/web.py
```

Expected: the fake runner verifies success/error/progress; manual and scheduled
jobs share the persisted lock/cooldown.

### Task 3: Build the responsive list-first search UI

**Files:**
- Create: `src/padel_availability/templates/index.html`
- Create: `src/padel_availability/static/app.css`
- Create: `src/padel_availability/static/app.js`
- Test: `tests/test_web_ui.py`

**Filter rule:** Compare slot start times in `Europe/Zurich` against the
half-open `[start, end)` range. Keep the slot's full end time and duration in
the result even if it extends beyond the requested end time.

- [ ] **Step 1: Add failing browser tests for the evening search**

Create a local HTML/JSON fixture with two configured clubs (one indoor, one
outdoor), one fresh available slot, an unknown slot, a stale slot, and one
location with no snapshot. In Chromium, select **Ce soir**, uncheck the indoor
club, and assert the matching outdoor slot is displayed with duration, local
time, and booking link. Assert unknown/stale/no-snapshot messages are separate;
reload and assert checkbox selections restore from local storage. Also assert a
slot starting at 21:30 is included in the `[18:00, 22:00)` range with its full
end time shown.

- [ ] **Step 2: Run UI tests to confirm they fail**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_web_ui.py
```

Expected: the page/UI modules do not exist and the tests fail on missing UI
behavior.

- [ ] **Step 3: Implement the approved accessible UI**

Render the single-page Jinja view with the refresh header, 14-day horizon,
optional time controls, **Ce soir** preset, indoor/outdoor/other cover filters,
and searchable checkbox list of 23 configured clubs. Initially check all clubs;
persist later selections in local storage only. Fetch snapshots from
`/api/availability`, filter by Europe/Zurich date and start time in
`[start, end)`, sort/group by local date/start time, and render one card per
slot. Put available slots first, unknown slots under **À vérifier**, stale data
under **Données anciennes**, and keep no-data/error/out-of-window labels
explicit. Open booking URLs in a new tab with `rel="noopener noreferrer"`.

Use semantic labels/checkboxes/time inputs, visible keyboard focus, 44px mobile
targets, responsive filter drawer on small screens, and textual status labels in
addition to color. Keep list as the only map alternative in v1.

- [ ] **Step 4: Connect refresh status and action**

Use `POST /api/refresh` and poll `GET /api/refresh/status` while queued/running.
Disable the button during an active job or global cooldown, show progress and the
next permitted refresh time, and keep the last successful snapshot visible until
the new run succeeds.

- [ ] **Step 5: Verify UI tests and quality checks**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_web_ui.py tests/test_web.py
.venv/bin/ruff check src/padel_availability/web.py src/padel_availability/templates src/padel_availability/static tests/test_web_ui.py
.venv/bin/pyright src/padel_availability/web.py
```

Expected: UI tests pass at mobile and desktop viewports; no keyboard-only action
is inaccessible.

### Task 4: Add the CT103 catalog bootstrap command

**Files:**
- Create: `deploy/ct103/bootstrap-catalog.sh`

- [ ] **Step 1: Add the safe one-time bootstrap script**

Create a shell script that requires a database path and refuses to run if that
file already exists. For a new path, run the existing `init-db`,
`import-candidates --input data/candidates.json`, and
`build-catalog --candidates data/candidates.json --verified data/verified_locations.json`
commands with a dated verification run ID. It must never delete or overwrite an
existing SQLite file.

- [ ] **Step 2: Verify local app and bootstrap commands**

Run the bootstrap against a new temporary SQLite path, verify that a second run
refuses the existing path without changing it, start the web entry point on
localhost, check `/healthz` and `/api/availability`, and run the full offline
tests. Confirm the CLI can still run independently without starting the web app.

### Task 5: Rewrite README and create project AGENTS.md

**Files:**
- Modify: `README.md`
- Create: `AGENTS.md`

- [ ] **Step 1: Rewrite README as the user/operator guide**

Document local setup and quality commands, catalog bootstrap, the public web
URL, club/time/coverage filters, local checkbox persistence, booking links,
snapshot status meanings, per-source collection horizons, 30-minute schedule,
five-minute global refresh limit, manual collector CLI commands, CT103 pull/build
deployment, and persistent DB location. State clearly that the app never books
or collects participant data.

- [ ] **Step 2: Write concise project AGENTS.md rules**

Document Python 3.12 and quality commands; keep visible-public-DOM-only, no
login/private API/booking/player data; preserve `available`/`unknown`/`stale` and
source-window meanings; never commit `var/*.sqlite3` or secrets; prefer a git
worktree for isolated feature work; and require reading/updating
`workspace/infra/` for real CT103/CT100 changes. State that project instructions
supplement, never override, workspace/cluster AGENTS.md files.

- [ ] **Step 3: Check README/AGENTS commands against actual entry points**

Run each documented `--help` command and use `git check-ignore var/catalog.sqlite3`
to confirm the local database is ignored.

### Task 6: Package the app and worker for CT103

**Files:**
- Create: `deploy/ct103/Dockerfile`
- Create: `deploy/ct103/compose.yaml`
- Modify: `.dockerignore` or create it if absent.

- [ ] **Step 1: Build a pinned Playwright Python image**

Use Python 3.12 and pin the official Playwright Python base image to the same
version resolved in `uv.lock` (currently Playwright 1.63.0). Install locked
`web`/`browser` groups and copy only application source, manifests, and web
assets; exclude `.venv`, `var`, caches, and tests from the image.

- [ ] **Step 2: Define web/worker Compose services and data volume**

Define one Waitress web service with one CT103 LAN port and one worker service
with no published port. Both mount the same persistent SQLite volume at
`/data/catalog.sqlite3`, use `Europe/Zurich`, restart unless stopped, and use a
health check against `/healthz`. Do not mount the Git checkout over `/data`.

- [ ] **Step 3: Validate the Compose configuration**

Run `docker compose -f deploy/ct103/compose.yaml config` from the repository
root. Check that only the web container publishes a port, both services share
the persistent DB mount, the worker starts exactly once, and no secret or
development volume appears in the rendered configuration. Build/runtime smoke
testing happens on CT103 in Task 7 because CT108 cannot access its Docker socket.

### Task 7: Publish the repository and deploy on CT103/NPM

**Files:**
- Modify in infra repo: `/home/agentops/workspace/infra/containers/ct103-services.md`
- Modify in infra repo: `/home/agentops/workspace/infra/03-network-security.md`

- [ ] **Step 1: Inspect deployment target and GitHub repository**

Use `gh repo view matthias-wyss/padel-availability` (or `git ls-remote` if `gh`
is unavailable) to verify the public repo/default branch. Read live CT103
config/status, `docker ps`, Compose support, and current NPM host state before
writing. Confirm CT103 port 8082 is unused. Do not read or print NPM secrets.

- [ ] **Step 2: Commit, merge, and publish project code**

Commit the tested web app on a feature branch, fast-forward merge to `master`
after tests pass, then push `master` to
`git@github.com:matthias-wyss/padel-availability.git` without force. If the
remote contains an unrelated initial commit or moved history, stop and report
instead of forcing a push.

- [ ] **Step 3: Pull/build the public repository on CT103**

Clone the public repo over HTTPS into `/opt/padel-availability` (or pull there
if already cloned), create the persistent `/var/lib/padel-availability` data
directory, and run the checked-in database bootstrap before starting services.
Build/start with `docker compose -f deploy/ct103/compose.yaml up -d --build`.
Trigger the initial full collection through the local app API, verify all
configured locations have a meaningful outcome, and only then add the public NPM
route. Show each server write command before running it and verify it afterward.

- [ ] **Step 4: Configure and verify NPM**

Create public NPM host `padel.matthiaswyss.ch` targeting CT103 port 8082, enable
HTTPS, and verify from an external route that the page and API work while the
container DB remains outside the Git checkout. If NPM credentials or access are
unavailable, stop and give the user the exact NPM UI/API action needed.

- [ ] **Step 5: Update and publish infra documentation**

Document the CT103 web/worker containers, persistent DB directory, port, NPM
hostname/target, initial bootstrap, and refresh operations in both infra files.
Commit and push the infra doc changes after live verification, per the infra
repository instructions.

### Task 8: Full acceptance

- [ ] Run `PYTHONPATH=src .venv/bin/python -m pytest -q`, `.venv/bin/ruff check .`,
  `.venv/bin/ruff format --check src tests`, and `.venv/bin/pyright`.
- [ ] Verify the 23 configured clubs render with accurate snapshot statuses;
  inspect actual DB windows and counts for the Plugin source-specific horizons.
- [ ] Verify a manual request, five-minute cooldown, one-active-job rule,
  scheduled run at a due Europe/Zurich tick, and clear blocked/error states.
- [ ] Confirm `git status` is clean and no local SQLite database, credentials, or
  player data are committed.
