# Padel Availability

Find public padel availability around Geneva and Lausanne: **https://padel.matthiaswyss.ch**.
The app reads collected snapshots from 23 configured club sources and links to
each club's public booking page. It never books, authenticates, pays, or collects
player data.

## Development

Sync the development tools and run the offline test suite:

```bash
uv sync --dev --group browser --group web
uv run ruff format --check src tests
uv run ruff check .
uv run pyright
PYTHONPATH=src uv run pytest -q
uv run playwright install chromium
```

The Python tools can also be run directly from `.venv/bin` when `uv` is unavailable:

```bash
.venv/bin/ruff format --check src tests
.venv/bin/ruff check .
.venv/bin/pyright
PYTHONPATH=src .venv/bin/python -m pytest -q
```

## Catalog And Report

The catalog is rebuilt only from the tracked candidate and verified JSON. The
local SQLite file is disposable and ignored by Git; the Markdown report is the
reviewable tracked artifact.

Initialize and build the local catalog:

```bash
uv run padel-availability init-db --database var/catalog.sqlite3
uv run padel-availability import-candidates --database var/catalog.sqlite3 --input data/candidates.json
uv run padel-availability build-catalog --database var/catalog.sqlite3 --candidates data/candidates.json --verified data/verified_locations.json --run-id inventory-2026-10-02
```

Regenerate the tracked Markdown report:

```bash
uv run padel-availability report --database var/catalog.sqlite3 --output reports/inventory.md
```

Inspect unresolved candidates and unknown facts:

```bash
rg -n '^## Missing or unknown facts|^### Unresolved candidates|Inconnu|not_confirmed|unresolved' reports/inventory.md
```

Use a `.json` output path for a machine-readable report.

## Public Web App

The app defaults to today through the next 14 days. Set a date range, an
optional start/end time range, durations, indoor/outdoor coverage, and clubs.
Slots disappear when their start time passes, including when the page remains
open. Duration checkboxes are cumulative, default to all durations present in
the loaded snapshots, and update the grouped results and summary. With no time
range, it shows all times; **Ce soir** selects today from 18:00 to 22:00. The
club checklist starts with all 23 configured locations selected and stores later
choices only in that browser's local storage.

Results are grouped by date in `Europe/Zurich`. When multiple courts have the
same club, start, and end time, they share one compact card with court labels
and counts; different durations stay separate. The summary counts grouped time
windows and court-time opportunities, not one card per court. If a source does
not name courts, its row count is shown as possibilities rather than inferred
physical courts.

**Réserver** opens the selected day on Playtomic `.com`/`.io` and Everness. The
exact time and court remain visible on the card for the visitor to choose on
those sites. AIRPAD, Matchpoint, Padel First, and Plugin.ch keep their verified
booking URLs because their public pages did not confirm a stable date-specific
URL. Links open in a new tab. Availability meaning stays explicit:

- **Disponible**: confirmed available in the latest successful snapshot.
- **À vérifier**: the source returned an unknown slot state; it is not counted
  as free.
- **Données anciennes**: the last successful snapshot is retained after a
  collection error and may no longer be current.
- **Pas encore collecté** / **Données indisponibles**: no snapshot or no usable
  successful result exists.
- **Hors période publiée**: the selected dates exceed that source's published
  collection window. A source's shorter window is never extended by guessing.

The **Actualiser** button requests a refresh of all 23 configured sources. It
does not book a court. Manual and scheduled collection share one active worker
and a global five-minute cooldown. The worker refreshes every 30 minutes from
07:00 through 23:00 `Europe/Zurich`; a blocked scheduled tick is skipped.
Opening or filtering the page does not contact booking sites. Non-Plugin
collectors use a 14-day horizon. Plugin's published windows are seven days for
Collonge-Bellerive, Cologny, CSU Champel, Drizia-Miremont, Fraisiers, and
Mies-Tannay; three days for Crans; and 14 days for Gland.

### Run locally

Bootstrap a new local catalog once (the script refuses an existing database):

```bash
uv run bash deploy/ct103/bootstrap-catalog.sh "$PWD/var/catalog.sqlite3"
```

Run the web app and worker in separate terminals:

```bash
PADEL_AVAILABILITY_DB="$PWD/var/catalog.sqlite3" \
PADEL_AVAILABILITY_DATA="$PWD/data" \
  uv run padel-availability-web
```

```bash
PADEL_AVAILABILITY_DB="$PWD/var/catalog.sqlite3" \
PADEL_AVAILABILITY_DATA="$PWD/data" \
  uv run padel-availability-worker
```

### Deploy on CT103

The public GitHub repository is pulled into `/opt/padel-availability`. The web
container listens on CT103 port `8082`; the worker has no published port. Both
mount `/var/lib/padel-availability` at `/data`; the database at
`/data/catalog.sqlite3` stays outside the checkout across pulls and rebuilds.

For first setup, clone the public repository, create the persistent directory,
run the catalog bootstrap, then build and start the Compose services:

```bash
git clone https://github.com/matthias-wyss/padel-availability.git /opt/padel-availability
mkdir -p /var/lib/padel-availability
cd /opt/padel-availability
docker compose -f deploy/ct103/compose.yaml build web
./deploy/ct103/bootstrap-catalog.sh /var/lib/padel-availability/catalog.sqlite3
docker compose -f deploy/ct103/compose.yaml up -d --build
```

Trigger and verify the initial all-source collection on CT103 before enabling
the public NPM host:

```bash
curl --fail --request POST http://127.0.0.1:8082/api/refresh
curl --fail http://127.0.0.1:8082/api/refresh/status
```

For updates, pull the fast-forwarded default branch and rebuild; do not replace
the persistent data path:

```bash
cd /opt/padel-availability
git pull --ff-only
docker compose -f deploy/ct103/compose.yaml up -d --build
```

The public host `padel.matthiaswyss.ch` is routed by NPM on CT100 to CT103:8082.
Real server changes must also be recorded in the matching
`workspace/infra/` documentation.

## Manual Availability Collection

Install the optional browser tools and Chromium once. On Linux, `--with-deps`
installs system packages and may require administrator privileges:

```bash
uv sync --dev --group browser
uv run playwright install --with-deps chromium
```

Collect the public Playtomic availability snapshot manually:

```bash
uv run padel-availability collect-playtomic \
  --database var/catalog.sqlite3 \
  --sources data/playtomic_sources.json \
  --days 14
```

This command is public and read-only against Playtomic. Collection is manual
and sequential: it does not book courts, use credentials, or run in the
background. Browser state is ephemeral and is not saved between runs. CAPTCHA
or login pages become explicit `error` outcomes; they are not bypassed. Each
outcome is persisted locally. An `error` or `unavailable` outcome keeps the
previous successful snapshot as stale rather than replacing its slots.

Collect the public Everness availability grid manually:

```bash
uv run padel-availability collect-everness \
  --database var/catalog.sqlite3 \
  --sources data/everness_sources.json \
  --days 14
```

This command reads the public Everness availability grid and is sequential,
read-only, and manual. Browser state is ephemeral and is not saved between runs.
It never logs in or reserves. Other portals without public availability remain unsupported;
they are not bypassed. Each outcome is persisted locally, and an `error` or
`unavailable` outcome keeps the previous successful snapshot as stale rather
than replacing its slots.

Collect the public Plugin.ch availability diaries manually:

```bash
uv run padel-availability collect-plugin \
  --database var/catalog.sqlite3 \
  --sources data/plugin_sources.json \
  --days 14
```

This command is manual, sequential, public, and read-only. It does not log in
or reserve; public diary visibility does not imply anonymous booking. Venue
access, account, and membership requirements remain unknown unless separately
verified. Each outcome is persisted locally, and an `error` outcome keeps the
previous successful snapshot as stale rather than replacing its slots.

Collect the public Padel First Vernier availability scheduler manually:

```bash
uv run padel-availability collect-padelfirst \
  --database var/catalog.sqlite3 \
  --sources data/padelfirst_sources.json \
  --days 14
```

This command reads the visible public Vernier scheduler and is sequential,
read-only, and manual. Browser state is ephemeral; it never logs in, reserves,
or opens payment. Login links shown in the public navigation are not used.
Each outcome is persisted locally, and an `error` or `unavailable` outcome
keeps the previous successful snapshot as stale rather than replacing its
slots.

Collect the public Matchpoint schedules for Jonction, Bernex, Parc des Evaux,
and Urban Padel Lausanne manually:

```bash
uv run padel-availability collect-matchpoint \
  --database var/catalog.sqlite3 \
  --sources data/matchpoint_sources.json \
  --days 14
```

This reads only the visible public court grids. It is sequential and read-only:
it does not log in, use private endpoints, click booking slots, reserve, or
persist participant names. If the optional-cookie notice blocks date controls,
it uses the visible Decline choice only; it never accepts optional cookies or
retains consent state between runs. Open matches count as occupied courts. The
Evaux and Jonction sources use the public center selectors `id=8` and `id=9`;
`club=Evaux` and `club=Jonction` are not valid selectors. This activation covers
exactly the four entries in `data/matchpoint_sources.json`; the other
unconfigured booking platforms are deferred. Each outcome is persisted locally,
and an `error` or `unavailable` outcome keeps the previous successful snapshot
as stale rather than replacing its slots.

Collect the four AIRPAD availability snapshots manually:

```bash
uv run padel-availability collect-airpad \
  --database var/catalog.sqlite3 \
  --sources data/airpad_sources.json \
  --days 14
```

This command opens the public Doinsport iframe through the AIRPAD reservation
page and is read-only, sequential, and manual. It does not book courts, use
credentials, or run in the background. Browser state is ephemeral and is not
saved between runs. CAPTCHA or login pages become explicit `error` outcomes;
they are not bypassed. This activation includes exactly the four AIRPAD sites
in `data/airpad_sources.json`. The Cherpines candidate is merged into the
AIRPAD Plan-les-Ouates location and is not collected as a separate site. Each
outcome is persisted locally, and an `error` or `unavailable` outcome keeps the
previous successful snapshot as stale rather than replacing its slots.

`reports/inventory.md` remains the separate static inventory report; it is not
an availability report.

## Data Boundaries

- Source freshness is explicit: `verified_at` identifies the catalog pass and
  every evidence item carries its own UTC `checked_at` timestamp. Rerun the
  review when a source may have changed; the catalog does not imply live data.
- Unknown facts remain `Inconnu` rather than being inferred from candidate
  text, directories, or neighboring locations.
- Inventory commands read local JSON and write only local SQLite/report
  artifacts. Manual collection reads public availability sources and requires
  no credentials, booking account, CAPTCHA bypass, payment, or personal data.
