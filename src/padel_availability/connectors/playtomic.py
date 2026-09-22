import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Literal, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from ..availability import (
    AvailabilityResult,
    AvailabilityRun,
    AvailabilitySlot,
    local_to_utc,
)
from ..models import LocationRecord, ModelError, _text, _url, _utc_timestamp


JsonFetcher = Callable[[str], object]
TransportKind = Literal["json", "browser_dom"]
PlaytomicStatus = Literal["public", "unavailable"]

_EXPECTED_LOCATION_IDS = frozenset(
    {
        "padel-station",
        "gva-palexpo",
        "padel-parc-etoy",
        "padel-parc-preverenges",
        "vaudoise-arena",
    }
)
_SLOT_STATUSES = frozenset({"available", "unavailable", "unknown"})
_ZURICH = ZoneInfo("Europe/Zurich")


class PlaytomicSourceError(ValueError):
    """Raised when a public Playtomic source or payload is unusable."""


@dataclass(frozen=True, slots=True)
class PlaytomicSource:
    location_id: str
    booking_url: str
    transport: TransportKind
    availability_url_template: str | None
    checked_at: str
    status: PlaytomicStatus

    def __post_init__(self) -> None:
        _text(self.location_id, "location_id")
        _url(self.booking_url, "booking_url")
        _utc_timestamp(self.checked_at, "checked_at")
        if self.transport not in {"json", "browser_dom"}:
            raise ModelError("transport has invalid value")
        if self.status not in {"public", "unavailable"}:
            raise ModelError("status has invalid value")
        if self.availability_url_template is not None:
            _url(self.availability_url_template, "availability_url_template")
            if (
                self.availability_url_template.count("{window_start}") != 1
                or self.availability_url_template.count("{window_end}") != 1
            ):
                raise ModelError("availability_url_template must contain date placeholders")
        if (
            self.transport == "json"
            and self.status == "public"
            and self.availability_url_template is None
        ):
            raise ModelError("public JSON sources require availability_url_template")
        if (
            self.transport == "browser_dom"
            and self.status == "public"
            and self.availability_url_template is not None
        ):
            raise ModelError("public browser sources must not have availability_url_template")
        if self.status == "unavailable" and self.availability_url_template is not None:
            raise ModelError("unavailable sources must not have availability_url_template")


def _source_error(message: str) -> PlaytomicSourceError:
    return PlaytomicSourceError(message[:160])


def load_playtomic_sources(path: Path) -> tuple[PlaytomicSource, ...]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise _source_error("could not read Playtomic source manifest") from error

    if not isinstance(raw, dict) or set(raw) != {"format_version", "sources"}:
        raise _source_error("source manifest must contain format_version and sources")
    if raw["format_version"] != 1 or isinstance(raw["format_version"], bool):
        raise _source_error("source manifest format_version must be 1")
    if not isinstance(raw["sources"], list):
        raise _source_error("source manifest sources must be a list")
    if len(raw["sources"]) != len(_EXPECTED_LOCATION_IDS):
        raise _source_error("source manifest must contain exactly five rows")

    sources: list[PlaytomicSource] = []
    for row in raw["sources"]:
        if not isinstance(row, dict) or set(row) != {
            "location_id",
            "booking_url",
            "transport",
            "availability_url_template",
            "checked_at",
            "status",
        }:
            raise _source_error("source row has invalid fields")
        try:
            source = PlaytomicSource(
                row["location_id"],
                row["booking_url"],
                row["transport"],
                row["availability_url_template"],
                row["checked_at"],
                row["status"],
            )
        except (ModelError, TypeError) as error:
            raise _source_error("source row failed validation") from error
        sources.append(source)

    location_ids = [source.location_id for source in sources]
    if len(set(location_ids)) != len(location_ids) or set(location_ids) != _EXPECTED_LOCATION_IDS:
        raise _source_error("source manifest must cover the exact five locations once")
    return tuple(sorted(sources, key=lambda source: source.location_id))


def fetch_public_json(url: str, *, timeout: float = 10.0) -> object:
    request = Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "padel-availability/0.1"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except HTTPError as error:
        raise _source_error(f"public source returned HTTP {error.code}") from error
    except (URLError, TimeoutError, OSError) as error:
        raise _source_error("public source request failed") from error
    except (UnicodeError, ValueError) as error:
        raise _source_error("public source returned invalid JSON") from error


def _parse_offset_timestamp(value: object, field: str) -> tuple[datetime, str]:
    if not isinstance(value, str) or not value.strip():
        raise _source_error(f"{field} must be an offset-aware ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as error:
        raise _source_error(f"{field} must be an offset-aware ISO-8601 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _source_error(f"{field} must be an offset-aware ISO-8601 timestamp")

    wall_time = parsed.replace(tzinfo=None)
    first = wall_time.replace(tzinfo=_ZURICH, fold=0)
    second = wall_time.replace(tzinfo=_ZURICH, fold=1)
    if first.utcoffset() != second.utcoffset():
        raise _source_error(f"{field} is ambiguous in Europe/Zurich")
    try:
        normalized = local_to_utc(value)
    except ModelError as error:
        raise _source_error(f"{field} must be an offset-aware ISO-8601 timestamp") from error
    return parsed, normalized


def _slot_key(
    location_id: str,
    court_label: str | None,
    starts_at: str,
    ends_at: str,
    external_id: str | None,
) -> str:
    if external_id is not None:
        return external_id
    value = "\x1f".join((location_id, court_label or "", starts_at, ends_at))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def parse_playtomic_slots(
    payload: object,
    *,
    location_id: str,
    run_id: str,
    window_start: date,
    window_end: date,
) -> tuple[AvailabilitySlot, ...]:
    if not isinstance(payload, dict) or not isinstance(payload.get("slots"), list):
        raise _source_error("payload must contain a slots list")
    if window_end <= window_start:
        raise _source_error("requested date window is invalid")

    slots: dict[str, AvailabilitySlot] = {}
    for index, item in enumerate(payload["slots"]):
        if not isinstance(item, dict):
            raise _source_error(f"slot {index} must be an object")
        required = {"external_id", "court_label", "starts_at", "ends_at", "status"}
        if not required.issubset(item):
            raise _source_error(f"slot {index} is missing required fields")
        external_id = item["external_id"]
        court_label = item["court_label"]
        status = item["status"]
        if external_id is not None and (not isinstance(external_id, str) or not external_id.strip()):
            raise _source_error(f"slot {index} has an invalid external_id")
        if court_label is not None and (not isinstance(court_label, str) or not court_label.strip()):
            raise _source_error(f"slot {index} has an invalid court_label")
        if not isinstance(status, str) or status not in _SLOT_STATUSES:
            raise _source_error(f"slot {index} has an invalid status")

        starts_local, starts_at = _parse_offset_timestamp(
            item["starts_at"], f"slot {index} starts_at"
        )
        _, ends_at = _parse_offset_timestamp(item["ends_at"], f"slot {index} ends_at")
        local_date = starts_local.astimezone(_ZURICH).date()
        if not window_start <= local_date < window_end:
            continue
        key = _slot_key(location_id, court_label, starts_at, ends_at, external_id)
        try:
            slot = AvailabilitySlot(
                run_id,
                location_id,
                key,
                external_id,
                court_label,
                starts_at,
                ends_at,
                "Europe/Zurich",
                status,
            )
        except ModelError as error:
            raise _source_error(f"slot {index} failed validation") from error
        existing = slots.get(key)
        if existing is not None:
            if existing != slot:
                kind = "external_id" if external_id is not None else "slot hash"
                raise _source_error(f"conflicting duplicate {kind}")
            continue
        slots[key] = slot

    return tuple(
        sorted(
            slots.values(),
            key=lambda slot: (slot.starts_at, slot.ends_at, slot.court_label or "", slot.slot_key),
        )
    )


class PlaytomicConnector:
    def __init__(
        self,
        sources: Sequence[PlaytomicSource],
        *,
        fetch_json: JsonFetcher = fetch_public_json,
    ) -> None:
        self._sources = {source.location_id: source for source in sources}
        self._fetch_json = fetch_json

    def collect(
        self,
        location: LocationRecord,
        *,
        run_id: str,
        window_start: date,
        window_end: date,
        collected_at: str,
    ) -> AvailabilityResult:
        source = self._sources.get(location.location_id)
        if source is None:
            raise _source_error("no source metadata for location")
        horizon_days = (window_end - window_start).days
        source_url = source.booking_url
        if source.status == "unavailable":
            run = AvailabilityRun(
                run_id,
                location.location_id,
                "playtomic",
                source_url,
                window_start.isoformat(),
                window_end.isoformat(),
                horizon_days,
                collected_at,
                "unavailable",
                "no public availability feed was verified",
            )
            return AvailabilityResult(run, ())

        template = source.availability_url_template
        if template is None:
            raise _source_error("public source has no availability URL template")
        try:
            source_url = template.format(
                window_start=window_start.isoformat(),
                window_end=window_end.isoformat(),
            )
        except (AttributeError, KeyError, ValueError) as error:
            raise _source_error("public availability URL template is invalid") from error
        slots = parse_playtomic_slots(
            self._fetch_json(source_url),
            location_id=location.location_id,
            run_id=run_id,
            window_start=window_start,
            window_end=window_end,
        )
        run = AvailabilityRun(
            run_id,
            location.location_id,
            "playtomic",
            source_url,
            window_start.isoformat(),
            window_end.isoformat(),
            horizon_days,
            collected_at,
            "success",
            None,
        )
        return AvailabilityResult(run, slots)
