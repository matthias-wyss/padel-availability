from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, Sequence
from zoneinfo import ZoneInfo

from ..availability import AvailabilitySlot, local_to_utc
from ..models import ModelError, _text
from .playtomic import PlaytomicSourceError, _slot_key


BrowserSlotStatus = Literal["available", "unavailable", "unknown"]

_SLOT_STATUSES = {"available", "unavailable", "unknown"}
_ZURICH = ZoneInfo("Europe/Zurich")


def _observation_timestamp(value: object, field: str) -> datetime:
    value = _text(value, field)
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as error:
        raise ModelError(f"{field} must be an offset-aware ISO-8601 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ModelError(f"{field} must be an offset-aware ISO-8601 timestamp")

    wall_time = parsed.replace(tzinfo=None)
    first = wall_time.replace(tzinfo=_ZURICH, fold=0)
    second = wall_time.replace(tzinfo=_ZURICH, fold=1)
    if first.utcoffset() != second.utcoffset():
        raise ModelError(f"{field} is ambiguous in Europe/Zurich")
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
        if not isinstance(self.status, str) or self.status not in _SLOT_STATUSES:
            raise ModelError("status has invalid value")


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
        if not isinstance(observation, BrowserSlotObservation):
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
        if existing is not None:
            if existing != slot:
                kind = "external_id" if observation.external_id is not None else "slot hash"
                raise PlaytomicSourceError(f"conflicting duplicate {kind}")
            continue
        slots[slot.slot_key] = slot

    return tuple(
        sorted(
            slots.values(),
            key=lambda slot: (slot.starts_at, slot.ends_at, slot.court_label or "", slot.slot_key),
        )
    )
