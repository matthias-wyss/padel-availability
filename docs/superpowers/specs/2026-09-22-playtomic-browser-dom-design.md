# Playtomic browser DOM transport

## Status

Design approved on 22 September 2026. This is an additive follow-up to the
public JSON connector design.

## Objective

Make the Playtomic collector useful when the public booking page renders
availability in the browser but exposes no usable unauthenticated JSON feed.
The collector will load the normal public page with a headless Chromium
context, read the visible DOM, normalize the observed slots, and persist them
through the existing SQLite snapshot flow.

The transport remains read-only. It never signs in, reserves a court, stores a
browser profile, or attempts to defeat an access control.

## Scope

The browser transport covers the same five catalog locations:

- `padel-station`;
- `gva-palexpo`;
- `padel-parc-etoy`;
- `padel-parc-preverenges`;
- `vaudoise-arena`.

The existing `collect-playtomic` command remains the entry point. The source
manifest selects the transport for each location, so a future verified JSON
source can continue using the standard-library adapter.

## Boundaries

- No account, login, payment, reservation, cancellation, or remote mutation.
- No persistent cookies, storage state, private tokens, or authorization
  headers. A browser context is temporary and is destroyed after one site.
- No CAPTCHA interaction, anti-bot bypass, rate-limit evasion, proxy rotation,
  fingerprint spoofing, or stealth plugin.
- No scheduler, daemon, web UI, or external headless-browser service.
- No live network request in the default test suite.
- A login page, CAPTCHA, access block, missing browser executable, timeout, or
  unknown DOM shape produces an explicit `error` or `unavailable` run.

## Runtime

Playwright is an optional dependency group because the static catalog must stay
usable without a browser:

```bash
uv sync --group browser
uv run playwright install chromium
```

The collector imports Playwright lazily. The standard-library JSON transport
does not import it. The browser command uses the synchronous Playwright API so
it fits the existing synchronous CLI and collector.

One Chromium process is launched per collection invocation. Each selected site
gets a new incognito browser context and page. The context is closed before
the next site starts. Navigation and DOM waits have bounded timeouts and no
automatic retries.

## Source manifest

Extend each source row with a transport field:

```json
{
  "location_id": "padel-station",
  "booking_url": "https://playtomic.com/fr/clubs/padel-station1",
  "transport": "browser_dom",
  "availability_url_template": null,
  "checked_at": "2026-09-22T00:00:00Z",
  "status": "public"
}
```

`transport` is `browser_dom` for the five current rows and `json` for a
verified public JSON source. A browser row does not need an availability URL;
the booking URL is the public source identity. The loader still requires
exactly one row for each of the five IDs and rejects unknown fields.

## Browser collection flow

For each requested local date in the half-open window:

1. Open the source booking URL in the temporary context.
2. Wait for the public booking view and its date controls to settle.
3. Select the requested date through the visible Playtomic control or its
   public date URL state, without constructing an undocumented API request.
4. Read visible court/slot elements and convert them to browser observations.
5. Continue through the requested horizon, deduplicating observations by
   external ID or the existing deterministic location/court/time hash.

The browser layer produces a small transport-neutral observation:

```python
@dataclass(frozen=True, slots=True)
class BrowserSlotObservation:
    external_id: str | None
    court_label: str | None
    starts_at: str
    ends_at: str
    status: Literal["available", "unavailable", "unknown"]
```

The DOM extractor uses visible slot semantics and accessibility attributes,
not hidden application state. A slot is `available` only when the page exposes
it as a selectable/free slot or labels it available. A disabled/booked slot is
`unavailable` only when that state is explicit. Ambiguous labels are
`unknown`; an empty valid date view is a successful zero-slot observation.

The existing availability parser then validates offset-aware timestamps,
rejects ambiguous local times, filters the requested window, hashes missing
IDs, and creates `AvailabilitySlot` values with `Europe/Zurich` display
timezone and UTC `Z` instants.

## Failure handling

Each site remains independent and sequential. Browser exceptions are converted
to bounded public error text and saved as that site's error run. A later error
never deletes the prior successful run; the existing snapshot query exposes it
as `stale` and reports `last_success_at`.

The browser adapter must distinguish these cases:

- valid page with no visible slots: `success`, zero slots;
- explicit public unavailable state: `unavailable`;
- timeout, malformed DOM, login/CAPTCHA/block, or missing runtime: `error`;
- programming errors: propagate rather than being silently converted.

## Tests and verification

Default tests remain offline and deterministic:

- sanitized DOM/observation fixtures for each location;
- date navigation and observation extraction without launching Chromium;
- available, unavailable, unknown, empty, malformed, and duplicate slots;
- UTC normalization and half-open horizon filtering;
- browser-missing and blocked-page error mapping through injected fakes;
- collector persistence, stale snapshots, and deterministic CLI freshness output.

A live smoke run is explicit and manual after installing Chromium. It may read
the five public pages but is not part of `pytest` and must not save cookies or
credentials.

## Acceptance criteria

1. The five manifest rows select `browser_dom` and can be collected through the
   existing CLI without authentication.
2. At least one currently displayed public slot can be normalized and saved
   when Playtomic exposes one; a page with no slots remains an explicit success
   with zero slots.
3. A blocked or unsupported page never becomes a false empty success.
4. No persistent browser state, auth code, CAPTCHA bypass, hidden API replay,
   reservation path, or external service is added.
5. Offline tests cover the DOM observation contract and existing catalog/report
   behavior remains unchanged.
