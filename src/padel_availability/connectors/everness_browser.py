import re
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, time, timedelta
from itertools import pairwise
from typing import Literal, cast
from zoneinfo import ZoneInfo

from ..availability import AvailabilitySlot
from .everness import EvernessSourceError
from .playtomic_browser import (
    BrowserSlotObservation,
    default_browser_factory,
    parse_browser_observations,
)

__all__ = [
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
}
_EVERNESS_BLOCK_MARKERS = ("captcha", "log in", "login", "sign in", "access denied")
_EVERNESS_LOADING_MARKERS = ("loading", "chargement", "please wait", "updating")
_EVERNESS_VISIBLE_DOM_SCRIPT = r"""
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
        style: cell.getAttribute('style') || ''
      }));
      rows.push({time: text(hour), cells});
    }
  }
  const visibleText = body.innerText || '';
  const normalizedText = visibleText.replace(/\s+/g, ' ').trim().toLowerCase();
  const loading = normalizedText.includes('loading') || normalizedText.includes('chargement') ||
    normalizedText.includes('please wait') || normalizedText.includes('updating') ||
    Array.from(body.querySelectorAll('.loading, [aria-busy="true"]')).some(visible);
  const fingerprintInput = JSON.stringify({
    dateLabel,
    courts,
    rows: rows.map(row => [row.time, row.cells.map(cell => [cell.class, cell.style])])
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


def _local_datetime(local_date: date, local_time: time, field: str) -> datetime:
    wall_time = datetime.combine(local_date, local_time)
    first = wall_time.replace(tzinfo=_EVERNESS_ZURICH, fold=0)
    second = wall_time.replace(tzinfo=_EVERNESS_ZURICH, fold=1)
    if first.utcoffset() != second.utcoffset():
        raise EvernessBrowserError(f"{field} is ambiguous in Europe/Zurich")
    return first


def _parse_date_label(label: str) -> date:
    match = re.fullmatch(r"([0-9]{1,2}) ([A-Za-z]{3}) ([0-9]{4})", label)
    if match is None or match.group(2).title() not in _EVERNESS_MONTHS:
        raise EvernessBrowserError("visible DOM has an invalid date label")
    try:
        return date(
            int(match.group(3)),
            _EVERNESS_MONTHS[match.group(2).title()],
            int(match.group(1)),
        )
    except ValueError as error:
        raise EvernessBrowserError("visible DOM has an invalid date label") from error


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


def parse_everness_dom(payload: object, requested_date: date) -> tuple[BrowserSlotObservation, ...]:
    """Parse the small visible-DOM payload returned by the Everness booking page."""
    dom = _dom_mapping(payload)
    visible_text = dom.get("visible_text")
    if not isinstance(visible_text, str):
        raise EvernessBrowserError("visible DOM is missing visible text")
    normalized_text = " ".join(visible_text.split()).casefold()
    if any(marker in normalized_text for marker in _EVERNESS_BLOCK_MARKERS):
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
        if len(cells) != len(court_labels):
            raise EvernessBrowserError("visible booking grid has a partial matrix")
        parsed_rows.append((row_time, cells))

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
