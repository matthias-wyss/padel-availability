import json
from datetime import date
from pathlib import Path

import pytest

from padel_availability.connectors.playtomic import (
    PlaytomicConnector,
    PlaytomicSource,
    PlaytomicSourceError,
    load_playtomic_sources,
    parse_playtomic_slots,
)
from padel_availability.models import LocationRecord, ModelError

ROOT = Path(__file__).parents[1]
FIXTURE_NAMES = (
    "padel-station",
    "gva-palexpo",
    "padel-parc-etoy",
    "padel-parc-preverenges",
    "vaudoise-arena",
)


def read_fixture(name: str) -> object:
    return json.loads((ROOT / "tests/fixtures/playtomic" / f"{name}.json").read_text())


def test_manifest_has_exact_verified_locations_and_no_guessed_feeds() -> None:
    sources = load_playtomic_sources(ROOT / "data/playtomic_sources.json")

    assert [source.location_id for source in sources] == sorted(FIXTURE_NAMES)
    assert all(source.transport == "browser_dom" for source in sources)
    assert all(source.status == "public" for source in sources)
    assert all(source.availability_url_template is None for source in sources)
    assert sources[0].checked_at.endswith("Z")


def test_browser_source_requires_no_json_url() -> None:
    source = PlaytomicSource(
        "padel-station",
        "https://playtomic.com/fr/clubs/padel-station1",
        "browser_dom",
        None,
        "2026-09-22T00:00:00Z",
        "public",
    )

    assert source.transport == "browser_dom"
    assert source.availability_url_template is None


def test_json_source_still_requires_a_window_template() -> None:
    source = PlaytomicSource(
        "padel-station",
        "https://playtomic.com/fr/clubs/padel-station1",
        "json",
        "https://public.example/slots?from={window_start}&to={window_end}",
        "2026-09-22T00:00:00Z",
        "public",
    )

    assert source.transport == "json"
    assert source.availability_url_template is not None


def test_source_transport_relationships_are_strict() -> None:
    with pytest.raises(ModelError, match="transport"):
        PlaytomicSource(
            "padel-station",
            "https://playtomic.com/fr/clubs/padel-station1",
            "xml",  # type: ignore[arg-type]
            None,
            "2026-09-22T00:00:00Z",
            "unavailable",
        )
    with pytest.raises(ModelError, match="availability_url_template"):
        PlaytomicSource(
            "padel-station",
            "https://playtomic.com/fr/clubs/padel-station1",
            "json",
            None,
            "2026-09-22T00:00:00Z",
            "public",
        )
    with pytest.raises(ModelError, match="availability_url_template"):
        PlaytomicSource(
            "padel-station",
            "https://playtomic.com/fr/clubs/padel-station1",
            "browser_dom",
            "https://public.example/slots?from={window_start}&to={window_end}",
            "2026-09-22T00:00:00Z",
            "public",
        )


def test_synthetic_fixtures_normalize_slots_and_preserve_state() -> None:
    for location_id in FIXTURE_NAMES:
        slots = parse_playtomic_slots(
            read_fixture(location_id),
            location_id=location_id,
            run_id="run-fixture",
            window_start=date(2026, 9, 22),
            window_end=date(2026, 9, 24),
        )

        assert len(slots) == 2
        assert {slot.status for slot in slots} == {"available", "unavailable"}
        assert all(slot.timezone == "Europe/Zurich" for slot in slots)
        assert all(slot.starts_at.endswith("Z") and slot.ends_at.endswith("Z") for slot in slots)
        assert tuple(slot.slot_key for slot in slots) == tuple(
            slot.slot_key
            for slot in parse_playtomic_slots(
                read_fixture(location_id),
                location_id=location_id,
                run_id="another-run",
                window_start=date(2026, 9, 22),
                window_end=date(2026, 9, 24),
            )
        )


def test_parser_rejects_malformed_payload_instead_of_empty_success() -> None:
    with pytest.raises(PlaytomicSourceError, match="slots"):
        parse_playtomic_slots(
            {"data": {}},
            location_id="padel-station",
            run_id="run-invalid",
            window_start=date(2026, 9, 22),
            window_end=date(2026, 9, 24),
        )


def test_parser_rejects_naive_and_ambiguous_timestamps() -> None:
    base = {
        "external_id": "slot-1",
        "court_label": "Court 1",
        "ends_at": "2026-09-22T19:00:00+02:00",
        "status": "available",
    }
    with pytest.raises(PlaytomicSourceError, match="offset-aware"):
        parse_playtomic_slots(
            {"slots": [{**base, "starts_at": "2026-09-22T18:00:00"}]},
            location_id="padel-station",
            run_id="run-naive",
            window_start=date(2026, 9, 22),
            window_end=date(2026, 9, 24),
        )

    with pytest.raises(PlaytomicSourceError, match="ambiguous"):
        parse_playtomic_slots(
            {
                "slots": [
                    {
                        **base,
                        "starts_at": "2026-10-25T02:30:00+02:00",
                        "ends_at": "2026-10-25T03:30:00+01:00",
                    }
                ]
            },
            location_id="padel-station",
            run_id="run-ambiguous",
            window_start=date(2026, 10, 25),
            window_end=date(2026, 10, 26),
        )


def test_parser_hashes_missing_ids_and_deduplicates_in_window() -> None:
    payload = {
        "slots": [
            {
                "external_id": None,
                "court_label": "Court 2",
                "starts_at": "2026-09-22T18:00:00+02:00",
                "ends_at": "2026-09-22T19:30:00+02:00",
                "status": "unknown",
            },
            {
                "external_id": None,
                "court_label": "Court 2",
                "starts_at": "2026-09-22T18:00:00+02:00",
                "ends_at": "2026-09-22T19:30:00+02:00",
                "status": "unknown",
            },
            {
                "external_id": "outside",
                "court_label": "Court 2",
                "starts_at": "2026-09-24T18:00:00+02:00",
                "ends_at": "2026-09-24T19:30:00+02:00",
                "status": "available",
            },
        ]
    }

    slots = parse_playtomic_slots(
        payload,
        location_id="padel-station",
        run_id="run-hash",
        window_start=date(2026, 9, 22),
        window_end=date(2026, 9, 24),
    )

    assert len(slots) == 1
    assert slots[0].external_id is None
    assert len(slots[0].slot_key) == 64


def test_parser_rejects_conflicting_duplicate_external_ids() -> None:
    payload = {
        "slots": [
            {
                "external_id": "same-id",
                "court_label": "Court 1",
                "starts_at": "2026-09-22T18:00:00+02:00",
                "ends_at": "2026-09-22T19:00:00+02:00",
                "status": "available",
            },
            {
                "external_id": "same-id",
                "court_label": "Court 1",
                "starts_at": "2026-09-22T18:00:00+02:00",
                "ends_at": "2026-09-22T19:00:00+02:00",
                "status": "unavailable",
            },
        ]
    }

    with pytest.raises(PlaytomicSourceError, match="conflicting duplicate external_id"):
        parse_playtomic_slots(
            payload,
            location_id="padel-station",
            run_id="run-conflict",
            window_start=date(2026, 9, 22),
            window_end=date(2026, 9, 24),
        )


def test_connector_returns_unavailable_without_calling_transport() -> None:
    source = PlaytomicSource(
        "padel-station",
        "https://playtomic.com/fr/clubs/padel-station1",
        "json",
        None,
        "2026-09-22T00:00:00Z",
        "unavailable",
    )
    called = False

    def fetch_json(_: str) -> object:
        nonlocal called
        called = True
        return {}

    result = PlaytomicConnector((source,), fetch_json=fetch_json).collect(
        LocationRecord(
            "padel-station",
            "Padel Station",
            "Chêne-Bourg",
            ("padel-station",),
            "public",
            "unknown",
            "yes",
            "unknown",
            "unknown",
            "unknown",
            "to_verify",
            (),
            (),
            (),
            "",
            booking_url=source.booking_url,
        ),
        run_id="run-unavailable",
        window_start=date(2026, 9, 22),
        window_end=date(2026, 9, 24),
        collected_at="2026-09-22T08:00:00Z",
    )

    assert result.run.status == "unavailable"
    assert result.slots == ()
    assert called is False


def test_connector_injects_fetcher_and_formats_public_window() -> None:
    source = PlaytomicSource(
        "padel-station",
        "https://playtomic.com/fr/clubs/padel-station1",
        "json",
        "https://public.example/slots?from={window_start}&to={window_end}",
        "2026-09-22T00:00:00Z",
        "public",
    )
    requested: list[str] = []

    def fetch_json(url: str) -> object:
        requested.append(url)
        return {"slots": []}

    result = PlaytomicConnector((source,), fetch_json=fetch_json).collect(
        LocationRecord(
            "padel-station",
            "Padel Station",
            "Chêne-Bourg",
            ("padel-station",),
            "public",
            "unknown",
            "yes",
            "unknown",
            "unknown",
            "unknown",
            "to_verify",
            (),
            (),
            (),
            "",
            booking_url=source.booking_url,
        ),
        run_id="run-public",
        window_start=date(2026, 9, 22),
        window_end=date(2026, 9, 24),
        collected_at="2026-09-22T08:00:00Z",
    )

    assert requested == ["https://public.example/slots?from=2026-09-22&to=2026-09-24"]
    assert result.run.status == "success"
    assert result.slots == ()
