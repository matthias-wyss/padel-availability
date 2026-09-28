import re
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal, Protocol, cast
from zoneinfo import ZoneInfo

from ..availability import AvailabilityResult, AvailabilityRun, AvailabilitySlot
from ..models import LocationRecord, ModelError
from .padelfirst import (
    PADEL_FIRST_SLOT_MINUTES,
    PadelFirstSource,
    PadelFirstSourceError,
)
from .playtomic import PlaytomicSourceError
from .playtomic_browser import (
    BrowserFactory,
    BrowserSlotObservation,
    _is_documented_browser_error,  # pyright: ignore[reportPrivateUsage]
    default_browser_factory,
    parse_browser_observations,
)

__all__ = [
    "PadelFirstBrowserConnector",
    "PadelFirstBrowserConnectorFactory",
    "PadelFirstBrowserError",
    "default_browser_factory",
    "parse_padelfirst_dom",
    "parse_padelfirst_observations",
]

_PADEL_FIRST_ZURICH = ZoneInfo("Europe/Zurich")
_PADEL_FIRST_TIMEOUT_MS = 15_000
_PADEL_FIRST_LOADING_MARKERS = ("loading", "chargement", "please wait", "mise à jour")
_PADEL_FIRST_BLOCK_MARKERS = (
    "captcha",
    "verify you are human",
    "access denied",
    "accès refusé",
    "connexion requise",
    "login required",
    "sign in required",
    "se connecter pour continuer",
    "authentication required",
)

_PADEL_FIRST_VISIBLE_DOM_SCRIPT = r"""
() => {
  const body = document.body;
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
  const visibleText = () => {
    if (!body) return '';
    const inner = body.innerText || '';
    if (inner.trim()) return inner;
    return Array.from(body.querySelectorAll('*')).filter(visible).map(text).join(' ');
  };
  const calendar = document.querySelector('#calendar');
  const calendarDates = calendar && visible(calendar)
    ? Array.from(calendar.querySelectorAll('.fc-day-top[data-date]'))
        .filter(visible).map(element => element.getAttribute('data-date')).filter(Boolean)
    : [];
  const calendarAvailableDates = [];
  if (calendar && visible(calendar)) {
    for (const event of Array.from(calendar.querySelectorAll('.fc-event.available')).filter(visible)) {
      const cell = event.closest('td');
      const table = event.closest('table');
      const row = cell?.parentElement;
      const cells = row ? Array.from(row.children) : [];
      const column = cell ? cells.indexOf(cell) : -1;
      const header = table?.querySelector('thead tr')?.children[column];
      const date = header?.getAttribute('data-date');
      if (date && !calendarAvailableDates.includes(date)) calendarAvailableDates.push(date);
    }
  }

  const table = document.querySelector('#scheduler-table');
  const courts = table && visible(table)
    ? Array.from(table.querySelectorAll('th.fc-court')).filter(visible).map(text)
    : [];
  const rows = [];
  if (table && visible(table)) {
    for (const row of Array.from(table.querySelectorAll('tbody tr')).filter(visible)) {
      const cells = Array.from(row.children).filter(visible);
      if (!cells.length) continue;
      const states = cells.slice(1).map(cell => {
        const state = Array.from(cell.querySelectorAll('.status, .match-block, .match-block2'))
          .find(visible) || null;
        return {
          external_id: state?.getAttribute('id') || null,
          class: state?.getAttribute('class') || '',
          checkin: state?.getAttribute('checkin') || null,
          hour: state?.getAttribute('hour') || null,
          court_id: state?.getAttribute('court_id') || null,
          text: state ? text(state) : text(cell)
        };
      });
      rows.push({time: text(cells[0]), cells: states});
    }
  }
  const title = document.querySelector('#scheduler .modal-title');
  const titleMatch = text(title).match(/\b(\d{4}-\d{2}-\d{2})\b/);
  const checkins = rows.flatMap(row => row.cells.map(cell => cell.checkin).filter(Boolean));
  const uniqueCheckins = [...new Set(checkins)];
  const schedulerDate = titleMatch?.[1] || (uniqueCheckins.length === 1 ? uniqueCheckins[0] : '');
  const visibleTextValue = visibleText();
  const normalizedText = visibleTextValue.replace(/\s+/g, ' ').trim().toLowerCase();
  const authenticationMarker = /captcha|verify\s+you\s+are\s+human|access\s+denied|accès\s+refusé|connexion\s+requise|login\s+required|sign\s+in\s+required|se\s+connecter\s+pour\s+continuer|authentication\s+required/i;
  const authenticationVisible = authenticationMarker.test(normalizedText) ||
    Array.from(body?.querySelectorAll('input[type="password"]') || []).some(visible) ||
    Array.from(body?.querySelectorAll('[role="dialog"], [aria-modal="true"]') || [])
      .some(element => visible(element) && authenticationMarker.test(text(element)));
  const loading = /loading|chargement|please\s+wait|mise\s+à\s+jour/i.test(normalizedText) ||
    Array.from(body?.querySelectorAll('.loading, [aria-busy="true"]') || []).some(visible);
  return {
    view: table && visible(table) ? 'scheduler' : calendar && visible(calendar) ? 'calendar' : 'unknown',
    date: schedulerDate,
    courts,
    rows,
    calendar_dates: calendarDates,
    calendar_available_dates: calendarAvailableDates,
    loading,
    authentication_visible: authenticationVisible,
    visible_text: visibleTextValue
  };
}
"""


class PadelFirstBrowserError(PadelFirstSourceError):
    """Raised when the visible Padel First booking DOM cannot be parsed safely."""

    def __init__(self, message: str) -> None:
        super().__init__(message[:160])


class _PadelFirstPage(Protocol):
    def goto(self, url: str, *, wait_until: str, timeout: int) -> object: ...

    def locator(self, selector: str) -> "_PadelFirstLocator": ...

    def wait_for_timeout(self, timeout: int) -> None: ...

    def evaluate(self, expression: str, arg: object = None) -> object: ...

    def close(self) -> None: ...


class _PadelFirstLocator(Protocol):
    def count(self) -> int: ...

    def nth(self, index: int) -> "_PadelFirstLocator": ...

    def is_visible(self) -> bool: ...

    def inner_text(self) -> str: ...

    def get_attribute(self, name: str) -> str | None: ...

    def evaluate(self, expression: str, arg: object = None) -> object: ...

    def click(self) -> None: ...


class _PadelFirstContext(Protocol):
    def new_page(self) -> _PadelFirstPage: ...

    def close(self) -> None: ...


class _PadelFirstBrowser(Protocol):
    def new_context(self) -> _PadelFirstContext: ...

    def __exit__(self, *args: object) -> None: ...


def _dom_mapping(value: object, field: str = "visible DOM") -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise PadelFirstBrowserError(f"{field} has an invalid shape")
    return cast(Mapping[str, object], value)


def _dom_text(mapping: Mapping[str, object], field: str) -> str:
    value = mapping.get(field)
    if not isinstance(value, str) or not value.strip():
        raise PadelFirstBrowserError(f"visible DOM is missing {field}")
    return value.strip()


def _local_datetime(local_date: date, local_time: time, field: str) -> datetime:
    wall_time = datetime.combine(local_date, local_time)
    first = wall_time.replace(tzinfo=_PADEL_FIRST_ZURICH, fold=0)
    second = wall_time.replace(tzinfo=_PADEL_FIRST_ZURICH, fold=1)
    if first.utcoffset() != second.utcoffset():
        raise PadelFirstBrowserError(f"{field} is ambiguous in Europe/Zurich")
    return first


def _parse_time(value: object) -> time:
    if not isinstance(value, str):
        raise PadelFirstBrowserError("visible scheduler has an invalid time")
    match = re.fullmatch(r"([01][0-9]|2[0-3]):([0-5][0-9])", value.strip())
    if match is None:
        raise PadelFirstBrowserError("visible scheduler has an invalid time")
    return time(int(match.group(1)), int(match.group(2)))


def _parse_date(value: object) -> date:
    if not isinstance(value, str):
        raise PadelFirstBrowserError("visible scheduler has an invalid date")
    try:
        parsed = date.fromisoformat(value.strip())
    except ValueError as error:
        raise PadelFirstBrowserError("visible scheduler has an invalid date") from error
    if parsed.isoformat() != value.strip():
        raise PadelFirstBrowserError("visible scheduler has an invalid date")
    return parsed


def _cell_status(value: object) -> Literal["available", "unavailable", "unknown"]:
    cell = _dom_mapping(value, "visible cell")
    classes = cell.get("class")
    if not isinstance(classes, str):
        raise PadelFirstBrowserError("visible cell is missing class state")
    normalized = {part.casefold() for part in classes.split()}
    if "available" in normalized:
        return "available"
    if normalized.intersection(
        {"unavailable", "approved", "booked", "match-block", "match-block2"}
    ):
        return "unavailable"
    return "unknown"


def _cell_external_id(value: object) -> str | None:
    cell = _dom_mapping(value, "visible cell")
    external_id = cell.get("external_id")
    if external_id is None:
        return None
    if not isinstance(external_id, str) or not external_id.strip():
        raise PadelFirstBrowserError("visible cell has an invalid external ID")
    return external_id.strip()


def _validate_optional_cell_date(value: object, requested_date: date, field: str) -> None:
    if value is not None and value != requested_date.isoformat():
        raise PadelFirstBrowserError(f"visible cell {field} does not match requested date")


def parse_padelfirst_dom(
    payload: object, requested_date: date
) -> tuple[BrowserSlotObservation, ...]:
    """Parse the visible Padel First scheduler payload returned by Playwright."""
    dom = _dom_mapping(payload)
    visible_text = dom.get("visible_text")
    if not isinstance(visible_text, str):
        raise PadelFirstBrowserError("visible DOM is missing visible text")
    normalized_text = " ".join(visible_text.split()).casefold()
    if any(marker in normalized_text for marker in _PADEL_FIRST_BLOCK_MARKERS):
        raise PadelFirstBrowserError("public Padel First page is blocked by login or CAPTCHA")

    loading = dom.get("loading")
    if not isinstance(loading, bool):
        raise PadelFirstBrowserError("visible DOM has an invalid loading state")
    if loading or any(marker in normalized_text for marker in _PADEL_FIRST_LOADING_MARKERS):
        raise PadelFirstBrowserError("visible Padel First scheduler is still loading")

    authentication_visible = dom.get("authentication_visible", False)
    if not isinstance(authentication_visible, bool):
        raise PadelFirstBrowserError("visible DOM has an invalid authentication state")
    if authentication_visible:
        raise PadelFirstBrowserError("public Padel First page is blocked by authentication")
    if dom.get("view") != "scheduler":
        raise PadelFirstBrowserError("visible Padel First scheduler was not found")
    if _parse_date(_dom_text(dom, "date")) != requested_date:
        raise PadelFirstBrowserError("visible Padel First date does not match requested date")

    raw_courts = dom.get("courts")
    raw_rows = dom.get("rows")
    if not isinstance(raw_courts, list) or not isinstance(raw_rows, list):
        raise PadelFirstBrowserError("visible scheduler is missing court or row labels")
    courts = cast(list[object], raw_courts)
    if not courts or not all(isinstance(court, str) and court.strip() for court in courts):
        raise PadelFirstBrowserError("visible scheduler is missing court labels")
    court_labels = [cast(str, court).strip() for court in courts]
    if len(set(court_labels)) != len(court_labels):
        raise PadelFirstBrowserError("visible scheduler has duplicate court labels")

    observations: list[BrowserSlotObservation] = []
    for raw_row in cast(list[object], raw_rows):
        row = _dom_mapping(raw_row, "visible row")
        row_time = _parse_time(row.get("time"))
        raw_cells = row.get("cells")
        if not isinstance(raw_cells, list):
            raise PadelFirstBrowserError("visible scheduler has a partial matrix")
        cells = cast(list[object], raw_cells)
        if len(cells) != len(court_labels):
            raise PadelFirstBrowserError("visible scheduler has a partial matrix")
        for court_label, raw_cell in zip(court_labels, cells):
            cell = _dom_mapping(raw_cell, "visible cell")
            _validate_optional_cell_date(cell.get("checkin"), requested_date, "date")
            hour = cell.get("hour")
            if hour is not None and hour != row_time.strftime("%H:%M"):
                raise PadelFirstBrowserError("visible cell hour does not match row time")
            start_local = _local_datetime(requested_date, row_time, "starts_at")
            end_local = (
                start_local.astimezone(UTC) + timedelta(minutes=PADEL_FIRST_SLOT_MINUTES)
            ).astimezone(_PADEL_FIRST_ZURICH)
            try:
                observations.append(
                    BrowserSlotObservation(
                        _cell_external_id(raw_cell),
                        court_label,
                        start_local.isoformat(timespec="seconds"),
                        end_local.isoformat(timespec="seconds"),
                        _cell_status(raw_cell),
                    )
                )
            except (ModelError, TypeError, ValueError) as error:
                raise PadelFirstBrowserError("visible cell failed validation") from error
    return tuple(observations)


def parse_padelfirst_observations(
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
        raise PadelFirstBrowserError(str(error)) from error


def _dom_date(payload: object) -> date | None:
    value = _dom_mapping(payload).get("date")
    if value is None or value == "":
        return None
    return _parse_date(value)


def _calendar_dates(payload: object) -> tuple[str, ...]:
    value = _dom_mapping(payload).get("calendar_available_dates")
    if not isinstance(value, list):
        raise PadelFirstBrowserError("visible calendar is missing availability dates")
    dates = tuple(_parse_date(item).isoformat() for item in cast(list[object], value))
    return tuple(dict.fromkeys(dates))


def _calendar_visible_dates(payload: object) -> tuple[str, ...]:
    value = _dom_mapping(payload).get("calendar_dates")
    if not isinstance(value, list):
        raise PadelFirstBrowserError("visible calendar is missing date cells")
    dates = tuple(_parse_date(item).isoformat() for item in cast(list[object], value))
    return tuple(dict.fromkeys(dates))


def _wait_for_calendar_date(
    page: _PadelFirstPage,
    requested_date: date,
    previous_dates: set[str],
    timeout_ms: int,
) -> object:
    for _ in range(max(1, timeout_ms // 100)):
        payload = page.evaluate(_PADEL_FIRST_VISIBLE_DOM_SCRIPT)
        visible_dates = set(_calendar_visible_dates(payload))
        if requested_date.isoformat() in visible_dates and visible_dates != previous_dates:
            return payload
        page.wait_for_timeout(100)
    raise PadelFirstBrowserError("timed out waiting for the requested Padel First month")


def _payload_loading(payload: object) -> bool:
    dom = _dom_mapping(payload)
    loading = dom.get("loading")
    if not isinstance(loading, bool):
        raise PadelFirstBrowserError("visible DOM has an invalid loading state")
    text = dom.get("visible_text")
    if not isinstance(text, str):
        raise PadelFirstBrowserError("visible DOM is missing visible text")
    normalized = " ".join(text.split()).casefold()
    return loading or any(marker in normalized for marker in _PADEL_FIRST_LOADING_MARKERS)


def _visible_locator(page: _PadelFirstPage, selector: str) -> _PadelFirstLocator:
    locator = page.locator(selector)
    if locator.count() != 1 or not locator.is_visible():
        raise PadelFirstBrowserError(f"visible Padel First control {selector} was not found")
    return locator


def _wait_for_payload(page: _PadelFirstPage, timeout_ms: int) -> object:
    for _ in range(max(1, timeout_ms // 100)):
        payload = page.evaluate(_PADEL_FIRST_VISIBLE_DOM_SCRIPT)
        dom = _dom_mapping(payload)
        visible_text = dom.get("visible_text")
        if isinstance(visible_text, str):
            normalized = " ".join(visible_text.split()).casefold()
            if any(marker in normalized for marker in _PADEL_FIRST_BLOCK_MARKERS):
                return payload
        if (
            page.locator("#calendar").count() == 1
            and page.locator("#calendar").is_visible()
            and not _payload_loading(payload)
        ):
            available_dates = _dom_mapping(payload).get("calendar_available_dates")
            if isinstance(available_dates, list) and available_dates:
                return payload
        page.wait_for_timeout(100)
    raise PadelFirstBrowserError("visible Padel First calendar was not found")


def _calendar_event_date(event: _PadelFirstLocator) -> str:
    value = event.get_attribute("data-date")
    if value is None:
        value = event.evaluate(
            """
            e => {
              const cell = e.closest('td');
              const table = e.closest('table');
              const row = cell?.parentElement;
              const cells = row ? Array.from(row.children) : [];
              const column = cell ? cells.indexOf(cell) : -1;
              return table?.querySelector('thead tr')?.children[column]?.getAttribute('data-date') || '';
            }
            """
        )
    if not isinstance(value, str) or not value.strip():
        raise PadelFirstBrowserError("visible Padel First event has no date")
    return _parse_date(value).isoformat()


def _wait_for_scheduler_date(
    page: _PadelFirstPage, requested_date: date, timeout_ms: int
) -> object:
    for _ in range(max(1, timeout_ms // 100)):
        payload = page.evaluate(_PADEL_FIRST_VISIBLE_DOM_SCRIPT)
        if (
            _dom_mapping(payload).get("view") == "scheduler"
            and _dom_date(payload) == requested_date
            and not _payload_loading(payload)
        ):
            return payload
        page.wait_for_timeout(100)
    raise PadelFirstBrowserError("timed out waiting for the requested Padel First scheduler")


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
        "padelfirst_browser",
        source_url,
        window_start.isoformat(),
        window_end.isoformat(),
        (window_end - window_start).days,
        collected_at,
        "unavailable",
        "public Padel First booking page is unavailable",
    )
    return AvailabilityResult(run, ())


class PadelFirstBrowserConnector:
    def __init__(
        self,
        sources: Sequence[PadelFirstSource],
        *,
        browser_factory: BrowserFactory = default_browser_factory,
        timeout_ms: int = _PADEL_FIRST_TIMEOUT_MS,
    ) -> None:
        self._sources = {source.location_id: source for source in sources}
        self._browser_factory = browser_factory
        self._timeout_ms = timeout_ms
        self._browser: _PadelFirstBrowser | None = None

    def open(self) -> None:
        if self._browser is not None:
            return
        session = self._browser_factory()
        try:
            browser = session.__enter__()
        except BaseException:
            session.__exit__(*sys.exc_info())
            raise
        self._browser = cast(_PadelFirstBrowser, browser)

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
            raise PadelFirstSourceError("requested date window is invalid")
        source = self._sources.get(location.location_id)
        if source is None:
            raise PadelFirstSourceError("no source metadata for location")
        if source.status == "unavailable":
            return _unavailable_result(
                source.booking_url,
                location.location_id,
                run_id,
                window_start,
                window_end,
                collected_at,
            )

        observations: list[BrowserSlotObservation] = []
        try:
            self.open()
            browser = self._browser
            if browser is None:
                raise PadelFirstBrowserError("browser session is not running")
            context = browser.new_context()
            try:
                page = context.new_page()
                try:
                    page.goto(source.booking_url, wait_until="commit", timeout=self._timeout_ms)
                    payload = _wait_for_payload(page, self._timeout_ms)
                    visible_dates = set(_calendar_visible_dates(payload))
                    available_dates = set(_calendar_dates(payload))
                    current_date = window_start
                    while current_date < window_end:
                        while current_date.isoformat() not in visible_dates:
                            if not visible_dates:
                                raise PadelFirstBrowserError(
                                    "visible Padel First calendar has no dates"
                                )
                            visible_date_values = [
                                date.fromisoformat(value) for value in visible_dates
                            ]
                            if current_date > max(visible_date_values):
                                selector = "#calendar .fc-next-button"
                            elif current_date < min(visible_date_values):
                                selector = "#calendar .fc-prev-button"
                            else:
                                break
                            _visible_locator(page, selector).click()
                            payload = _wait_for_calendar_date(
                                page, current_date, visible_dates, self._timeout_ms
                            )
                            visible_dates = set(_calendar_visible_dates(payload))
                            available_dates = set(_calendar_dates(payload))
                        if current_date.isoformat() in available_dates:
                            events = page.locator("#calendar .fc-event.available")
                            matched: _PadelFirstLocator | None = None
                            for index in range(events.count()):
                                event = events.nth(index)
                                if not event.is_visible():
                                    continue
                                try:
                                    if _calendar_event_date(event) == current_date.isoformat():
                                        matched = event
                                        break
                                except PadelFirstBrowserError:
                                    continue
                            if matched is None:
                                raise PadelFirstBrowserError(
                                    "visible Padel First date event was not found"
                                )
                            matched.click()
                            scheduler_payload = _wait_for_scheduler_date(
                                page, current_date, self._timeout_ms
                            )
                            observations.extend(
                                parse_padelfirst_dom(scheduler_payload, current_date)
                            )
                            _visible_locator(page, "#scheduler .close-modal").click()
                            page.wait_for_timeout(100)
                        current_date += timedelta(days=1)
                finally:
                    page.close()
            finally:
                context.close()
        except (PadelFirstBrowserError, PadelFirstSourceError):
            raise
        except Exception as error:
            if _is_documented_browser_error(error):
                raise PadelFirstSourceError("browser navigation or extraction failed") from error
            raise

        slots = parse_padelfirst_observations(
            tuple(observations),
            location_id=location.location_id,
            run_id=run_id,
            window_start=window_start,
            window_end=window_end,
        )
        run = AvailabilityRun(
            run_id,
            location.location_id,
            "padelfirst_browser",
            source.booking_url,
            window_start.isoformat(),
            window_end.isoformat(),
            (window_end - window_start).days,
            collected_at,
            "success",
            None,
        )
        return AvailabilityResult(run, slots)


PadelFirstBrowserConnectorFactory = Callable[
    [Sequence[PadelFirstSource]], PadelFirstBrowserConnector
]
