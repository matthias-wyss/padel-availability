import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ..models import ModelError, _text, _url, _utc_timestamp

AirpadStatus = Literal["public", "unavailable"]

AIRPAD_LOCATION_IDS: frozenset[str] = frozenset(
    {
        "airpad-les-acacias",
        "airpad-la-praille",
        "airpad-meyrin",
        "airpad-plan-les-ouates",
    }
)
AIRPAD_LOCATION_LABELS: Mapping[str, str] = {
    "airpad-les-acacias": "LES ACACIAS",
    "airpad-la-praille": "LA PRAILLE",
    "airpad-meyrin": "MEYRIN",
    "airpad-plan-les-ouates": "PLAN-LES-OUATES",
}
_AIRPAD_BOOKING_URL = "https://www.airpad.ch/reserve"


class AirpadSourceError(ValueError):
    """Raised when a public AIRPAD source or manifest is unusable."""


@dataclass(frozen=True, slots=True)
class AirpadSource:
    location_id: str
    booking_url: str
    checked_at: str
    status: AirpadStatus

    def __post_init__(self) -> None:
        _text(self.location_id, "location_id")
        _url(self.booking_url, "booking_url")
        _utc_timestamp(self.checked_at, "checked_at")
        if self.status not in {"public", "unavailable"}:
            raise ModelError("status has invalid value")


def _source_error(message: str) -> AirpadSourceError:
    return AirpadSourceError(message[:160])


def load_airpad_sources(path: Path) -> tuple[AirpadSource, ...]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise _source_error("could not read AIRPAD source manifest") from error

    if not isinstance(raw, dict) or set(raw) != {"format_version", "sources"}:
        raise _source_error("source manifest must contain format_version and sources")
    if raw["format_version"] != 1 or isinstance(raw["format_version"], bool):
        raise _source_error("source manifest format_version must be 1")
    if not isinstance(raw["sources"], list):
        raise _source_error("source manifest sources must be a list")
    if len(raw["sources"]) != len(AIRPAD_LOCATION_IDS):
        raise _source_error("source manifest must contain exactly four rows")

    sources: list[AirpadSource] = []
    for row in raw["sources"]:
        if not isinstance(row, dict) or set(row) != {
            "location_id",
            "booking_url",
            "checked_at",
            "status",
        }:
            raise _source_error("source row has invalid fields")
        if row["booking_url"] != _AIRPAD_BOOKING_URL:
            raise _source_error("source row must use the common AIRPAD booking URL")
        try:
            source = AirpadSource(
                row["location_id"],
                row["booking_url"],
                row["checked_at"],
                row["status"],
            )
        except (ModelError, TypeError) as error:
            raise _source_error("source row failed validation") from error
        sources.append(source)

    location_ids = [source.location_id for source in sources]
    if len(set(location_ids)) != len(location_ids) or set(location_ids) != AIRPAD_LOCATION_IDS:
        raise _source_error("source manifest must cover the exact four locations once")
    return tuple(sorted(sources, key=lambda source: source.location_id))
