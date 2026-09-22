# Padel Availability

Verified padel club catalog for the Geneva to Lausanne region.

This first slice is a read-only inventory catalog, not an automatic booking
service. It does not make reservations or payments, and availability scrapers
or a web UI are not included yet.

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

## Data Boundaries

- Source freshness is explicit: `verified_at` identifies the catalog pass and
  every evidence item carries its own UTC `checked_at` timestamp. Rerun the
  review when a source may have changed; the catalog does not imply live data.
- Unknown facts remain `Inconnu` rather than being inferred from candidate
  text, directories, or neighboring locations.
- The CLI reads local JSON and writes only the local SQLite/report artifacts. It
  performs no network automation and requires no credentials, booking account,
  CAPTCHA bypass, payment, or personal data.
