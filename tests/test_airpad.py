import json
from pathlib import Path

import pytest

from padel_availability.connectors import (
    AIRPAD_LOCATION_IDS,
    AIRPAD_LOCATION_LABELS,
    AirpadSourceError,
    load_airpad_sources,
)

LOCATION_IDS = (
    "airpad-les-acacias",
    "airpad-la-praille",
    "airpad-meyrin",
    "airpad-plan-les-ouates",
)
BOOKING_URL = "https://www.airpad.ch/reserve"


def manifest_rows(location_ids: tuple[str, ...] = LOCATION_IDS) -> list[dict[str, str]]:
    return [
        {
            "location_id": location_id,
            "booking_url": BOOKING_URL,
            "checked_at": "2026-09-22T00:00:00Z",
            "status": "public",
        }
        for location_id in location_ids
    ]


def write_manifest(path: Path, rows: list[dict[str, str]]) -> None:
    path.write_text(json.dumps({"format_version": 1, "sources": rows}))


def test_load_airpad_sources_accepts_exact_four_rows(tmp_path: Path) -> None:
    path = tmp_path / "airpad_sources.json"
    write_manifest(path, manifest_rows())

    sources = load_airpad_sources(path)

    assert tuple(source.location_id for source in sources) == tuple(sorted(LOCATION_IDS))
    assert all(source.booking_url == BOOKING_URL for source in sources)
    assert all(source.status == "public" for source in sources)


def test_load_airpad_sources_rejects_missing_or_extra_location(tmp_path: Path) -> None:
    path = tmp_path / "airpad_sources.json"

    write_manifest(path, manifest_rows(LOCATION_IDS[:-1]))
    with pytest.raises(AirpadSourceError):
        load_airpad_sources(path)

    write_manifest(path, manifest_rows(LOCATION_IDS[:-1] + ("airpad-unknown",)))
    with pytest.raises(AirpadSourceError):
        load_airpad_sources(path)


def test_load_airpad_sources_rejects_duplicate_rows(tmp_path: Path) -> None:
    path = tmp_path / "airpad_sources.json"
    write_manifest(path, manifest_rows(LOCATION_IDS[:-1] + (LOCATION_IDS[0],)))

    with pytest.raises(AirpadSourceError):
        load_airpad_sources(path)


@pytest.mark.parametrize(
    "booking_url",
    ("https://www.airpad.ch/private", "https://example.com/reserve"),
)
def test_load_airpad_sources_rejects_wrong_booking_url(tmp_path: Path, booking_url: str) -> None:
    path = tmp_path / "airpad_sources.json"
    rows = manifest_rows()
    rows[0]["booking_url"] = booking_url
    write_manifest(path, rows)

    with pytest.raises(AirpadSourceError):
        load_airpad_sources(path)


@pytest.mark.parametrize("checked_at", ("2026-09-22T00:00:00+02:00", "2026-09-22T00:00:00"))
def test_load_airpad_sources_rejects_invalid_checked_at(tmp_path: Path, checked_at: str) -> None:
    path = tmp_path / "airpad_sources.json"
    rows = manifest_rows()
    rows[0]["checked_at"] = checked_at
    write_manifest(path, rows)

    with pytest.raises(AirpadSourceError):
        load_airpad_sources(path)


def test_load_airpad_sources_rejects_missing_or_extra_row_fields(tmp_path: Path) -> None:
    path = tmp_path / "airpad_sources.json"

    rows = manifest_rows()
    del rows[0]["status"]
    write_manifest(path, rows)
    with pytest.raises(AirpadSourceError):
        load_airpad_sources(path)

    rows = manifest_rows()
    rows[0]["extra"] = "not allowed"
    write_manifest(path, rows)
    with pytest.raises(AirpadSourceError):
        load_airpad_sources(path)


def test_load_airpad_sources_rejects_invalid_status(tmp_path: Path) -> None:
    path = tmp_path / "airpad_sources.json"
    rows = manifest_rows()
    rows[0]["status"] = "members"
    write_manifest(path, rows)

    with pytest.raises(AirpadSourceError):
        load_airpad_sources(path)


def test_airpad_location_labels_are_explicit() -> None:
    assert AIRPAD_LOCATION_IDS == frozenset(LOCATION_IDS)
    assert AIRPAD_LOCATION_LABELS == {
        "airpad-les-acacias": "LES ACACIAS",
        "airpad-la-praille": "LA PRAILLE",
        "airpad-meyrin": "MEYRIN",
        "airpad-plan-les-ouates": "PLAN-LES-OUATES",
    }
