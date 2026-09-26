import re
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, time, timedelta
from typing import Literal, Protocol, cast
from zoneinfo import ZoneInfo

from ..availability import AvailabilityResult, AvailabilityRun, AvailabilitySlot
from ..models import LocationRecord, ModelError
from .matchpoint import (
    MATCHPOINT_EXPECTED_CENTERS,
    MatchpointSource,
    MatchpointSourceError,
)
from .playtomic import PlaytomicSourceError
from .playtomic_browser import (
    BrowserFactory,
    BrowserSlotObservation,
    _is_documented_browser_error,  # pyright: ignore[reportPrivateUsage]
    default_browser_factory,
    parse_browser_observations,
)

MatchpointBrowserStatus = Literal["available", "unavailable", "unknown"]

__all__ = [
    "BrowserSlotObservation",
    "MatchpointBrowserConnector",
    "MatchpointBrowserConnectorFactory",
    "MatchpointBrowserError",
    "MatchpointBrowserStatus",
    "default_browser_factory",
    "parse_matchpoint_dom",
    "parse_matchpoint_observations",
]

_MATCHPOINT_ZURICH = ZoneInfo("Europe/Zurich")
_MATCHPOINT_TIMEOUT_MS = 15_000
_MATCHPOINT_SLOT_STATES: dict[str, MatchpointBrowserStatus] = {
    "available": "available",
    "booked": "unavailable",
    "open_match": "unavailable",
}

_MATCHPOINT_VISIBLE_DOM_SCRIPT = r"""
() => {
  const visible = element => {
    if (!element) return false;
    const rect = element.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return false;
    for (let current = element; current; current = current.parentElement) {
      const style = getComputedStyle(current);
      if (current.hidden || current.getAttribute('aria-hidden') === 'true' ||
          style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') {
        return false;
      }
    }
    return true;
  };
  const text = element => (element?.textContent || '').replace(/\s+/g, ' ').trim();
  const numericAttribute = (element, name) => {
    const value = Number(element.getAttribute(name));
    return Number.isFinite(value) ? value : null;
  };
  const parseVisibleDate = value => {
    const match = String(value || '').trim().match(/^(?:[\p{L}]+,\s*)?(\d{1,2})\s+([\p{L}]+),?\s+(\d{4})$/u);
    if (!match) return '';
    const monthName = match[2].normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
    const months = {
      janvier: 1, fevrier: 2, mars: 3, avril: 4, mai: 5, juin: 6,
      juillet: 7, aout: 8, septembre: 9, octobre: 10, novembre: 11, decembre: 12
    };
    const month = months[monthName];
    const day = Number(match[1]);
    const year = Number(match[3]);
    if (!month || day < 1 || day > 31) return '';
    const candidate = new Date(Date.UTC(year, month - 1, day));
    if (candidate.getUTCFullYear() !== year || candidate.getUTCMonth() !== month - 1 ||
        candidate.getUTCDate() !== day) return '';
    return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
  };
  const parseRange = value => {
    const match = String(value || '').match(/\b([01]\d|2[0-3]):([0-5]\d)\s*[-–]\s*([01]\d|2[0-3]):([0-5]\d)\b/);
    if (!match) return null;
    return [`${match[1]}:${match[2]}`, `${match[3]}:${match[4]}`];
  };

  const body = document.body;
  const visibleBodyText = body?.innerText || '';
  const normalizedText = visibleBodyText.replace(/\s+/g, ' ').trim().toLowerCase();
  const centerElement = document.querySelector('#labelCentro');
  const center = centerElement && visible(centerElement) ? text(centerElement) : '';
  const authenticationMarker = /captcha|verify\s+you\s+are\s+human|access\s+denied|accès\s+refusé|login\s+required|sign\s+in\s+required|authentication\s+required|connexion\s+requise|se\s+connecter\s+pour\s+continuer/i;
  const authenticationVisible = authenticationMarker.test(normalizedText) ||
    Array.from(body?.querySelectorAll('input[type="password"]') || []).some(visible) ||
    Array.from(body?.querySelectorAll('[role="dialog"], [aria-modal="true"]') || [])
      .some(element => visible(element) && authenticationMarker.test(text(element)));
  const loading = Array.from(body?.querySelectorAll('.loading, [aria-busy="true"]') || []).some(visible) ||
    /\bloading\b|chargement|please\s+wait|mise\s+à\s+jour/i.test(normalizedText);
  const visibleDateMatch = visibleBodyText.match(/(?:[\p{L}]+,\s*)?\d{1,2}\s+[\p{L}]+,?\s+\d{4}/u);
  const root = document.querySelector('.myReservas');
  const svg = root && visible(root)
    ? (root.matches('svg') ? root : root.querySelector('svg'))
    : null;
  const date = visibleDateMatch ? parseVisibleDate(visibleDateMatch[0]) : '';
  const slotsByKey = new Map();
  const courts = [];

  if (svg && visible(svg)) {
    const svgTexts = Array.from(svg.querySelectorAll('text')).filter(visible);
    const headers = Array.from(svg.querySelectorAll('rect.fondoCabecera')).filter(visible)
      .map(rect => ({
        rect,
        x: numericAttribute(rect, 'x'),
        y: numericAttribute(rect, 'y'),
        width: numericAttribute(rect, 'width'),
        height: numericAttribute(rect, 'height')
      }))
      .filter(item => item.x !== null && item.x > 0 && item.width !== null &&
        item.y !== null && item.height !== null);
    const columns = headers.map(header => {
      const labels = svgTexts.filter(element => {
        const x = numericAttribute(element, 'x');
        const y = numericAttribute(element, 'y');
        return x !== null && y !== null && x >= header.x && x < header.x + header.width &&
          y >= header.y && y <= header.y + header.height;
      }).map(text);
      const courtLabel = labels.filter(label => /terrain|court/i.test(label)).at(-1) || labels.at(-1) || '';
      return {...header, courtLabel};
    }).filter(column => column.courtLabel);
    for (const column of columns) {
      if (!courts.includes(column.courtLabel)) courts.push(column.courtLabel);
    }

    const timeTicks = svgTexts.filter(element => element.classList.contains('celdaTxt'))
      .map(element => ({time: text(element), y: numericAttribute(element, 'y')}))
      .filter(item => item.y !== null && /^[0-2]\d:[0-5]\d$/.test(item.time))
      .map(item => ({time: item.time, y: item.y}));
    let pixelsPerMinute = null;
    for (let index = 1; index < timeTicks.length; index += 1) {
      const [previousHour, previousMinute] = timeTicks[index - 1].time.split(':').map(Number);
      const [hour, minute] = timeTicks[index].time.split(':').map(Number);
      const deltaMinutes = hour * 60 + minute - (previousHour * 60 + previousMinute);
      const deltaY = timeTicks[index].y - timeTicks[index - 1].y;
      if (deltaMinutes > 0 && deltaY > 0) {
        pixelsPerMinute = deltaY / deltaMinutes;
        break;
      }
    }

    const geometryRange = (y, height) => {
      if (pixelsPerMinute === null) return null;
      const tick = timeTicks.filter(item => item.y >= y && item.y < y + height)
        .sort((left, right) => left.y - right.y)[0];
      const duration = Math.round(height / pixelsPerMinute);
      if (!tick || Math.abs(duration * pixelsPerMinute - height) > 1 ||
          duration <= 0 || duration > 240) return null;
      const [hour, minute] = tick.time.split(':').map(Number);
      const startMinutes = hour * 60 + minute;
      const endMinutes = startMinutes + duration;
      if (endMinutes >= 24 * 60) return null;
      return [
        `${String(Math.floor(startMinutes / 60)).padStart(2, '0')}:${String(startMinutes % 60).padStart(2, '0')}`,
        `${String(Math.floor(endMinutes / 60)).padStart(2, '0')}:${String(endMinutes % 60).padStart(2, '0')}`
      ];
    };
    const columnAt = x => columns.find(item => x >= item.x && x < item.x + item.width);
    const addSlot = (column, range, state, x, y) => {
      if (!range) return;
      const [start, end] = range;
      const key = `${column.courtLabel}|${start}|${end}`;
      const existing = slotsByKey.get(key);
      if (existing && existing.state !== 'available' && state === 'available') return;
      slotsByKey.set(key, {court: column.courtLabel, start, end, state, x, y});
    };
    const buttons = Array.from(svg.querySelectorAll('rect.buttonHora')).filter(visible);
    for (const button of buttons) {
      const x = numericAttribute(button, 'x');
      const y = numericAttribute(button, 'y');
      const width = numericAttribute(button, 'width');
      const height = numericAttribute(button, 'height');
      if (x === null || y === null || width === null || height === null) continue;
      const column = columnAt(x + width / 2);
      if (!column) continue;

      const cellTexts = svgTexts.filter(element => {
        if (element.classList.contains('celdaTxt') || element.className.baseVal.startsWith('cabecera')) {
          return false;
        }
        const textX = numericAttribute(element, 'x');
        const textY = numericAttribute(element, 'y');
        return textX !== null && textY !== null && textX >= x - 1 && textX <= x + width + 1 &&
          textY >= y - 2 && textY <= y + height + 2;
      });
      const offer = cellTexts.find(element => element.classList.contains('horaFijaConTexto'));
      const fixedSlot = cellTexts.find(element => element.classList.contains('horaFija'));
      const openMatch = cellTexts.find(element => element.classList.contains('fechaSupEvtSolo'));
      const completeMarker = cellTexts.some(element => /\bcomplet(?:e)?\b/i.test(text(element)));
      const price = Array.from(svg.querySelectorAll('rect.rectPrecio')).some(element => {
        if (!visible(element)) return false;
        const priceX = numericAttribute(element, 'x');
        const priceY = numericAttribute(element, 'y');
        return priceX !== null && priceY !== null && priceX >= x && priceX <= x + width &&
          priceY >= y && priceY <= y + height;
      });
      const rangeElement = offer || fixedSlot || openMatch;
      const range = rangeElement ? parseRange(text(rangeElement)) : null;
      let state = 'unknown';
      if (openMatch || button.parentElement?.classList.contains('datosEvento')) {
        state = 'open_match';
      } else if (completeMarker) {
        state = 'booked';
      } else if (offer && price) {
        state = 'available';
      } else if (fixedSlot) {
        state = 'available';
      } else if (cellTexts.length === 0) {
        state = 'available';
      }

      addSlot(column, range || geometryRange(y, height), state, x, y);
    }

    for (const event of Array.from(svg.querySelectorAll('rect.evento')).filter(visible)) {
      const x = numericAttribute(event, 'x');
      const y = numericAttribute(event, 'y');
      const width = numericAttribute(event, 'width');
      const height = numericAttribute(event, 'height');
      if (x === null || y === null || width === null || height === null) continue;
      const column = columnAt(x + width / 2);
      if (!column) continue;
      const eventTexts = svgTexts.filter(element => {
        if (!element.classList.contains('fechaSupEvtSolo') &&
            !element.classList.contains('fechaSupEvt')) return false;
        const textX = numericAttribute(element, 'x');
        const textY = numericAttribute(element, 'y');
        return textX !== null && textY !== null && textX >= x - 1 && textX <= x + width + 1 &&
          textY >= y - 2 && textY <= y + height + 2;
      });
      const eventText = eventTexts.find(element => parseRange(text(element)) !== null);
      const range = eventText ? parseRange(text(eventText)) : geometryRange(y, height);
      const fill = (event.getAttribute('fill') || getComputedStyle(event).fill).toLowerCase();
      const state = fill.includes('22c55e') || fill.includes('34, 197, 94')
        ? 'open_match'
        : fill.includes('ef4444') || fill.includes('239, 68, 68')
          ? 'booked'
          : 'unknown';
      addSlot(column, range, state, x, y);
    }
  }

  const slots = Array.from(slotsByKey.values())
    .sort((left, right) => left.y - right.y || left.x - right.x)
    .map(({court, start, end, state}) => ({court, start, end, state}));
  const emptyMarker = /no\s+(?:available\s+)?slots|aucun\s+créneau|aucune\s+disponibilité/i.test(normalizedText);
  return {
    view: svg && visible(svg) ? 'booking' : 'unknown',
    date,
    center,
    courts,
    slots,
    loading,
    authentication_visible: authenticationVisible,
    empty_grid: slots.length === 0 && emptyMarker
  };
}
"""


class _MatchpointPage(Protocol):
    def goto(self, url: str, *, wait_until: str, timeout: int) -> object: ...

    def locator(self, selector: str) -> "_MatchpointLocator": ...

    def wait_for_timeout(self, timeout: int) -> None: ...

    def evaluate(self, expression: str, arg: object = None) -> object: ...

    def close(self) -> None: ...


class _MatchpointLocator(Protocol):
    def count(self) -> int: ...

    def is_visible(self) -> bool: ...

    def click(self) -> None: ...


class _MatchpointContext(Protocol):
    def new_page(self) -> _MatchpointPage: ...

    def close(self) -> None: ...


class _MatchpointBrowser(Protocol):
    def new_context(self) -> _MatchpointContext: ...

    def __exit__(self, *args: object) -> None: ...


class MatchpointBrowserError(MatchpointSourceError):
    """Raised when the visible Matchpoint booking grid cannot be parsed safely."""


def _dom_mapping(value: object, field: str = "visible DOM") -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise MatchpointBrowserError(f"{field} has an invalid shape")
    return cast(Mapping[str, object], value)


def _parse_date(value: object) -> date:
    if not isinstance(value, str):
        raise MatchpointBrowserError("visible Matchpoint date is invalid")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise MatchpointBrowserError("visible Matchpoint date is invalid") from error
    if parsed.isoformat() != value:
        raise MatchpointBrowserError("visible Matchpoint date is invalid")
    return parsed


def _parse_time(value: object, field: str) -> time:
    if not isinstance(value, str):
        raise MatchpointBrowserError(f"visible slot {field} is invalid")
    match = re.fullmatch(r"([01][0-9]|2[0-3]):([0-5][0-9])", value.strip())
    if match is None:
        raise MatchpointBrowserError(f"visible slot {field} is invalid")
    return time(int(match.group(1)), int(match.group(2)))


def _local_datetime(local_date: date, local_time: time, field: str) -> datetime:
    wall_time = datetime.combine(local_date, local_time)
    first = wall_time.replace(tzinfo=_MATCHPOINT_ZURICH, fold=0)
    second = wall_time.replace(tzinfo=_MATCHPOINT_ZURICH, fold=1)
    if first.utcoffset() != second.utcoffset():
        raise MatchpointBrowserError(f"visible slot {field} is ambiguous in Europe/Zurich")
    return first


def _slot_observation(
    value: object,
    *,
    requested_date: date,
    court_labels: set[str],
) -> BrowserSlotObservation:
    slot = _dom_mapping(value, "visible slot")
    if set(slot) != {"court", "start", "end", "state"}:
        raise MatchpointBrowserError("visible slot has invalid fields")

    court = slot.get("court")
    state = slot.get("state")
    if not isinstance(court, str) or court not in court_labels:
        raise MatchpointBrowserError("visible slot has an unknown court label")
    if not isinstance(state, str) or not state:
        raise MatchpointBrowserError("visible slot has an invalid state")

    start_time = _parse_time(slot.get("start"), "start time")
    end_time = _parse_time(slot.get("end"), "end time")
    if end_time <= start_time:
        raise MatchpointBrowserError("visible slot has an invalid duration")
    start_local = _local_datetime(requested_date, start_time, "starts_at")
    end_local = _local_datetime(requested_date, end_time, "ends_at")

    try:
        return BrowserSlotObservation(
            None,
            court,
            start_local.isoformat(timespec="seconds"),
            end_local.isoformat(timespec="seconds"),
            _MATCHPOINT_SLOT_STATES.get(state, "unknown"),
        )
    except (ModelError, TypeError, ValueError) as error:
        raise MatchpointBrowserError("visible slot failed validation") from error


def parse_matchpoint_dom(
    payload: object,
    requested_date: date,
    *,
    expected_center: str | None = None,
) -> tuple[BrowserSlotObservation, ...]:
    """Parse sanitized public Matchpoint slot observations for one date."""
    dom = _dom_mapping(payload)
    if dom.get("view") != "booking":
        raise MatchpointBrowserError("visible Matchpoint booking view was not found")
    if _parse_date(dom.get("date")) != requested_date:
        raise MatchpointBrowserError("visible Matchpoint date does not match requested date")
    if expected_center is not None:
        center = dom.get("center")
        if not isinstance(center, str) or center.strip() != expected_center:
            raise MatchpointBrowserError(
                "visible Matchpoint center does not match requested location"
            )

    loading = dom.get("loading")
    authentication_visible = dom.get("authentication_visible")
    if not isinstance(loading, bool) or not isinstance(authentication_visible, bool):
        raise MatchpointBrowserError("visible Matchpoint state flags are invalid")
    if authentication_visible:
        raise MatchpointBrowserError("public Matchpoint page is blocked by authentication")
    if loading:
        raise MatchpointBrowserError("visible Matchpoint grid is still loading")

    raw_courts = dom.get("courts")
    raw_slots = dom.get("slots")
    if not isinstance(raw_courts, list) or not isinstance(raw_slots, list):
        raise MatchpointBrowserError("visible Matchpoint grid is missing court or slot data")
    courts = cast(list[object], raw_courts)
    if not courts or not all(isinstance(court, str) and court.strip() for court in courts):
        raise MatchpointBrowserError("visible Matchpoint grid is missing court labels")
    court_labels = {cast(str, court).strip() for court in courts}
    if len(court_labels) != len(courts):
        raise MatchpointBrowserError("visible Matchpoint grid has duplicate court labels")

    empty_grid = dom.get("empty_grid")
    if not isinstance(empty_grid, bool):
        raise MatchpointBrowserError("visible Matchpoint grid has an invalid empty state")
    slots = cast(list[object], raw_slots)
    if not slots:
        if empty_grid:
            return ()
        raise MatchpointBrowserError("visible Matchpoint booking view has no availability state")
    if empty_grid:
        raise MatchpointBrowserError("visible Matchpoint grid has conflicting empty state")

    observations: list[BrowserSlotObservation] = []
    seen: set[tuple[str, str, str]] = set()
    seen_courts: set[str] = set()
    for raw_slot in slots:
        observation = _slot_observation(
            raw_slot,
            requested_date=requested_date,
            court_labels=court_labels,
        )
        key = (observation.court_label or "", observation.starts_at, observation.ends_at)
        if key in seen:
            raise MatchpointBrowserError("visible Matchpoint grid has duplicate slots")
        seen.add(key)
        seen_courts.add(observation.court_label or "")
        observations.append(observation)
    if seen_courts != court_labels:
        raise MatchpointBrowserError("visible Matchpoint grid has a partial court matrix")
    return tuple(observations)


def parse_matchpoint_observations(
    observations: Sequence[BrowserSlotObservation],
    *,
    location_id: str,
    run_id: str,
    window_start: date,
    window_end: date,
) -> tuple[AvailabilitySlot, ...]:
    try:
        return parse_browser_observations(
            observations,
            location_id=location_id,
            run_id=run_id,
            window_start=window_start,
            window_end=window_end,
        )
    except PlaytomicSourceError as error:
        raise MatchpointBrowserError(str(error)[:160]) from error


def _visible_locator(page: _MatchpointPage, selector: str) -> _MatchpointLocator:
    locator = page.locator(selector)
    if locator.count() != 1 or not locator.is_visible():
        raise MatchpointBrowserError(f"visible Matchpoint control {selector} was not found")
    return locator


def _wait_for_consent_overlay(page: _MatchpointPage, timeout_ms: int) -> None:
    overlay = page.locator(".banner-block-screen")
    for _ in range(max(1, timeout_ms // 100)):
        if overlay.count() == 0 or not overlay.is_visible():
            return
        page.wait_for_timeout(100)
    raise MatchpointBrowserError("optional cookie banner did not close after declining")


def _decline_optional_cookies(page: _MatchpointPage, timeout_ms: int) -> None:
    for label in ("Décliner", "Decline"):
        decline = page.locator(f'input.boton-userpreferences[value="{label}"]:visible')
        count = decline.count()
        if count == 0:
            continue
        if count != 1 or not decline.is_visible():
            raise MatchpointBrowserError("visible optional-cookie decline control is ambiguous")
        decline.click()
        _wait_for_consent_overlay(page, timeout_ms)
        return


def _matchpoint_grid_ready(dom: Mapping[str, object]) -> bool:
    raw_courts = dom.get("courts")
    raw_slots = dom.get("slots")
    if not isinstance(raw_courts, list) or not raw_courts or not isinstance(raw_slots, list):
        return False
    courts = cast(list[object], raw_courts)
    slots = cast(list[object], raw_slots)
    if not all(isinstance(court, str) and court.strip() for court in courts):
        return False
    if not slots:
        return dom.get("empty_grid") is True
    slot_courts: set[str] = set()
    for raw_slot in slots:
        if not isinstance(raw_slot, Mapping):
            return False
        court = cast(Mapping[str, object], raw_slot).get("court")
        if isinstance(court, str):
            slot_courts.add(court)
    return set(cast(list[str], courts)) <= slot_courts


def _wait_for_matchpoint_date(
    page: _MatchpointPage, requested_date: date, timeout_ms: int
) -> object:
    for _ in range(max(1, timeout_ms // 100)):
        payload = page.evaluate(_MATCHPOINT_VISIBLE_DOM_SCRIPT)
        dom = _dom_mapping(payload)
        if dom.get("authentication_visible") is True:
            return payload
        if (
            dom.get("view") == "booking"
            and dom.get("date") == requested_date.isoformat()
            and dom.get("loading") is False
            and _matchpoint_grid_ready(dom)
        ):
            return payload
        page.wait_for_timeout(100)
    raise MatchpointBrowserError("timed out waiting for the requested Matchpoint date")


def _unavailable_result(
    source_url: str,
    location_id: str,
    run_id: str,
    window_start: date,
    window_end: date,
    collected_at: str,
) -> AvailabilityResult:
    run = AvailabilityRun(
        run_id,
        location_id,
        "matchpoint_browser",
        source_url,
        window_start.isoformat(),
        window_end.isoformat(),
        (window_end - window_start).days,
        collected_at,
        "unavailable",
        "public Matchpoint booking grid is unavailable",
    )
    return AvailabilityResult(run, ())


class MatchpointBrowserConnector:
    def __init__(
        self,
        sources: Sequence[MatchpointSource],
        *,
        browser_factory: BrowserFactory = default_browser_factory,
        timeout_ms: int = _MATCHPOINT_TIMEOUT_MS,
    ) -> None:
        self._sources = {source.location_id: source for source in sources}
        self._browser_factory = browser_factory
        self._timeout_ms = timeout_ms
        self._browser: _MatchpointBrowser | None = None

    def open(self) -> None:
        if self._browser is not None:
            return
        session = self._browser_factory()
        try:
            browser = session.__enter__()
        except BaseException:
            session.__exit__(*sys.exc_info())
            raise
        self._browser = cast(_MatchpointBrowser, browser)

    def close(self) -> None:
        browser = self._browser
        self._browser = None
        if browser is not None:
            browser.__exit__(None, None, None)

    def collect(
        self,
        location: LocationRecord,
        *,
        run_id: str,
        window_start: date,
        window_end: date,
        collected_at: str,
    ) -> AvailabilityResult:
        if window_end <= window_start:
            raise MatchpointSourceError("requested date window is invalid")
        source = self._sources.get(location.location_id)
        if source is None:
            raise MatchpointSourceError("no source metadata for location")
        if source.status == "unavailable":
            return _unavailable_result(
                source.booking_url,
                location.location_id,
                run_id,
                window_start,
                window_end,
                collected_at,
            )
        expected_center = MATCHPOINT_EXPECTED_CENTERS.get(location.location_id)
        if expected_center is None:
            raise MatchpointSourceError("no expected center metadata for location")

        observations: list[BrowserSlotObservation] = []
        try:
            self.open()
            browser = self._browser
            if browser is None:
                raise MatchpointBrowserError("browser session is not running")
            context = browser.new_context()
            try:
                page = context.new_page()
                try:
                    page.goto(source.booking_url, wait_until="commit", timeout=self._timeout_ms)
                    _decline_optional_cookies(page, self._timeout_ms)
                    current_date = window_start
                    payload = _wait_for_matchpoint_date(page, current_date, self._timeout_ms)
                    while current_date < window_end:
                        observations.extend(
                            parse_matchpoint_dom(
                                payload,
                                current_date,
                                expected_center=expected_center,
                            )
                        )
                        current_date += timedelta(days=1)
                        if current_date < window_end:
                            _decline_optional_cookies(page, self._timeout_ms)
                            _visible_locator(page, "button.manyana").click()
                            payload = _wait_for_matchpoint_date(
                                page, current_date, self._timeout_ms
                            )
                finally:
                    page.close()
            finally:
                context.close()
        except (MatchpointBrowserError, MatchpointSourceError):
            raise
        except Exception as error:
            if _is_documented_browser_error(error):
                raise MatchpointSourceError("browser navigation or extraction failed") from error
            raise

        slots = parse_matchpoint_observations(
            tuple(observations),
            location_id=location.location_id,
            run_id=run_id,
            window_start=window_start,
            window_end=window_end,
        )
        run = AvailabilityRun(
            run_id,
            location.location_id,
            "matchpoint_browser",
            source.booking_url,
            window_start.isoformat(),
            window_end.isoformat(),
            (window_end - window_start).days,
            collected_at,
            "success",
            None,
        )
        return AvailabilityResult(run, slots)


MatchpointBrowserConnectorFactory = Callable[
    [Sequence[MatchpointSource]], MatchpointBrowserConnector
]
