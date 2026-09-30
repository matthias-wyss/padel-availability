# Padel Results and Booking Links

## Status

Design and written spec approved by the user, 2026-09-30.

## Goal

Make the public availability list easier to scan by showing one result card per
club and exact time window, rather than one card per available court. Where a
booking platform supports a verified public date link, send visitors directly
to the corresponding day.

## Observed UI

The live page showed 7,331 available slot records as separate cards. Records for
different courts at the same club and same time repeated the same club name,
time, freshness, and booking link. The approved visual direction remains
Minimal Swiss; v1 keeps the date/coverage/club filters and chronological list.

## Result grouping

- Apply the existing club, coverage, date, and time filters to individual slot
  records first.
- Group matching records by `location_id`, exact `starts_at`, exact `ends_at`,
  snapshot state, and slot state. Different durations remain separate cards.
- Never merge fresh `available`, `unknown`, and stale slots together.
- Keep each court label and source slot in the fetched data; group only for
  presentation. Show one compact card with the time range, duration, club,
  municipality, cover, freshness, and reservation link. Show the number of
  matching courts and their labels when present.
- When court labels are absent, do not infer that multiple records are distinct
  courts; use a neutral count of matching source entries. When only some rows
  have labels, show named courts and unlabelled possibilities separately.
- Update the result summary to count grouped time windows and matching
  court-time opportunities. The latter is the sum across result windows, not a
  count of distinct physical courts.
- Keep **À vérifier** and **Données anciennes** in their existing separate
  sections, grouped by the same exact-window rule.

## Booking links

- A date-level link is sufficient; the user chooses the exact court/time on the
  venue site when that platform does not expose a public URL for one exact slot.
- Validate date-link behavior for all configured booking platform families by
  navigating their public pages and checking the visible selected date. When a
  date control is needed, use only that visible control. Do not click a free
  slot, book, log in, or call private APIs.
- Add a platform-specific date URL only when the public route is verified to
  open the requested day. For Playtomic `.com`, Playtomic `.io` redirects, and
  Everness, set `date=YYYY-MM-DD` using the slot's Europe/Zurich date and preserve
  other URL components.
- If a platform has no verified public date link, retain its existing verified
  booking URL. Never invent parameters or a private deep link.
- Use the same day-level reservation link for every court in a merged card;
  preserve `target="_blank"` and `rel="noopener noreferrer"`.

### Public date-link validation (2026-09-30)

For sample day `2026-10-01`, using only public pages and visible DOM:

- Playtomic `.com`: `?date=2026-10-01` opened the visible booking day `2026-10-01`.
- Playtomic `.io` (Vaudoise Arena): the route redirected to its `.com` club page,
  and the same `date` parameter opened the visible day `2026-10-01` while
  preserving its existing `q` parameter.
- Everness: `?date=2026-10-01` opened the visible booking day `1 oct. 2026`.
- AIRPAD: the date query remained in the URL but did not set an active date on
  the generic reservation landing page; its public Doinsport frame initially
  showed a location-selection view.
- Matchpoint: the date query remained in the URL while the visible grid stayed
  on its default day; the visible next-day control was blocked by the page
  overlay during the probe.
- Padel First: the date query remained in the URL but did not select a day in
  the visible calendar.
- Plugin.ch: the date query was ignored by the public diary route; its visible
  datepicker probe did not complete because Playwright could not click the
  matched visible day after the datepicker changed.

Therefore, this revision adds date parameters only for Playtomic `.com`,
Playtomic `.io`, and Everness. AIRPAD, Matchpoint, Padel First, and Plugin.ch
retain their existing booking URLs; do not claim those links preselect a day.

## Compact presentation

On desktop, use compact chronological rows/cards with the time range and club
name first, court count/labels and cover/freshness as supporting metadata, and
one clear **Réserver** action. On mobile, keep the same information in a
single-column card with the action below the details and a minimum 44px target.
Keep textual status labels, keyboard focus, responsive filters, and the existing
color/status semantics. Do not add a map, a client framework, or new runtime
dependencies.

## Scope and data boundaries

- Preserve all individual `AvailabilitySlot` records in SQLite and the API;
  aggregation is a presentation concern.
- Retain stale, unknown, no-data, unavailable, and out-of-window distinctions.
- Keep existing booking URLs when a safe public date URL cannot be established.
- Do not trigger collection from page loads or filters.

## Acceptance

- Two courts with the same club, start, and end time appear as one card with
  their court count/labels; two durations with the same start remain separate.
- Mixed labeled/unlabeled groups show known court labels separately from neutral
  unlabelled possibilities.
- Unknown and stale records remain in their separate sections after grouping.
- Filters are applied before grouping; the summary reports grouped windows and
  court-time opportunities, not raw duplicate cards or distinct physical court
  assets.
- Playtomic `.com` opens the selected Europe/Zurich day with a correct `date`
  parameter; each other platform uses a date URL only after public validation.
- Unsupported direct-date routes retain the current booking URL without guessed
  parameters.
- The compact card works at mobile and desktop widths, remains keyboard
  accessible, and still shows the real end time/duration and freshness.
