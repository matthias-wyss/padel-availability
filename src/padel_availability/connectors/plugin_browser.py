import re
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime, time, timedelta
from typing import Protocol, Self, cast
from zoneinfo import ZoneInfo

from ..availability import AvailabilityResult, AvailabilityRun, AvailabilitySlot
from ..models import LocationRecord
from .playtomic import PlaytomicSourceError
from .playtomic_browser import (
    BrowserFactory,
    BrowserSlotObservation,
    _is_documented_browser_error,  # pyright: ignore[reportPrivateUsage]
    default_browser_factory,
    parse_browser_observations,
)
from .plugin import PluginSource, PluginSourceError

__all__ = [
    "PluginBrowserConnector",
    "PluginBrowserConnectorFactory",
    "PluginBrowserError",
    "parse_plugin_dom",
]

_PLUGIN_TIMEOUT_MS = 15_000

_ZURICH = ZoneInfo("Europe/Zurich")
_PAYLOAD_FIELDS = {
    "view",
    "date",
    "activity",
    "courts",
    "slots",
    "loading",
    "authentication_visible",
    "empty_grid",
}
_SLOT_FIELDS = {"court", "start", "end", "state"}
_AVAILABLE = {"available", "free", "open", "libre", "frei"}
_UNAVAILABLE = {"booked", "occupied", "reserved", "unavailable", "réservé", "besetzt"}
_AMBIGUOUS = {"unknown", "partially booked", "partially reserved", "check availability", "?"}

_PLUGIN_VISIBLE_DOM_SCRIPT = r"""
() => {
  const visible = element => {
    const rect = element.getBoundingClientRect();
    if (!rect.width || !rect.height) return false;
    for (let current = element; current; current = current.parentElement) {
      const style = getComputedStyle(current);
      if (style.display === 'none' || style.visibility === 'hidden' ||
          Number(style.opacity) === 0 || current.getAttribute('aria-hidden') === 'true') return false;
    }
    return true;
  };
  const body = document.body;
  const text = (body?.innerText || '').toLocaleLowerCase();
  const activityControl = Array.from(document.querySelectorAll('.sports-types select, select'))
    .find(visible);
  const activity = activityControl?.selectedOptions[0]?.innerText.trim().split(/\s+-\s+/)[0] || '';
  const dateLabel = Array.from(document.querySelectorAll('.header_date'))
    .find(visible)?.innerText.replace(/\s+/g, ' ').trim() || '';
  const months = {jan:1, january:1, janvier:1, januar:1, feb:2, february:2, février:2,
    februar:2, mar:3, march:3, mars:3, märz:3, apr:4, april:4, avr:4, mai:5,
    may:5, jun:6, june:6, juin:6, juni:6, jul:7, july:7, juillet:7, juli:7,
    aug:8, august:8, août:8, sep:9, sept:9, september:9, octobre:10, october:10,
    oktober:10, oct:10, nov:11, november:11, novembre:11, dec:12, december:12,
    décembre:12, dezember:12, déc:12};
  const isoDate = dateLabel.match(/\b(\d{4}-\d{2}-\d{2})\b/);
  const dateMatch = dateLabel.match(/(\d{1,2})\s+([\p{L}.]+)\s+(\d{4})/u);
  const month = dateMatch && months[dateMatch[2].toLocaleLowerCase().replace(/\.$/, '')];
  const selectedDate = isoDate ? isoDate[1] : dateMatch && month
    ? `${dateMatch[3]}-${String(month).padStart(2, '0')}-${dateMatch[1].padStart(2, '0')}` : '';
  const courts = [];
  const slots = [];
  const stateOf = value => {
    const state = value.trim().toLocaleLowerCase();
    if (/^(available|free|open|libre|frei)$/.test(state)) return 'available';
    if (/^(booked|occupied|reserved|unavailable|réservé|besetzt)$/.test(state)) return 'unavailable';
    if (/^(unknown|partially booked|partially reserved|check availability|\?|notallowed)$/.test(state)) return 'unknown';
    return state ? 'unrecognized' : '';
  };
  const visualStateOf = (cell, value) => {
    const classNames = cell.className.toLocaleLowerCase();
    if (/\b(?:notallowed|tempnotallowed)\b/.test(classNames)) return 'unknown';
    if (/\bcursor\b/.test(classNames)) return 'available';
    if (!/\b(?:time_extra|time_30)\b/.test(classNames)) return '';
    const background = getComputedStyle(cell).backgroundColor.toLocaleLowerCase();
    const transparent = background === 'transparent' || /rgba\(0,\s*0,\s*0,\s*0\)/.test(background);
    if (!value && transparent) return 'available';
    if (/^\d{2}:\d{2}$/.test(value) && !transparent) return 'unavailable';
    return '';
  };
  const addCourt = name => {
    if (name && !/^(sa|di|lu|ma|me|je|ve)\s+\d+$/i.test(name) && !courts.includes(name)) courts.push(name);
  };
  const cells = Array.from(document.querySelectorAll('td.terrainTxt')).filter(visible);
  for (const cell of cells) {
    const court = (cell.getAttribute('terrain') || '').trim();
    addCourt(court);
    const start = (cell.getAttribute('heure') || '').trim();
    if (!court || !start) continue;
    const stateText = (cell.innerText || '').trim();
    const classNames = cell.className.toLocaleLowerCase();
    const textState = stateOf(stateText);
    const visualText = !stateText || /^\d{2}:\d{2}$/.test(stateText)
      ? visualStateOf(cell, stateText) : '';
    const state = visualText || textState;
    const step = Number((classNames.match(/time_(\d+)/) || [])[1]);
    const rowspan = Number(cell.getAttribute('rowspan') || 1);
    let endMinutes = Number(start.slice(0, 2)) * 60 + Number(start.slice(3)) + step * rowspan;
    if (!step) {
      const rows = Array.from(cell.closest('table')?.querySelectorAll('tr') || []);
      const nextHour = rows[rows.indexOf(cell.closest('tr')) + rowspan]
        ?.querySelector('.hour_slot')?.innerText.trim();
      if (nextHour && /^\d{2}:\d{2}$/.test(nextHour)) {
        endMinutes = Number(nextHour.slice(0, 2)) * 60 + Number(nextHour.slice(3));
      }
    }
    if (endMinutes > Number(start.slice(0, 2)) * 60 + Number(start.slice(3)) && /^\d{2}:\d{2}$/.test(start)) {
      slots.push({court, start, end: `${String(Math.floor(endMinutes / 60)).padStart(2, '0')}:${String(endMinutes % 60).padStart(2, '0')}`, state});
    }
  }
  const scaleBars = Array.from(document.querySelectorAll(
    '.dhx_cal_header .dhx_scale_bar:not(.dhx_second_scale_bar)'
  ))
    .filter(visible);
  for (const heading of scaleBars) addCourt((heading.innerText || '').trim());
  for (const event of Array.from(document.querySelectorAll('.dhx_cal_event')).filter(visible)) {
    const label = event.getAttribute('aria-label') || '';
    const match = label.match(/Start date:\s*(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})\s+End date:\s*(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})/i);
    if (!match || match[1] !== selectedDate || match[3] !== selectedDate) continue;
    const rect = (event.parentElement || event).getBoundingClientRect();
    const header = scaleBars.length ? scaleBars.reduce((best, item) => {
      const candidate = item.getBoundingClientRect();
      return Math.abs(candidate.left + candidate.width / 2 - (rect.left + rect.width / 2)) <
        Math.abs(best.getBoundingClientRect().left + best.getBoundingClientRect().width / 2 - (rect.left + rect.width / 2))
        ? item : best;
    }, scaleBars[0]) : null;
    const court = header ? (header.innerText || '').trim() : '';
    const explicitState = label.match(/;\s*(.*?)\s*$/)?.[1];
    const state = explicitState ? stateOf(explicitState) : '';
    if (court) slots.push({court, start:match[2], end:match[4], state});
  }
  const table = Array.from(document.querySelectorAll('table.reservation'))
    .filter(visible).find(candidate => !candidate.querySelector('td.terrainTxt'));
  if (table) {
    const headings = Array.from(table.querySelectorAll('thead th')).filter(visible).slice(1)
      .map(cell => (cell.innerText || '').trim());
    for (const court of headings) addCourt(court);
    for (const row of Array.from(table.querySelectorAll('tbody tr')).filter(visible)) {
      const rowText = (row.querySelector('th')?.innerText || '').trim();
      const times = rowText.match(/(\d{2}:\d{2})\s*[-–]\s*(\d{2}:\d{2})/);
      if (!times) continue;
      const rowCells = Array.from(row.querySelectorAll('td')).filter(visible);
      rowCells.forEach((cell, index) => {
        const court = headings[index];
        const text = (cell.innerText || '').trim();
        const state = /notallowed/i.test(cell.className) ? 'unknown' : stateOf(text);
        if (court) slots.push({court, start:times[1], end:times[2], state});
      });
    }
  }
  const loading = /\b(chargement en cours|loading(?:\.\.\.)?)\b/i.test(body?.innerText || '');
  const authentication_visible = /captcha|verify you are human|login required|log in to continue|sign in to continue/i.test(body?.innerText || '');
  const empty_grid = !loading && courts.length > 0 && slots.length === 0 &&
    /aucun créneau|no availability|no available slots/i.test(body?.innerText || '');
  return {view: dateLabel ? 'booking' : 'unknown', date: selectedDate, activity, courts, slots,
    loading, authentication_visible, empty_grid};
}
"""

_PLUGIN_ACTIVITY_CONTROL_SCRIPT = r"""
() => {
  const visible = element => {
    const rect = element.getBoundingClientRect();
    if (!rect.width || !rect.height) return false;
    for (let current = element; current; current = current.parentElement) {
      const style = getComputedStyle(current);
      if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0 ||
          current.getAttribute('aria-hidden') === 'true') return false;
    }
    return true;
  };
  const controls = Array.from(document.querySelectorAll('select'));
  const matches = controls.flatMap((control, index) => {
    if (!visible(control)) return [];
    const option = Array.from(control.options).find(candidate => {
      const label = (candidate.innerText || '').trim().replace(/\s+/g, ' ');
      return label.split(/\s+-\s+/)[0].trim().toLocaleLowerCase() === 'padel';
    });
    return option ? [{index, label: option.innerText.trim(), selected: option.selected}] : [];
  });
  if (matches.length !== 1) {
    return {status: matches.length ? 'ambiguous' : 'missing', index: -1, label: '', selected: false};
  }
  return {status: 'ok', ...matches[0]};
}
"""

_PLUGIN_NEXT_CONTROL_SCRIPT = r"""
() => {
  const visible = element => {
    const rect = element.getBoundingClientRect();
    if (!rect.width || !rect.height) return false;
    for (let current = element; current; current = current.parentElement) {
      const style = getComputedStyle(current);
      if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0 ||
          current.getAttribute('aria-hidden') === 'true') return false;
    }
    return true;
  };
  const controls = Array.from(document.querySelectorAll(
    '.header_date button, .header_date a, .header_date [role="button"]'
  )).filter(visible).filter(element => {
    const label = [element.innerText, element.getAttribute('aria-label'), element.title]
      .filter(Boolean).join(' ').toLocaleLowerCase();
    return /next|following|demain|suivant|siguiente|›|→|chevron_right/.test(label);
  });
  if (controls.length > 1) return '!ambiguous';
  if (!controls.length) return '';
  const element = controls[0];
  const label = element.getAttribute('aria-label');
  if (label) return `${element.tagName.toLocaleLowerCase()}[aria-label=${JSON.stringify(label)}]`;
  const title = element.title;
  if (title) return `${element.tagName.toLocaleLowerCase()}[title=${JSON.stringify(title)}]`;
  const text = (element.innerText || '').trim();
  return text ? `${element.tagName.toLocaleLowerCase()}:has-text(${JSON.stringify(text)})` : '';
}
"""

_PLUGIN_COOKIE_CONTROL_SCRIPT = r"""
() => {
  const visible = element => {
    const rect = element.getBoundingClientRect();
    if (!rect.width || !rect.height) return false;
    for (let current = element; current; current = current.parentElement) {
      const style = getComputedStyle(current);
      if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0 ||
          current.getAttribute('aria-hidden') === 'true') return false;
    }
    return true;
  };
  const controls = Array.from(document.querySelectorAll('button, input[type="button"], [role="button"]'))
    .filter(visible).filter(element => {
      const label = [element.innerText, element.value, element.getAttribute('aria-label'), element.title]
        .filter(Boolean).join(' ').toLocaleLowerCase();
      return /decline|reject|refuser|refuse/.test(label);
    });
  if (controls.length > 1) return '!ambiguous';
  if (!controls.length) return '';
  const element = controls[0];
  for (const attribute of ['aria-label', 'value', 'title']) {
    const value = element.getAttribute(attribute);
    if (value) return `${element.tagName.toLocaleLowerCase()}[${attribute}=${JSON.stringify(value)}]`;
  }
  const text = (element.innerText || '').trim();
  return text ? `${element.tagName.toLocaleLowerCase()}:has-text(${JSON.stringify(text)})` : '';
}
"""


class PluginBrowserError(PluginSourceError):
    """Raised when the visible public Plugin diary cannot be parsed safely."""

    def __init__(self, message: str) -> None:
        super().__init__(message[:160])


class _PluginLocator(Protocol):
    def count(self) -> int: ...

    def is_visible(self) -> bool: ...

    def click(self) -> None: ...

    def nth(self, index: int) -> "_PluginLocator": ...

    def select_option(self, *, label: str) -> object: ...


class _PluginPage(Protocol):
    def goto(self, url: str, *, wait_until: str, timeout: int) -> object: ...

    def locator(self, selector: str) -> _PluginLocator: ...

    def wait_for_timeout(self, timeout: int) -> None: ...

    def evaluate(self, expression: str, arg: object = None) -> object: ...

    def close(self) -> None: ...


class _PluginContext(Protocol):
    def new_page(self) -> _PluginPage: ...

    def close(self) -> None: ...


class _PluginBrowser(Protocol):
    def __enter__(self) -> Self: ...

    def __exit__(self, *args: object) -> None: ...

    def new_context(self) -> _PluginContext: ...


def _visible_locator(page: _PluginPage, selector: str) -> _PluginLocator:
    locator = page.locator(selector)
    if locator.count() != 1 or not locator.is_visible():
        raise PluginBrowserError("visible Plugin date control was not found")
    return locator


def _decline_optional_cookies(page: _PluginPage) -> None:
    selector = page.evaluate(_PLUGIN_COOKIE_CONTROL_SCRIPT)
    if selector is None or selector == "":
        return
    if selector == "!ambiguous":
        raise PluginBrowserError("visible optional-cookie decline control is ambiguous")
    if not isinstance(selector, str):
        raise PluginBrowserError("visible optional-cookie control is invalid")
    _visible_locator(page, selector).click()


def _select_plugin_activity(page: _PluginPage, timeout_ms: int) -> None:
    previous_diary: tuple[object, object, object, object] | None = None
    for _ in range(max(1, timeout_ms // 100)):
        payload = _mapping(
            page.evaluate(_PLUGIN_ACTIVITY_CONTROL_SCRIPT), "visible Plugin activity"
        )
        status = payload.get("status")
        if status == "ok":
            raw_index = payload.get("index")
            label = payload.get("label")
            selected = payload.get("selected")
            if (
                type(raw_index) is not int
                or raw_index < 0
                or not isinstance(label, str)
                or not label.strip()
                or type(selected) is not bool
            ):
                raise PluginBrowserError("visible Plugin activity control has an invalid response")
            if selected:
                return
            diary = _mapping(page.evaluate(_PLUGIN_VISIBLE_DOM_SCRIPT), "visible DOM")
            current_diary = (
                diary.get("view"),
                diary.get("date"),
                diary.get("courts"),
                diary.get("slots"),
            )
            if (
                diary.get("view") == "booking"
                and isinstance(diary.get("date"), str)
                and isinstance(diary.get("courts"), list)
                and diary.get("courts")
                and isinstance(diary.get("slots"), list)
                and (diary.get("slots") or diary.get("empty_grid") is True)
            ):
                if current_diary == previous_diary:
                    locator = page.locator("select").nth(raw_index)
                    if locator.count() != 1 or not locator.is_visible():
                        raise PluginBrowserError(
                            "visible Plugin Padel activity control was not found"
                        )
                    locator.select_option(label=label)
                    return
                previous_diary = current_diary
            else:
                previous_diary = None
        if status == "ambiguous":
            raise PluginBrowserError("visible Plugin Padel activity control is ambiguous")
        if status not in {"missing", "ok"}:
            raise PluginBrowserError("visible Plugin activity control has an invalid response")
        page.wait_for_timeout(100)
    raise PluginBrowserError("visible Plugin Padel activity control was not found")


def _plugin_grid_ready(dom: Mapping[str, object]) -> bool:
    courts, slots = dom.get("courts"), dom.get("slots")
    if not isinstance(courts, list) or not courts or not isinstance(slots, list):
        return False
    court_labels = cast(list[object], courts)
    if not all(isinstance(court, str) and court for court in court_labels):
        return False
    if dom.get("empty_grid") is True:
        return not slots
    if not slots:
        return False
    intervals: dict[tuple[str, str], set[str]] = {}
    for slot in cast(list[object], slots):
        if not isinstance(slot, Mapping):
            return False
        slot_dom = cast(Mapping[str, object], slot)
        start, end, court = slot_dom.get("start"), slot_dom.get("end"), slot_dom.get("court")
        if not all(isinstance(value, str) for value in (start, end, court)):
            return False
        intervals.setdefault((cast(str, start), cast(str, end)), set()).add(cast(str, court))
    return bool(intervals) and all(
        value == set(cast(list[str], court_labels)) for value in intervals.values()
    )


def _wait_for_plugin_date(
    page: _PluginPage,
    requested_date: date,
    timeout_ms: int,
    *,
    expected_activity: str = "Padel",
) -> object:
    previous_ready_dom: dict[str, object] | None = None
    wrong_activity_observed = False
    for _ in range(max(1, timeout_ms // 100)):
        try:
            payload = page.evaluate(_PLUGIN_VISIBLE_DOM_SCRIPT)
        except Exception as error:
            if not _is_documented_browser_error(error):
                raise
            previous_ready_dom = None
            page.wait_for_timeout(100)
            continue
        dom = _mapping(payload, "visible DOM")
        if dom.get("authentication_visible") is True:
            return payload
        if (
            dom.get("view") == "booking"
            and dom.get("date") == requested_date.isoformat()
            and isinstance(dom.get("activity"), str)
            and dom.get("activity")
            and dom.get("activity") != expected_activity
        ):
            wrong_activity_observed = True
        if (
            dom.get("view") == "booking"
            and dom.get("date") == requested_date.isoformat()
            and dom.get("activity") == expected_activity
            and dom.get("loading") is False
            and _plugin_grid_ready(dom)
        ):
            current_dom = dict(dom)
            if current_dom == previous_ready_dom:
                return payload
            previous_ready_dom = current_dom
        else:
            previous_ready_dom = None
        page.wait_for_timeout(100)
    if wrong_activity_observed:
        raise PluginBrowserError("selected activity does not match expected activity")
    raise PluginBrowserError("timed out waiting for the requested Plugin date")


def _parse_plugin_observations(
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
        raise PluginBrowserError(str(error)) from error


class PluginBrowserConnector:
    def __init__(
        self,
        sources: Sequence[PluginSource],
        *,
        browser_factory: BrowserFactory = default_browser_factory,
        timeout_ms: int = _PLUGIN_TIMEOUT_MS,
    ) -> None:
        self._sources = {source.location_id: source for source in sources}
        self._browser_factory = browser_factory
        self._timeout_ms = timeout_ms
        self._browser: _PluginBrowser | None = None

    def open(self) -> None:
        if self._browser is not None:
            return
        session = self._browser_factory()
        try:
            browser = session.__enter__()
        except BaseException:
            session.__exit__(*sys.exc_info())
            raise
        self._browser = cast(_PluginBrowser, browser)

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
            raise PluginSourceError("requested date window is invalid")
        source = self._sources.get(location.location_id)
        if source is None:
            raise PluginSourceError("no source metadata for location")
        if source.status == "unavailable":
            run = AvailabilityRun(
                run_id,
                location.location_id,
                "plugin_browser",
                source.booking_url,
                window_start.isoformat(),
                window_end.isoformat(),
                (window_end - window_start).days,
                collected_at,
                "unavailable",
                "public Plugin booking diary is unavailable",
            )
            return AvailabilityResult(run, ())
        observations: list[BrowserSlotObservation] = []
        try:
            self.open()
            browser = self._browser
            if browser is None:
                raise PluginBrowserError("browser session is not running")
            context = browser.new_context()
            try:
                page = context.new_page()
                try:
                    page.goto(source.booking_url, wait_until="commit", timeout=self._timeout_ms)
                    _decline_optional_cookies(page)
                    _select_plugin_activity(page, self._timeout_ms)
                    current_date = window_start
                    payload = _wait_for_plugin_date(
                        page, current_date, self._timeout_ms, expected_activity="Padel"
                    )
                    while current_date < window_end:
                        observations.extend(parse_plugin_dom(payload, current_date))
                        current_date += timedelta(days=1)
                        if current_date < window_end:
                            selector = page.evaluate(_PLUGIN_NEXT_CONTROL_SCRIPT)
                            if selector == "!ambiguous":
                                raise PluginBrowserError(
                                    "visible Plugin next-day control is ambiguous"
                                )
                            if not isinstance(selector, str) or not selector:
                                raise PluginBrowserError(
                                    "visible Plugin next-day control was not found"
                                )
                            _visible_locator(page, selector).click()
                            payload = _wait_for_plugin_date(
                                page, current_date, self._timeout_ms, expected_activity="Padel"
                            )
                finally:
                    page.close()
            finally:
                context.close()
        except (PluginBrowserError, PluginSourceError):
            self.close()
            raise
        except Exception as error:
            self.close()
            if _is_documented_browser_error(error):
                raise PluginBrowserError("browser navigation or extraction failed") from error
            raise
        finally:
            self.close()

        slots = _parse_plugin_observations(
            tuple(observations),
            location_id=location.location_id,
            run_id=run_id,
            window_start=window_start,
            window_end=window_end,
        )
        run = AvailabilityRun(
            run_id,
            location.location_id,
            "plugin_browser",
            source.booking_url,
            window_start.isoformat(),
            window_end.isoformat(),
            (window_end - window_start).days,
            collected_at,
            "success",
            None,
        )
        return AvailabilityResult(run, slots)


PluginBrowserConnectorFactory = Callable[[Sequence[PluginSource]], PluginBrowserConnector]


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise PluginBrowserError(f"{field} has an invalid shape")
    return cast(Mapping[str, object], value)


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PluginBrowserError(f"{field} must be nonempty text")
    return value.strip()


def _zurich_wall_time(local_date: date, local_time: time) -> datetime:
    wall_time = datetime.combine(local_date, local_time)
    first = wall_time.replace(tzinfo=_ZURICH, fold=0)
    second = wall_time.replace(tzinfo=_ZURICH, fold=1)
    if first.utcoffset() != second.utcoffset():
        raise PluginBrowserError("slot time is ambiguous in Europe/Zurich")
    return first


def parse_plugin_dom(
    payload: object,
    requested_date: date,
    *,
    expected_activity: str = "Padel",
) -> tuple[BrowserSlotObservation, ...]:
    """Validate and normalize the sanitized visible Plugin diary payload."""
    dom = _mapping(payload, "visible DOM")
    if set(dom) != _PAYLOAD_FIELDS:
        raise PluginBrowserError("visible DOM has invalid payload fields")
    if dom["view"] != "booking":
        raise PluginBrowserError("visible booking view was not found")
    selected_date = _text(dom["date"], "date")
    try:
        parsed_date = date.fromisoformat(selected_date)
    except ValueError as error:
        raise PluginBrowserError("selected date is not ISO format") from error
    if parsed_date != requested_date or selected_date != requested_date.isoformat():
        raise PluginBrowserError("selected date does not match requested date")
    activity = _text(dom["activity"], "activity")
    if "captcha" in activity.casefold():
        raise PluginBrowserError("visible CAPTCHA text blocks the public page")
    if activity != expected_activity:
        raise PluginBrowserError("selected activity does not match expected activity")
    if type(dom["loading"]) is not bool or type(dom["authentication_visible"]) is not bool:
        raise PluginBrowserError("loading or authentication state is invalid")
    if dom["loading"]:
        raise PluginBrowserError("visible diary is still loading")
    if dom["authentication_visible"]:
        raise PluginBrowserError("authentication or CAPTCHA is visible")
    if type(dom["empty_grid"]) is not bool:
        raise PluginBrowserError("empty-grid state is invalid")

    raw_courts = dom["courts"]
    if not isinstance(raw_courts, list) or not raw_courts:
        raise PluginBrowserError("visible courts are missing")
    courts = [_text(court, "court") for court in cast(list[object], raw_courts)]
    if len(set(courts)) != len(courts):
        raise PluginBrowserError("visible courts contain duplicates")
    raw_slots = dom["slots"]
    if not isinstance(raw_slots, list):
        raise PluginBrowserError("visible slots are missing")
    if dom["empty_grid"]:
        if raw_slots:
            raise PluginBrowserError("empty grid contains slots")
        return ()
    if not raw_slots:
        raise PluginBrowserError("empty grid is not explicitly marked")

    observations: list[BrowserSlotObservation] = []
    keys: set[tuple[str, str, str]] = set()
    interval_courts: dict[tuple[str, str], set[str]] = {}
    for item in cast(list[object], raw_slots):
        slot = _mapping(item, "visible slot")
        if set(slot) != _SLOT_FIELDS:
            if "state" not in slot:
                raise PluginBrowserError("visible slot state is missing")
            raise PluginBrowserError("visible slot has invalid fields")
        court = _text(slot["court"], "court")
        if court not in courts:
            raise PluginBrowserError("slot references an unlisted court")
        start_text = _text(slot["start"], "time")
        end_text = _text(slot["end"], "time")
        if (
            re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", start_text) is None
            or re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", end_text) is None
        ):
            raise PluginBrowserError("slot time must use valid HH:MM format")
        start_time, end_time = time.fromisoformat(start_text), time.fromisoformat(end_text)
        start_local = _zurich_wall_time(requested_date, start_time)
        end_local = _zurich_wall_time(requested_date, end_time)
        if end_local.astimezone(UTC) <= start_local.astimezone(UTC):
            raise PluginBrowserError("slot duration must be positive")
        key = (court, start_text, end_text)
        if key in keys:
            raise PluginBrowserError("visible slots contain duplicates")
        keys.add(key)
        interval = (start_text, end_text)
        courts_in_interval = interval_courts.setdefault(interval, set())
        if court in courts_in_interval:
            raise PluginBrowserError("visible slot matrix has a duplicate court interval")
        courts_in_interval.add(court)
        raw_state = _text(slot["state"], "state").casefold()
        if raw_state in _AVAILABLE:
            status = "available"
        elif raw_state in _UNAVAILABLE:
            status = "unavailable"
        elif raw_state in _AMBIGUOUS:
            status = "unknown"
        else:
            raise PluginBrowserError("slot state is unrecognized")
        observations.append(
            BrowserSlotObservation(
                None,
                court,
                start_local.isoformat(timespec="seconds"),
                end_local.isoformat(timespec="seconds"),
                status,
            )
        )
    if any(courts_in_interval != set(courts) for courts_in_interval in interval_courts.values()):
        raise PluginBrowserError("visible slot matrix is missing a court")
    return tuple(observations)
