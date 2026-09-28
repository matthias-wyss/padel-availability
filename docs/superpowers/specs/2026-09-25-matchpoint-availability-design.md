# Matchpoint Browser Availability Design

Date: 2026-09-25
Status: approved by user on 2026-09-25

## Objective

Add manual, read-only collection for the public Matchpoint booking grids used by
Padel Connect Bernex and Urban Padel Lausanne. Both grids are accessible without
logging in and use the same Matchpoint scheduling interface.

The initial activation covers catalog locations `bernex` and
`urban-padel-lausanne`, uses the existing local-day collection window in
`Europe/Zurich`, stores instants in UTC, and preserves immediate-save and
stale-snapshot semantics.

## Current Evidence

- Padel Connect's official site links to its online Matchpoint booking portal at
  `https://padelgeneva.matchpoint.com.es/Booking/Grid.aspx`. Opened without an
  account, the public grid shows Bernex and its two visible courts, Bernex
  Terrain Bleu and Bernex Terrain Vert.
- The public Padel Connect grid has visible date controls, slot intervals, and
  prices. The date grid loads without submitting the visible registration or
  login links. Booking instructions on the official Padel Connect site require
  an account and credit balance to place a booking; this connector will not
  create or use an account.
- Padel Academy identifies Padel Connect as the booking provider for Bernex,
  Evaux, and Jonction. The currently confirmed unauthenticated Matchpoint grid
  shows Bernex only. No public grids for Evaux or Jonction have been confirmed.
- Urban Padel's official page links to its Matchpoint portal. The public portal
  at `https://urbanpadellausanne.matchpoint.com.es/Booking/Grid.aspx` loads
  without login and shows the Padel schedule with four courts.
- Both portals display a visible Matchpoint schedule in the `.myReservas`
  region and identify Matchpoint as the software provider. Their visible date
  controls and court grids are similar, while court labels and durations vary by
  tenant.

## Scope And Boundaries

- Add `data/matchpoint_sources.json` with exactly the public Bernex and Urban
  Padel Lausanne source rows.
- Add a Matchpoint source model and strict manifest loader.
- Add one shared visible-DOM browser connector for the two Matchpoint tenants.
- Add `collect_matchpoint()` and a manual `collect-matchpoint` CLI command.
- Update the two catalog records' booking URL/platform evidence from current
  official pages and refresh booking-related notes that are now stale; do not
  change unrelated venue facts or infer account/access rules that the sources
  do not establish.
- Reuse the existing Playwright installation, slot observation/normalization,
  SQLite persistence, and stale-snapshot behavior. Add no dependencies.
- Read only visible DOM, visible attributes, accessibility state, and visible
  page content. Do not use private endpoints, network responses, inline
  application scripts, browser profiles, or hidden state; do not inspect or
  import cookies or local storage.
- If a visible cookie notice blocks date navigation, use its visible `Decline`
  control only to reject optional cookies in the current ephemeral browser
  context. Never accept cookies or preserve consent state between runs.
- Do not log in, create accounts, click reservation slots, submit forms, or
  trigger payment. Visible date controls may be used to read the requested
  collection window.
- Do not persist player names or other participant details. A Matchpoint open
  match occupies the court and is not a free full-court booking.
- Generic visible registration/login navigation does not alone block a source;
  an explicit authentication challenge, CAPTCHA, access denial, or missing
  public grid is a bounded source error.
- Evaux and Jonction remain out of the initial manifest until their public
  no-login booking grids are confirmed. Other uncovered platforms (Plugin.ch,
  Green Club, Bookinea, Padel One, and the Cherpines AIRPAD site) are deferred.

## Architecture

### Source metadata

Create a Matchpoint-specific manifest and frozen source model with:

- `location_id`: exactly `bernex` or `urban-padel-lausanne`;
- `booking_url`: the exact tenant's public `Booking/Grid.aspx` URL;
- `checked_at`: UTC timestamp;
- `status`: `public` or `unavailable`.

The strict loader validates exact row fields, supported IDs, unique coverage,
URLs, timestamps, and status, following the existing source-manifest pattern.

### Visible DOM and slot semantics

The browser script emits a sanitized payload from the visible Matchpoint
calendar only: visible date, court labels, time labels, slot state markers, and
loading/authentication booleans. It checks visible page text locally for
loading/authentication markers but does not return that text, participant names,
or hidden application data.

The parser uses the visible grid's actual slot intervals, so different court
durations across tenants are preserved rather than forced to one fixed length.
It maps explicitly free slots to `available`, booked/full/open-match slots to
`unavailable` for full-court availability, and unrecognized visible states to
`unknown`. A missing/partial court-time matrix, stale date, or still-loading
grid is an error; the parser must not treat absent or malformed cells as free.

Local calendar dates and times are interpreted in `Europe/Zurich` and normalized
through the existing availability helpers. Matchpoint does not need external
slot IDs; only stable visible identifiers, if present, may be retained.

### Browser and collection lifecycle

Open one Chromium session and process configured sources and requested dates
sequentially. Use only the visible date control/navigation and wait for the
visible grid to match the requested date before parsing. Use a fresh browser
context and close pages, contexts, and the browser in `finally` blocks.

Documented browser/source failures become bounded collection errors and
preserve the previous successful snapshot. Programming errors propagate. Each
successful location result is persisted immediately.

## Collection And CLI

The command is:

```text
padel-availability collect-matchpoint \
  --database var/catalog.sqlite3 \
  --sources data/matchpoint_sources.json \
  --days 14
```

`--location-id bernex` and `--location-id urban-padel-lausanne` select one
configured source. `--days` requires a positive horizon. Output matches the
existing manual collection commands.

## Testing And Acceptance

Add offline tests for:

- exact manifest fields, URLs, UTC timestamps, source statuses, duplicate
  rejection, and exact two-location coverage;
- sanitized visible grid fixtures for both tenants, court/date labels, differing
  slot durations, available/unavailable/unknown states, and no participant
  names in emitted payloads;
- local date/time conversion, date mismatch, loading/authentication detection,
  malformed/partial grids, browser cleanup, startup failures, and programming
  error propagation;
- collector selection, local collection window, immediate persistence, stale
  snapshot preservation, CLI selection/output, and positive-day validation.

Acceptance requires:

1. Offline tests pass for both portal variants.
2. Full-repository Ruff format/lint, Pyright, and pytest checks pass.
3. A no-login live smoke reads a short date window from Bernex and Urban Padel.
4. No credentials, profiles, live booking data, player names, or generated
   database files are committed.

## Non-Goals

- Adding Plugin.ch, Green Club, Bookinea, Padel One, or AIRPAD Cherpines in this
  change.
- Adding Padel Connect Evaux/Jonction until public no-login grids are verified.
- Using Matchpoint's private endpoints, account sessions, or undocumented
  application state.
- Login, account creation, booking, payment, or background scheduling.
- Generalizing all booking providers into a registry or adding dependencies.
