from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from padel_availability.connectors.plugin import (
    PLUGIN_BOOKING_URLS,
    PLUGIN_LOCATION_IDS,
    PluginSource,
    PluginSourceError,
    load_plugin_sources,
)

ROOT = Path(__file__).parents[1]
CHECKED_AT = "2026-09-26T00:00:00Z"
PLUGIN_URLS = {
    "cologny": "https://reservation.cs-cologny.ch/diary",
    "collonge-bellerive": "https://reservation.tccb.ch/diary",
    "crans-vd": "https://tccrans.plugin.ch/user/diary",
    "csu-champel": "https://unige.plugin.ch/",
    "drizia-miremont": "https://tcdrizia.plugin.ch/",
    "fraisiers": "https://tcfraisiers.plugin.ch/?sport=301",
    "gland": "https://tcgland.plugin.ch/user/diary",
    "mies-tannay": "https://tcmt.plugin.ch/user/diary",
}


def _row(location_id: str, booking_url: str | None = None) -> dict[str, object]:
    return {
        "location_id": location_id,
        "booking_url": booking_url or PLUGIN_URLS[location_id],
        "checked_at": CHECKED_AT,
        "status": "public",
    }


def _write_manifest(path: Path, rows: Sequence[object]) -> None:
    path.write_text(json.dumps({"format_version": 1, "sources": rows}), encoding="utf-8")


def test_plugin_constants_and_model_are_strict() -> None:
    assert PLUGIN_BOOKING_URLS == PLUGIN_URLS
    assert PLUGIN_LOCATION_IDS == frozenset(PLUGIN_URLS)
    source = PluginSource("cologny", PLUGIN_URLS["cologny"], CHECKED_AT, "public")
    assert source.location_id == "cologny"
    with pytest.raises((PluginSourceError, ValueError)):
        PluginSource("cologny", PLUGIN_URLS["cologny"], CHECKED_AT, "private")  # type: ignore[arg-type]


def test_load_plugin_sources_returns_exact_sorted_manifest() -> None:
    sources = load_plugin_sources(ROOT / "data/plugin_sources.json")

    assert tuple(source.location_id for source in sources) == tuple(sorted(PLUGIN_URLS))
    assert {source.location_id: source.booking_url for source in sources} == PLUGIN_URLS
    assert all(source.status == "public" for source in sources)
    assert all(source.checked_at == CHECKED_AT for source in sources)


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [_row(location_id) for location_id in sorted(PLUGIN_URLS) if location_id != "gland"],
        [_row(location_id) for location_id in sorted(set(PLUGIN_URLS) - {"gland"})]
        + [_row("fraisiers")],
        [_row(location_id) for location_id in sorted(PLUGIN_URLS)]
        + [_row("other", "https://example.test/")],
    ],
)
def test_load_plugin_sources_rejects_empty_missing_duplicate_and_extra_rows(
    tmp_path: Path, rows: list[object]
) -> None:
    path = tmp_path / "sources.json"
    _write_manifest(path, rows)

    with pytest.raises(PluginSourceError):
        load_plugin_sources(path)


def test_load_plugin_sources_rejects_unsupported_exact_url(tmp_path: Path) -> None:
    path = tmp_path / "sources.json"
    rows = [_row(location_id) for location_id in sorted(PLUGIN_URLS)]
    rows[0] = {**rows[0], "booking_url": "https://tccologny.plugin.ch/diary"}
    _write_manifest(path, rows)

    with pytest.raises(PluginSourceError):
        load_plugin_sources(path)


@pytest.mark.parametrize(
    "row,manifest",
    [
        ({**_row("cologny"), "checked_at": "2026-09-26"}, None),
        ({**_row("cologny"), "status": "private"}, None),
        ({**_row("cologny"), "extra": True}, None),
        (None, {"format_version": 1, "sources": []}),
        (None, {"format_version": 1, "sources": [], "extra": True}),
    ],
)
def test_load_plugin_sources_rejects_invalid_fields_and_manifest_shape(
    tmp_path: Path, row: dict[str, object] | None, manifest: dict[str, object] | None
) -> None:
    path = tmp_path / "sources.json"
    rows = [_row(location_id) for location_id in sorted(PLUGIN_URLS)]
    if row is not None:
        rows[0] = row
    if manifest is None:
        _write_manifest(path, rows)
    else:
        path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(PluginSourceError):
        load_plugin_sources(path)


def test_load_plugin_sources_rejects_malformed_json_with_bounded_error(tmp_path: Path) -> None:
    path = tmp_path / "sources.json"
    path.write_text("{" + "x" * 1000, encoding="utf-8")

    with pytest.raises(PluginSourceError) as exc_info:
        load_plugin_sources(path)

    assert len(str(exc_info.value)) <= 160


def test_load_plugin_sources_rejects_deeply_nested_json_with_bounded_error(
    tmp_path: Path,
) -> None:
    path = tmp_path / "sources.json"
    path.write_text("[" * 10000 + "0" + "]" * 10000, encoding="utf-8")

    with pytest.raises(PluginSourceError) as exc_info:
        load_plugin_sources(path)

    assert len(str(exc_info.value)) <= 160
