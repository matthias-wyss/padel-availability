from __future__ import annotations

import logging
import os
import signal
import sqlite3
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from .collector import (
    CollectionOutcome,
    collect_airpad,
    collect_everness,
    collect_matchpoint,
    collect_padelfirst,
    collect_playtomic,
    collect_plugin,
)
from .connectors.airpad import load_airpad_sources
from .connectors.everness import load_everness_sources
from .connectors.matchpoint import load_matchpoint_sources
from .connectors.padelfirst import load_padelfirst_sources
from .connectors.playtomic import load_playtomic_sources
from .connectors.plugin import load_plugin_sources
from .database import connect, initialize, list_locations

type RefreshTrigger = Literal["manual", "scheduled"]
type RefreshState = Literal["idle", "queued", "running", "success", "partial", "error"]
type RefreshRunner = Callable[
    [sqlite3.Connection, Path, datetime, Callable[[CollectionOutcome], None]],
    tuple[CollectionOutcome, ...],
]

SCHEDULE_TZ = ZoneInfo("Europe/Zurich")
COOLDOWN = timedelta(minutes=5)
logger = logging.getLogger(__name__)
PLUGIN_HORIZONS = {
    "collonge-bellerive": 7,
    "cologny": 7,
    "csu-champel": 7,
    "drizia-miremont": 7,
    "fraisiers": 7,
    "mies-tannay": 7,
    "crans-vd": 3,
    "gland": 14,
}


@dataclass(frozen=True, slots=True)
class RefreshStatus:
    job_id: str | None
    trigger: RefreshTrigger | None
    status: RefreshState
    requested_at: str | None
    started_at: str | None
    finished_at: str | None
    completed_locations: int
    total_locations: int
    next_allowed_at: str | None
    error: str | None


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("refresh timestamps must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _configured_location_ids(data_directory: Path) -> frozenset[str]:
    source_groups = (
        load_playtomic_sources(data_directory / "playtomic_sources.json"),
        load_airpad_sources(data_directory / "airpad_sources.json"),
        load_everness_sources(data_directory / "everness_sources.json"),
        load_padelfirst_sources(data_directory / "padelfirst_sources.json"),
        load_matchpoint_sources(data_directory / "matchpoint_sources.json"),
        load_plugin_sources(data_directory / "plugin_sources.json"),
    )
    return frozenset(source.location_id for sources in source_groups for source in sources)


def run_all_sources(
    connection: sqlite3.Connection,
    data_directory: Path,
    now: datetime,
    on_outcome: Callable[[CollectionOutcome], None],
) -> tuple[CollectionOutcome, ...]:
    locations = list_locations(connection)
    outcomes: list[CollectionOutcome] = []

    def record(items: tuple[CollectionOutcome, ...]) -> None:
        for outcome in items:
            outcomes.append(outcome)
            on_outcome(outcome)

    record(
        collect_playtomic(
            connection,
            locations,
            load_playtomic_sources(data_directory / "playtomic_sources.json"),
            now=now,
            horizon_days=14,
        )
    )
    record(
        collect_airpad(
            connection,
            locations,
            load_airpad_sources(data_directory / "airpad_sources.json"),
            now=now,
            horizon_days=14,
        )
    )
    record(
        collect_everness(
            connection,
            locations,
            load_everness_sources(data_directory / "everness_sources.json"),
            now=now,
            horizon_days=14,
        )
    )
    record(
        collect_padelfirst(
            connection,
            locations,
            load_padelfirst_sources(data_directory / "padelfirst_sources.json"),
            now=now,
            horizon_days=14,
        )
    )
    record(
        collect_matchpoint(
            connection,
            locations,
            load_matchpoint_sources(data_directory / "matchpoint_sources.json"),
            now=now,
            horizon_days=14,
        )
    )

    plugin_sources = load_plugin_sources(data_directory / "plugin_sources.json")
    for source in sorted(plugin_sources, key=lambda item: item.location_id):
        record(
            collect_plugin(
                connection,
                locations,
                plugin_sources,
                now=now,
                horizon_days=PLUGIN_HORIZONS.get(source.location_id, 14),
                location_id=source.location_id,
            )
        )
    return tuple(sorted(outcomes, key=lambda outcome: outcome.location_id))


def next_scheduled_at(now: datetime) -> str:
    if now.tzinfo is None:
        raise ValueError("schedule timestamps must be timezone-aware")
    local_now = now.astimezone(SCHEDULE_TZ)
    for day_offset in range(3):
        day = local_now.date() + timedelta(days=day_offset)
        for hour in range(7, 24):
            for minute in (0, 30):
                if hour == 23 and minute == 30:
                    continue
                candidate = datetime.combine(day, time(hour, minute), tzinfo=SCHEDULE_TZ)
                if candidate.astimezone(UTC) > now.astimezone(UTC):
                    return candidate.isoformat()
    raise RuntimeError("unable to calculate next scheduled refresh")


def _scheduled_tick(now: datetime) -> str | None:
    if now.tzinfo is None:
        raise ValueError("schedule timestamps must be timezone-aware")
    local_now = now.astimezone(SCHEDULE_TZ)
    if local_now.hour < 7 or local_now.hour > 23 or local_now.minute not in (0, 30):
        return None
    if local_now.hour == 23 and local_now.minute != 0:
        return None
    tick = local_now.replace(minute=local_now.minute, second=0, microsecond=0)
    return _timestamp(tick)


def _next_allowed_at(last_started_at: str | None, now: datetime) -> str | None:
    if last_started_at is None:
        return None
    next_allowed = _parse_timestamp(last_started_at) + COOLDOWN
    return _timestamp(next_allowed) if next_allowed > now.astimezone(UTC) else None


def _read_status(connection: sqlite3.Connection, now: datetime) -> RefreshStatus:
    control = connection.execute(
        "SELECT last_started_at FROM availability_refresh_control WHERE singleton_id = 1"
    ).fetchone()
    latest = connection.execute(
        "SELECT * FROM availability_refresh_jobs ORDER BY requested_at DESC, job_id DESC LIMIT 1"
    ).fetchone()
    allowed_at = _next_allowed_at(control["last_started_at"], now) if control else None
    if latest is None:
        return RefreshStatus(None, None, "idle", None, None, None, 0, 0, allowed_at, None)
    return RefreshStatus(
        latest["job_id"],
        latest["trigger"],
        latest["status"],
        latest["requested_at"],
        latest["started_at"],
        latest["finished_at"],
        latest["completed_locations"],
        latest["total_locations"],
        allowed_at,
        latest["error"],
    )


def _active_job(connection: sqlite3.Connection) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT * FROM availability_refresh_jobs "
        "WHERE status IN ('queued', 'running') ORDER BY requested_at DESC LIMIT 1"
    ).fetchone()


def _enqueue(
    connection: sqlite3.Connection,
    trigger: RefreshTrigger,
    now: datetime,
    total_locations: int,
) -> tuple[RefreshStatus, int]:
    connection.execute("BEGIN IMMEDIATE")
    try:
        active = _active_job(connection)
        if active is not None:
            status = _read_status(connection, now)
            connection.rollback()
            return status, 409

        control = connection.execute(
            "SELECT last_started_at FROM availability_refresh_control WHERE singleton_id = 1"
        ).fetchone()
        if control is not None and _next_allowed_at(control["last_started_at"], now) is not None:
            status = _read_status(connection, now)
            connection.rollback()
            return status, 429

        connection.execute(
            """
            INSERT INTO availability_refresh_jobs (
                job_id, trigger, status, requested_at, total_locations
            ) VALUES (?, ?, 'queued', ?, ?)
            """,
            (uuid.uuid4().hex, trigger, _timestamp(now), total_locations),
        )
        status = _read_status(connection, now)
        connection.commit()
        return status, 202
    except BaseException:
        connection.rollback()
        raise


class RefreshCoordinator:
    def __init__(
        self,
        database_path: Path,
        data_directory: Path,
        runner: RefreshRunner | None = None,
    ) -> None:
        self.database_path = database_path
        self.data_directory = data_directory
        self.runner = runner or run_all_sources
        self.total_locations = len(_configured_location_ids(data_directory))
        connection = connect(database_path)
        try:
            initialize(connection)
        finally:
            connection.close()

    def request_manual(self, now: datetime | None = None) -> tuple[RefreshStatus, int]:
        current = now or datetime.now(UTC)
        connection = connect(self.database_path)
        try:
            return _enqueue(connection, "manual", current, self.total_locations)
        finally:
            connection.close()

    def status(self, now: datetime | None = None) -> RefreshStatus:
        connection = connect(self.database_path)
        try:
            return _read_status(connection, now or datetime.now(UTC))
        finally:
            connection.close()

    def enqueue_scheduled(self, now: datetime) -> bool:
        tick = _scheduled_tick(now)
        if tick is None:
            return False
        connection = connect(self.database_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            control = connection.execute(
                "SELECT last_started_at, last_scheduled_tick "
                "FROM availability_refresh_control WHERE singleton_id = 1"
            ).fetchone()
            if control is None or control["last_scheduled_tick"] == tick:
                connection.rollback()
                return False
            connection.execute(
                "UPDATE availability_refresh_control SET last_scheduled_tick = ? "
                "WHERE singleton_id = 1",
                (tick,),
            )
            active = _active_job(connection)
            cooldown_active = _next_allowed_at(control["last_started_at"], now) is not None
            if active is not None or cooldown_active:
                connection.commit()
                return False
            connection.execute(
                """
                INSERT INTO availability_refresh_jobs (
                    job_id, trigger, status, requested_at, total_locations
                ) VALUES (?, 'scheduled', 'queued', ?, ?)
                """,
                (uuid.uuid4().hex, _timestamp(now), self.total_locations),
            )
            connection.commit()
            return True
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _recover_interrupted_job(self, now: datetime) -> None:
        connection = connect(self.database_path)
        try:
            with connection:
                connection.execute(
                    """
                    UPDATE availability_refresh_jobs
                    SET status = 'error', finished_at = ?, error = 'Worker restarted during collection.'
                    WHERE status = 'running'
                    """,
                    (_timestamp(now),),
                )
        finally:
            connection.close()

    def run_pending_once(self, now: datetime | None = None) -> bool:
        current = now or datetime.now(UTC)
        connection = connect(self.database_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute(
                "SELECT 1 FROM availability_refresh_jobs WHERE status = 'running' LIMIT 1"
            ).fetchone():
                connection.rollback()
                return False
            job = connection.execute(
                "SELECT job_id FROM availability_refresh_jobs WHERE status = 'queued' "
                "ORDER BY requested_at, job_id LIMIT 1"
            ).fetchone()
            if job is None:
                connection.commit()
                return False
            started_at = _timestamp(current)
            connection.execute(
                "UPDATE availability_refresh_control SET last_started_at = ? "
                "WHERE singleton_id = 1",
                (started_at,),
            )
            connection.execute(
                "UPDATE availability_refresh_jobs SET status = 'running', started_at = ? "
                "WHERE job_id = ?",
                (started_at, job["job_id"]),
            )
            connection.commit()

            def record(outcome: CollectionOutcome) -> None:
                with connection:
                    connection.execute(
                        "UPDATE availability_refresh_jobs "
                        "SET completed_locations = completed_locations + 1 "
                        "WHERE job_id = ?",
                        (job["job_id"],),
                    )

            try:
                outcomes = self.runner(connection, self.data_directory, current, record)
                success_count = sum(outcome.status == "success" for outcome in outcomes)
                if not outcomes or success_count == 0:
                    final_status: RefreshState = "error"
                    error = "No source collections succeeded."
                elif success_count < len(outcomes):
                    final_status = "partial"
                    error = "One or more source collections failed."
                else:
                    final_status = "success"
                    error = None
            except Exception as exception:
                logger.exception("Availability refresh failed")
                final_status = "error"
                error = f"Refresh worker failed ({type(exception).__name__})."

            with connection:
                connection.execute(
                    "UPDATE availability_refresh_jobs SET status = ?, finished_at = ?, error = ? "
                    "WHERE job_id = ?",
                    (final_status, _timestamp(datetime.now(UTC)), error, job["job_id"]),
                )
            return True
        finally:
            connection.close()

    def run_forever(self, stop_event: threading.Event) -> None:
        self._recover_interrupted_job(datetime.now(UTC))
        while not stop_event.is_set():
            now = datetime.now(UTC)
            self.enqueue_scheduled(now)
            if self.run_pending_once(now):
                continue
            stop_event.wait(5)


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    database_path = Path(os.environ.get("PADEL_AVAILABILITY_DB", root / "var/catalog.sqlite3"))
    data_directory = Path(os.environ.get("PADEL_AVAILABILITY_DATA", root / "data"))
    coordinator = RefreshCoordinator(database_path, data_directory)
    stop_event = threading.Event()

    def stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    coordinator.run_forever(stop_event)


if __name__ == "__main__":
    main()
