import re
from collections.abc import Mapping
from datetime import UTC, date, datetime, time
from typing import cast
from zoneinfo import ZoneInfo

from .playtomic_browser import BrowserSlotObservation

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
    return state;
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
    const stateText = (cell.matches('td.terrainTxt')
      ? cell.querySelector('.event-time .start')?.innerText || '' : cell.innerText || '').trim();
    const classNames = cell.className.toLocaleLowerCase();
    let state = stateOf(stateText);
    if (/notallowed/.test(classNames)) state = 'unknown';
    else if (/^\d{2}:\d{2}$/.test(stateText)) state = 'unavailable';
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
    if (state && endMinutes > Number(start.slice(0, 2)) * 60 + Number(start.slice(3)) && /^\d{2}:\d{2}$/.test(start)) {
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


class PluginBrowserError(ValueError):
    """Raised when the visible public Plugin diary cannot be parsed safely."""

    def __init__(self, message: str) -> None:
        super().__init__(message[:160])


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
        if re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", start_text) is None or re.fullmatch(
            r"(?:[01]\d|2[0-3]):[0-5]\d", end_text
        ) is None:
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
