from __future__ import annotations

import importlib.util
import sqlite3
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

import pytest

from padel_availability.collector import CollectionOutcome
from padel_availability.database import connect, initialize
from padel_availability.inventory import build_catalog, load_candidates, load_locations
from padel_availability.models import LocationRecord, VerificationRun

ROOT = Path(__file__).parents[1]
DATA = ROOT / "data"


def test_manual_refresh_persists_status_and_global_cooldown(tmp_path: Path) -> None:
    if importlib.util.find_spec("padel_availability.refresh") is None:
        pytest.fail("refresh worker is not implemented yet", pytrace=False)
    from padel_availability.refresh import RefreshCoordinator

    database_path = tmp_path / "catalog.sqlite3"
    connection = connect(database_path)
    initialize(connection)
    connection.close()

    calls = 0

    def runner(
        _connection: sqlite3.Connection,
        _data_directory: Path,
        now: datetime,
        on_outcome: Callable[[CollectionOutcome], None],
    ) -> tuple[CollectionOutcome, ...]:
        nonlocal calls
        calls += 1
        outcome = CollectionOutcome(
            "cologny",
            f"run-{calls}",
            "success",
            2,
            now.date().isoformat(),
            (now.date() + timedelta(days=7)).isoformat(),
            None,
        )
        on_outcome(outcome)
        return (outcome,)

    now = datetime(2026, 9, 29, 8, 0, tzinfo=UTC)
    coordinator = RefreshCoordinator(database_path, DATA, runner=runner)
    queued, code = coordinator.request_manual(now=now)

    assert code == 202
    assert queued.status == "queued"
    already_running, code = coordinator.request_manual(now=now + timedelta(minutes=1))
    assert code == 409
    assert already_running.job_id == queued.job_id
    assert coordinator.run_pending_once(now=now + timedelta(seconds=2)) is True

    completed = RefreshCoordinator(database_path, DATA, runner=runner).status()
    assert completed.status == "success"
    assert completed.completed_locations == 1
    assert calls == 1

    throttled, code = coordinator.request_manual(now=now + timedelta(minutes=4, seconds=59))
    assert code == 429
    assert throttled.next_allowed_at == "2026-09-29T08:05:02Z"
    accepted, code = coordinator.request_manual(now=now + timedelta(minutes=5, seconds=2))
    assert code == 202
    assert accepted.status == "queued"


def test_all_source_runner_uses_configured_plugin_horizons(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if importlib.util.find_spec("padel_availability.refresh") is None:
        pytest.fail("refresh worker is not implemented yet", pytrace=False)
    from padel_availability import refresh

    database_path = tmp_path / "catalog.sqlite3"
    connection = connect(database_path)
    initialize(connection)
    candidates = load_candidates(DATA / "candidates.json")
    locations = load_locations(DATA / "verified_locations.json")
    build_catalog(
        connection,
        candidates,
        locations,
        VerificationRun(
            "refresh-test",
            "2026-09-29T00:00:00Z",
            "2026-09-29T00:00:00Z",
            len(candidates),
            0,
            "refresh runner test catalog",
        ),
    )

    calls: dict[str, list[tuple[int, str | None]]] = {
        name: []
        for name in ("playtomic", "airpad", "everness", "padelfirst", "matchpoint", "plugin")
    }

    def fake_collector(name: str) -> Callable[..., tuple[CollectionOutcome, ...]]:
        def collect(
            _connection: sqlite3.Connection,
            _locations: Sequence[LocationRecord],
            sources: Sequence[object],
            *,
            now: datetime | None = None,
            horizon_days: int = 14,
            location_id: str | None = None,
        ) -> tuple[CollectionOutcome, ...]:
            del now
            calls[name].append((horizon_days, location_id))
            source_ids = {cast(str, cast(Any, source).location_id) for source in sources}
            ids = (location_id,) if location_id is not None else tuple(sorted(source_ids))
            return tuple(
                CollectionOutcome(
                    item,
                    f"test-{name}-{item}",
                    "success",
                    0,
                    "2026-09-29",
                    "2026-10-13",
                    None,
                )
                for item in ids
            )

        return collect

    for name in calls:
        monkeypatch.setattr(refresh, f"collect_{name}", fake_collector(name))

    progress: list[str] = []
    outcomes = refresh.run_all_sources(
        connection,
        DATA,
        datetime(2026, 9, 29, 8, 0, tzinfo=UTC),
        lambda outcome: progress.append(outcome.location_id),
    )

    assert calls["playtomic"] == [(14, None)]
    assert calls["airpad"] == [(14, None)]
    assert calls["everness"] == [(14, None)]
    assert calls["padelfirst"] == [(14, None)]
    assert calls["matchpoint"] == [(14, None)]
    assert sorted(calls["plugin"]) == [
        (3, "crans-vd"),
        (7, "collonge-bellerive"),
        (7, "cologny"),
        (7, "csu-champel"),
        (7, "drizia-miremont"),
        (7, "fraisiers"),
        (7, "mies-tannay"),
        (14, "gland"),
    ]
    assert len(outcomes) == len(progress) == 23
    connection.close()


def test_scheduled_refresh_runs_on_due_ticks_and_skips_blocked_ticks(tmp_path: Path) -> None:
    if importlib.util.find_spec("padel_availability.refresh") is None:
        pytest.fail("refresh worker is not implemented yet", pytrace=False)
    from padel_availability.refresh import RefreshCoordinator

    database_path = tmp_path / "catalog.sqlite3"
    connection = connect(database_path)
    initialize(connection)
    connection.close()

    def runner(
        _connection: sqlite3.Connection,
        _data_directory: Path,
        now: datetime,
        on_outcome: Callable[[CollectionOutcome], None],
    ) -> tuple[CollectionOutcome, ...]:
        outcome = CollectionOutcome(
            "cologny",
            "scheduled-run",
            "success",
            1,
            now.date().isoformat(),
            (now.date() + timedelta(days=7)).isoformat(),
            None,
        )
        on_outcome(outcome)
        return (outcome,)

    coordinator = RefreshCoordinator(database_path, DATA, runner=runner)
    local_due = datetime(2026, 9, 29, 7, 0, tzinfo=ZoneInfo("Europe/Zurich"))
    assert coordinator.enqueue_scheduled(local_due) is True
    assert coordinator.enqueue_scheduled(local_due + timedelta(seconds=30)) is False
    assert coordinator.run_pending_once(now=local_due + timedelta(minutes=29)) is True

    blocked_tick = local_due + timedelta(minutes=30)
    assert coordinator.enqueue_scheduled(blocked_tick) is False
    assert coordinator.enqueue_scheduled(blocked_tick + timedelta(seconds=30)) is False
    assert coordinator.enqueue_scheduled(local_due + timedelta(minutes=35)) is False
    assert coordinator.enqueue_scheduled(local_due + timedelta(hours=1)) is True
    assert coordinator.status().trigger == "scheduled"


def test_partial_collection_reports_progress_without_source_error_details(tmp_path: Path) -> None:
    if importlib.util.find_spec("padel_availability.refresh") is None:
        pytest.fail("refresh worker is not implemented yet", pytrace=False)
    from padel_availability.refresh import RefreshCoordinator

    database_path = tmp_path / "catalog.sqlite3"
    connection = connect(database_path)
    initialize(connection)
    connection.close()

    def runner(
        _connection: sqlite3.Connection,
        _data_directory: Path,
        now: datetime,
        on_outcome: Callable[[CollectionOutcome], None],
    ) -> tuple[CollectionOutcome, ...]:
        outcomes = (
            CollectionOutcome("cologny", "success", "success", 1, "2026-09-29", "2026-10-06", None),
            CollectionOutcome(
                "collonge-bellerive",
                "failure",
                "error",
                0,
                "2026-09-29",
                "2026-10-06",
                "internal path /private/data",
            ),
        )
        for outcome in outcomes:
            on_outcome(outcome)
        return outcomes

    now = datetime(2026, 9, 29, 8, 0, tzinfo=UTC)
    coordinator = RefreshCoordinator(database_path, DATA, runner=runner)
    _queued, code = coordinator.request_manual(now=now)
    assert code == 202
    assert coordinator.run_pending_once(now=now + timedelta(seconds=1)) is True
    completed = coordinator.status(now=now + timedelta(seconds=2))
    assert completed.status == "partial"
    assert completed.completed_locations == 2
    assert completed.error == "One or more source collections failed."
