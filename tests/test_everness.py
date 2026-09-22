import json
from pathlib import Path

import pytest

from padel_availability.connectors import (
    EVERNESS_BOOKING_URL,
    EVERNESS_LOCATION_IDS,
    EvernessSource,
    EvernessSourceError,
    load_everness_sources,
)

LOCATION_ID = "everness"
CHECKED_AT = "2026-09-22T00:00:00Z"


def manifest_rows(location_ids: tuple[str, ...] = (LOCATION_ID,)) -> list[dict[str, str]]:
    return [
        {
            "location_id": location_id,
            "booking_url": EVERNESS_BOOKING_URL,
            "checked_at": CHECKED_AT,
            "status": "public",
        }
        for location_id in location_ids
    ]


def write_manifest(path: Path, rows: list[dict[str, str]]) -> None:
    path.write_text(json.dumps({"format_version": 1, "sources": rows}))


def test_load_everness_sources_accepts_exact_one_row(tmp_path: Path) -> None:
    path = tmp_path / "everness_sources.json"
    write_manifest(path, manifest_rows())

    sources = load_everness_sources(path)

    assert sources == (EvernessSource(LOCATION_ID, EVERNESS_BOOKING_URL, CHECKED_AT, "public"),)


def test_load_everness_sources_rejects_missing_or_extra_location(tmp_path: Path) -> None:
    path = tmp_path / "everness_sources.json"

    write_manifest(path, [])
    with pytest.raises(EvernessSourceError):
        load_everness_sources(path)

    write_manifest(path, manifest_rows(("other-location",)))
    with pytest.raises(EvernessSourceError):
        load_everness_sources(path)


def test_load_everness_sources_rejects_duplicate_rows(tmp_path: Path) -> None:
    path = tmp_path / "everness_sources.json"
    write_manifest(path, manifest_rows((LOCATION_ID, LOCATION_ID)))

    with pytest.raises(EvernessSourceError):
        load_everness_sources(path)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("booking_url", "https://example.com/everness"),
        ("checked_at", "2026-09-22T00:00:00+02:00"),
        ("checked_at", "2026-09-22T00:00:00"),
        ("status", "members"),
    ),
)
def test_load_everness_sources_rejects_wrong_url_or_timestamp(
    tmp_path: Path, field: str, value: str
) -> None:
    path = tmp_path / "everness_sources.json"
    rows = manifest_rows()
    rows[0][field] = value
    write_manifest(path, rows)

    with pytest.raises(EvernessSourceError):
        load_everness_sources(path)


def test_everness_constants_are_explicit() -> None:
    assert EVERNESS_LOCATION_IDS == frozenset({"everness"})
    assert EVERNESS_BOOKING_URL == "https://padel.everness.ch/"
