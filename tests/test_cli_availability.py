import sqlite3
import sys
from pathlib import Path

import pytest

from padel_availability import cli
from padel_availability.availability import (
    AvailabilityResult,
    AvailabilityRun,
    AvailabilitySlot,
)
from padel_availability.collector import CollectionOutcome
from padel_availability.connectors.playtomic import PlaytomicSource
from padel_availability.database import save_availability_result
from padel_availability.models import LocationRecord

ROOT = Path(__file__).parents[1]
PLAYTOMIC_IDS = (
    "gva-palexpo",
    "padel-parc-etoy",
    "padel-parc-preverenges",
    "padel-station",
    "vaudoise-arena",
)


def ready_catalog(database: Path) -> None:
    assert cli.main(["init-db", "--database", str(database)]) == 0
    assert cli.main(
        [
            "import-candidates",
            "--database",
            str(database),
            "--input",
            str(ROOT / "data/candidates.json"),
        ]
    ) == 0
    assert cli.main(
        [
            "build-catalog",
            "--database",
            str(database),
            "--candidates",
            str(ROOT / "data/candidates.json"),
            "--verified",
            str(ROOT / "data/verified_locations.json"),
            "--run-id",
            "inventory-test",
        ]
    ) == 0


def test_collect_playtomic_parser_defaults() -> None:
    arguments = cli._parser().parse_args(["collect-playtomic", "--database", "catalog.sqlite3"])

    assert arguments.sources == Path("data/playtomic_sources.json")
    assert arguments.location_id is None
    assert arguments.days == 14


def test_collect_playtomic_rejects_non_positive_days(tmp_path: Path) -> None:
    assert cli.main(
        [
            "collect-playtomic",
            "--database",
            str(tmp_path / "catalog.sqlite3"),
            "--days",
            "0",
        ]
    ) == 2


def test_collect_playtomic_prints_collector_outcomes_deterministically(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "catalog.sqlite3"
    ready_catalog(database)
    source_path = ROOT / "data/playtomic_sources.json"
    calls: list[tuple[frozenset[str], frozenset[str], int, str | None]] = []

    def fake_collect(
        connection: sqlite3.Connection,
        locations: tuple[LocationRecord, ...],
        sources: tuple[PlaytomicSource, ...],
        *,
        horizon_days: int,
        location_id: str | None,
    ) -> tuple[CollectionOutcome, ...]:
        calls.append(
            (
                frozenset(location.location_id for location in locations),
                frozenset(source.location_id for source in sources),
                horizon_days,
                location_id,
            )
        )
        outcomes = (
            CollectionOutcome(
                "gva-palexpo", "run-gva", "success", 3, "2030-01-02", "2030-01-16", None
            ),
            CollectionOutcome(
                "padel-parc-etoy",
                "run-etoy",
                "error",
                0,
                "2030-01-02",
                "2030-01-16",
                "temporary\nsource failure",
            ),
            CollectionOutcome(
                "padel-parc-preverenges",
                "run-preverenges",
                "unavailable",
                0,
                "2030-01-02",
                "2030-01-16",
                "no public availability feed was verified",
            ),
            CollectionOutcome(
                "padel-station", "run-station", "success", 2, "2030-01-02", "2030-01-16", None
            ),
            CollectionOutcome(
                "vaudoise-arena", "run-vaudoise", "success", 1, "2030-01-02", "2030-01-16", None
            ),
        )
        prior_success = AvailabilityRun(
            "prior-etoy",
            "padel-parc-etoy",
            "playtomic",
            "https://playtomic.example/padel-parc-etoy",
            "2030-01-02",
            "2030-01-16",
            14,
            "2029-12-01T00:00:00Z",
            "success",
            None,
        )
        prior_slot = AvailabilitySlot(
            "prior-etoy",
            "padel-parc-etoy",
            "prior-slot",
            "prior-slot",
            "Court 1",
            "2030-01-03T08:00:00Z",
            "2030-01-03T09:00:00Z",
            "Europe/Zurich",
            "available",
        )
        save_availability_result(connection, AvailabilityResult(prior_success, (prior_slot,)))
        for outcome in outcomes:
            run = AvailabilityRun(
                outcome.run_id,
                outcome.location_id,
                "playtomic",
                f"https://playtomic.example/{outcome.location_id}",
                outcome.window_start,
                outcome.window_end,
                14,
                "2030-01-02T00:00:00Z",
                outcome.status,
                outcome.error,
            )
            save_availability_result(connection, AvailabilityResult(run, ()))
        return outcomes

    monkeypatch.setattr(cli, "collect_playtomic", fake_collect)

    assert cli.main(
        [
            "collect-playtomic",
            "--database",
            str(database),
            "--sources",
            str(source_path),
            "--days",
            "14",
        ]
    ) == 0

    catalog_ids, source_ids, horizon_days, location_id = calls[0]
    assert set(PLAYTOMIC_IDS) <= catalog_ids
    assert source_ids == frozenset(PLAYTOMIC_IDS)
    assert (horizon_days, location_id) == (14, None)
    assert capsys.readouterr().out.splitlines() == [
        ("gva-palexpo status=success slots=3 window=2030-01-02..2030-01-16 "
         "error=none last_success=2030-01-02T00:00:00Z"),
        ("padel-parc-etoy status=stale slots=1 window=2030-01-02..2030-01-16 "
         "error=temporary source failure last_success=2029-12-01T00:00:00Z"),
        ("padel-parc-preverenges status=unavailable slots=0 "
         "window=2030-01-02..2030-01-16 error=no public availability feed was verified "
         "last_success=none"),
        ("padel-station status=success slots=2 window=2030-01-02..2030-01-16 "
         "error=none last_success=2030-01-02T00:00:00Z"),
        ("vaudoise-arena status=success slots=1 window=2030-01-02..2030-01-16 "
         "error=none last_success=2030-01-02T00:00:00Z"),
    ]


def test_collect_playtomic_can_select_one_location(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "catalog.sqlite3"
    ready_catalog(database)
    calls: list[str | None] = []

    def fake_collect(
        connection: sqlite3.Connection,
        locations: tuple[LocationRecord, ...],
        sources: tuple[PlaytomicSource, ...],
        *,
        horizon_days: int,
        location_id: str | None,
    ) -> tuple[CollectionOutcome, ...]:
        del connection, sources, horizon_days
        calls.append(location_id)
        assert set(PLAYTOMIC_IDS) <= {location.location_id for location in locations}
        return (
            CollectionOutcome(
                "padel-station",
                "run-station",
                "unavailable",
                0,
                "2030-02-01",
                "2030-02-15",
                "feed unavailable",
            ),
        )

    monkeypatch.setattr(cli, "collect_playtomic", fake_collect)

    assert cli.main(
        [
            "collect-playtomic",
            "--database",
            str(database),
            "--sources",
            str(ROOT / "data/playtomic_sources.json"),
            "--location-id",
            "padel-station",
        ]
    ) == 0

    assert calls == ["padel-station"]
    assert capsys.readouterr().out.splitlines() == [
        ("padel-station status=unavailable slots=0 window=2030-02-01..2030-02-15 "
         "error=feed unavailable last_success=none")
    ]


def test_collect_playtomic_returns_two_when_catalog_is_missing_locations(tmp_path: Path) -> None:
    database = tmp_path / "catalog.sqlite3"
    assert cli.main(["init-db", "--database", str(database)]) == 0

    assert cli.main(
        [
            "collect-playtomic",
            "--database",
            str(database),
            "--sources",
            str(ROOT / "data/playtomic_sources.json"),
        ]
    ) == 2


def test_collect_playtomic_reports_missing_playwright_with_setup_guidance(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "catalog.sqlite3"
    ready_catalog(database)
    calls: list[None] = []

    def missing_playwright(*_args: object, **_kwargs: object) -> tuple[CollectionOutcome, ...]:
        calls.append(None)
        return ()

    monkeypatch.setattr(cli, "collect_playtomic", missing_playwright)
    monkeypatch.setitem(sys.modules, "playwright", None)

    assert cli.main(
        [
            "collect-playtomic",
            "--database",
            str(database),
            "--sources",
            str(ROOT / "data/playtomic_sources.json"),
        ]
    ) == 2

    assert calls == []
    error = capsys.readouterr().err
    assert "uv sync --group browser" in error
    assert "uv run playwright install chromium" in error
