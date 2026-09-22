# Padel Availability

Verified padel club catalog for the Geneva to Lausanne region.

This first slice is a read-only inventory catalog with manual Playtomic
availability collection, not an automatic booking service. It does not make
reservations or payments.

## Development

Sync the development tools and run the offline test suite:

```bash
uv sync --dev
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest
```

The equivalent tool commands are also useful when `uv` is unavailable:

```bash
ruff format --check .
ruff check .
pyright
pytest
```

## Build And Report

The catalog is rebuilt only from the tracked candidate and verified JSON. The
local SQLite file is disposable and ignored by Git; the Markdown report is the
reviewable tracked artifact.

Initialize and build the local catalog:

```bash
uv run padel-availability init-db --database var/catalog.sqlite3
uv run padel-availability import-candidates --database var/catalog.sqlite3 --input data/candidates.json
uv run padel-availability build-catalog --database var/catalog.sqlite3 --candidates data/candidates.json --verified data/verified_locations.json --run-id inventory-2026-09-21
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

## Manual Availability Collection

Install the optional browser tools and Chromium once:

```bash
uv sync --group browser
uv run playwright install chromium
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
