import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import pytest

from padel_availability.availability import local_window
from padel_availability.collector import collect_playtomic
from padel_availability.connectors.playtomic import (
    PlaytomicSource,
    PlaytomicSourceError,
    load_playtomic_sources,
)
from padel_availability.database import (
    connect,
    get_availability_snapshot,
    initialize,
    insert_candidates,
    list_availability_runs,
    upsert_location,
)
from padel_availability.inventory import load_candidates, load_locations
from padel_availability.models import LocationRecord, ModelError


ROOT = Path(__file__).parents[1]
PLAYTOMIC_IDS = (
    "gva-palexpo",
    "padel-parc-etoy",
    "padel-parc-preverenges",
    "padel-station",
    "vaudoise-arena",
)
ZURICH = ZoneInfo("Europe/Zurich")


def read_fixture(location_id: str) -> object:
    path = ROOT / "tests/fixtures/playtomic" / f"{location_id}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def five_playtomic_locations() -> tuple[LocationRecord, ...]:
    locations = load_locations(ROOT / "data/verified_locations.json")
    by_id = {location.location_id: location for location in locations}
    return tuple(by_id[location_id] for location_id in PLAYTOMIC_IDS)


def five_playtomic_sources() -> tuple[PlaytomicSource, ...]:
    manifest_sources = load_playtomic_sources(ROOT / "data/playtomic_sources.json")
    return tuple(
        replace(
            source,
            availability_url_template=(
                f"https://fixtures.example/{source.location_id}"
                "?from={window_start}&to={window_end}"
            ),
            status="public",
        )
        for source in manifest_sources
    )


def ready_database(tmp_path: Path) -> sqlite3.Connection:
    connection = connect(tmp_path / "catalog.sqlite3")
    initialize(connection)
    locations = five_playtomic_locations()
    candidates = load_candidates(ROOT / "data/candidates.json")
    candidate_ids = {
        candidate_id for location in locations for candidate_id in location.candidate_ids
    }
    insert_candidates(
        connection,
        tuple(candidate for candidate in candidates if candidate.candidate_id in candidate_ids),
    )
    for location in locations:
        upsert_location(connection, location)
    return connection


def fixture_fetch_json(url: str) -> object:
    location_id = urlparse(url).path.rsplit("/", 1)[-1]
    return read_fixture(location_id)


def test_collection_runs_all_selected_sites_independently(tmp_path: Path) -> None:
    connection = ready_database(tmp_path)
    try:
        outcomes = collect_playtomic(
            connection,
            five_playtomic_locations(),
            five_playtomic_sources(),
            now=datetime(2026, 9, 22, 9, 0, tzinfo=ZURICH),
            horizon_days=14,
            fetch_json=fixture_fetch_json,
        )

        assert [outcome.location_id for outcome in outcomes] == list(PLAYTOMIC_IDS)
        assert [outcome.status for outcome in outcomes] == ["success"] * 5
        assert [outcome.slot_count for outcome in outcomes] == [3] * 5
        assert all(outcome.window_start == "2026-09-22" for outcome in outcomes)
        assert all(outcome.window_end == "2026-10-06" for outcome in outcomes)
        assert all(outcome.location_id in outcome.run_id for outcome in outcomes)
        assert len({run.collected_at for run in list_availability_runs(connection)}) == 1
        assert {run.collected_at for run in list_availability_runs(connection)} == {
            "2026-09-22T07:00:00Z"
        }
    finally:
        connection.close()


def test_collection_selects_one_location_and_converts_utc_now(tmp_path: Path) -> None:
    connection = ready_database(tmp_path)
    try:
        outcomes = collect_playtomic(
            connection,
            five_playtomic_locations(),
            five_playtomic_sources(),
            now=datetime(2026, 9, 22, 23, 30, tzinfo=timezone.utc),
            horizon_days=2,
            location_id="padel-station",
            fetch_json=fixture_fetch_json,
        )

        assert len(outcomes) == 1
        assert outcomes[0].window_start == "2026-09-23"
        assert outcomes[0].window_end == "2026-09-25"
        assert outcomes[0].slot_count == 2
        assert local_window(datetime(2026, 9, 22, 23, 30, tzinfo=timezone.utc), 2) == (
            datetime(2026, 9, 23).date(),
            datetime(2026, 9, 25).date(),
        )
    finally:
        connection.close()


def test_collection_rejects_non_positive_horizon(tmp_path: Path) -> None:
    connection = ready_database(tmp_path)
    try:
        with pytest.raises(ModelError, match="positive"):
            collect_playtomic(
                connection,
                five_playtomic_locations(),
                five_playtomic_sources(),
                now=datetime(2026, 9, 22, 9, 0, tzinfo=ZURICH),
                horizon_days=0,
                location_id="padel-station",
                fetch_json=fixture_fetch_json,
            )
    finally:
        connection.close()


def test_source_error_is_persisted_and_does_not_stop_other_sites(tmp_path: Path) -> None:
    connection = ready_database(tmp_path)

    def fetch_json(url: str) -> object:
        if urlparse(url).path.endswith("padel-parc-etoy"):
            raise PlaytomicSourceError("fixture source failed")
        return fixture_fetch_json(url)

    try:
        outcomes = collect_playtomic(
            connection,
            five_playtomic_locations(),
            five_playtomic_sources(),
            now=datetime(2026, 9, 22, 9, 0, tzinfo=ZURICH),
            fetch_json=fetch_json,
        )

        failed = next(outcome for outcome in outcomes if outcome.location_id == "padel-parc-etoy")
        assert failed.status == "error"
        assert failed.error == "fixture source failed"
        assert len(list_availability_runs(connection)) == 5
        assert len(list_availability_runs(connection, "padel-parc-etoy")) == 1
        assert len(list_availability_runs(connection, "gva-palexpo")) == 1
    finally:
        connection.close()


def test_failed_second_collection_keeps_previous_slots_stale(tmp_path: Path) -> None:
    connection = ready_database(tmp_path)
    sources = five_playtomic_sources()
    try:
        collect_playtomic(
            connection,
            five_playtomic_locations(),
            sources,
            now=datetime(2026, 9, 22, 9, 0, tzinfo=ZURICH),
            location_id="padel-station",
            fetch_json=fixture_fetch_json,
        )

        def failed_fetch(_: str) -> object:
            raise PlaytomicSourceError("temporary source failure")

        outcomes = collect_playtomic(
            connection,
            five_playtomic_locations(),
            sources,
            now=datetime(2026, 9, 22, 10, 0, tzinfo=ZURICH),
            location_id="padel-station",
            fetch_json=failed_fetch,
        )

        assert outcomes[0].status == "error"
        snapshot = get_availability_snapshot(connection, "padel-station")
        assert snapshot is not None
        assert snapshot.status == "stale"
        assert len(snapshot.slots) == 3
        assert snapshot.latest_run.status == "error"
    finally:
        connection.close()


def test_programming_errors_are_not_swallowed(tmp_path: Path) -> None:
    connection = ready_database(tmp_path)

    def fetch_json(_: str) -> object:
        raise RuntimeError("programming failure")

    try:
        with pytest.raises(RuntimeError, match="programming failure"):
            collect_playtomic(
                connection,
                five_playtomic_locations(),
                five_playtomic_sources(),
                now=datetime(2026, 9, 22, 9, 0, tzinfo=ZURICH),
                location_id="padel-station",
                fetch_json=fetch_json,
            )
        assert list_availability_runs(connection) == ()
    finally:
        connection.close()


def test_base_exception_is_not_swallowed(tmp_path: Path) -> None:
    connection = ready_database(tmp_path)

    class FatalCollectionError(BaseException):
        pass

    def fetch_json(_: str) -> object:
        raise FatalCollectionError

    try:
        with pytest.raises(FatalCollectionError):
            collect_playtomic(
                connection,
                five_playtomic_locations(),
                five_playtomic_sources(),
                now=datetime(2026, 9, 22, 9, 0, tzinfo=ZURICH),
                location_id="padel-station",
                fetch_json=fetch_json,
            )
        assert list_availability_runs(connection) == ()
    finally:
        connection.close()
