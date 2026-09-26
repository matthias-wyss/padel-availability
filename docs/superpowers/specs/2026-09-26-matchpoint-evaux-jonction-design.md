# Matchpoint Evaux and Jonction Availability Design

Date: 2026-09-26
Status: approved by user on 2026-09-26

## Objective

Extend the existing read-only Matchpoint collector to the two additional public
Padel Connect court grids used by Parc des Evaux and L'Asphalte / Pointe de la
Jonction. Reuse the existing visible-DOM parser and collection lifecycle; do
not create a second connector.

## Current Evidence

- The public Padel Connect tenant is
  `https://padelgeneva.matchpoint.com.es/Booking/Grid.aspx`.
- Its public visible center map selects Evaux with `id=8` and Jonction with
  `id=9`. The exact public grid URLs are:
  - `https://padelgeneva.matchpoint.com.es/Booking/Grid.aspx?id=8`
  - `https://padelgeneva.matchpoint.com.es/Booking/Grid.aspx?id=9`
- A no-login browser smoke on 2026-09-26 rendered `Parc des Evaux` with three
  courts (`Evaux 1`, `Evaux 2`, `Evaux 3`) and `Jonction` with two courts
  (`Jonction 1`, `Jonction 2`).
- The Fondation des Evaux page confirms three outdoor courts and links Padel
  Connect for reservations.
- The Padel Academy and Ville de Geneve pages confirm the Jonction location,
  two covered courts, and Padel Connect / online reservation.
- The query parameter is public navigation state selecting a visible center; it
  is not a private endpoint or an account session.

## Scope And Boundaries

- Expand `data/matchpoint_sources.json` from the two existing rows to exactly
  four rows: `bernex`, `evaux`, `asphalte-jonction`, and
  `urban-padel-lausanne`.
- Use the exact `id=8` and `id=9` URLs above for the new source rows.
- Extend the strict Matchpoint source model and loader to cover the four
  supported IDs and URLs exactly once.
- Add booking URL, platform, and fact-specific evidence to the Evaux and
  Jonction catalog records without changing unrelated venue facts or inferring
  membership and account rules beyond the checked sources.
- Reuse the current browser connector, visible SVG extraction, Europe/Zurich
  date handling, UTC normalization, immediate persistence, and stale-snapshot
  semantics.
- Read only the visible public grid, visible attributes, and visible page
  content. Do not use private endpoints, network responses, inline application
  state, browser profiles, cookies, local storage, credentials, or account
  sessions.
- Clicking the visible cookie `Decline` control remains allowed only to reject
  optional cookies in the ephemeral browser context. Never accept optional
  cookies or persist consent.
- Do not log in, create accounts, click booking slots, reserve, pay, or persist
  participant names. Open matches remain unavailable for full-court booking.

## Architecture

The existing `MatchpointBrowserConnector` processes all configured sources
sequentially. Each source URL selects its center before the public grid loads,
so the connector needs no center-clicking logic. The current DOM script already
extracts the rendered court labels, slot geometry, and visual availability
states generically.

`MATCHPOINT_BOOKING_URLS` and `MATCHPOINT_LOCATION_IDS` become the single source
of truth for the four supported locations. The manifest loader continues to
reject unsupported IDs, wrong URLs, duplicate rows, missing coverage, malformed
timestamps, and invalid statuses.

The catalog records retain their existing verification status and unknown
fields. Their booking evidence records identify the official venue or operator
page and the corresponding public Matchpoint grid.

## Failure Handling

- A public grid that fails to load, shows an authentication challenge, has a
  stale date, or has a missing/partial court matrix becomes a bounded source
  error and preserves the previous successful snapshot.
- A changed or invalid center ID is detected by the expected visible center and
  court labels in offline/live acceptance checks; it must not silently collect
  Bernex data for Evaux or Jonction.
- Unknown visual states remain `unknown`; absent or malformed cells are never
  treated as available.
- Programming errors still propagate.

## Testing And Acceptance

Add offline coverage for:

- exact four-row manifest coverage and the two new URLs;
- Evaux and Jonction sanitized DOM fixtures, court labels, variable durations,
  and available/unavailable/unknown state mapping;
- collector selection and catalog evidence for both new location IDs;
- no participant fields, credentials, or generated databases in committed
  files.

Acceptance requires:

1. The full offline test suite passes.
2. Ruff format/lint and Pyright pass for the repository.
3. A no-login live smoke reads a short window from Bernex, Evaux, Jonction,
   and Urban Padel Lausanne.
4. The smoke reports the expected visible center and court labels for all four
   locations.

## Non-Goals

- Login, account creation, balance management, reservation, payment, or
  background scheduling.
- Private Matchpoint service calls or scraping hidden application state.
- A new connector abstraction, platform registry, or external dependency.
- Adding other deferred booking platforms.
