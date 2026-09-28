import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from ..models import (
    ModelError,
)
from ..models import (
    validate_text as _text,
)
from ..models import (
    validate_url as _url,
)
from ..models import (
    validate_utc_timestamp as _utc_timestamp,
)

PadelFirstStatus = Literal["public", "unavailable"]

PADEL_FIRST_LOCATION_IDS: frozenset[str] = frozenset({"vernier"})
PADEL_FIRST_BOOKING_URL = "https://padelfirst.ss-r.ch/court-vernier/"
PADEL_FIRST_SLOT_MINUTES = 90


class PadelFirstSourceError(ValueError):
    """Raised when a Padel First source or manifest is unusable."""


@dataclass(frozen=True, slots=True)
class PadelFirstSource:
    location_id: str
    booking_url: str
    checked_at: str
    status: PadelFirstStatus

    def __post_init__(self) -> None:
        _text(self.location_id, "location_id")
        _url(self.booking_url, "booking_url")
        _utc_timestamp(self.checked_at, "checked_at")
        if self.status not in {"public", "unavailable"}:
            raise ModelError("status has invalid value")


def _source_error(message: str) -> PadelFirstSourceError:
    return PadelFirstSourceError(message[:160])


def load_padelfirst_sources(path: Path) -> tuple[PadelFirstSource, ...]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise _source_error("could not read Padel First source manifest") from error

    if not isinstance(raw, dict):
        raise _source_error("source manifest must contain format_version and sources")
    manifest = cast(dict[str, object], raw)
    if set(manifest) != {"format_version", "sources"}:
        raise _source_error("source manifest must contain format_version and sources")
    if manifest["format_version"] != 1 or isinstance(manifest["format_version"], bool):
        raise _source_error("source manifest format_version must be 1")
    raw_sources_value = manifest["sources"]
    if not isinstance(raw_sources_value, list):
        raise _source_error("source manifest sources must be a list")
    raw_sources = cast(list[object], raw_sources_value)
    if len(raw_sources) != len(PADEL_FIRST_LOCATION_IDS):
        raise _source_error("source manifest must contain exactly one row")

    sources: list[PadelFirstSource] = []
    for raw_row in raw_sources:
        if not isinstance(raw_row, dict):
            raise _source_error("source row has invalid fields")
        row = cast(dict[str, object], raw_row)
        if set(row) != {"location_id", "booking_url", "checked_at", "status"}:
            raise _source_error("source row has invalid fields")
        if row["booking_url"] != PADEL_FIRST_BOOKING_URL:
            raise _source_error("source row must use the common Padel First booking URL")
        try:
            source = PadelFirstSource(
                cast(str, row["location_id"]),
                cast(str, row["booking_url"]),
                cast(str, row["checked_at"]),
                cast(PadelFirstStatus, row["status"]),
            )
        except (ModelError, TypeError) as error:
            raise _source_error("source row failed validation") from error
        sources.append(source)

    location_ids = [source.location_id for source in sources]
    if (
        len(set(location_ids)) != len(location_ids)
        or frozenset(location_ids) != PADEL_FIRST_LOCATION_IDS
    ):
        raise _source_error("source manifest must cover the exact one location once")
    return tuple(sorted(sources, key=lambda source: source.location_id))
