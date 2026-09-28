from __future__ import annotations

import json
from pathlib import Path

import pytest

from padel_availability.connectors.padelfirst import (
    PADEL_FIRST_BOOKING_URL,
    PADEL_FIRST_LOCATION_IDS,
    PADEL_FIRST_SLOT_MINUTES,
    PadelFirstSourceError,
    load_padelfirst_sources,
)

ROOT = Path(__file__).parents[1]


def _manifest_row() -> dict[str, object]:
    return {
        "location_id": "vernier",
        "booking_url": PADEL_FIRST_BOOKING_URL,
        "checked_at": "2026-09-23T00:00:00Z",
        "status": "public",
    }


def _write_manifest(path: Path, rows: list[object]) -> None:
    path.write_text(json.dumps({"format_version": 1, "sources": rows}), encoding="utf-8")


def test_padelfirst_constants_are_explicit() -> None:
    assert PADEL_FIRST_LOCATION_IDS == frozenset({"vernier"})
    assert PADEL_FIRST_BOOKING_URL == "https://padelfirst.ss-r.ch/court-vernier/"
    assert PADEL_FIRST_SLOT_MINUTES == 90


def test_load_padelfirst_sources_accepts_exact_one_row() -> None:
    sources = load_padelfirst_sources(ROOT / "data/padelfirst_sources.json")

    assert len(sources) == 1
    assert sources[0].location_id == "vernier"
    assert sources[0].booking_url == PADEL_FIRST_BOOKING_URL
    assert sources[0].status == "public"


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [{**_manifest_row(), "location_id": "other"}],
        [_manifest_row(), {**_manifest_row(), "location_id": "other"}],
    ],
)
def test_load_padelfirst_sources_rejects_missing_or_extra_location(
    tmp_path: Path, rows: list[object]
) -> None:
    path = tmp_path / "sources.json"
    _write_manifest(path, rows)

    with pytest.raises(PadelFirstSourceError, match="location|exactly one row"):
        load_padelfirst_sources(path)


def test_load_padelfirst_sources_rejects_duplicate_rows(tmp_path: Path) -> None:
    path = tmp_path / "sources.json"
    _write_manifest(path, [_manifest_row(), _manifest_row()])

    with pytest.raises(PadelFirstSourceError, match="exactly one row"):
        load_padelfirst_sources(path)


@pytest.mark.parametrize(
    "field,value,match",
    [
        ("booking_url", "https://example.test/", "URL"),
        ("checked_at", "2026-09-23", "row failed validation"),
        ("status", "private", "row failed validation"),
    ],
)
def test_load_padelfirst_sources_rejects_invalid_fields(
    tmp_path: Path, field: str, value: object, match: str
) -> None:
    path = tmp_path / "sources.json"
    row = _manifest_row()
    row[field] = value
    _write_manifest(path, [row])

    with pytest.raises(PadelFirstSourceError, match=match):
        load_padelfirst_sources(path)


def test_load_padelfirst_sources_rejects_extra_row_fields(tmp_path: Path) -> None:
    path = tmp_path / "sources.json"
    row = {**_manifest_row(), "extra": True}
    _write_manifest(path, [row])

    with pytest.raises(PadelFirstSourceError, match="invalid fields"):
        load_padelfirst_sources(path)
