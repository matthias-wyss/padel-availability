import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal, Protocol, Self, cast
from zoneinfo import ZoneInfo

from ..availability import AvailabilityResult, AvailabilityRun, AvailabilitySlot, local_to_utc
from ..models import LocationRecord, ModelError, _text  # pyright: ignore[reportPrivateUsage]
from .playtomic import (  # pyright: ignore[reportPrivateUsage]
    PlaytomicSource,
    PlaytomicSourceError,
    _slot_key,  # pyright: ignore[reportPrivateUsage]
)

BrowserSlotStatus = Literal["available", "unavailable", "unknown"]

_SLOT_STATUSES = {"available", "unavailable", "unknown"}
_ZURICH = ZoneInfo("Europe/Zurich")
_BROWSER_TIMEOUT_MS = 15_000
_CHROMIUM_ARGS = ("--disable-gpu", "--disable-dev-shm-usage")
_VISIBLE_DOM_SCRIPT = """
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
  const heading = Array.from(body.querySelectorAll('h2')).some(element =>
    visible(element) && /available courts|terrains disponibles/i.test(element.innerText || '')
  );
  const dateControls = Array.from(body.querySelectorAll('input[type="date"]'))
    .filter(element => element.parentElement && visible(element.parentElement))
  const dates = dateControls.map(element => element.value);
  const date = dates.length > 0 && dates.every(value => value === dates[0]) ? dates[0] : '';
  const slots = Array.from(body.querySelectorAll(
    '[data-tracking-property-time][data-tracking-property-duration]'
  )).filter(visible).map(element => {
    const row = element.closest('div.flex.border-b');
    return {
      external_id: element.getAttribute('data-slot-id'),
      time: element.getAttribute('data-tracking-property-time'),
      duration: element.getAttribute('data-tracking-property-duration'),
      class: element.getAttribute('class') || '',
      disabled: element.hasAttribute('disabled') || element.getAttribute('aria-disabled') === 'true',
      court: row?.querySelector('div.shrink-0 .truncate')?.textContent?.trim() || null
    };
  });
  const courtRows = Array.from(body.querySelectorAll('div.flex.border-b'))
    .filter(element => visible(element) && element.querySelector('div.shrink-0 .truncate'));
  return {
    view: heading ? 'booking' : 'unknown',
    date,
    dates,
    slots,
    empty_grid: heading && slots.length === 0 && courtRows.length > 0,
    visible_text: body.innerText || ''
  };
}
"""
_SELECT_DATE_SCRIPT = """
value => {
  const visible = element => {
    const rect = element.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return false;
    for (let current = element; current; current = current.parentElement) {
      const style = getComputedStyle(current);
      if (style.display === 'none' || style.visibility === 'hidden') return false;
    }
    return true;
  };
  const inputs = Array.from(document.querySelectorAll('input[type="date"]'))
    .filter(input => input.parentElement && visible(input.parentElement));
  const values = inputs.map(input => input.value);
  if (new Set(values).size > 1) return false;
  for (const input of inputs) {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
    setter?.call(input, value);
    input.dispatchEvent(new Event('input', {bubbles: true}));
    input.dispatchEvent(new Event('change', {bubbles: true}));
  }
  return true;
}
"""
_NO_SLOT_MARKERS = (
    "no available courts",
    "no available slots",
    "no availability",
    "aucun terrain disponible",
    "aucun créneau disponible",
    "aucune disponibilité",
    "pas de créneau disponible",
)
_UNAVAILABLE_MARKERS = (
    "club is temporarily unavailable",
    "service temporarily unavailable",
    "ce club est temporairement indisponible",
)
_LOADING_MARKERS = ("loading", "chargement en cours")
_BLOCK_MARKERS = (
    "captcha",
    "verify you are human",
    "log in to continue",
    "login required",
    "sign in to continue",
    "access denied",
    "accès refusé",
)


class PlaytomicBrowserError(PlaytomicSourceError):
    """Raised when the visible public booking DOM cannot be observed safely."""

    def __init__(self, message: str) -> None:
        super().__init__(message[:160])


class PlaytomicBrowserUnavailable(PlaytomicBrowserError):
    """Raised for an explicit public unavailable marker."""


class _BrowserPage(Protocol):
    def goto(self, url: str, *, wait_until: str, timeout: int) -> object: ...

    def wait_for_timeout(self, timeout: int) -> None: ...

    def evaluate(self, expression: str, arg: object = None) -> object: ...

    def close(self) -> None: ...


class _BrowserContext(Protocol):
    def new_page(self) -> _BrowserPage: ...

    def close(self) -> None: ...


class _BrowserSession(Protocol):
    def __enter__(self) -> Self: ...

    def __exit__(self, *args: object) -> None: ...

    def new_context(self) -> _BrowserContext: ...


BrowserFactory = Callable[[], _BrowserSession]


def _observation_timestamp(value: object, field: str) -> datetime:
    value = _text(value, field)
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as error:
        raise ModelError(f"{field} must be an offset-aware ISO-8601 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ModelError(f"{field} must be an offset-aware ISO-8601 timestamp")

    return parsed


@dataclass(frozen=True, slots=True)
class BrowserSlotObservation:
    external_id: str | None
    court_label: str | None
    starts_at: str
    ends_at: str
    status: BrowserSlotStatus

    def __post_init__(self) -> None:
        for field in ("external_id", "court_label"):
            value = getattr(self, field)
            if value is not None:
                _text(value, field)
        starts_at = _observation_timestamp(self.starts_at, "starts_at")
        ends_at = _observation_timestamp(self.ends_at, "ends_at")
        if ends_at <= starts_at:
            raise ModelError("ends_at must be after starts_at")
        if self.status not in _SLOT_STATUSES:
            raise ModelError("status has invalid value")


def _dom_mapping(value: object, field: str = "visible DOM") -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise PlaytomicBrowserError(f"{field} has an invalid shape")
    return cast(Mapping[str, object], value)


def _dom_text(mapping: Mapping[str, object], field: str) -> str:
    value = mapping.get(field)
    if not isinstance(value, str) or not value.strip():
        raise PlaytomicBrowserError(f"visible DOM is missing {field}")
    return value.strip()


def _local_datetime(local_date: date, local_time: time, field: str) -> datetime:
    wall_time = datetime.combine(local_date, local_time)
    first = wall_time.replace(tzinfo=_ZURICH, fold=0)
    second = wall_time.replace(tzinfo=_ZURICH, fold=1)
    if first.utcoffset() != second.utcoffset():
        raise PlaytomicBrowserError(f"{field} is ambiguous in Europe/Zurich")
    return first


def _parse_visible_slot(item: object, requested_date: date) -> BrowserSlotObservation:
    slot = _dom_mapping(item, "visible slot")
    external_id = slot.get("external_id")
    local_time_text = _dom_text(slot, "time")
    duration_text = _dom_text(slot, "duration")
    classes = slot.get("class")
    disabled = slot.get("disabled")
    court_label = slot.get("court")
    if external_id is not None and (not isinstance(external_id, str) or not external_id.strip()):
        raise PlaytomicBrowserError("visible slot has an invalid external ID")
    if not isinstance(classes, str):
        raise PlaytomicBrowserError("visible slot is missing class state")
    if not isinstance(disabled, bool):
        raise PlaytomicBrowserError("visible slot has an invalid disabled state")
    if court_label is not None and (not isinstance(court_label, str) or not court_label.strip()):
        raise PlaytomicBrowserError("visible slot has an invalid court label")
    match = re.fullmatch(r"([0-9]{1,2})(?::([0-9]{2}))?\s*([AP]M)", local_time_text.upper())
    if match is None:
        raise PlaytomicBrowserError("visible slot has an ambiguous time")
    hour = int(match.group(1))
    minute = int(match.group(2) or "0")
    if not 1 <= hour <= 12 or not 0 <= minute <= 59:
        raise PlaytomicBrowserError("visible slot has an ambiguous time")
    if match.group(3) == "PM" and hour != 12:
        hour += 12
    if match.group(3) == "AM" and hour == 12:
        hour = 0
    parsed_time = time(hour, minute)
    try:
        duration = int(duration_text)
    except ValueError as error:
        raise PlaytomicBrowserError("visible slot has an invalid duration") from error
    if duration <= 0:
        raise PlaytomicBrowserError("visible slot has an invalid duration")

    start_local = _local_datetime(requested_date, parsed_time, "starts_at")
    end_local = (start_local.astimezone(UTC) + timedelta(minutes=duration)).astimezone(_ZURICH)
    starts_at = start_local.isoformat(timespec="seconds")
    ends_at = end_local.isoformat(timespec="seconds")
    try:
        return BrowserSlotObservation(
            external_id,
            court_label,
            starts_at,
            ends_at,
            "unavailable" if disabled else "available" if "bg-white" in classes else "unknown",
        )
    except ModelError as error:
        raise PlaytomicBrowserError("visible slot failed validation") from error


def parse_visible_dom(payload: object, requested_date: date) -> tuple[BrowserSlotObservation, ...]:
    """Parse the small visible-DOM payload returned by Playwright."""
    dom = _dom_mapping(payload)
    visible_text = dom.get("visible_text")
    if not isinstance(visible_text, str):
        raise PlaytomicBrowserError("visible DOM is missing visible text")
    normalized_text = " ".join(visible_text.split()).casefold()
    if any(marker in normalized_text for marker in _BLOCK_MARKERS):
        raise PlaytomicBrowserError("public page is blocked by login or CAPTCHA")
    if any(marker in normalized_text for marker in _UNAVAILABLE_MARKERS):
        raise PlaytomicBrowserUnavailable("public page is explicitly unavailable")
    if dom.get("view") != "booking":
        raise PlaytomicBrowserError("visible booking view was not found")
    dates_value = dom.get("dates")
    if not isinstance(dates_value, list):
        raise PlaytomicBrowserError("visible DOM is missing date controls")
    raw_dates = cast(list[object], dates_value)
    if not all(isinstance(value, str) for value in raw_dates):
        raise PlaytomicBrowserError("visible DOM is missing date controls")
    dates = cast(list[str], raw_dates)
    if len(set(dates)) > 1:
        raise PlaytomicBrowserError("visible date controls have divergent values")
    if len(dates) != 1 or dates[0] != requested_date.isoformat():
        raise PlaytomicBrowserError("visible date control did not select the requested date")
    raw_slots_value = dom.get("slots")
    if not isinstance(raw_slots_value, list):
        raise PlaytomicBrowserError("visible DOM is missing slot cards")
    raw_slots = cast(list[object], raw_slots_value)
    observations = tuple(_parse_visible_slot(item, requested_date) for item in raw_slots)
    if observations:
        return observations
    if dom.get("empty_grid") is True or any(
        marker in normalized_text for marker in _NO_SLOT_MARKERS
    ):
        return ()
    raise PlaytomicBrowserError("visible booking view has no explicit availability state")


def extract_browser_observations(
    page: _BrowserPage, requested_date: date
) -> tuple[BrowserSlotObservation, ...]:
    payload = page.evaluate(_VISIBLE_DOM_SCRIPT)
    return parse_visible_dom(payload, requested_date)


def _select_date(page: _BrowserPage, requested_date: date) -> None:
    if page.evaluate(_SELECT_DATE_SCRIPT, requested_date.isoformat()) is not True:
        raise PlaytomicBrowserError("visible date controls have divergent values")


def parse_browser_observations(
    observations: Sequence[BrowserSlotObservation],
    *,
    location_id: str,
    run_id: str,
    window_start: date,
    window_end: date,
) -> tuple[AvailabilitySlot, ...]:
    if window_end <= window_start:
        raise PlaytomicSourceError("requested date window is invalid")

    slots: dict[str, AvailabilitySlot] = {}
    for index, observation in enumerate(observations):
        if type(observation) is not BrowserSlotObservation:
            raise PlaytomicSourceError(f"observation {index} is invalid")
        starts_local = _observation_timestamp(observation.starts_at, "starts_at")
        local_date = starts_local.astimezone(_ZURICH).date()
        if not window_start <= local_date < window_end:
            continue
        try:
            starts_at = local_to_utc(observation.starts_at)
            ends_at = local_to_utc(observation.ends_at)
            slot = AvailabilitySlot(
                run_id,
                location_id,
                _slot_key(
                    location_id,
                    observation.court_label,
                    starts_at,
                    ends_at,
                    observation.external_id,
                ),
                observation.external_id,
                observation.court_label,
                starts_at,
                ends_at,
                "Europe/Zurich",
                observation.status,
            )
        except ModelError as error:
            raise PlaytomicSourceError(f"observation {index} failed validation") from error
        existing = slots.get(slot.slot_key)
        if existing is not None and existing != slot:
            if (
                observation.external_id is None
                or existing.starts_at == slot.starts_at
                and existing.ends_at == slot.ends_at
            ):
                kind = "external_id" if observation.external_id is not None else "slot hash"
                raise PlaytomicSourceError(f"conflicting duplicate {kind}")
            try:
                slot = AvailabilitySlot(
                    run_id,
                    location_id,
                    _slot_key(
                        location_id,
                        observation.court_label,
                        starts_at,
                        ends_at,
                        None,
                    ),
                    observation.external_id,
                    observation.court_label,
                    starts_at,
                    ends_at,
                    "Europe/Zurich",
                    observation.status,
                )
            except ModelError as error:
                raise PlaytomicSourceError(f"observation {index} failed validation") from error
            existing = slots.get(slot.slot_key)
            if existing is not None and existing != slot:
                raise PlaytomicSourceError("conflicting duplicate slot hash")
        elif existing is not None:
            continue
        slots[slot.slot_key] = slot

    return tuple(
        sorted(
            slots.values(),
            key=lambda slot: (slot.starts_at, slot.ends_at, slot.court_label or "", slot.slot_key),
        )
    )


class _PlaywrightBrowserSession:
    def __init__(self) -> None:
        self._playwright: Any = None
        self._browser: Any = None

    def __enter__(self) -> Self:
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        try:
            self._browser = self._playwright.chromium.launch(
                headless=True, args=list(_CHROMIUM_ARGS)
            )
        except Exception:
            self._playwright.stop()
            self._playwright = None
            raise
        return self

    def __exit__(self, *_args: object) -> None:
        try:
            if self._browser is not None:
                self._browser.close()
        finally:
            if self._playwright is not None:
                self._playwright.stop()

    def new_context(self) -> _BrowserContext:
        if self._browser is None:
            raise PlaytomicBrowserError("browser session is not running")
        return cast(_BrowserContext, self._browser.new_context())


def _default_browser_factory() -> _BrowserSession:
    return _PlaywrightBrowserSession()


def _is_documented_browser_error(error: Exception) -> bool:
    if isinstance(error, (OSError, TimeoutError)):
        return True
    try:
        from playwright.sync_api import Error as PlaywrightError
    except ImportError:
        return False
    return isinstance(error, PlaywrightError)


def _payload_is_ready(
    payload: object,
    requested_date: date,
    previous_payload: object | None = None,
    *,
    refresh_observed: bool = False,
) -> bool:
    if not isinstance(payload, Mapping):
        return False
    dom = cast(Mapping[str, object], payload)
    visible_text = dom.get("visible_text")
    if isinstance(visible_text, str):
        normalized_text = " ".join(visible_text.split()).casefold()
        if any(marker in normalized_text for marker in _BLOCK_MARKERS + _UNAVAILABLE_MARKERS):
            return True
        if any(marker in normalized_text for marker in _LOADING_MARKERS):
            return False
    if dom.get("view") != "booking" or dom.get("date") != requested_date.isoformat():
        return False
    payload_changed = _payload_content(dom) != _payload_content(previous_payload)
    date_changed = _payload_date(previous_payload) != requested_date.isoformat()
    slots = dom.get("slots")
    if isinstance(slots, list) and _has_visible_slot(cast(list[object], slots)):
        return not date_changed or payload_changed or refresh_observed
    if dom.get("empty_grid") is True:
        return not date_changed or payload_changed or refresh_observed
    if isinstance(visible_text, str):
        normalized_text = " ".join(visible_text.split()).casefold()
        if any(marker in normalized_text for marker in _NO_SLOT_MARKERS):
            return not date_changed or payload_changed or refresh_observed
    return False


def _payload_date(payload: object) -> str | None:
    if not isinstance(payload, Mapping):
        return None
    dom = cast(Mapping[str, object], payload)
    value = dom.get("date")
    return value if isinstance(value, str) else None


def _payload_content(payload: object) -> tuple[object, tuple[bool, bool, bool, bool]] | None:
    if not isinstance(payload, Mapping):
        return None
    dom = cast(Mapping[str, object], payload)
    visible_text = dom.get("visible_text")
    normalized_text = (
        " ".join(visible_text.split()).casefold() if isinstance(visible_text, str) else ""
    )
    marker_state: tuple[bool, bool, bool, bool] = (
        any(marker in normalized_text for marker in _NO_SLOT_MARKERS),
        any(marker in normalized_text for marker in _UNAVAILABLE_MARKERS),
        any(marker in normalized_text for marker in _BLOCK_MARKERS),
        any(marker in normalized_text for marker in _LOADING_MARKERS),
    )
    return (dom.get("slots"), dom.get("empty_grid") is True), marker_state


def _has_visible_slot(slots: list[object]) -> bool:
    for item in slots:
        if not isinstance(item, Mapping):
            continue
        mapping = cast(Mapping[str, object], item)
        if isinstance(mapping.get("time"), str) and isinstance(mapping.get("duration"), str):
            return True
    return False


def _wait_for_visible_dom(
    page: _BrowserPage,
    requested_date: date,
    timeout_ms: int,
    previous_payload: object | None = None,
) -> tuple[object, bool]:
    attempts = max(1, timeout_ms // 100)
    payload: object = None
    refresh_observed = False
    for _ in range(attempts):
        payload = page.evaluate(_VISIBLE_DOM_SCRIPT)
        refresh_observed = refresh_observed or _payload_has_marker(payload, _LOADING_MARKERS)
        if _payload_is_ready(
            payload,
            requested_date,
            previous_payload,
            refresh_observed=refresh_observed,
        ):
            return payload, refresh_observed
        page.wait_for_timeout(100)
    raise PlaytomicBrowserError("timed out waiting for the visible booking view")


def _payload_has_marker(payload: object, markers: tuple[str, ...]) -> bool:
    if not isinstance(payload, Mapping):
        return False
    dom = cast(Mapping[str, object], payload)
    visible_text = dom.get("visible_text")
    if not isinstance(visible_text, str):
        return False
    normalized_text = " ".join(visible_text.split()).casefold()
    return any(marker in normalized_text for marker in markers)


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
        "playtomic_browser",
        source_url,
        window_start.isoformat(),
        window_end.isoformat(),
        (window_end - window_start).days,
        collected_at,
        "unavailable",
        "public booking page is explicitly unavailable",
    )
    return AvailabilityResult(run, ())


class BrowserConnector(Protocol):
    def open(self) -> None: ...

    def close(self) -> None: ...

    def collect(
        self,
        location: LocationRecord,
        *,
        run_id: str,
        window_start: date,
        window_end: date,
        collected_at: str,
    ) -> AvailabilityResult: ...


class PlaytomicBrowserConnector:
    def __init__(
        self,
        sources: Sequence[PlaytomicSource],
        *,
        browser_factory: BrowserFactory = _default_browser_factory,
        timeout_ms: int = _BROWSER_TIMEOUT_MS,
    ) -> None:
        self._sources = {source.location_id: source for source in sources}
        self._browser_factory = browser_factory
        self._timeout_ms = timeout_ms
        self._browser: _BrowserSession | None = None

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
            raise PlaytomicSourceError("requested date window is invalid")
        location_id = location.location_id
        source = self._sources.get(location_id)
        if source is None:
            raise PlaytomicSourceError("no source metadata for location")
        if source.transport != "browser_dom":
            raise PlaytomicSourceError("source is not configured for browser DOM transport")
        source_url = source.booking_url
        if source.status == "unavailable":
            return _unavailable_result(
                source_url, location_id, run_id, window_start, window_end, collected_at
            )

        observations: list[BrowserSlotObservation] = []
        try:
            self.open()
            browser = self._browser
            if browser is None:
                raise PlaytomicBrowserError("browser session is not running")
            context = browser.new_context()
            try:
                page = context.new_page()
                try:
                    page.goto(source_url, wait_until="commit", timeout=self._timeout_ms)
                    current_date = window_start
                    while current_date < window_end:
                        previous_payload = page.evaluate(_VISIBLE_DOM_SCRIPT)
                        _select_date(page, current_date)
                        payload, _refresh_observed = _wait_for_visible_dom(
                            page,
                            current_date,
                            self._timeout_ms,
                            previous_payload,
                        )
                        try:
                            observations.extend(parse_visible_dom(payload, current_date))
                        except PlaytomicBrowserUnavailable:
                            return _unavailable_result(
                                source_url,
                                location_id,
                                run_id,
                                window_start,
                                window_end,
                                collected_at,
                            )
                        current_date += timedelta(days=1)
                finally:
                    page.close()
            finally:
                context.close()
        except PlaytomicBrowserError:
            raise
        except PlaytomicSourceError:
            raise
        except Exception as error:
            if _is_documented_browser_error(error):
                raise PlaytomicSourceError(
                    "browser navigation or extraction failed"[:160]
                ) from error
            raise

        slots = parse_browser_observations(
            tuple(observations),
            location_id=location_id,
            run_id=run_id,
            window_start=window_start,
            window_end=window_end,
        )
        run = AvailabilityRun(
            run_id,
            location_id,
            "playtomic_browser",
            source_url,
            window_start.isoformat(),
            window_end.isoformat(),
            (window_end - window_start).days,
            collected_at,
            "success",
            None,
        )
        return AvailabilityResult(run, slots)


BrowserConnectorFactory = Callable[[Sequence[PlaytomicSource]], BrowserConnector]
