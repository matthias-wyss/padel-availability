# AIRPAD Browser Availability Design

Date: 2026-09-22
Status: approved design, pending implementation

## Objective

Add manual, read-only availability collection for the four AIRPAD venues that
share the public AIRPAD reservation portal:

- `airpad-les-acacias`
- `airpad-la-praille`
- `airpad-meyrin`
- `airpad-plan-les-ouates`

The default collection window is 14 local days in `Europe/Zurich`. Results use
the existing availability schema, UTC persistence, immediate per-location
saves, and stale snapshot semantics already used by Playtomic.

`cherpines` is explicitly out of scope for this first AIRPAD activation even
though its catalog reservation link also points to AIRPAD.

## Current Evidence

`https://www.airpad.ch/reserve` embeds the public application at
`https://airpad.doinsport.club/home` in an iframe. The visible flow is:

1. Select `1.Terrains`.
2. Select one of `LA PRAILLE`, `LES ACACIAS`, `MEYRIN`, or `PLAN-LES-OUATES`.
3. Select the visible court/activity option.
4. Select dates and read the visible booking grid.

The implementation must follow these visible interactions rather than rely on
application state, private APIs, or network responses.

## Scope And Boundaries

- Add `data/airpad_sources.json` with exactly the four AIRPAD rows.
- Add an AIRPAD source loader and a dedicated browser DOM connector.
- Add `collect_airpad()` and a `collect-airpad` CLI command.
- Reuse the existing browser lifecycle, slot normalization, UTC conversion,
  database persistence, and stale snapshot behavior where the existing
  interfaces permit it.
- Use one Chromium process per collection invocation and a fresh context/page
  per venue.
- Read only visible DOM, visible attributes, accessibility state, and visible
  iframe content.
- Do not use login, credentials, cookies, local storage, hidden application
  state, network interception, private APIs, or CAPTCHA bypass.
- Do not add background scheduling or booking/payment behavior.

## Architecture

### Source metadata

Create an AIRPAD-specific manifest and validated source model. Each row stores:

- `location_id`
- common public `booking_url`: `https://www.airpad.ch/reserve`
- `checked_at`
- public/unavailable status

The location-to-portal-label mapping is explicit and validated:

| Location ID | Visible AIRPAD label |
|---|---|
| `airpad-les-acacias` | `LES ACACIAS` |
| `airpad-la-praille` | `LA PRAILLE` |
| `airpad-meyrin` | `MEYRIN` |
| `airpad-plan-les-ouates` | `PLAN-LES-OUATES` |

### Browser connector

The dedicated connector opens the common public page, resolves the
`airpad.doinsport.club` iframe by its public URL, and drives the visible
selection flow for each requested venue. It must not use the frame's internal
Angular state or direct service endpoints.

The connector emits normalized observations containing court label, local start
time, duration, optional external ID, and one of `available`, `unavailable`, or
`unknown`. Missing IDs use the existing deterministic slot hash. A loaded grid
with visible court rows and no slot cards is a valid zero-slot state; an
incomplete page, login/CAPTCHA state, or missing visible availability contract
is an error.

### Collection and CLI

`collect_airpad()` processes the four configured locations sequentially,
persists each result immediately, continues after documented source/browser
errors, and closes the browser in `finally`. The command follows the existing
manual collection shape:

```text
padel-availability collect-airpad \
  --database var/catalog.sqlite3 \
  --sources data/airpad_sources.json \
  --days 14
```

`--location-id` selects one AIRPAD venue. Output includes location, status,
slot count, local window, error, and last successful snapshot, matching the
Playtomic command.

## Error And State Semantics

- A public page that cannot expose the booking iframe or visible booking
  contract becomes a bounded `error` result.
- Login and CAPTCHA pages become explicit errors and are never bypassed.
- A valid empty grid is a successful zero-slot result.
- A source/browser error is saved for that venue and does not stop other AIRPAD
  venues.
- Failed or unavailable runs preserve the previous successful slots as stale.
- Date transitions must reject unchanged stale DOM and accept only a visible
  refreshed date/grid state.

## Testing And Acceptance

Add offline tests for:

- exact four-row manifest validation and label mapping;
- iframe/visible selector extraction using sanitized AIRPAD fixtures;
- visible available, unavailable, unknown, empty-grid, login, CAPTCHA, and
  malformed states;
- time/duration parsing, missing-ID hashes, collisions, Zurich local dates,
  UTC conversion, and date transitions;
- one browser session, fresh venue contexts, immediate persistence,
  continuation after one venue error, and stale snapshots;
- CLI output and setup/runtime errors.

Acceptance requires:

1. The offline suite passes.
2. Changed AIRPAD files pass targeted Ruff and Pyright checks.
3. A two-day live smoke runs all four AIRPAD venues through the public iframe.
4. No credentials, browser profile, generated database, or network fixture is
   committed.

## Non-Goals

- Generalizing every platform into a registry in this change.
- Supporting `cherpines` before its scope and identity are explicitly decided.
- Reusing hidden Doinsport APIs or extracting private network payloads.
