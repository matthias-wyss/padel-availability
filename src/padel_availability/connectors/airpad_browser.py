import re
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime, time, timedelta
from typing import Protocol, cast
from zoneinfo import ZoneInfo

from ..availability import AvailabilityResult, AvailabilityRun, AvailabilitySlot
from ..models import LocationRecord, ModelError
from .airpad import AIRPAD_LOCATION_LABELS, AirpadSource, AirpadSourceError
from .playtomic import PlaytomicSourceError
from .playtomic_browser import (
    BrowserFactory,
    BrowserSlotObservation,
    _is_documented_browser_error,  # pyright: ignore[reportPrivateUsage]
    default_browser_factory,
    parse_browser_observations,
)

_AIRPAD_ZURICH = ZoneInfo("Europe/Zurich")
_AIRPAD_BLOCK_MARKERS = (
    "captcha",
    "verify you are human",
    "sign in to continue",
    "login required",
    "authentication required",
    "access denied",
)
_AIRPAD_LOADING_MARKERS = ("loading", "chargement")
_AIRPAD_BROWSER_URL_PREFIX = "https://airpad.doinsport.club/"
_AIRPAD_TIMEOUT_MS = 15_000
_AIRPAD_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
_AIRPAD_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


class AirpadBrowserError(AirpadSourceError):
    """Raised when the visible AIRPAD booking DOM cannot be parsed safely."""

    def __init__(self, message: str) -> None:
        super().__init__(message[:160])


_AIRPAD_VISIBLE_DOM_SCRIPT = r"""
() => {
  const body = document.body;
  const visible = element => {
    const rect = element.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return false;
    for (let current = element; current; current = current.parentElement) {
      const style = getComputedStyle(current);
      if (style.display === 'none' || style.visibility === 'hidden') return false;
    }
    return true;
  };
  const text = element => (element.innerText || element.textContent || '').trim();
  const months = {
    january: 1, february: 2, march: 3, april: 4, may: 5, june: 6,
    july: 7, august: 8, september: 9, october: 10, november: 11, december: 12
  };
  const dateFromLabel = label => {
    const match = label.trim().match(/^([A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})$/);
    if (!match) return '';
    const month = months[match[1].toLowerCase()];
    if (!month) return '';
    return `${match[3]}-${String(month).padStart(2, '0')}-${String(match[2]).padStart(2, '0')}`;
  };
  const dateButtons = Array.from(body.querySelectorAll('.date-slot')).filter(visible);
  const selectedDates = dateButtons.filter(element =>
    element.getAttribute('aria-current') === 'date' ||
    (element.getAttribute('class') || '').split(/\s+/).includes('active')
  );
  const activeDate = selectedDates.length === 1 ? selectedDates[0] : null;
  const activeDateLabel = activeDate ? text(activeDate) : '';
  const authenticationMarker = /captcha|verify\s+you\s+are\s+human|sign\s+in\s+to\s+continue|login\s+required|authentication\s+required|access\s+denied/i;
  const authenticationVisible =
    Array.from(body.querySelectorAll('input[type="password"]')).some(visible) ||
    Array.from(body.querySelectorAll('[role="dialog"], [aria-modal="true"]'))
      .some(element => visible(element) && authenticationMarker.test(text(element)));
  const rows = Array.from(body.querySelectorAll('.playground-slot')).filter(visible);
  const courtRows = rows.filter(row => {
    const title = row.querySelector('.section-title');
    return title && visible(title) && text(title);
  });
  const slots = [];
  const emptyRows = [];
  let invalidRows = rows.length === 0 || courtRows.length !== rows.length;
  for (const row of rows) {
    const title = row.querySelector('.section-title');
    const court = title && visible(title) ? text(title) : null;
    const empty = Boolean(row.querySelector('.empty_playground')) &&
      visible(row.querySelector('.empty_playground'));
    const rowSlotStart = slots.length;
    const slotContainers = Array.from(row.querySelectorAll('.slot-container')).filter(visible);
    if (slotContainers.length) {
      for (const container of slotContainers) {
        const startElement = container.querySelector('.start-time .time');
        const start = startElement && visible(startElement) ? text(startElement) : '';
        const offers = Array.from(container.querySelectorAll('.slot-price-list ion-item'))
          .filter(visible);
        if (!court || !/^([01][0-9]|2[0-3]):([0-5][0-9])$/.test(start) || !offers.length) {
          invalidRows = true;
          continue;
        }
        for (const offer of offers) {
          const durationElement = offer.querySelector('ion-label');
          const duration = durationElement && visible(durationElement)
            ? text(durationElement).match(/\d+\s*min/i)?.[0] || ''
            : '';
          if (!duration) {
            invalidRows = true;
            continue;
          }
          const classes = offer.getAttribute('class') || '';
          const disabled = offer.hasAttribute('disabled') ||
            offer.getAttribute('aria-disabled') === 'true' ||
            row.hasAttribute('disabled') || row.getAttribute('aria-disabled') === 'true' ||
            (classes.toLowerCase().split(/\s+/).some(value =>
              ['disabled', 'unavailable', 'booked'].includes(value)));
          slots.push({
            external_id: offer.getAttribute('data-slot-id') || offer.getAttribute('data-id') || null,
            court,
            time: start,
            duration,
            class: `${classes} ${disabled ? 'disabled' : 'available'}`.trim(),
            disabled,
            empty_playground: false
          });
        }
      }
    } else {
      const cards = Array.from(row.querySelectorAll('.info-playground > *')).filter(element =>
        visible(element) && (
          (element.getAttribute('class') || '').split(/\s+/).includes('duration-card') ||
          /Start\s+\d{2}:\d{2}/i.test(text(element)) || /\d+\s*min/i.test(text(element))
        )
      );
      for (const card of cards) {
        const classes = card.getAttribute('class') || '';
        slots.push({
          external_id: card.getAttribute('data-slot-id') || card.getAttribute('data-id') ||
            row.getAttribute('data-slot-id') || null,
          court,
          time: text(card).match(/Start\s+(\d{2}:\d{2})/i)?.[1] || null,
          duration: text(card).match(/Start\s+\d{2}:\d{2}\s*(\d+\s*min)/i)?.[1] || null,
          class: classes,
          disabled: card.hasAttribute('disabled') || card.getAttribute('aria-disabled') === 'true' ||
            row.hasAttribute('disabled') || row.getAttribute('aria-disabled') === 'true',
          empty_playground: empty
        });
      }
    }
    const hasOffers = slots.length > rowSlotStart;
    if (empty && court) emptyRows.push(court);
    if (!court || empty && hasOffers || !empty && !hasOffers) invalidRows = true;
  }
  const calendar = Array.from(body.querySelectorAll('.calendar-block')).some(visible);
  return {
    view: calendar && dateButtons.length > 0 ? 'booking' : 'unknown',
    date: activeDate ? dateFromLabel(activeDate.getAttribute('aria-label') || '') : '',
    active_date_label: activeDateLabel,
    authentication_visible: authenticationVisible,
    slots,
    empty_grid: courtRows.length > 0 && courtRows.length === rows.length &&
      emptyRows.length === rows.length && slots.length === 0,
    empty_rows: emptyRows,
    invalid_rows: invalidRows,
    visible_text: body.innerText || ''
  };
}
"""


def _dom_mapping(value: object, field: str = "visible DOM") -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise AirpadBrowserError(f"{field} has an invalid shape")
    return cast(Mapping[str, object], value)


def _dom_text(mapping: Mapping[str, object], field: str) -> str:
    value = mapping.get(field)
    if not isinstance(value, str) or not value.strip():
        raise AirpadBrowserError(f"visible DOM is missing {field}")
    return value.strip()


def _local_datetime(local_date: date, local_time: time, field: str) -> datetime:
    wall_time = datetime.combine(local_date, local_time)
    first = wall_time.replace(tzinfo=_AIRPAD_ZURICH, fold=0)
    second = wall_time.replace(tzinfo=_AIRPAD_ZURICH, fold=1)
    if first.utcoffset() != second.utcoffset():
        raise AirpadBrowserError(f"{field} is ambiguous in Europe/Zurich")
    return first


def _parse_airpad_slot(item: object, requested_date: date) -> BrowserSlotObservation:
    slot = _dom_mapping(item, "visible slot")
    external_id = slot.get("external_id")
    court = slot.get("court")
    classes = slot.get("class")
    disabled = slot.get("disabled")
    local_time_text = _dom_text(slot, "time")
    duration_text = _dom_text(slot, "duration")
    if external_id == "" or external_id is None:
        normalized_external_id = None
    elif isinstance(external_id, str) and external_id.strip():
        normalized_external_id = external_id
    else:
        raise AirpadBrowserError("visible slot has an invalid external ID")
    if not isinstance(court, str) or not court.strip():
        raise AirpadBrowserError("visible slot is missing court label")
    if not isinstance(classes, str):
        raise AirpadBrowserError("visible slot is missing class state")
    if not isinstance(disabled, bool):
        raise AirpadBrowserError("visible slot has an invalid disabled state")

    time_match = re.fullmatch(r"([01][0-9]|2[0-3]):([0-5][0-9])", local_time_text)
    duration_match = re.fullmatch(r"([0-9]+)\s*min", duration_text, re.IGNORECASE)
    if time_match is None:
        raise AirpadBrowserError("visible slot has an invalid time")
    if duration_match is None or int(duration_match.group(1)) <= 0:
        raise AirpadBrowserError("visible slot has an invalid duration")
    parsed_time = time(int(time_match.group(1)), int(time_match.group(2)))
    duration = int(duration_match.group(1))
    start_local = _local_datetime(requested_date, parsed_time, "starts_at")
    end_local = (start_local.astimezone(UTC) + timedelta(minutes=duration)).astimezone(
        _AIRPAD_ZURICH
    )
    normalized_classes = {part.casefold() for part in classes.split()}
    if disabled or normalized_classes & {"disabled", "unavailable", "booked"}:
        status = "unavailable"
    elif normalized_classes & {"available", "free", "slot-available"}:
        status = "available"
    else:
        status = "unknown"
    try:
        return BrowserSlotObservation(
            normalized_external_id,
            court.strip(),
            start_local.isoformat(timespec="seconds"),
            end_local.isoformat(timespec="seconds"),
            status,
        )
    except (ModelError, TypeError) as error:
        raise AirpadBrowserError("visible slot failed validation") from error


def _has_valid_court_rows(value: object) -> bool:
    if not isinstance(value, list):
        return False
    rows = cast(list[object], value)
    return all(isinstance(row, str) and row.strip() for row in rows)


def parse_airpad_dom(payload: object, requested_date: date) -> tuple[BrowserSlotObservation, ...]:
    """Parse the small visible-DOM payload returned by the AIRPAD iframe."""
    dom = _dom_mapping(payload)
    visible_text = dom.get("visible_text")
    if not isinstance(visible_text, str):
        raise AirpadBrowserError("visible DOM is missing visible text")
    normalized_text = " ".join(visible_text.split()).casefold()
    if any(marker in normalized_text for marker in _AIRPAD_BLOCK_MARKERS):
        raise AirpadBrowserError("public AIRPAD page is blocked by login or CAPTCHA")
    if dom.get("authentication_visible") is True:
        raise AirpadBrowserError("public AIRPAD page is blocked by authentication")
    if dom.get("view") != "booking":
        raise AirpadBrowserError("visible AIRPAD booking view was not found")
    if dom.get("date") != requested_date.isoformat():
        raise AirpadBrowserError("visible AIRPAD date does not match requested date")
    raw_slots = dom.get("slots")
    if not isinstance(raw_slots, list):
        raise AirpadBrowserError("visible DOM is missing slot cards")
    observations = tuple(
        _parse_airpad_slot(item, requested_date) for item in cast(list[object], raw_slots)
    )
    if dom.get("invalid_rows") is True:
        raise AirpadBrowserError("visible booking row has a partial matrix or no explicit state")
    if observations:
        return observations
    empty_rows = dom.get("empty_rows")
    if dom.get("empty_grid") is True:
        return ()
    if empty_rows:
        if not _has_valid_court_rows(empty_rows):
            raise AirpadBrowserError("visible booking row is missing court label")
        return ()
    raise AirpadBrowserError("visible AIRPAD booking view has no explicit availability state")


class _AirpadPage(Protocol):
    @property
    def frames(self) -> Sequence["_AirpadFrame"]: ...

    def goto(self, url: str, *, wait_until: str, timeout: int) -> object: ...

    def wait_for_timeout(self, timeout: int) -> None: ...

    def evaluate(self, expression: str, arg: object = None) -> object: ...

    def close(self) -> None: ...


class _AirpadLocator(Protocol):
    def filter(self, *, has_text: str) -> "_AirpadLocator": ...

    def nth(self, index: int) -> "_AirpadLocator": ...

    def count(self) -> int: ...

    def is_visible(self) -> bool: ...

    def click(self) -> None: ...

    def all_inner_texts(self) -> list[str]: ...

    def inner_text(self) -> str: ...

    def get_attribute(self, name: str) -> str | None: ...


class _AirpadFrame(Protocol):
    @property
    def url(self) -> str: ...

    def locator(self, selector: str) -> _AirpadLocator: ...

    def evaluate(self, expression: str, arg: object = None) -> object: ...


class _AirpadContext(Protocol):
    def new_page(self) -> _AirpadPage: ...

    def close(self) -> None: ...


class _AirpadBrowser(Protocol):
    def new_context(self) -> object: ...

    def __exit__(self, *args: object) -> None: ...


def extract_airpad_observations(
    page: _AirpadPage, requested_date: date
) -> tuple[BrowserSlotObservation, ...]:
    return parse_airpad_dom(page.evaluate(_AIRPAD_VISIBLE_DOM_SCRIPT), requested_date)


def _airpad_visible_locator(
    frame: _AirpadFrame, selector: str, *, text: str | None = None
) -> _AirpadLocator:
    locator = frame.locator(selector)
    if text is not None:
        locator = locator.filter(has_text=text)
    if locator.count() != 1 or not locator.is_visible():
        raise AirpadBrowserError(f"visible AIRPAD control {selector} was not found")
    return locator


def _airpad_exact_visible_locator(frame: _AirpadFrame, selector: str, text: str) -> _AirpadLocator:
    locator = frame.locator(selector)
    matches = [
        locator.nth(index)
        for index in range(locator.count())
        if locator.nth(index).is_visible() and locator.nth(index).inner_text().strip() == text
    ]
    if len(matches) != 1:
        raise AirpadBrowserError(
            f"visible AIRPAD location label {text!r} was not found exactly once"
        )
    return matches[0]


def _wait_for_exact_visible_locator(
    page: _AirpadPage,
    frame: _AirpadFrame,
    selector: str,
    text: str,
    timeout_ms: int,
) -> _AirpadLocator:
    for _ in range(max(1, timeout_ms // 100)):
        try:
            return _airpad_exact_visible_locator(frame, selector, text)
        except AirpadBrowserError:
            page.wait_for_timeout(100)
    raise AirpadBrowserError(f"visible AIRPAD location label {text!r} was not found exactly once")


def _wait_for_visible_locator(
    page: _AirpadPage, frame: _AirpadFrame, selector: str, timeout_ms: int
) -> _AirpadLocator:
    for _ in range(max(1, timeout_ms // 100)):
        locator = frame.locator(selector)
        if locator.count() == 1 and locator.is_visible():
            return locator
        page.wait_for_timeout(100)
    raise AirpadBrowserError(f"visible AIRPAD control {selector} was not found")


def _wait_for_airpad_booking_view(
    page: _AirpadPage, frame: _AirpadFrame, label: str, timeout_ms: int
) -> None:
    for _ in range(max(1, timeout_ms // 100)):
        dom = _dom_mapping(frame.evaluate(_AIRPAD_VISIBLE_DOM_SCRIPT))
        visible_text = dom.get("visible_text")
        if (
            dom.get("view") == "booking"
            and isinstance(visible_text, str)
            and label.casefold() in visible_text.casefold()
        ):
            return
        page.wait_for_timeout(100)
    raise AirpadBrowserError("visible AIRPAD booking view did not match requested location")


def _airpad_frame(page: _AirpadPage, timeout_ms: int) -> _AirpadFrame:
    for _ in range(max(1, timeout_ms // 100)):
        frames = [
            frame for frame in page.frames if frame.url.startswith(_AIRPAD_BROWSER_URL_PREFIX)
        ]
        if len(frames) == 1:
            return frames[0]
        if len(frames) > 1:
            raise AirpadBrowserError("visible AIRPAD booking frame selection was ambiguous")
        page.wait_for_timeout(100)
    raise AirpadBrowserError("visible AIRPAD booking frame was not found")


def _airpad_date_label(requested_date: date) -> str:
    return f"{_AIRPAD_MONTHS[requested_date.month - 1]} {requested_date.day:02d}, {requested_date.year}"


def _wait_for_airpad_date(
    page: _AirpadPage,
    frame: _AirpadFrame,
    requested_date: date,
    timeout_ms: int,
    previous_payload: object,
    require_refresh: bool,
) -> object:
    previous_grid = _airpad_grid(previous_payload)
    refresh_observed = False
    for _ in range(max(1, timeout_ms // 100)):
        payload = frame.evaluate(_AIRPAD_VISIBLE_DOM_SCRIPT)
        if isinstance(payload, Mapping):
            dom = cast(Mapping[str, object], payload)
            visible_text = dom.get("visible_text")
            if isinstance(visible_text, str):
                normalized_text = " ".join(visible_text.split()).casefold()
                loading_observed = any(
                    marker in normalized_text for marker in _AIRPAD_LOADING_MARKERS
                )
                refresh_observed = refresh_observed or loading_observed
                if loading_observed:
                    page.wait_for_timeout(100)
                    continue
            active_label_matches = _airpad_active_date_matches(
                dom.get("active_date_label"), requested_date
            )
            refresh_observed = refresh_observed or active_label_matches
            if (
                _airpad_grid_ready(dom)
                and _airpad_payload_date(dom, requested_date) == requested_date.isoformat()
                and (not require_refresh or refresh_observed or _airpad_grid(dom) != previous_grid)
            ):
                if dom.get("date") == requested_date.isoformat():
                    return dom
                return {**dom, "date": requested_date.isoformat()}
        page.wait_for_timeout(100)
    raise AirpadBrowserError("timed out waiting for the requested AIRPAD date")


def _select_airpad_date(
    page: _AirpadPage, frame: _AirpadFrame, requested_date: date, timeout_ms: int
) -> object:
    previous_payload = frame.evaluate(_AIRPAD_VISIBLE_DOM_SCRIPT)
    previous_date = _airpad_payload_date(previous_payload, requested_date)
    _airpad_visible_locator(frame, ".btn-date-calendar").click()
    label = _airpad_date_label(requested_date)
    _airpad_visible_locator(frame, f'button.days-btn[aria-label="{label}"]').click()
    return _wait_for_airpad_date(
        page,
        frame,
        requested_date,
        timeout_ms,
        previous_payload,
        previous_date != requested_date.isoformat(),
    )


def _airpad_active_date_matches(label: object, requested_date: date) -> bool:
    if not isinstance(label, str):
        return False
    parts = " ".join(label.split()).replace(",", "").split()
    return (
        len(parts) == 3
        and parts[0].casefold() == _AIRPAD_WEEKDAYS[requested_date.weekday()].casefold()
        and parts[1].isdigit()
        and int(parts[1]) == requested_date.day
        and parts[2].casefold() == _AIRPAD_MONTHS[requested_date.month - 1][:3].casefold()
    )


def _airpad_payload_date(payload: object, requested_date: date | None = None) -> str | None:
    if not isinstance(payload, Mapping):
        return None
    dom = cast(Mapping[str, object], payload)
    value = dom.get("date")
    if isinstance(value, str) and value:
        return value
    if requested_date is not None and _airpad_active_date_matches(
        dom.get("active_date_label"), requested_date
    ):
        return requested_date.isoformat()
    return value if isinstance(value, str) else None


def _airpad_grid(payload: object) -> tuple[object, object, object, object] | None:
    if not isinstance(payload, Mapping):
        return None
    dom = cast(Mapping[str, object], payload)
    return (dom.get("slots"), dom.get("empty_grid"), dom.get("empty_rows"), dom.get("invalid_rows"))


def _airpad_grid_ready(payload: object) -> bool:
    if not isinstance(payload, Mapping):
        return False
    dom = cast(Mapping[str, object], payload)
    raw_slots = dom.get("slots")
    return dom.get("invalid_rows") is False and (
        dom.get("empty_grid") is True
        or isinstance(raw_slots, list)
        and bool(cast(list[object], raw_slots))
    )


def _airpad_time_range_label(frame: _AirpadFrame) -> str:
    locator = _airpad_visible_locator(frame, ".select-time-range")
    labels = [label.strip() for label in locator.all_inner_texts() if label.strip()]
    if len(labels) != 1:
        raise AirpadBrowserError("visible AIRPAD time range is ambiguous")
    return labels[0]


def _advance_airpad_time_range(
    page: _AirpadPage,
    frame: _AirpadFrame,
    requested_date: date,
    previous_label: str,
    timeout_ms: int,
) -> tuple[str, object]:
    _airpad_visible_locator(frame, ".btn-arrow-right").click()
    payload: object = None
    range_changed = False
    for _ in range(max(1, timeout_ms // 100)):
        page.wait_for_timeout(100)
        label = _airpad_time_range_label(frame)
        payload = frame.evaluate(_AIRPAD_VISIBLE_DOM_SCRIPT)
        if label != previous_label:
            range_changed = True
            if not _airpad_grid_ready(payload):
                continue
            if _airpad_payload_date(payload, requested_date) != requested_date.isoformat():
                raise AirpadBrowserError("visible AIRPAD date changed during time-range navigation")
            dom = _dom_mapping(payload)
            if dom.get("date") == requested_date.isoformat():
                return label, payload
            return label, {**dom, "date": requested_date.isoformat()}
    if range_changed:
        raise AirpadBrowserError("timed out waiting for the refreshed AIRPAD time range")
    return previous_label, payload


def _airpad_locator_is_disabled(locator: _AirpadLocator) -> bool:
    return (
        locator.get_attribute("disabled") is not None
        or locator.get_attribute("aria-disabled") == "true"
    )


def _collect_airpad_date(
    page: _AirpadPage,
    frame: _AirpadFrame,
    requested_date: date,
    timeout_ms: int,
) -> list[BrowserSlotObservation]:
    payload = _select_airpad_date(page, frame, requested_date, timeout_ms)
    observations: list[BrowserSlotObservation] = []
    seen_ranges: set[str] = set()
    for range_index in range(8):
        range_label = _airpad_time_range_label(frame)
        if range_label in seen_ranges:
            break
        seen_ranges.add(range_label)
        observations.extend(parse_airpad_dom(payload, requested_date))
        if range_index == 7:
            break
        arrow = frame.locator(".btn-arrow-right")
        if arrow.count() != 1 or not arrow.is_visible() or _airpad_locator_is_disabled(arrow):
            break
        _, payload = _advance_airpad_time_range(
            page,
            frame,
            requested_date,
            range_label,
            timeout_ms,
        )
    return observations


def parse_airpad_observations(
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
        "airpad_browser",
        source_url,
        window_start.isoformat(),
        window_end.isoformat(),
        (window_end - window_start).days,
        collected_at,
        "unavailable",
        "public AIRPAD booking page is unavailable",
    )
    return AvailabilityResult(run, ())


class AirpadBrowserConnector:
    def __init__(
        self,
        sources: Sequence[AirpadSource],
        *,
        browser_factory: BrowserFactory = default_browser_factory,
        timeout_ms: int = _AIRPAD_TIMEOUT_MS,
    ) -> None:
        self._sources = {source.location_id: source for source in sources}
        self._browser_factory = browser_factory
        self._timeout_ms = timeout_ms
        self._browser: _AirpadBrowser | None = None

    def open(self) -> None:
        if self._browser is None:
            session = self._browser_factory()
            self._browser = session.__enter__()

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
            raise AirpadSourceError("requested date window is invalid")
        source = self._sources.get(location.location_id)
        if source is None:
            raise AirpadSourceError("no source metadata for location")
        if source.status == "unavailable":
            return _unavailable_result(
                source.booking_url,
                location.location_id,
                run_id,
                window_start,
                window_end,
                collected_at,
            )
        if location.location_id not in AIRPAD_LOCATION_LABELS:
            raise AirpadSourceError("location has no AIRPAD booking label")

        observations: list[BrowserSlotObservation] = []
        try:
            self.open()
            browser = self._browser
            if browser is None:
                raise AirpadBrowserError("browser session is not running")
            context = cast(_AirpadContext, browser.new_context())
            try:
                page = context.new_page()
                try:
                    page.goto(source.booking_url, wait_until="commit", timeout=self._timeout_ms)
                    frame = _airpad_frame(page, self._timeout_ms)
                    _wait_for_exact_visible_locator(
                        page, frame, ".item-title", "1.Terrains", self._timeout_ms
                    ).click()
                    label = AIRPAD_LOCATION_LABELS[location.location_id]
                    _wait_for_exact_visible_locator(
                        page, frame, ".activity-card", label, self._timeout_ms
                    ).click()
                    _wait_for_airpad_booking_view(page, frame, label, self._timeout_ms)
                    _wait_for_visible_locator(page, frame, ".btn-date-calendar", self._timeout_ms)
                    _wait_for_visible_locator(page, frame, ".select-time-range", self._timeout_ms)
                    current_date = window_start
                    while current_date < window_end:
                        observations.extend(
                            _collect_airpad_date(page, frame, current_date, self._timeout_ms)
                        )
                        current_date += timedelta(days=1)
                finally:
                    page.close()
            finally:
                context.close()
        except (AirpadBrowserError, AirpadSourceError):
            raise
        except Exception as error:
            if isinstance(error, RuntimeError) or _is_documented_browser_error(error):
                raise AirpadSourceError("browser navigation or extraction failed") from error
            raise

        try:
            slots = parse_airpad_observations(
                tuple(observations),
                location_id=location.location_id,
                run_id=run_id,
                window_start=window_start,
                window_end=window_end,
            )
        except PlaytomicSourceError as error:
            raise AirpadSourceError(str(error)[:160]) from error
        run = AvailabilityRun(
            run_id,
            location.location_id,
            "airpad_browser",
            source.booking_url,
            window_start.isoformat(),
            window_end.isoformat(),
            (window_end - window_start).days,
            collected_at,
            "success",
            None,
        )
        return AvailabilityResult(run, slots)


AirpadBrowserConnectorFactory = Callable[[Sequence[AirpadSource]], AirpadBrowserConnector]
