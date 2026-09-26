from __future__ import annotations

import json
from pathlib import Path

import pytest

from padel_availability.connectors.matchpoint import load_matchpoint_sources

ROOT = Path(__file__).parents[1]
BERNEX_URL = "https://padelgeneva.matchpoint.com.es/Booking/Grid.aspx"
JONCTION_URL = "https://padelgeneva.matchpoint.com.es/Booking/Grid.aspx?id=9"
EVAUX_URL = "https://padelgeneva.matchpoint.com.es/Booking/Grid.aspx?id=8"
URBAN_URL = "https://urbanpadellausanne.matchpoint.com.es/Booking/Grid.aspx"


def _row(location_id: str, booking_url: str | None = None) -> dict[str, object]:
    urls = {
        "asphalte-jonction": JONCTION_URL,
        "bernex": BERNEX_URL,
        "evaux": EVAUX_URL,
        "urban-padel-lausanne": URBAN_URL,
    }
    return {
        "location_id": location_id,
        "booking_url": booking_url or urls.get(location_id, BERNEX_URL),
        "checked_at": "2026-09-26T00:00:00Z",
        "status": "public",
    }


def _write_manifest(path: Path, sources: list[object]) -> None:
    path.write_text(
        json.dumps({"format_version": 1, "sources": sources}),
        encoding="utf-8",
    )


def test_load_matchpoint_sources_accepts_exact_four_public_sources() -> None:
    sources = load_matchpoint_sources(ROOT / "data/matchpoint_sources.json")

    assert len(sources) == 4
    assert [source.location_id for source in sources] == [
        "asphalte-jonction",
        "bernex",
        "evaux",
        "urban-padel-lausanne",
    ]
    assert [source.booking_url for source in sources] == [
        JONCTION_URL,
        BERNEX_URL,
        EVAUX_URL,
        URBAN_URL,
    ]
    assert [source.checked_at for source in sources] == [
        "2026-09-26T00:00:00Z",
        "2026-09-26T00:00:00Z",
        "2026-09-26T00:00:00Z",
        "2026-09-26T00:00:00Z",
    ]
    assert [source.status for source in sources] == [
        "public",
        "public",
        "public",
        "public",
    ]


def test_load_matchpoint_sources_sorts_rows_by_location_id(tmp_path: Path) -> None:
    path = tmp_path / "sources.json"
    _write_manifest(
        path,
        [
            _row("urban-padel-lausanne"),
            _row("evaux"),
            _row("asphalte-jonction"),
            _row("bernex"),
        ],
    )

    sources = load_matchpoint_sources(path)

    assert [source.location_id for source in sources] == [
        "asphalte-jonction",
        "bernex",
        "evaux",
        "urban-padel-lausanne",
    ]


@pytest.mark.parametrize(
    "sources",
    [
        [],
        [_row("bernex")],
        [_row("bernex"), _row("bernex")],
        [_row("bernex"), _row("evaux")],
        [
            _row("asphalte-jonction"),
            _row("bernex"),
            _row("evaux"),
        ],
        [
            _row("asphalte-jonction"),
            _row("bernex"),
            _row("evaux"),
            _row("evaux"),
        ],
    ],
)
def test_load_matchpoint_sources_rejects_non_exact_location_coverage(
    tmp_path: Path, sources: list[object]
) -> None:
    path = tmp_path / "sources.json"
    _write_manifest(path, sources)

    with pytest.raises(ValueError, match="location|source"):
        load_matchpoint_sources(path)


@pytest.mark.parametrize(
    "field,value",
    [
        ("booking_url", "https://example.test/"),
        ("checked_at", "2026-09-25"),
        ("status", "private"),
    ],
)
def test_load_matchpoint_sources_rejects_invalid_row_values(
    tmp_path: Path, field: str, value: object
) -> None:
    path = tmp_path / "sources.json"
    row = _row("bernex")
    row[field] = value
    _write_manifest(
        path,
        [
            row,
            _row("asphalte-jonction"),
            _row("evaux"),
            _row("urban-padel-lausanne"),
        ],
    )

    with pytest.raises(ValueError):
        load_matchpoint_sources(path)


def test_load_matchpoint_sources_rejects_extra_fields(tmp_path: Path) -> None:
    path = tmp_path / "sources.json"
    bernex = {**_row("bernex"), "extra": True}
    _write_manifest(
        path,
        [
            bernex,
            _row("asphalte-jonction"),
            _row("evaux"),
            _row("urban-padel-lausanne"),
        ],
    )

    with pytest.raises(ValueError, match="field"):
        load_matchpoint_sources(path)


def test_load_matchpoint_sources_rejects_malformed_json(tmp_path: Path) -> None:
    path = tmp_path / "sources.json"
    path.write_text("{invalid", encoding="utf-8")

    with pytest.raises(ValueError, match="manifest|source"):
        load_matchpoint_sources(path)
