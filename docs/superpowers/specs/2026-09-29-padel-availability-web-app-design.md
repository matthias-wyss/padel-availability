# Public Padel Availability Web App

## Status

Design approved; README and AGENTS.md added to scope; written spec review pending, 2026-09-29.

## Goal

Help people quickly find a public padel court they can book soon, especially
after work, by searching configured clubs and linking directly to the venue's
booking page.

## User and product boundary

- The app is public and requires no account.
- It reads collected public availability snapshots. Opening or filtering the
  page never starts a collection.
- The only user-triggered action that writes snapshots is **Actualiser**, which
  requests a collection of all 23 configured source locations. A scheduled
  background job also updates snapshots. Neither action books, authenticates,
  pays, or collects player data.
- Booking links leave the app and open the club's public booking page.
- The selector includes the 23 locations with configured public collectors;
  the six catalog locations without a configured source are not presented as
  searchable availability venues.

## Main interaction

Use a compact, mobile-first, list-first finder rather than a map. The first
screen contains:

1. Refresh status: last update, next scheduled run, and the button to request a
   refresh of all configured sources.
2. Search controls for the next 14 days, an optional start/end time range, and
   court coverage. With no time range, show all times. **Ce soir** fills today's
   date and 18:00–22:00 but is not a fixed default.
3. A searchable checkbox list of configured clubs, grouped by municipality.
   All 23 are checked on first use; later selections are stored in that
   browser's local storage, not in a server-side user profile.
4. Available slots grouped by Europe/Zurich date and sorted by start time.

Each result shows club, municipality, indoor/outdoor/other cover status, court
label when present, start/end time, duration, snapshot freshness, and a
**Réserver** link to the source. Duration is displayed, not filtered by default.
On desktop, filters stay in a sidebar and results occupy the main column. On
mobile, filters collapse above the results.

## Data semantics

Reuse the existing `AvailabilitySnapshot` and `AvailabilitySlot` values without
inferring availability:

- `available`: appears in the main results.
- `unknown`: appears in a separate **À vérifier** section and is never counted as
  confirmed free.
- `unavailable`: omitted from the free-results list.
- `stale`: previous successful slots may appear only in **Données anciennes**,
  with their last successful timestamp.
- No snapshot, an error without a previous success, or a selected date beyond
  that source's `window_end` is shown as **Pas encore collecté**,
  **Données indisponibles**, or **Hors période publiée**, as applicable. Never
  describe these states as “aucune disponibilité”.

The database covers 29 catalog locations, but only 23 have configured sources.
Initially, the local DB has snapshots for the eight Plugin locations; production
must perform an initial complete collection before public launch. Current Plugin
public calendars expose different horizons (six sites: seven days, Crans: three,
Gland: at least fourteen). Persist and display each source's actual window; do
not attempt to bypass disabled dates.

## Visual direction and accessibility

Use the verified UI/UX Pro Max direction **Minimalism & Swiss Style**: neutral
surfaces, clear grid, compact readable cards, and a blue primary action. Use the
verified finder palette as guidance: blue (`#2563EB`) for primary controls,
available green, uncertain amber, occupied/error red, and neutral surfaces.
Statuses also need text labels; color alone must not convey availability. Use a
readable sans-serif/system fallback, visible keyboard focus, and labeled native controls.
Do not use emoji as UI icons. Do not add a map in v1 because venue coordinates
are incomplete.

## Refresh and deployment architecture

- Deploy one dedicated Docker Compose web service on CT103 (separate from its
  personal website container), behind CT100/Nginx Proxy Manager at
  `padel.matthiaswyss.ch`.
- CT103 pulls the public GitHub repository
  `matthias-wyss/padel-availability` over HTTPS. The production SQLite database
  is mounted in a persistent Docker volume outside the Git checkout, so deploys
  do not replace snapshots.
- Use Flask + Waitress, server-rendered HTML templates, and lightweight native
  JavaScript. Reuse the project's Python models, SQLite access, source manifests,
  and collectors; do not add a separate SPA build chain.
- The same deployment hosts one collector worker/scheduler. `GET` routes only read
  snapshots; a public `POST /api/refresh` requests a full refresh, returns
  immediately, and the UI polls a refresh-status route. Persist job state and the
  shared cooldown/lock in SQLite so concurrent requests cannot start another job.
- On first deployment, build the catalog from tracked candidate/verified JSON
  and complete an initial collection of all configured locations before making
  the NPM route public.
- Schedule a complete source refresh daily every 30 minutes from 07:00 through
  23:00 in `Europe/Zurich`.
- **Actualiser** requests a refresh of all configured locations. Manual and
  scheduled starts share one global five-minute cooldown and one active
  collector. While running or cooling down, the UI shows status/countdown and
  does not start a duplicate job; a scheduled tick blocked by an active job or
  cooldown is skipped rather than queued for a burst later.
- Refreshes run asynchronously. The web app keeps serving the latest snapshots
  while a job runs and shows progress/completion/per-location errors. Collection
  failures preserve prior successful snapshots as stale.
- Page reads never contact booking sites. The public refresh endpoint accepts
  no arbitrary URL, shell command, or user-supplied source path.

Any real CT103/CT100 deployment change must be verified and reflected in the
matching `workspace/infra/` documentation and committed/pushed there as required
by the infra repository instructions.

## Project documentation

- Rewrite the root `README.md` as the operator/user entry point: local setup,
  catalog initialization, supported collection commands, the web app's search
  and status behavior, source-specific availability windows, refresh cadence,
  public deployment URL, and where production data persists.
- Create a root `AGENTS.md` with repo-specific contribution rules: Python 3.12
  and quality-check commands, visible-public-DOM-only collection, no booking or
  private endpoints, preservation of unknown/stale distinctions, no committing
  ignored SQLite databases or secrets, and the infra-document process for real
  CT103/CT100 changes.
- Keep instructions concise and consistent with the existing workspace and
  cluster-level `AGENTS.md`; the project file adds repo context, not overrides.

## Acceptance checks

- A visitor can select configured clubs and indoor/outdoor coverage, enter a
  custom time range or use **Ce soir**, and browse up to fourteen days.
- Confirmed free slots are easy to scan chronologically and link to the venue's
  booking page.
- Unknown, stale, unavailable, no-snapshot, and out-of-window states are visibly
  distinct and never masquerade as confirmed free slots.
- Anonymous page loads do not start collection; refresh requests and scheduled
  runs share one worker and enforce the global five-minute cooldown.
- The interface works at 375px and desktop widths, supports keyboard operation,
  and does not rely on color alone.
- CT103 can pull the public GitHub repo and deploy without overwriting the
  persistent SQLite volume; NPM serves the public hostname over HTTPS.
- README and `AGENTS.md` describe the implemented commands, public/read-only
  boundaries, snapshot semantics, deployment layout, and verification checks.
