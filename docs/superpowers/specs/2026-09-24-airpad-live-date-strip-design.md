# AIRPAD Live Doinsport DOM Compatibility Design

## Goal

Restore live AIRPAD availability collection for its four configured sites when
the current public Doinsport booking page renders dates without date-strip
`aria-label` attributes and exposes slots through nested duration offers.

## Verified Failure

The public flow at `https://www.airpad.ch/reserve` loads the Doinsport iframe,
then `1.Terrains`, then the selected AIRPAD venue. The current page exposes
visible date-strip buttons such as `Thu 24 Sep`; the active button has an
`active` class but no `aria-label`. The current booking view also exposes
`.slot-container` elements with `.start-time .time` and one or more visible
`.slot-price-list ion-item` duration offers. Rows without offers display a
visible `.empty_playground` message. The existing extractor expects a date
`aria-label` and old `.info-playground > *` cards, so it misses current dates and
slot offers. The public booking page's generic `Sign in` and `Login or register`
navigation also appears in its visible text and currently triggers the broad
login marker even though the booking grid is public.

The public iframe's shared navigation includes generic `Sign in` and `Login or
register` links. These are not an authentication challenge and must not block
public slot collection.

The visible date picker still exposes a full accessible name such as
`September 24, 2026`, which the connector clicks. The active date-strip text can
therefore confirm the selected weekday, day, and month against the exact date
the connector requested, including its year.

## Approved Design

- Keep navigation and extraction limited to visible public DOM, visible
  attributes, and accessibility labels. Do not use private endpoints, hidden
  application state, network interception, login, or booking actions.
- Keep the existing ISO date extraction when a visible `aria-label` provides
  one.
- Also return the active visible date-strip text from the DOM script.
- After clicking the visible full-date picker entry, accept the selected date
  only when either the existing ISO value equals the requested date or the
  normalized active label matches the requested date's English weekday, day,
  and month. The full-year date picker label is the year-bearing selection; use
  the requested full ISO date only after the active strip confirms it.
- Treat a matching active date-strip label as visible date-transition evidence.
  If the requested date was already active, accept an unchanged grid without
  waiting for an artificial refresh. If changing dates, an unchanged previous
  date label remains stale and must not be accepted.
- After a time-range control changes its visible label, wait until each visible
  court row has either a valid duration offer or an explicit empty marker before
  parsing that range. The label change alone is not a complete grid.
- Keep source error and stale snapshot behavior unchanged.
- Allow generic public login-navigation links in the page chrome. Continue to
  reject explicit CAPTCHA, access-denied, sign-in-required, or other bounded
  authentication challenges and visible password/dialog challenges; never
  interact with login controls.
- For the current booking grid, emit one availability observation per visible
  duration option inside each `.slot-container`, using the visible start time,
  court title, and `ion-label` duration. A visible disabled/unavailable marker
  remains unavailable; a visible selectable duration offer without such a
  marker is available. Do not click offers or persist prices.
- Treat a row with visible `.empty_playground` content and no offers as an
  explicit empty row. A row that has neither a valid offer nor an explicit
  empty-state marker is malformed and remains an error. Reject malformed rows
  before returning any slots.
- Allow generic login-navigation links in the page chrome, but reject visible
  password inputs, authentication dialogs, explicit sign-in-required text,
  CAPTCHA, and access-denied markers. Never interact with login controls.

## Testing

- Add sanitized HTML fixtures for the current visible AIRPAD date-strip,
  `.slot-container` offers, an explicitly empty row, and an authentication
  dialog; include no scripts or network data and omit date-strip `aria-label`.
- Test visible-label matching and mismatch, including a year-boundary date.
- Test multiple duration offers at one start time, explicit empty rows, generic
  login navigation, visible password/dialog authentication challenges, and
  CAPTCHA errors.
- Test that an already-active requested date can be collected without a grid
  refresh and that changing to another date still rejects stale grid content.
- Run the live two-day AIRPAD collection for all four sites with no
  `LD_LIBRARY_PATH` or `FONTCONFIG_FILE` overrides, then inspect each persisted
  run and slot through the application database API.
- Repeat the all-source smoke and the repository's complete Ruff, Pyright, and
  pytest checks.

## Boundaries

- No dependency, CLI, manifest, or persistence schema changes.
- No automatic collection scheduling or booking behavior.
- No changes to Playtomic, Everness, or Padel First semantics.
- The existing project work remains uncommitted until the user explicitly
  requests integration.
