import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from ..models import ModelError
from ..models import validate_literal as _literal
from ..models import validate_text as _text
from ..models import validate_url as _url
from ..models import validate_utc_timestamp as _utc_timestamp

PluginStatus = Literal["public", "unavailable"]

PLUGIN_BOOKING_URLS = {
    "cologny": "https://reservation.cs-cologny.ch/diary",
    "collonge-bellerive": "https://reservation.tccb.ch/diary",
    "crans-vd": "https://tccrans.plugin.ch/user/diary",
    "csu-champel": "https://unige.plugin.ch/",
    "drizia-miremont": "https://tcdrizia.plugin.ch/",
    "fraisiers": "https://tcfraisiers.plugin.ch/?sport=301",
    "gland": "https://tcgland.plugin.ch/user/diary",
    "mies-tannay": "https://tcmt.plugin.ch/user/diary",
}
PLUGIN_LOCATION_IDS = frozenset(PLUGIN_BOOKING_URLS)


class PluginSourceError(ValueError):
    """Raised when a Plugin source or manifest is unusable."""


def _source_error(message: str) -> PluginSourceError:
    return PluginSourceError(message[:160])


@dataclass(frozen=True, slots=True)
class PluginSource:
    location_id: str
    booking_url: str
    checked_at: str
    status: PluginStatus

    def __post_init__(self) -> None:
        try:
            _text(self.location_id, "location_id")
            _url(self.booking_url, "booking_url")
            _utc_timestamp(self.checked_at, "checked_at")
            _literal(self.status, "status", {"public", "unavailable"})
        except (ModelError, TypeError) as error:
            raise _source_error(str(error)) from error


def load_plugin_sources(path: Path) -> tuple[PluginSource, ...]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise _source_error("could not read Plugin source manifest") from error

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
    if len(raw_sources) != len(PLUGIN_LOCATION_IDS):
        raise _source_error("source manifest must contain exactly eight rows")

    sources: list[PluginSource] = []
    for raw_row in raw_sources:
        if not isinstance(raw_row, dict):
            raise _source_error("source row has invalid fields")
        row = cast(dict[str, object], raw_row)
        if set(row) != {"location_id", "booking_url", "checked_at", "status"}:
            raise _source_error("source row has invalid fields")
        try:
            source = PluginSource(
                cast(str, row["location_id"]),
                cast(str, row["booking_url"]),
                cast(str, row["checked_at"]),
                cast(PluginStatus, row["status"]),
            )
        except (PluginSourceError, TypeError) as error:
            raise _source_error("source row failed validation") from error
        if PLUGIN_BOOKING_URLS.get(source.location_id) != source.booking_url:
            raise _source_error("source row must use its exact Plugin booking URL")
        sources.append(source)

    location_ids = [source.location_id for source in sources]
    if (
        len(set(location_ids)) != len(location_ids)
        or frozenset(location_ids) != PLUGIN_LOCATION_IDS
    ):
        raise _source_error("source manifest must cover the exact eight locations once")
    return tuple(sorted(sources, key=lambda source: source.location_id))
