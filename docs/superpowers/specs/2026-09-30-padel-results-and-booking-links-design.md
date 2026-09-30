# Padel Results and Booking Links

## Status

Design approved in chat; written spec awaiting user review, 2026-09-30.

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
  courts; use a neutral count of matching source entries.
- Update the result summary to count grouped time windows and matching
  court-time opportunities. The latter is the sum across result windows, not a
  count of distinct physical courts.
- Keep **À vérifier** and **Données anciennes** in their existing separate
  sections, grouped by the same exact-window rule.

## Booking links

- A date-level link is sufficient; the user chooses the exact court/time on the
  venue site when that platform does not expose a public URL for one exact slot.
- Validate date-link behavior for all configured booking platform families by
  navigating their public pages and using only visible date controls. Do not
  click a free slot, book, log in, or call private APIs.
- Add a platform-specific date URL only when the public route is verified to
  open the requested day. For Playtomic `.com` club pages, set `date=YYYY-MM-DD`
  using the slot's Europe/Zurich date and preserve other URL components.
- If a platform has no verified public date link, retain its existing verified
  booking URL. Never invent parameters or a private deep link.
- Use the same day-level reservation link for every court in a merged card;
  preserve `target="_blank"` and `rel="noopener noreferrer"`.

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
