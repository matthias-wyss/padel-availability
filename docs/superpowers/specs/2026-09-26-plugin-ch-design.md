# Plugin.ch Public Availability Connector

## Status

Approved design. Checked public booking routes on 2026-09-26.

## Objective

Add one browser-DOM connector for the eight Plugin.ch tenants already present in
the catalog. The connector reads public padel availability without logging in,
booking a court, using private endpoints, or collecting participant data.

The first implementation covers:

| Location ID | Public booking route | Platform |
| --- | --- | --- |
| `fraisiers` | `https://tcfraisiers.plugin.ch/?sport=301` | Plugin.ch |
| `csu-champel` | `https://unige.plugin.ch/` | Plugin.ch |
| `drizia-miremont` | `https://tcdrizia.plugin.ch/` | Plugin.ch |
| `cologny` | `https://reservation.cs-cologny.ch/diary` | Plugin.ch |
| `collonge-bellerive` | `https://reservation.tccb.ch/diary` | Plugin.ch |
| `mies-tannay` | `https://tcmt.plugin.ch/user/diary` | Plugin.ch |
| `crans-vd` | `https://tccrans.plugin.ch/user/diary` | Plugin.ch |
| `gland` | `https://tcgland.plugin.ch/user/diary` | Plugin.ch |

Some tenants expose a public diary while requiring membership or an account to
complete a reservation. That distinction remains in the catalog facts and does
not block read-only availability collection when the diary is public.

## Architecture

Add the following project components:

- `src/padel_availability/connectors/plugin.py` — strict source model and manifest loader.
- `src/padel_availability/connectors/plugin_browser.py` — visible DOM extraction, validation, and connector.
- `data/plugin_sources.json` — exactly the eight source rows above.
- `tests/test_plugin.py` and `tests/test_plugin_browser.py` — manifest, parser, fixture, and lifecycle coverage.

Register the connector in the existing collector and CLI patterns with a
`collect-plugin` command. Reuse `BrowserSlotObservation`, timezone handling,
database persistence, stale-snapshot behavior, and the existing browser
factory conventions. Do not add a generic connector framework or a new
dependency.

## Source Contract

Each manifest row contains the existing source fields:

- `location_id`
- `booking_url`
- `checked_at`, initially `2026-09-26T00:00:00Z`
- `status`, initially `public`

The loader rejects wrong fields, duplicate or missing IDs, non-Plugin routes,
invalid timestamps, and manifests whose coverage is not exactly the eight
declared locations. Rows are returned sorted by `location_id`.

The catalog records for all eight locations gain the matching booking URL and
`Plugin.ch` booking platform evidence. Existing membership, access, and
account facts are preserved rather than inferred from public diary visibility.

## Browser Data Flow

For each requested location and date window:

1. Open the source URL in an ephemeral browser context.
2. Decline optional cookies only when a visible decline control is present; never accept optional cookies.
3. Wait for a stable visible Plugin diary and the requested date.
4. Confirm that the visible activity is `Padel`.
5. Extract a sanitized payload containing only:
   - `view`
   - selected `date`
   - selected `activity`
   - visible `courts`
   - visible `slots` with `court`, `start`, `end`, and `state`
   - `loading`
   - `authentication_visible`
   - explicit `empty_grid`
6. Navigate to later dates using visible date controls only.
7. Parse observations and pass them through the existing UTC normalization pipeline.

The route tenant is the source identity. If a stable tenant label is exposed in
the visible DOM, it may be validated as an additional drift guard; the parser
must not rely on hidden metadata or request parameters for identity.

The parser supports variable slot durations and Europe/Zurich local times. It
does not collect names, account identifiers, prices, or booking links from slot
cells.

## State And Failure Handling

Map visible cell states conservatively:

- free/open booking cell: `available`
- reserved, closed, or occupied cell: `unavailable`
- explicitly recognized ambiguous visual state: `unknown`

Fail closed with a connector error when:

- the page is loading or the diary is not visible;
- an authentication, CAPTCHA, or access-denied view is visible;
- the selected date does not match the requested date;
- the selected activity is not `Padel`;
- court labels or slot fields are malformed;
- the visible matrix is partial or contains duplicate slots;
- a cell has an absent or unrecognized raw state, or its visual state cannot be
  trusted as availability.

An explicitly visible no-availability message is a successful empty result.
Absence of both slots and an explicit empty marker is an error, not an empty
success. Browser and parser errors use the existing bounded error messages and
stale-snapshot persistence rules.

Always close page, context, and browser resources, including parser and
navigation failures.

## Testing And Verification

Offline tests cover:

- exact eight-row manifest coverage, URLs, ordering, and rejection cases;
- sanitized fixtures for the common Plugin diary layout and any observed layout variant;
- date, activity, court matrix, variable duration, state, empty-grid, authentication, and malformed-DOM validation;
- browser lifecycle, visible date navigation, optional-cookie handling, and startup errors;
- collector execution for all eight catalog locations.

Documentation and generated inventory reports are updated with the eight source
URLs and platform evidence. Verification includes the full test suite, Ruff,
Pyright, and a read-only live smoke for all eight public routes.

## Non-Goals

- No login, membership activation, reservation, payment, or account automation.
- No private Plugin API or reverse-engineered request contract.
- No automatic discovery of new Plugin tenants outside the eight catalog records.
- No per-tenant parser until a fixture demonstrates a real DOM divergence.
