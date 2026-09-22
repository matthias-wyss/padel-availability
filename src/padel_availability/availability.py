from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from .models import ModelError, _literal, _optional_text, _text, _url, _utc_timestamp


AvailabilityRunStatus = Literal["success", "error", "unavailable"]
SlotStatus = Literal["available", "unavailable", "unknown"]
SnapshotStatus = Literal["success", "stale", "error", "unavailable"]

_AVAILABILITY_RUN_STATUSES = {"success", "error", "unavailable"}
_SLOT_STATUSES = {"available", "unavailable", "unknown"}
_SNAPSHOT_STATUSES = {"success", "stale", "error", "unavailable"}
_ZURICH = ZoneInfo("Europe/Zurich")


def _date_value(value: object, field: str) -> date:
    if not isinstance(value, str) or not value.strip():
        raise ModelError(f"{field} must be an ISO-8601 date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ModelError(f"{field} must be an ISO-8601 date") from error
    if parsed.isoformat() != value:
        raise ModelError(f"{field} must be an ISO-8601 date")
    return parsed


def _timestamp_value(value: str, field: str) -> datetime:
    _utc_timestamp(value, field)
    return datetime.fromisoformat(value[:-1] + "+00:00")


def local_window(now: datetime, horizon_days: int) -> tuple[date, date]:
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ModelError("now must be a timezone-aware datetime")
    if not isinstance(horizon_days, int) or horizon_days <= 0:
        raise ModelError("horizon_days must be a positive integer")
    window_start = now.astimezone(_ZURICH).date()
    return window_start, window_start + timedelta(days=horizon_days)


def local_to_utc(value: str) -> str:
    value = _text(value, "timestamp")
    try:
        parsed = datetime.fromisoformat(
            value[:-1] + "+00:00" if value.endswith("Z") else value
        )
    except ValueError as error:
        raise ModelError("timestamp must be an offset-aware ISO-8601 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ModelError("timestamp must be an offset-aware ISO-8601 timestamp")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class AvailabilityRun:
    run_id: str
    location_id: str
    connector: str
    source_url: str
    window_start: str
    window_end: str
    horizon_days: int
    collected_at: str
    status: AvailabilityRunStatus
    error: str | None

    def __post_init__(self) -> None:
        for field in ("run_id", "location_id", "connector"):
            _text(getattr(self, field), field)
        _url(self.source_url, "source_url")
        window_start = _date_value(self.window_start, "window_start")
        window_end = _date_value(self.window_end, "window_end")
        if window_end <= window_start:
            raise ModelError("window_end must be after window_start")
        if not isinstance(self.horizon_days, int) or self.horizon_days <= 0:
            raise ModelError("horizon_days must be a positive integer")
        if window_end - window_start != timedelta(days=self.horizon_days):
            raise ModelError("horizon_days must match the window length")
        _utc_timestamp(self.collected_at, "collected_at")
        _literal(self.status, "status", _AVAILABILITY_RUN_STATUSES)
        _optional_text(self.error, "error")
        if self.status == "success" and self.error is not None:
            raise ModelError("error must be null for success")
        if self.status != "success" and (self.error is None or not self.error.strip()):
            raise ModelError("error is required for error and unavailable statuses")


@dataclass(frozen=True, slots=True)
class AvailabilitySlot:
    run_id: str
    location_id: str
    slot_key: str
    external_id: str | None
    court_label: str | None
    starts_at: str
    ends_at: str
    timezone: str
    status: SlotStatus

    def __post_init__(self) -> None:
        for field in ("run_id", "location_id", "slot_key", "timezone"):
            _text(getattr(self, field), field)
        _optional_text(self.external_id, "external_id")
        if self.external_id is not None and not self.external_id.strip():
            raise ModelError("external_id must be a non-empty string or null")
        _optional_text(self.court_label, "court_label")
        starts_at = _timestamp_value(self.starts_at, "starts_at")
        ends_at = _timestamp_value(self.ends_at, "ends_at")
        if ends_at <= starts_at:
            raise ModelError("ends_at must be after starts_at")
        _literal(self.status, "status", _SLOT_STATUSES)


@dataclass(frozen=True, slots=True)
class AvailabilityResult:
    run: AvailabilityRun
    slots: tuple[AvailabilitySlot, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.run, AvailabilityRun):
            raise ModelError("run must be an AvailabilityRun")
        if not isinstance(self.slots, tuple) or not all(
            isinstance(slot, AvailabilitySlot) for slot in self.slots
        ):
            raise ModelError("slots must contain AvailabilitySlot values")
        if any(
            slot.run_id != self.run.run_id or slot.location_id != self.run.location_id
            for slot in self.slots
        ):
            raise ModelError("slots must belong to the result run")


@dataclass(frozen=True, slots=True)
class AvailabilitySnapshot:
    location_id: str
    latest_run: AvailabilityRun
    slots: tuple[AvailabilitySlot, ...]
    status: SnapshotStatus
    last_success_at: str | None

    def __post_init__(self) -> None:
        _text(self.location_id, "location_id")
        if not isinstance(self.latest_run, AvailabilityRun):
            raise ModelError("latest_run must be an AvailabilityRun")
        if self.latest_run.location_id != self.location_id:
            raise ModelError("latest_run must belong to location_id")
        if not isinstance(self.slots, tuple) or not all(
            isinstance(slot, AvailabilitySlot) for slot in self.slots
        ):
            raise ModelError("slots must contain AvailabilitySlot values")
        if any(slot.location_id != self.location_id for slot in self.slots):
            raise ModelError("slots must belong to location_id")
        _literal(self.status, "status", _SNAPSHOT_STATUSES)
        if self.last_success_at is not None:
            _utc_timestamp(self.last_success_at, "last_success_at")
