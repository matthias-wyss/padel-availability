import re
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime, time, timedelta
from itertools import pairwise
from typing import Literal, Protocol, cast
from zoneinfo import ZoneInfo

from ..availability import AvailabilityResult, AvailabilityRun, AvailabilitySlot
from ..models import LocationRecord
from .everness import EvernessSource, EvernessSourceError
from .playtomic import PlaytomicSourceError
from .playtomic_browser import (
    BrowserFactory,
    BrowserSlotObservation,
    _is_documented_browser_error,  # pyright: ignore[reportPrivateUsage]
    default_browser_factory,
    parse_browser_observations,
)

__all__ = [
    "EvernessBrowserConnector",
    "EvernessBrowserConnectorFactory",
    "EvernessBrowserError",
    "default_browser_factory",
    "parse_everness_dom",
    "parse_everness_observations",
]

_EVERNESS_ZURICH = ZoneInfo("Europe/Zurich")
_EVERNESS_MONTHS = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
    "janv": 1,
    "févr": 2,
    "mars": 3,
    "avr": 4,
    "mai": 5,
    "juin": 6,
    "juil": 7,
    "août": 8,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "déc": 12,
}
_EVERNESS_WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
    "lundi": 0,
    "mardi": 1,
    "mercredi": 2,
    "jeudi": 3,
    "vendredi": 4,
    "samedi": 5,
    "dimanche": 6,
}
_EVERNESS_BLOCK_MARKERS = (
    "captcha",
    "log in to continue",
    "login required",
    "login-required",
    "login to continue",
    "sign in required",
    "sign-in required",
    "sign in to continue",
    "sign-in to continue",
    "authenticate to continue",
    "authentication required",
    "connexion requise",
    "connexion nécessaire",
    "se connecter pour continuer",
    "access denied",
    "accès refusé",
)
_EVERNESS_UNAVAILABLE_MARKERS = (
    "club is temporarily unavailable",
    "service temporarily unavailable",
    "ce club est temporairement indisponible",
)
_EVERNESS_LOADING_MARKERS = ("loading", "chargement", "please wait", "updating")
_EVERNESS_TIMEOUT_MS = 15_000
_EVERNESS_VISIBLE_DOM_SCRIPT = r"""
() => {
  const body = document.body;
  if (!body) {
    return {
      view: 'unknown',
      date_label: '',
      courts: [],
      rows: [],
      grid_fingerprint: '',
      loading: true,
      authentication_visible: false,
      visible_text: ''
    };
  }
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
  const text = element => (element.innerText || element.textContent || '').trim();
  const dateElement = document.querySelector('#multi-language-date');
  const table = document.querySelector('#table_reservation');
  const dateLabel = dateElement && visible(dateElement) ? text(dateElement) : '';
  const headers = table && visible(table)
    ? Array.from(table.querySelectorAll('.table_header')).filter(visible)
    : [];
  const courts = headers.map(text);
  const rows = [];
  if (table && visible(table)) {
    for (const hour of Array.from(table.querySelectorAll('.hour_slot')).filter(visible)) {
      const row = hour.closest('tr') || hour.parentElement;
      if (!row || !visible(row)) continue;
      const cells = Array.from(row.querySelectorAll('.terrainTxt')).filter(visible).map(cell => ({
        class: cell.getAttribute('class') || '',
        style: cell.getAttribute('style') || '',
        colspan: cell.getAttribute('colspan')
      }));
      rows.push({time: text(hour), cells});
    }
  }
  const visibleText = body.innerText || '';
  const normalizedText = visibleText.replace(/\s+/g, ' ').trim().toLowerCase();
  const authenticationMarker = /captcha|log[\s-]+in(?:\s+(?:required|to continue))|login(?:[-\s]+(?:required|to continue))|sign[\s-]+in(?:[-\s]+(?:required|to continue))|authenticate(?:\s+(?:required|to continue))|authentication\s+required|connexion\s+(?:requise|nécessaire|required)|se connecter\s+pour continuer|access denied|accès refusé/i;
  const authenticationContainerMarker = /auth|login|signin|sign-in|connexion/i;
  const authenticationVisible = authenticationMarker.test(normalizedText) ||
    Array.from(body.querySelectorAll(
      'input[type="password"], form, dialog, [role="dialog"], [role="alertdialog"], [aria-modal="true"], [class*="overlay"], [class*="modal"]'
    )).some(element => {
      if (!visible(element)) return false;
      const attributes = `${element.id || ''} ${String(element.className || '')}`;
      return element.matches('input[type="password"]') ||
        authenticationMarker.test(text(element)) || authenticationContainerMarker.test(attributes);
    });
  const bodyLoading = visible(body) &&
    (body.classList.contains('loading') || body.getAttribute('aria-busy') === 'true');
  const loading = bodyLoading || normalizedText.includes('loading') || normalizedText.includes('chargement') ||
    normalizedText.includes('please wait') || normalizedText.includes('updating') ||
    Array.from(body.querySelectorAll('.loading, [aria-busy="true"]')).some(visible);
  const fingerprintInput = JSON.stringify({
    courts,
    rows: rows.map(row => [row.time, row.cells.map(cell => [cell.class, cell.style, cell.colspan])])
  });
  let hash = 2166136261;
  for (let index = 0; index < fingerprintInput.length; index += 1) {
    hash ^= fingerprintInput.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  const gridFingerprint = `fnv1a-${(hash >>> 0).toString(16).padStart(8, '0')}`;
  return {
    view: dateLabel && table && visible(table) ? 'booking' : 'unknown',
    date_label: dateLabel,
    courts,
    rows,
    grid_fingerprint: gridFingerprint,
    loading,
    authentication_visible: authenticationVisible,
    visible_text: visibleText
  };
}
"""


class EvernessBrowserError(EvernessSourceError):
    """Raised when the visible Everness booking DOM cannot be parsed safely."""

    def __init__(self, message: str) -> None:
        super().__init__(message[:160])


def _dom_mapping(value: object, field: str = "visible DOM") -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise EvernessBrowserError(f"{field} has an invalid shape")
    return cast(Mapping[str, object], value)


def _dom_text(mapping: Mapping[str, object], field: str) -> str:
    value = mapping.get(field)
    if not isinstance(value, str) or not value.strip():
        raise EvernessBrowserError(f"visible DOM is missing {field}")
    return value.strip()


def _dom_authentication_visible(dom: Mapping[str, object]) -> bool:
    value = dom.get("authentication_visible", False)
    if not isinstance(value, bool):
        raise EvernessBrowserError("visible DOM has an invalid authentication state")
    return value


def _local_datetime(local_date: date, local_time: time, field: str) -> datetime:
    wall_time = datetime.combine(local_date, local_time)
    first = wall_time.replace(tzinfo=_EVERNESS_ZURICH, fold=0)
    second = wall_time.replace(tzinfo=_EVERNESS_ZURICH, fold=1)
    if first.utcoffset() != second.utcoffset():
        raise EvernessBrowserError(f"{field} is ambiguous in Europe/Zurich")
    return first


def _parse_date_label(label: str) -> date:
    match = re.fullmatch(
        r"([0-9]{1,2})\s+([^\W\d_]+\.?)\s+([0-9]{4})(?:\s+([^\W\d_]+\.?))?",
        label,
    )
    if match is None:
        raise EvernessBrowserError("visible DOM has an invalid date label")
    month_name = match.group(2).casefold().rstrip(".")
    month = next(
        (number for name, number in _EVERNESS_MONTHS.items() if month_name.startswith(name.casefold())),
        None,
    )
    if month is None:
        raise EvernessBrowserError("visible DOM has an invalid date label")
    try:
        parsed = date(
            int(match.group(3)),
            month,
            int(match.group(1)),
        )
    except ValueError as error:
        raise EvernessBrowserError("visible DOM has an invalid date label") from error
    weekday = match.group(4)
    if weekday is not None:
        weekday_number = _EVERNESS_WEEKDAYS.get(weekday.casefold().rstrip("."))
        if weekday_number is None or weekday_number != parsed.weekday():
            raise EvernessBrowserError("visible DOM has an invalid date label")
    return parsed


def _parse_row_time(value: object) -> time:
    if not isinstance(value, str):
        raise EvernessBrowserError("visible row has an invalid time")
    match = re.fullmatch(r"([01][0-9]|2[0-3]):([0-5][0-9])", value.strip())
    if match is None:
        raise EvernessBrowserError("visible row has an invalid time")
    return time(int(match.group(1)), int(match.group(2)))


def _cell_status(value: object) -> Literal["available", "unavailable", "unknown"]:
    cell = _dom_mapping(value, "visible cell")
    classes = cell.get("class")
    style = cell.get("style")
    if not isinstance(classes, str) or not isinstance(style, str):
        raise EvernessBrowserError("visible cell is missing class or style state")
    normalized_classes = {part.casefold() for part in classes.split()}
    if "notallowed" in normalized_classes:
        return "unavailable"
    if "cursor" in normalized_classes:
        return "available"
    return "unknown"


def _cell_span(value: object) -> int:
    cell = _dom_mapping(value, "visible cell")
    span = cell.get("colspan")
    if span is None:
        return 1
    if isinstance(span, bool):
        raise EvernessBrowserError("visible cell has an invalid span")
    if isinstance(span, int):
        if span > 0:
            return span
        raise EvernessBrowserError("visible cell has an invalid span")
    if isinstance(span, str) and re.fullmatch(r"[1-9][0-9]*", span):
        return int(span)
    raise EvernessBrowserError("visible cell has an invalid span")


def parse_everness_dom(payload: object, requested_date: date) -> tuple[BrowserSlotObservation, ...]:
    """Parse the small visible-DOM payload returned by the Everness booking page."""
    dom = _dom_mapping(payload)
    visible_text = dom.get("visible_text")
    if not isinstance(visible_text, str):
        raise EvernessBrowserError("visible DOM is missing visible text")
    normalized_text = " ".join(visible_text.split()).casefold()
    if any(marker in normalized_text for marker in _EVERNESS_UNAVAILABLE_MARKERS):
        raise EvernessBrowserError("public Everness page is explicitly unavailable")
    if _dom_authentication_visible(dom) or any(
        marker in normalized_text for marker in _EVERNESS_BLOCK_MARKERS
    ):
        raise EvernessBrowserError("public Everness page is blocked by login or CAPTCHA")
    loading = dom.get("loading")
    if not isinstance(loading, bool):
        raise EvernessBrowserError("visible DOM has an invalid loading state")
    if loading or any(marker in normalized_text for marker in _EVERNESS_LOADING_MARKERS):
        raise EvernessBrowserError("visible Everness booking page is still loading")
    if dom.get("view") != "booking":
        raise EvernessBrowserError("visible Everness booking view was not found")
    date_label = _dom_text(dom, "date_label")
    if _parse_date_label(date_label) != requested_date:
        raise EvernessBrowserError("visible Everness date does not match requested date")
    _dom_text(dom, "grid_fingerprint")

    raw_courts = dom.get("courts")
    raw_rows = dom.get("rows")
    if not isinstance(raw_courts, list) or not isinstance(raw_rows, list):
        raise EvernessBrowserError("visible DOM is missing booking grid labels")
    courts = cast(list[object], raw_courts)
    if not courts or not all(isinstance(court, str) and court.strip() for court in courts):
        raise EvernessBrowserError("visible DOM is missing court labels")
    court_labels = cast(list[str], courts)
    if len(set(court_labels)) != len(court_labels):
        raise EvernessBrowserError("visible DOM has duplicate court labels")

    rows = cast(list[object], raw_rows)
    parsed_rows: list[tuple[time, list[object]]] = []
    for raw_row in rows:
        row = _dom_mapping(raw_row, "visible row")
        row_time = _parse_row_time(row.get("time"))
        raw_cells = row.get("cells")
        if not isinstance(raw_cells, list):
            raise EvernessBrowserError("visible booking grid has a partial matrix")
        cells = cast(list[object], raw_cells)
        expanded_cells: list[object] = []
        for cell in cells:
            span = _cell_span(cell)
            if len(expanded_cells) + span > len(court_labels):
                raise EvernessBrowserError("visible booking grid has a partial matrix")
            expanded_cells.extend([cell] * span)
        if len(expanded_cells) != len(court_labels):
            raise EvernessBrowserError("visible booking grid has a partial matrix")
        parsed_rows.append((row_time, expanded_cells))

    if not parsed_rows:
        return ()
    starts = [datetime.combine(requested_date, row_time) for row_time, _ in parsed_rows]
    intervals: list[timedelta] = []
    for previous, current in pairwise(starts):
        interval = current - previous
        if interval <= timedelta(0):
            raise EvernessBrowserError("visible booking grid has an invalid duration")
        intervals.append(interval)
    if not intervals:
        raise EvernessBrowserError("visible booking grid has an invalid duration")

    observations: list[BrowserSlotObservation] = []
    for row_index, (row_time, cells) in enumerate(parsed_rows):
        duration = intervals[min(row_index, len(intervals) - 1)]
        start_local = _local_datetime(requested_date, row_time, "starts_at")
        end_local = (start_local.astimezone(UTC) + duration).astimezone(_EVERNESS_ZURICH)
        for court, cell in zip(court_labels, cells):
            try:
                observations.append(
                    BrowserSlotObservation(
                        None,
                        court.strip(),
                        start_local.isoformat(timespec="seconds"),
                        end_local.isoformat(timespec="seconds"),
                        _cell_status(cell),
                    )
                )
            except (TypeError, ValueError) as error:
                raise EvernessBrowserError("visible cell failed validation") from error
    return tuple(observations)


def parse_everness_observations(
    observations: Sequence[BrowserSlotObservation],
    *,
    location_id: str,
    run_id: str,
    window_start: date,
    window_end: date,
) -> tuple[AvailabilitySlot, ...]:
    return parse_browser_observations(
        observations,
        location_id=location_id,
        run_id=run_id,
        window_start=window_start,
        window_end=window_end,
    )


class _EvernessLocator(Protocol):
    def locator(self, selector: str) -> "_EvernessLocator": ...

    def nth(self, index: int) -> "_EvernessLocator": ...

    def count(self) -> int: ...

    def is_visible(self) -> bool: ...

    def inner_text(self) -> str: ...

    def get_attribute(self, name: str) -> str | None: ...

    def click(self) -> None: ...


class _EvernessPage(Protocol):
    def goto(self, url: str, *, wait_until: str, timeout: int) -> object: ...

    def locator(self, selector: str) -> _EvernessLocator: ...

    def wait_for_timeout(self, timeout: int) -> None: ...

    def evaluate(self, expression: str, arg: object = None) -> object: ...

    def close(self) -> None: ...


class _EvernessContext(Protocol):
    def new_page(self) -> _EvernessPage: ...

    def close(self) -> None: ...


class _EvernessBrowser(Protocol):
    def new_context(self) -> _EvernessContext: ...

    def __exit__(self, *args: object) -> None: ...


def _everness_visible_locator(
    root: _EvernessPage | _EvernessLocator, selector: str
) -> _EvernessLocator:
    locator = root.locator(selector)
    if locator.count() != 1 or not locator.is_visible():
        raise EvernessBrowserError(f"visible Everness control {selector} was not found")
    return locator


def _everness_payload_text(payload: object) -> str:
    dom = _dom_mapping(payload)
    visible_text = dom.get("visible_text")
    if not isinstance(visible_text, str):
        raise EvernessBrowserError("visible DOM is missing visible text")
    normalized_text = " ".join(visible_text.split()).casefold()
    if any(marker in normalized_text for marker in _EVERNESS_UNAVAILABLE_MARKERS):
        raise EvernessBrowserError("public Everness page is explicitly unavailable")
    if _dom_authentication_visible(dom) or any(
        marker in normalized_text for marker in _EVERNESS_BLOCK_MARKERS
    ):
        raise EvernessBrowserError("public Everness page is blocked by login or CAPTCHA")
    return normalized_text


def _everness_payload_date(payload: object) -> date | None:
    value = _dom_mapping(payload).get("date_label")
    if value is None:
        return None
    if not isinstance(value, str):
        raise EvernessBrowserError("visible DOM has an invalid date label")
    return _parse_date_label(value)


def _everness_payload_fingerprint(payload: object) -> str:
    value = _dom_mapping(payload).get("grid_fingerprint")
    if not isinstance(value, str) or not value.strip():
        raise EvernessBrowserError("visible DOM is missing grid fingerprint")
    return value


def _everness_payload_loading(payload: object) -> bool:
    dom = _dom_mapping(payload)
    loading = dom.get("loading")
    if not isinstance(loading, bool):
        raise EvernessBrowserError("visible DOM has an invalid loading state")
    normalized_text = _everness_payload_text(payload)
    return loading or any(marker in normalized_text for marker in _EVERNESS_LOADING_MARKERS)


def _wait_for_everness_locator(
    page: _EvernessPage, selector: str, timeout_ms: int
) -> _EvernessLocator:
    for _ in range(max(1, timeout_ms // 100)):
        locator = page.locator(selector)
        if locator.count() == 1 and locator.is_visible():
            return locator
        page.wait_for_timeout(100)
    raise EvernessBrowserError(f"visible Everness control {selector} was not found")


def _wait_for_everness_page(page: _EvernessPage, timeout_ms: int) -> object:
    for _ in range(max(1, timeout_ms // 100)):
        payload = page.evaluate(_EVERNESS_VISIBLE_DOM_SCRIPT)
        _everness_payload_text(payload)
        if (
            page.locator("#table_reservation").count() == 1
            and page.locator("#table_reservation").is_visible()
            and page.locator("#datepicker").count() == 1
            and page.locator("#multi-language-date").count() == 1
            and page.locator("#multi-language-date").is_visible()
        ):
            return payload
        page.wait_for_timeout(100)
    raise EvernessBrowserError("visible Everness booking controls were not found")


def _datepicker_month(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"([^\W\d_]+\.?)\s+([0-9]{4})", value.strip())
    if match is None:
        raise EvernessBrowserError("visible Everness datepicker has an invalid month label")
    month_name = match.group(1).casefold().rstrip(".")
    month = next(
        (number for name, number in _EVERNESS_MONTHS.items() if month_name.startswith(name.casefold())),
        None,
    )
    if month is None:
        raise EvernessBrowserError("visible Everness datepicker has an invalid month label")
    return month, int(match.group(2))


def _select_everness_date(
    page: _EvernessPage, requested_date: date, timeout_ms: int
) -> None:
    date_control = _everness_visible_locator(page, "#multi-language-date")
    if _parse_date_label(date_control.inner_text()) == requested_date:
        return
    date_control.click()
    datepicker = _wait_for_everness_locator(page, "#datepicker", timeout_ms)
    jquery_title = datepicker.locator(".ui-datepicker-title")
    if jquery_title.count() == 1 and jquery_title.is_visible():
        month_select = _everness_visible_locator(datepicker, ".ui-datepicker-month")
        year_select = _everness_visible_locator(datepicker, ".ui-datepicker-year")

        def selected_value(select: _EvernessLocator) -> str:
            selected = select.locator("option:checked")
            if selected.count() != 1:
                raise EvernessBrowserError(
                    "visible Everness datepicker has an invalid selected month or year"
                )
            value = selected.get_attribute("value")
            if value is None:
                raise EvernessBrowserError(
                    "visible Everness datepicker has an invalid selected month or year"
                )
            return value

        month_value = selected_value(month_select)
        year_value = selected_value(year_select)
        try:
            current = date(int(year_value), int(month_value) + 1, 1)
        except (TypeError, ValueError) as error:
            raise EvernessBrowserError(
                "visible Everness datepicker has invalid selected month or year"
            ) from error
        target = date(requested_date.year, requested_date.month, 1)
        for _ in range(24):
            if current == target:
                days = datepicker.locator('td[data-handler="selectDay"]')
                matches: list[_EvernessLocator] = []
                for index in range(days.count()):
                    day = days.nth(index)
                    if (
                        day.is_visible()
                        and day.get_attribute("data-month") == str(requested_date.month - 1)
                        and day.get_attribute("data-year") == str(requested_date.year)
                        and day.inner_text().strip() == str(requested_date.day)
                    ):
                        matches.append(day)
                if len(matches) != 1:
                    raise EvernessBrowserError("visible Everness date control was ambiguous")
                matches[0].click()
                return
            selector = ".ui-datepicker-next" if current < target else ".ui-datepicker-prev"
            _everness_visible_locator(datepicker, selector).click()
            month_value = selected_value(month_select)
            year_value = selected_value(year_select)
            try:
                current = date(int(year_value), int(month_value) + 1, 1)
            except (TypeError, ValueError) as error:
                raise EvernessBrowserError(
                    "visible Everness datepicker has invalid selected month or year"
                ) from error
        raise EvernessBrowserError("visible Everness datepicker could not reach requested date")

    for _ in range(24):
        switch = _everness_visible_locator(datepicker, ".datepicker-switch")
        month, year = _datepicker_month(switch.inner_text())
        current = date(year, month, 1)
        target = date(requested_date.year, requested_date.month, 1)
        if current == target:
            days = datepicker.locator(".day")
            matches: list[_EvernessLocator] = []
            for index in range(days.count()):
                day = days.nth(index)
                classes = (day.get_attribute("class") or "").split()
                if (
                    day.is_visible()
                    and day.inner_text().strip() == str(requested_date.day)
                    and not {"old", "new", "disabled"}.intersection(classes)
                ):
                    matches.append(day)
            if len(matches) != 1:
                raise EvernessBrowserError("visible Everness date control was ambiguous")
            matches[0].click()
            return
        selector = ".next" if current < target else ".prev"
        _everness_visible_locator(datepicker, selector).click()
    raise EvernessBrowserError("visible Everness datepicker could not reach requested date")


def _wait_for_everness_date(
    page: _EvernessPage,
    requested_date: date,
    previous_payload: object,
    timeout_ms: int,
) -> object:
    previous_date = _everness_payload_date(previous_payload)
    previous_fingerprint = _everness_payload_fingerprint(previous_payload)
    refresh_observed = False
    stable_fingerprint: str | None = None
    for _ in range(max(1, timeout_ms // 100)):
        payload = page.evaluate(_EVERNESS_VISIBLE_DOM_SCRIPT)
        _everness_payload_text(payload)
        loading = _everness_payload_loading(payload)
        if loading:
            refresh_observed = True
        fingerprint = _everness_payload_fingerprint(payload)
        label = _everness_visible_locator(page, "#multi-language-date").inner_text()
        label_date = _parse_date_label(label)
        payload_date = _everness_payload_date(payload)
        if not loading and label_date == requested_date and payload_date == requested_date:
            if previous_date == requested_date:
                return payload
            if not refresh_observed and fingerprint == previous_fingerprint:
                stable_fingerprint = None
            elif stable_fingerprint == fingerprint:
                return payload
            else:
                stable_fingerprint = fingerprint
        else:
            stable_fingerprint = None
        page.wait_for_timeout(100)
    raise EvernessBrowserError("timed out waiting for requested date and refreshed Everness grid")


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
        "everness_browser",
        source_url,
        window_start.isoformat(),
        window_end.isoformat(),
        (window_end - window_start).days,
        collected_at,
        "unavailable",
        "public Everness booking page is unavailable",
    )
    return AvailabilityResult(run, ())


class EvernessBrowserConnector:
    def __init__(
        self,
        sources: Sequence[EvernessSource],
        *,
        browser_factory: BrowserFactory = default_browser_factory,
        timeout_ms: int = _EVERNESS_TIMEOUT_MS,
    ) -> None:
        self._sources = {source.location_id: source for source in sources}
        self._browser_factory = browser_factory
        self._timeout_ms = timeout_ms
        self._browser: _EvernessBrowser | None = None

    def open(self) -> None:
        if self._browser is not None:
            return
        session = self._browser_factory()
        try:
            browser = session.__enter__()
        except BaseException:
            session.__exit__(*sys.exc_info())
            raise
        self._browser = cast(_EvernessBrowser, browser)

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
            raise EvernessSourceError("requested date window is invalid")
        source = self._sources.get(location.location_id)
        if source is None:
            raise EvernessSourceError("no source metadata for location")
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
                raise EvernessBrowserError("browser session is not running")
            context = browser.new_context()
            try:
                page = context.new_page()
                try:
                    page.goto(source.booking_url, wait_until="commit", timeout=self._timeout_ms)
                    _wait_for_everness_page(page, self._timeout_ms)
                    current_date = window_start
                    while current_date < window_end:
                        previous_payload = page.evaluate(_EVERNESS_VISIBLE_DOM_SCRIPT)
                        _select_everness_date(page, current_date, self._timeout_ms)
                        payload = _wait_for_everness_date(
                            page, current_date, previous_payload, self._timeout_ms
                        )
                        observations.extend(parse_everness_dom(payload, current_date))
                        current_date += timedelta(days=1)
                finally:
                    page.close()
            finally:
                context.close()
        except (EvernessBrowserError, EvernessSourceError):
            raise
        except Exception as error:
            if _is_documented_browser_error(error):
                raise EvernessSourceError("browser navigation or extraction failed") from error
            raise

        try:
            slots = parse_everness_observations(
                tuple(observations),
                location_id=location.location_id,
                run_id=run_id,
                window_start=window_start,
                window_end=window_end,
            )
        except PlaytomicSourceError as error:
            raise EvernessSourceError(str(error)[:160]) from error
        run = AvailabilityRun(
            run_id,
            location.location_id,
            "everness_browser",
            source.booking_url,
            window_start.isoformat(),
            window_end.isoformat(),
            (window_end - window_start).days,
            collected_at,
            "success",
            None,
        )
        return AvailabilityResult(run, slots)


EvernessBrowserConnectorFactory = Callable[
    [Sequence[EvernessSource]], EvernessBrowserConnector
]
