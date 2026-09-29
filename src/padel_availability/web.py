import os
from dataclasses import asdict
from datetime import UTC, datetime
from math import ceil
from pathlib import Path

from flask import Flask, Response, jsonify, render_template
from waitress import serve

from .connectors.airpad import load_airpad_sources
from .connectors.everness import load_everness_sources
from .connectors.matchpoint import load_matchpoint_sources
from .connectors.padelfirst import load_padelfirst_sources
from .connectors.playtomic import load_playtomic_sources
from .connectors.plugin import load_plugin_sources
from .database import (
    connect,
    get_availability_snapshot,
    get_latest_successful_availability_run,
    list_locations,
)
from .refresh import RefreshCoordinator, next_scheduled_at


def _configured_location_ids(data_directory: Path) -> frozenset[str]:
    ids: set[str] = set()
    for source in load_airpad_sources(data_directory / "airpad_sources.json"):
        ids.add(source.location_id)
    for source in load_everness_sources(data_directory / "everness_sources.json"):
        ids.add(source.location_id)
    for source in load_matchpoint_sources(data_directory / "matchpoint_sources.json"):
        ids.add(source.location_id)
    for source in load_padelfirst_sources(data_directory / "padelfirst_sources.json"):
        ids.add(source.location_id)
    for source in load_playtomic_sources(data_directory / "playtomic_sources.json"):
        ids.add(source.location_id)
    for source in load_plugin_sources(data_directory / "plugin_sources.json"):
        ids.add(source.location_id)
    return frozenset(ids)


def create_app(database_path: Path, data_directory: Path) -> Flask:
    app = Flask(__name__)
    configured_ids = _configured_location_ids(data_directory)
    refresh = RefreshCoordinator(database_path, data_directory)

    @app.get("/healthz")
    def health() -> tuple[dict[str, str], int]:
        return {"status": "ok"}, 200

    @app.get("/")
    def index() -> str:
        return render_template("index.html")

    @app.get("/api/availability")
    def availability() -> tuple[dict[str, object], int]:
        connection = connect(database_path)
        try:
            locations_by_id = {
                location.location_id: location for location in list_locations(connection)
            }
            rows: dict[str, dict[str, object]] = {}
            for location_id in sorted(configured_ids):
                location = locations_by_id.get(location_id)
                if location is None:
                    continue
                snapshot = get_availability_snapshot(connection, location_id)
                row: dict[str, object] = {
                    "location_id": location.location_id,
                    "canonical_name": location.canonical_name,
                    "municipality": location.municipality,
                    "overall_cover_status": location.overall_cover_status,
                    "booking_url": location.booking_url,
                    "snapshot_status": "no_data",
                    "window_start": None,
                    "window_end": None,
                    "last_success_at": None,
                    "slots": [],
                }
                if snapshot is not None:
                    successful_run = get_latest_successful_availability_run(connection, location_id)
                    row.update(
                        {
                            "snapshot_status": snapshot.status,
                            "window_start": (
                                successful_run.window_start if successful_run is not None else None
                            ),
                            "window_end": (
                                successful_run.window_end if successful_run is not None else None
                            ),
                            "last_success_at": snapshot.last_success_at,
                            "slots": [
                                {
                                    "court_label": slot.court_label,
                                    "starts_at": slot.starts_at,
                                    "ends_at": slot.ends_at,
                                    "status": slot.status,
                                }
                                for slot in snapshot.slots
                            ],
                        }
                    )
                rows[location_id] = row
        finally:
            connection.close()

        return {
            "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "locations": rows,
        }, 200

    @app.post("/api/refresh")
    def request_refresh() -> Response:
        status, code = refresh.request_manual()
        response = jsonify(asdict(status))
        response.status_code = code
        if code == 429 and status.next_allowed_at is not None:
            next_allowed = datetime.fromisoformat(status.next_allowed_at)
            response.headers["Retry-After"] = str(
                max(1, ceil((next_allowed - datetime.now(UTC)).total_seconds()))
            )
        return response

    @app.get("/api/refresh/status")
    def refresh_status() -> dict[str, object]:
        status = asdict(refresh.status())
        status["next_scheduled_at"] = next_scheduled_at(datetime.now(UTC))
        return status

    return app


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    database_path = Path(os.environ.get("PADEL_AVAILABILITY_DB", str(root / "var/catalog.sqlite3")))
    data_directory = Path(os.environ.get("PADEL_AVAILABILITY_DATA", str(root / "data")))
    serve(create_app(database_path, data_directory), host="0.0.0.0", port=8082)
