# Everness Browser Availability Design

Date: 2026-09-22
Status: approved design, pending implementation

## Objective

Add manual, read-only availability collection for the public Everness padel
portal at `https://padel.everness.ch/`.

The first activation covers the catalog location `everness`, uses the existing
14 local-day default in `Europe/Zurich`, stores instants in UTC, and preserves
the existing immediate-save and stale-snapshot semantics.

## Current Evidence

The public page renders a server-backed reservation grid without requiring an
account. The visible page contains:

- `#multi-language-date`, which displays the selected date;
- `#datepicker`, the visible date navigation control;
- `#table_reservation`, the visible reservation table;
- `.table_header`, the visible court labels;
- `.hour_slot`, the visible local start times;
- `.terrainTxt`, one visible court/time cell per row.

The current public page shows three courts and visible 90-minute time steps.
Availability is reflected in visible cell classes/styles: `.cursor` is
selectable, `.notallowed` is blocked, and an unclassified visible cell is
unknown until its state becomes clear. This design must be verified with
sanitized fixtures rather than depending on inline scripts.

## Scope And Boundaries

- Add `data/everness_sources.json` with exactly the `everness` source row.
- Add an Everness source model and manifest loader.
- Add a dedicated visible-DOM browser connector and `collect_everness()`.
- Add the `collect-everness` CLI command and README documentation.
- Use one Chromium process per collection invocation and a fresh context/page
  per venue.
- Read only visible DOM, visible attributes, accessibility state, and visible
  page content.
- Do not parse inline JavaScript state, hidden `num` identifiers, cookies,
  local storage, private endpoints, network responses, credentials, login
  forms, CAPTCHA, reservation, payment, or background scheduling.
- Treat a visible login/CAPTCHA page, missing grid, ambiguous date control, or
  malformed visible grid as a bounded source error.

## Architecture

### Source metadata

Create an Everness-specific manifest and frozen source model with:

- `location_id`: exactly `everness`;
- `booking_url`: exactly `https://padel.everness.ch/`;
- `checked_at`: UTC timestamp;
- `status`: `public` or `unavailable`.

The loader validates the exact row fields, URL, timestamp, status, duplicate
rejection, and exact one-location coverage.

### Browser connector

The connector opens the public booking page, waits for the visible reservation
contract, and iterates each requested local date by clicking the visible
calendar control inside `#datepicker`. It maps the visible date label in
`#multi-language-date` (for example, `22 Sep 2026`) to the requested local
date and rejects ambiguous or missing controls.

For each stable visible grid:

1. Read non-empty visible `.table_header` court labels in column order.
2. Read visible `.hour_slot` labels as local `HH:MM` start times.
3. Read matching visible `.terrainTxt` cells by row and column.
4. Map visible state classes/styles to `available`, `unavailable`, or
   `unknown`.
5. Derive each duration from the difference between adjacent visible start
   times; use the preceding visible interval for the final row.
6. Emit `None` for external IDs because the IDs present in inline scripts are
   outside the allowed visible-DOM boundary.

The parser must require a non-empty visible court label for every column and a
valid visible time for every row. It must reject a partial table rather than
turning it into false zero availability. A valid table with no selectable
cells is a successful zero-slot result only after the visible grid is stable.

Date transitions must reject unchanged stale grid content. A new date is
accepted only after either a visible loading transition followed by a stable
grid or a changed visible grid fingerprint. Identical grids without an
observable refresh become a bounded error so a prior date cannot overwrite a
successful snapshot as fresh data.

### Collection and CLI

`collect_everness()` processes the one configured location sequentially,
persists its result immediately, continues through documented browser/source
errors, and closes the browser in `finally`. The command follows the existing
manual shape:

```text
padel-availability collect-everness \
  --database var/catalog.sqlite3 \
  --sources data/everness_sources.json \
  --days 14
```

`--location-id` selects `everness`; `--days` validates a positive horizon. The
output matches Playtomic and AIRPAD with location, status, slots, local window,
error, and last successful snapshot.

## Error And State Semantics

- A public page without the visible Everness table becomes a bounded `error`.
- Login and CAPTCHA pages become explicit errors and are never bypassed.
- A stable visible grid with no selectable cells is a successful zero-slot run.
- A source/browser error is persisted for Everness and does not erase a
  previous successful slot set; the previous snapshot is exposed as stale.
- Browser/runtime errors are mapped to the connector error type; programming
  errors propagate.
- No attempt is made to select a cell, submit a reservation, or open payment.

## Testing And Acceptance

Add offline tests for:

- exact one-row manifest validation and URL/status rules;
- sanitized visible table fixtures with court labels, times, state classes,
  empty cells, hidden cells, and malformed rows;
- derived durations, missing-ID hashes, Europe/Zurich local dates, UTC
  conversion, and duplicate handling;
- date selection, stable-grid waiting, stale-grid rejection, and consecutive
  valid zero-slot dates with an observable refresh;
- one browser session, fresh context/page cleanup, startup failure persistence,
  and programming-error propagation;
- CLI selection, positive-day validation, output, and runtime setup errors.

Acceptance requires:

1. The offline suite passes.
2. Changed Everness files pass targeted Ruff and Pyright checks.
3. A two-day live smoke runs the public Everness grid without credentials.
4. No credentials, browser profile, generated database, hidden application
   state, or network fixture is committed.

## Explicitly Deferred Sources

- Bookinea `maisonnex`: the public page exposes a Padel product but instructs
  users to contact the centre to reserve; it exposes no public time grid.
- Padel Connect `evaux`: the public instructions require account/login and a
  funded balance before selecting a court.
- Padel One `padel-one-echandens`: the public instructions require the app and
  an account to view/select booking slots.
- Padel Academy-linked sites: the public pages expose lessons and course
  registration, not a court-availability grid.

These sources must not be automated by bypassing their access requirements.
Padel First/Vernier is a separate public-contract investigation after
Everness, because its current WordPress page exposes account and club routes
but no confirmed visible grid in the initial fetch.

## Non-Goals

- Generalizing all platforms into a registry.
- Extracting Plugin inline JavaScript or private endpoints.
- Login, account creation, reservation, payment, or calendar synchronization.
- Automatic scheduling or a web interface.
