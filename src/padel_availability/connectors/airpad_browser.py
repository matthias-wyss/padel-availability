import re
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, time, timedelta
from typing import Protocol, cast
from zoneinfo import ZoneInfo

from ..availability import AvailabilitySlot
from ..models import ModelError
from .airpad import AirpadSourceError
from .playtomic_browser import (
    BrowserSlotObservation,
    parse_browser_observations,
)

_AIRPAD_ZURICH = ZoneInfo("Europe/Zurich")
_AIRPAD_BLOCK_MARKERS = (
    "captcha",
    "verify you are human",
    "sign in",
    "login",
    "access denied",
)
_AIRPAD_EMPTY_MARKERS = (
    "aucun créneau disponible",
    "no available slots",
    "no availability",
)


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
  const activeDate = dateButtons.find(element =>
    element.getAttribute('aria-current') === 'date' ||
    (element.getAttribute('class') || '').split(/\s+/).includes('active')
  ) || dateButtons[0];
  const rows = Array.from(body.querySelectorAll('.playground-slot')).filter(visible);
  const slots = [];
  const emptyRows = [];
  for (const row of rows) {
    const title = row.querySelector('.section-title');
    const court = title && visible(title) ? text(title) : null;
    const cards = Array.from(row.querySelectorAll('.info-playground > *')).filter(element =>
      visible(element) && (
        (element.getAttribute('class') || '').split(/\s+/).includes('duration-card') ||
        /Start\s+\d{2}:\d{2}/i.test(text(element)) || /\d+\s*min/i.test(text(element))
      )
    );
    const empty = Boolean(row.querySelector('.empty_playground')) &&
      visible(row.querySelector('.empty_playground'));
    if (empty) emptyRows.push(court);
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
  const calendar = Array.from(body.querySelectorAll('.calendar-block')).some(visible);
  return {
    view: calendar && dateButtons.length > 0 ? 'booking' : 'unknown',
    date: activeDate ? dateFromLabel(activeDate.getAttribute('aria-label') || '') : '',
    slots,
    empty_grid: rows.length > 0 && slots.length === 0,
    empty_rows: emptyRows,
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


def parse_airpad_dom(payload: object, requested_date: date) -> tuple[BrowserSlotObservation, ...]:
    """Parse the small visible-DOM payload returned by the AIRPAD iframe."""
    dom = _dom_mapping(payload)
    visible_text = dom.get("visible_text")
    if not isinstance(visible_text, str):
        raise AirpadBrowserError("visible DOM is missing visible text")
    normalized_text = " ".join(visible_text.split()).casefold()
    if any(marker in normalized_text for marker in _AIRPAD_BLOCK_MARKERS):
        raise AirpadBrowserError("public AIRPAD page is blocked by login or CAPTCHA")
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
    if observations:
        return observations
    if dom.get("empty_grid") is True or dom.get("empty_rows"):
        return ()
    if any(marker in normalized_text for marker in _AIRPAD_EMPTY_MARKERS):
        return ()
    raise AirpadBrowserError("visible AIRPAD booking view has no explicit availability state")


class _AirpadPage(Protocol):
    def evaluate(self, expression: str, arg: object = None) -> object: ...


def extract_airpad_observations(
    page: _AirpadPage, requested_date: date
) -> tuple[BrowserSlotObservation, ...]:
    return parse_airpad_dom(page.evaluate(_AIRPAD_VISIBLE_DOM_SCRIPT), requested_date)


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
