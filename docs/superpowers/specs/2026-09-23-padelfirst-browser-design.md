# Padel First Browser Availability Design

Date: 2026-09-23
Status: approved for implementation by the explicit Padel First implementation request

## Objective

Add manual, read-only availability collection for the public Padel First Vernier
portal at `https://padelfirst.ss-r.ch/court-vernier/`.

The first activation covers the existing catalog location `vernier`, uses the
existing 14 local-day default in `Europe/Zurich`, stores instants in UTC, and
preserves immediate-save and stale-snapshot semantics.

## Current Evidence

The public page renders a FullCalendar month view and exposes a visible
scheduler after clicking a visible green `disponible` event. The scheduler
contains:

- `#calendar`, with visible `.fc-day-top[data-date]` cells and visible
  `.fc-event.available` day events;
- `#scheduler-table`, with visible `th.fc-court` court labels;
- visible scheduler rows whose first cell is a local `HH:MM` time;
- `span.status.available` for an open court/time cell;
- `span.status.unavailable` and `.match-block`/`.match-block2` for occupied or
  blocked cells;
- visible `checkin`, `hour`, `court_id`, and `id` attributes on scheduler state
  elements.

The venue publishes a 1h30 booking duration, and the public scheduler confirms
that duration on booked cells. Open cells omit the duration attribute, so the
source contract uses the published fixed duration of 90 minutes.

## Scope And Boundaries

- Add `data/padelfirst_sources.json` with exactly the `vernier` source row.
- Add a Padel First source model and strict manifest loader.
- Add a dedicated visible-DOM browser connector and `collect_padelfirst()`.
- Add the `collect-padelfirst` CLI command and README documentation.
- Reuse the existing browser factory, slot observation model, normalization,
  SQLite persistence, and stale snapshot behavior.
- Read only visible DOM, visible attributes, accessibility state, and visible
  page content.
- Do not parse inline JavaScript, cookies, local storage, private endpoints,
  network responses, credentials, login forms, CAPTCHA, reservation, payment,
  or hidden application state.
- Generic public navigation links such as `Connexion` and `S’identifier` are
  not a block by themselves; only a visible authentication challenge, CAPTCHA,
  access-denied page, or missing booking view is a bounded source error.
- Never click a scheduler cell, submit a form, open payment, or follow account
  routes.

## Architecture

### Source metadata

Create a Padel First-specific manifest and frozen source model with:

- `location_id`: exactly `vernier`;
- `booking_url`: exactly `https://padelfirst.ss-r.ch/court-vernier/`;
- `checked_at`: UTC timestamp;
- `status`: `public` or `unavailable`.

The fixed duration remains a code constant of 90 minutes because the first
activation has one verified venue and no per-source duration variation.

### Visible DOM payload and parser

The visible-DOM script returns only:

- the visible booking-page state;
- visible calendar date markers mapped from event column to `YYYY-MM-DD`;
- visible scheduler date and court labels;
- visible row times;
- each visible state cell's class, ID, and visible attributes;
- visible page text for bounded loading/authentication detection.

The parser validates a complete court/time matrix. `available` maps to
`available`; `unavailable`, `approved`, `booked`, and explicit blocked cells
map to `unavailable`; an unclassified visible state maps to `unknown`.
Scheduler state IDs are used as visible external IDs. Local times are parsed in
`Europe/Zurich`, end times add 90 minutes, and final normalization delegates to
the shared Playtomic browser helpers.

### Browser lifecycle

The connector opens one Chromium session, creates one fresh context/page, and
uses only visible calendar events and the visible scheduler modal. It maps
calendar event columns to dates from the visible FullCalendar header, clicks
the event for each requested date, waits for a visible scheduler title and
matching visible `checkin`, then parses the stable table. Visible calendar
month navigation is used when the requested window crosses a month boundary.

Dates without a visible green day event contribute no open slots; malformed or
partially rendered scheduler data is an error rather than a false success.
Pages, contexts, and browser sessions are always closed. Programming errors
propagate; documented browser/source failures become bounded collection errors.

## Collection And CLI

`collect_padelfirst()` processes the exact `vernier` catalog location
sequentially, saves each result immediately, preserves the previous successful
snapshot after an error, and closes the connector in `finally`.

The command is:

```text
padel-availability collect-padelfirst \
  --database var/catalog.sqlite3 \
  --sources data/padelfirst_sources.json \
  --days 14
```

`--location-id vernier` selects the one activated source and `--days` requires
a positive horizon. Output matches the existing manual collection commands.

## Testing And Acceptance

Add offline tests for:

- exact manifest fields, URL, timestamp, status, duplicate rejection, and
  exact one-location coverage;
- sanitized visible calendar/scheduler payloads, available/unavailable/match
  states, 90-minute conversion, Europe/Zurich to UTC conversion, date mismatch,
  incomplete matrix, and authentication/loading errors;
- visible event date mapping, scheduler date refresh, month navigation,
  one-session/fresh-context lifecycle, cleanup, startup failure persistence, and
  programming-error propagation;
- collector selection, UTC local window, stale persistence, and CLI selection,
  output, positive-day validation, and Playwright runtime guidance.

Acceptance requires:

1. The offline suite passes.
2. Changed Padel First files pass Ruff and Pyright.
3. A two-day live smoke reads the public Vernier scheduler without credentials.
4. No credentials, browser profile, generated database, hidden state, or live
   response is committed.

## Non-Goals

- Generalizing all reservation portals into a registry.
- Extracting private Padel First endpoints or inline application state.
- Login, account creation, reservation, payment, or calendar synchronization.
- Automatic scheduling or background collection.
