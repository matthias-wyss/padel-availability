from __future__ import annotations

import importlib.util
import json
import sqlite3
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from padel_availability.availability import (
    AvailabilityResult,
    AvailabilityRun,
    AvailabilityRunStatus,
    AvailabilitySlot,
)
from padel_availability.database import connect, initialize, save_availability_result
from padel_availability.inventory import build_catalog, load_candidates, load_locations
from padel_availability.models import LocationRecord, VerificationRun

ROOT = Path(__file__).parents[1]
DATA = ROOT / "data"
WINDOW_START = date(2026, 9, 28)
CONFIGURED_LOCATION_IDS = {
    "airpad-la-praille",
    "airpad-les-acacias",
    "airpad-meyrin",
    "airpad-plan-les-ouates",
    "asphalte-jonction",
    "bernex",
    "collonge-bellerive",
    "cologny",
    "crans-vd",
    "csu-champel",
    "drizia-miremont",
    "evaux",
    "everness",
    "fraisiers",
    "gland",
    "gva-palexpo",
    "mies-tannay",
    "padel-parc-etoy",
    "padel-parc-preverenges",
    "padel-station",
    "urban-padel-lausanne",
    "vaudoise-arena",
    "vernier",
}


def _database(path: Path) -> tuple[sqlite3.Connection, dict[str, LocationRecord]]:
    connection = connect(path)
    initialize(connection)
    candidates = load_candidates(DATA / "candidates.json")
    locations = load_locations(DATA / "verified_locations.json")
    build_catalog(
        connection,
        candidates,
        locations,
        VerificationRun(
            "web-api-test",
            "2026-09-28T00:00:00Z",
            "2026-09-28T00:00:00Z",
            len(candidates),
            0,
            "web API test catalog",
        ),
    )
    return connection, {location.location_id: location for location in locations}


def _save_run(
    connection: sqlite3.Connection,
    location: LocationRecord,
    *,
    run_id: str,
    window_end: date,
    collected_at: str,
    status: AvailabilityRunStatus,
    slots: Sequence[AvailabilitySlot] = (),
    error: str | None = None,
) -> None:
    assert location.booking_url is not None
    run = AvailabilityRun(
        run_id,
        location.location_id,
        "plugin_browser",
        location.booking_url,
        WINDOW_START.isoformat(),
        window_end.isoformat(),
        (window_end - WINDOW_START).days,
        collected_at,
        status,
        error,
    )
    save_availability_result(connection, AvailabilityResult(run, tuple(slots)))


def _available_slot(location_id: str, run_id: str) -> AvailabilitySlot:
    return AvailabilitySlot(
        run_id,
        location_id,
        f"{run_id}-slot",
        None,
        "Padel 1",
        "2026-09-28T16:00:00Z",
        "2026-09-28T17:30:00Z",
        "Europe/Zurich",
        "available",
    )


def _configured_ids(data_directory: Path) -> set[str]:
    ids: set[str] = set()
    for manifest_path in sorted(data_directory.glob("*_sources.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if isinstance(manifest, list):
            rows = cast(list[dict[str, object]], manifest)
        else:
            manifest_mapping = cast(dict[str, object], manifest)
            rows = cast(list[dict[str, object]], manifest_mapping["sources"])
        ids.update(cast(str, row["location_id"]) for row in rows)
    return ids


def test_availability_api_preserves_snapshot_status_and_source_window(tmp_path: Path) -> None:
    if importlib.util.find_spec("padel_availability.web") is None:
        pytest.fail("public web API module is not implemented yet", pytrace=False)
    from padel_availability.web import create_app

    connection, locations = _database(tmp_path / "catalog.sqlite3")
    try:
        _save_run(
            connection,
            locations["cologny"],
            run_id="cologny-success",
            window_end=date(2026, 10, 5),
            collected_at="2026-09-28T12:00:00Z",
            status="success",
            slots=(_available_slot("cologny", "cologny-success"),),
        )
        _save_run(
            connection,
            locations["collonge-bellerive"],
            run_id="collonge-success",
            window_end=date(2026, 10, 5),
            collected_at="2026-09-28T12:00:00Z",
            status="success",
            slots=(_available_slot("collonge-bellerive", "collonge-success"),),
        )
        _save_run(
            connection,
            locations["collonge-bellerive"],
            run_id="collonge-error",
            window_end=date(2026, 10, 12),
            collected_at="2026-09-28T13:00:00Z",
            status="error",
            error="public diary was unavailable",
        )
        _save_run(
            connection,
            locations["crans-vd"],
            run_id="crans-empty",
            window_end=date(2026, 10, 1),
            collected_at="2026-09-28T12:00:00Z",
            status="success",
        )
        runs_before = connection.execute("SELECT COUNT(*) FROM availability_runs").fetchone()[0]

        response = (
            create_app(tmp_path / "catalog.sqlite3", DATA).test_client().get("/api/availability")
        )

        assert response.status_code == 200
        payload_object = response.get_json()
        assert isinstance(payload_object, dict)
        payload = cast(dict[str, object], payload_object)
        rows = cast(dict[str, dict[str, object]], payload["locations"])
        assert set(rows) == _configured_ids(DATA) == CONFIGURED_LOCATION_IDS
        assert rows["cologny"]["snapshot_status"] == "success"
        assert rows["cologny"]["window_end"] == "2026-10-05"
        cologny_slots = cast(list[dict[str, object]], rows["cologny"]["slots"])
        assert cologny_slots[0]["status"] == "available"
        assert rows["collonge-bellerive"]["snapshot_status"] == "stale"
        assert rows["collonge-bellerive"]["window_end"] == "2026-10-05"
        assert rows["collonge-bellerive"]["last_success_at"] == "2026-09-28T12:00:00Z"
        assert "public diary was unavailable" not in response.get_data(as_text=True)
        assert rows["crans-vd"]["snapshot_status"] == "success"
        assert rows["crans-vd"]["slots"] == []
        assert rows["mies-tannay"]["snapshot_status"] == "no_data"
        assert rows["mies-tannay"]["window_end"] is None

        connection = connect(tmp_path / "catalog.sqlite3")
        try:
            runs_after = connection.execute("SELECT COUNT(*) FROM availability_runs").fetchone()[0]
        finally:
            connection.close()
        assert runs_after == runs_before
    finally:
        connection.close()


def test_health_route_is_lightweight(tmp_path: Path) -> None:
    from padel_availability.web import create_app

    response = create_app(tmp_path / "catalog.sqlite3", DATA).test_client().get("/healthz")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_refresh_routes_queue_only_one_fixed_all_source_job(tmp_path: Path) -> None:
    from padel_availability.web import create_app

    database_path = tmp_path / "catalog.sqlite3"
    connection, _locations = _database(database_path)
    connection.close()
    client = create_app(database_path, DATA).test_client()

    first = client.post("/api/refresh", json={"source_url": "https://example.invalid/"})
    assert first.status_code == 202
    first_payload_object = first.get_json()
    assert isinstance(first_payload_object, dict)
    first_payload = cast(dict[str, object], first_payload_object)
    assert first_payload["status"] == "queued"
    assert first_payload["trigger"] == "manual"
    assert first_payload["total_locations"] == 23

    duplicate = client.post("/api/refresh")
    assert duplicate.status_code == 409
    duplicate_payload_object = duplicate.get_json()
    assert isinstance(duplicate_payload_object, dict)
    duplicate_payload = cast(dict[str, object], duplicate_payload_object)
    assert duplicate_payload["job_id"] == first_payload["job_id"]

    status = client.get("/api/refresh/status")
    assert status.status_code == 200
    status_payload_object = status.get_json()
    assert isinstance(status_payload_object, dict)
    status_payload = cast(dict[str, object], status_payload_object)
    assert status_payload["status"] == "queued"
    assert status_payload["next_scheduled_at"] is not None

    connection = connect(database_path)
    try:
        assert (
            connection.execute("SELECT COUNT(*) FROM availability_refresh_jobs").fetchone()[0] == 1
        )
    finally:
        connection.close()


def test_refresh_route_returns_retry_after_for_shared_cooldown(tmp_path: Path) -> None:
    from padel_availability.web import create_app

    database_path = tmp_path / "catalog.sqlite3"
    connection, _locations = _database(database_path)
    connection.close()
    client = create_app(database_path, DATA).test_client()
    assert client.post("/api/refresh").status_code == 202

    started_at = (datetime.now(UTC) - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    finished_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    connection = connect(database_path)
    try:
        with connection:
            connection.execute(
                "UPDATE availability_refresh_jobs SET status = 'success', started_at = ?, finished_at = ?",
                (started_at, finished_at),
            )
            connection.execute(
                "UPDATE availability_refresh_control SET last_started_at = ? WHERE singleton_id = 1",
                (started_at,),
            )
    finally:
        connection.close()

    throttled = client.post("/api/refresh")
    assert throttled.status_code == 429
    assert 0 < int(throttled.headers["Retry-After"]) <= 240
