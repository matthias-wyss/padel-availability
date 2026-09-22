import sqlite3
import sys
import types
from dataclasses import replace
from pathlib import Path

import pytest

from padel_availability import cli
from padel_availability.availability import (
    AvailabilityResult,
    AvailabilityRun,
    AvailabilitySlot,
)
from padel_availability.collector import CollectionOutcome
from padel_availability.connectors.airpad import AirpadSource
from padel_availability.connectors.everness import EvernessSource
from padel_availability.connectors.playtomic import PlaytomicSource, load_playtomic_sources
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


def test_collect_playtomic_reports_partial_playwright_with_setup_guidance(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "catalog.sqlite3"
    ready_catalog(database)
    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    monkeypatch.delitem(sys.modules, "playwright.sync_api", raising=False)

    assert cli.main(
        [
            "collect-playtomic",
            "--database",
            str(database),
            "--sources",
            str(ROOT / "data/playtomic_sources.json"),
        ]
    ) == 2

    error = capsys.readouterr().err
    assert "uv sync --group browser" in error
    assert "uv run playwright install chromium" in error


def test_collect_playtomic_reports_missing_chromium_with_setup_guidance(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "catalog.sqlite3"
    ready_catalog(database)
    calls: list[None] = []

    def fake_collect(*_args: object, **_kwargs: object) -> tuple[CollectionOutcome, ...]:
        calls.append(None)
        return ()

    driver = types.SimpleNamespace(
        chromium=types.SimpleNamespace(executable_path=str(tmp_path / "missing-chromium")),
        stop=lambda: None,
    )
    sync_api = types.ModuleType("playwright.sync_api")
    sync_api.sync_playwright = lambda: types.SimpleNamespace(start=lambda: driver)  # type: ignore[attr-defined]
    monkeypatch.setattr(cli, "collect_playtomic", fake_collect)
    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api)

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


def test_collect_playtomic_reports_chromium_launch_failure_with_setup_guidance(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "catalog.sqlite3"
    ready_catalog(database)
    executable = tmp_path / "chromium"
    executable.touch()
    calls: list[None] = []
    launch_calls: list[dict[str, object]] = []
    stop_calls: list[None] = []

    def fake_launch(**kwargs: object) -> object:
        launch_calls.append(kwargs)
        raise RuntimeError("missing shared library")

    driver = types.SimpleNamespace(
        chromium=types.SimpleNamespace(
            executable_path=str(executable),
            launch=fake_launch,
        ),
        stop=lambda: stop_calls.append(None),
    )
    sync_api = types.ModuleType("playwright.sync_api")
    sync_api.sync_playwright = lambda: types.SimpleNamespace(start=lambda: driver)  # type: ignore[attr-defined]

    def fake_collect(*_args: object, **_kwargs: object) -> tuple[CollectionOutcome, ...]:
        calls.append(None)
        return ()

    monkeypatch.setattr(cli, "collect_playtomic", fake_collect)
    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api)

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
    assert launch_calls == [{"headless": True, "args": ["--disable-gpu", "--disable-dev-shm-usage"]}]
    assert stop_calls == [None]
    error = capsys.readouterr().err
    assert "uv sync --group browser" in error
    assert "uv run playwright install chromium" in error


def test_collect_playtomic_does_not_require_playwright_for_unavailable_source(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "catalog.sqlite3"
    ready_catalog(database)
    sources = tuple(
        replace(source, status="unavailable")
        if source.location_id == "padel-station"
        else source
        for source in load_playtomic_sources(ROOT / "data/playtomic_sources.json")
    )

    def unavailable_sources(_path: Path) -> tuple[PlaytomicSource, ...]:
        return sources

    monkeypatch.setattr(cli, "load_playtomic_sources", unavailable_sources)
    monkeypatch.setitem(sys.modules, "playwright", None)

    assert cli.main(
        [
            "collect-playtomic",
            "--database",
            str(database),
            "--location-id",
            "padel-station",
        ]
    ) == 0

    output = capsys.readouterr().out
    assert "padel-station status=unavailable" in output
    assert "error=public booking page is explicitly unavailable" in output


def test_collect_airpad_reports_outcomes(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "catalog.sqlite3"
    ready_catalog(database)
    calls: list[tuple[frozenset[str], frozenset[str], int, str | None]] = []

    def fake_collect(
        connection: sqlite3.Connection,
        locations: tuple[LocationRecord, ...],
        received_sources: tuple[AirpadSource, ...],
        *,
        horizon_days: int,
        location_id: str | None,
    ) -> tuple[CollectionOutcome, ...]:
        calls.append(
            (
                frozenset(location.location_id for location in locations),
                frozenset(source.location_id for source in received_sources),
                horizon_days,
                location_id,
            )
        )
        outcomes = (
            CollectionOutcome(
                "airpad-la-praille", "run-praille", "error", 0,
                "2030-01-02", "2030-01-16", "temporary source failure",
            ),
            CollectionOutcome(
                "airpad-les-acacias", "run-acacias", "success", 3,
                "2030-01-02", "2030-01-16", None,
            ),
            CollectionOutcome(
                "airpad-meyrin", "run-meyrin", "unavailable", 0,
                "2030-01-02", "2030-01-16", "public AIRPAD booking page is unavailable",
            ),
            CollectionOutcome(
                "airpad-plan-les-ouates", "run-plan", "success", 1,
                "2030-01-02", "2030-01-16", None,
            ),
        )
        prior_run = AvailabilityRun(
            "prior-praille", "airpad-la-praille", "airpad_browser",
            "https://www.airpad.ch/reserve", "2030-01-02", "2030-01-16", 14,
            "2029-12-01T00:00:00Z", "success", None,
        )
        prior_slot = AvailabilitySlot(
            "prior-praille", "airpad-la-praille", "prior-slot", "prior-slot",
            "Court 1", "2030-01-03T08:00:00Z", "2030-01-03T09:00:00Z",
            "Europe/Zurich", "available",
        )
        save_availability_result(connection, AvailabilityResult(prior_run, (prior_slot,)))
        for outcome in outcomes:
            run = AvailabilityRun(
                outcome.run_id, outcome.location_id, "airpad_browser",
                "https://www.airpad.ch/reserve", outcome.window_start, outcome.window_end,
                14, "2030-01-02T00:00:00Z", outcome.status, outcome.error,
            )
            save_availability_result(connection, AvailabilityResult(run, ()))
        return outcomes

    monkeypatch.setattr(cli, "collect_airpad", fake_collect)
    monkeypatch.setattr(cli, "_check_playwright_runtime", lambda: None)

    assert cli.main(
        [
            "collect-airpad",
            "--database",
            str(database),
            "--sources",
            str(ROOT / "data/airpad_sources.json"),
            "--days",
            "14",
        ]
    ) == 0

    catalog_ids, source_ids, horizon_days, location_id = calls[0]
    assert catalog_ids >= {
        "airpad-la-praille",
        "airpad-les-acacias",
        "airpad-meyrin",
        "airpad-plan-les-ouates",
    }
    assert source_ids == frozenset(
        {
            "airpad-la-praille",
            "airpad-les-acacias",
            "airpad-meyrin",
            "airpad-plan-les-ouates",
        }
    )
    assert (horizon_days, location_id) == (14, None)
    assert capsys.readouterr().out.splitlines() == [
        ("airpad-la-praille status=stale slots=1 window=2030-01-02..2030-01-16 "
         "error=temporary source failure last_success=2029-12-01T00:00:00Z"),
        ("airpad-les-acacias status=success slots=3 window=2030-01-02..2030-01-16 "
         "error=none last_success=2030-01-02T00:00:00Z"),
        ("airpad-meyrin status=unavailable slots=0 window=2030-01-02..2030-01-16 "
         "error=public AIRPAD booking page is unavailable last_success=none"),
        ("airpad-plan-les-ouates status=success slots=1 window=2030-01-02..2030-01-16 "
         "error=none last_success=2030-01-02T00:00:00Z"),
    ]


def test_collect_airpad_can_select_one_location(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "catalog.sqlite3"
    ready_catalog(database)
    calls: list[tuple[frozenset[str], int, str | None]] = []

    def fake_collect(
        connection: sqlite3.Connection,
        locations: tuple[LocationRecord, ...],
        sources: tuple[AirpadSource, ...],
        *,
        horizon_days: int,
        location_id: str | None,
    ) -> tuple[CollectionOutcome, ...]:
        del connection
        calls.append(
            (
                frozenset(source.location_id for source in sources),
                horizon_days,
                location_id,
            )
        )
        assert location_id == "airpad-meyrin"
        return (
            CollectionOutcome(
                "airpad-meyrin",
                "run-meyrin",
                "success",
                2,
                "2030-01-02",
                "2030-01-16",
                None,
            ),
        )

    monkeypatch.setattr(cli, "collect_airpad", fake_collect)
    monkeypatch.setattr(cli, "_check_playwright_runtime", lambda: None)

    assert cli.main(
        [
            "collect-airpad",
            "--database",
            str(database),
            "--sources",
            str(ROOT / "data/airpad_sources.json"),
            "--location-id",
            "airpad-meyrin",
        ]
    ) == 0

    assert len(calls) == 1
    source_ids, horizon_days, location_id = calls[0]
    assert source_ids == {
        "airpad-la-praille",
        "airpad-les-acacias",
        "airpad-meyrin",
        "airpad-plan-les-ouates",
    }
    assert (horizon_days, location_id) == (14, "airpad-meyrin")
    assert capsys.readouterr().out.splitlines() == [
        ("airpad-meyrin status=success slots=2 window=2030-01-02..2030-01-16 "
         "error=none last_success=none"),
    ]


def test_collect_airpad_rejects_non_positive_days(tmp_path: Path) -> None:
    assert cli.main(
        [
            "collect-airpad",
            "--database",
            str(tmp_path / "catalog.sqlite3"),
            "--days",
            "0",
        ]
    ) == 2


def test_collect_airpad_reports_missing_playwright_with_setup_guidance(
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

    monkeypatch.setattr(cli, "collect_airpad", missing_playwright)
    monkeypatch.setitem(sys.modules, "playwright", None)

    assert cli.main(
        [
            "collect-airpad",
            "--database",
            str(database),
            "--sources",
            str(ROOT / "data/airpad_sources.json"),
        ]
    ) == 2

    assert calls == []
    error = capsys.readouterr().err
    assert "uv sync --group browser" in error
    assert "uv run playwright install chromium" in error


def _everness_source() -> EvernessSource:
    return EvernessSource(
        "everness",
        "https://padel.everness.ch/",
        "2026-09-22T00:00:00Z",
        "public",
    )


def test_collect_everness_reports_outcomes(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "catalog.sqlite3"
    ready_catalog(database)
    calls: list[tuple[frozenset[str], frozenset[str], int, str | None]] = []
    loaded_paths: list[Path] = []

    def fake_load(path: Path) -> tuple[EvernessSource, ...]:
        loaded_paths.append(path)
        return (_everness_source(),)

    def fake_collect(
        connection: sqlite3.Connection,
        locations: tuple[LocationRecord, ...],
        sources: tuple[EvernessSource, ...],
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
        prior_run = AvailabilityRun(
            "prior-everness",
            "everness",
            "everness_browser",
            "https://padel.everness.ch/",
            "2030-01-02",
            "2030-01-16",
            14,
            "2029-12-01T00:00:00Z",
            "success",
            None,
        )
        prior_slot = AvailabilitySlot(
            "prior-everness",
            "everness",
            "prior-slot",
            "prior-slot",
            "Court 1",
            "2030-01-03T08:00:00Z",
            "2030-01-03T09:00:00Z",
            "Europe/Zurich",
            "available",
        )
        save_availability_result(connection, AvailabilityResult(prior_run, (prior_slot,)))
        outcome = CollectionOutcome(
            "everness",
            "run-everness",
            "error",
            0,
            "2030-01-02",
            "2030-01-16",
            "temporary source failure",
        )
        save_availability_result(
            connection,
            AvailabilityResult(
                AvailabilityRun(
                    outcome.run_id,
                    outcome.location_id,
                    "everness_browser",
                    "https://padel.everness.ch/",
                    outcome.window_start,
                    outcome.window_end,
                    14,
                    "2030-01-02T00:00:00Z",
                    outcome.status,
                    outcome.error,
                ),
                (),
            ),
        )
        return (outcome,)

    monkeypatch.setattr(cli, "load_everness_sources", fake_load)
    monkeypatch.setattr(cli, "collect_everness", fake_collect)
    monkeypatch.setattr(cli, "_check_playwright_runtime", lambda: None)

    assert cli.main(["collect-everness", "--database", str(database)]) == 0

    catalog_ids, source_ids, horizon_days, location_id = calls[0]
    assert "everness" in catalog_ids
    assert source_ids == frozenset({"everness"})
    assert (horizon_days, location_id) == (14, None)
    assert loaded_paths == [Path("data/everness_sources.json")]
    assert "everness status=stale slots=1 window=2030-01-02..2030-01-16 " \
        "error=temporary source failure last_success=2029-12-01T00:00:00Z" in capsys.readouterr().out


def test_collect_everness_selects_exact_location(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "catalog.sqlite3"
    ready_catalog(database)
    calls: list[tuple[frozenset[str], int, str | None]] = []

    def fake_collect(
        connection: sqlite3.Connection,
        locations: tuple[LocationRecord, ...],
        sources: tuple[EvernessSource, ...],
        *,
        horizon_days: int,
        location_id: str | None,
    ) -> tuple[CollectionOutcome, ...]:
        del connection
        calls.append((frozenset(source.location_id for source in sources), horizon_days, location_id))
        assert {location.location_id for location in locations} >= {"everness"}
        return (CollectionOutcome("everness", "run-everness", "success", 2, "2030-01-02", "2030-01-16", None),)

    def fake_load(_path: Path) -> tuple[EvernessSource, ...]:
        return (_everness_source(),)

    monkeypatch.setattr(cli, "collect_everness", fake_collect)
    monkeypatch.setattr(cli, "load_everness_sources", fake_load)
    monkeypatch.setattr(cli, "_check_playwright_runtime", lambda: None)

    assert cli.main(
        [
            "collect-everness",
            "--database",
            str(database),
            "--location-id",
            "everness",
        ]
    ) == 0

    assert calls == [(frozenset({"everness"}), 14, "everness")]
    assert capsys.readouterr().out.splitlines() == [
        (
            "everness status=success slots=2 window=2030-01-02..2030-01-16 "
            "error=none last_success=none"
        )
    ]


def test_collect_everness_rejects_non_positive_days(tmp_path: Path) -> None:
    assert cli.main(
        [
            "collect-everness",
            "--database",
            str(tmp_path / "catalog.sqlite3"),
            "--days",
            "0",
        ]
    ) == 2


def test_collect_everness_reports_missing_playwright_with_setup_guidance(
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

    def fake_load(_path: Path) -> tuple[EvernessSource, ...]:
        return (_everness_source(),)

    monkeypatch.setattr(cli, "collect_everness", missing_playwright)
    monkeypatch.setattr(cli, "load_everness_sources", fake_load)
    monkeypatch.setitem(sys.modules, "playwright", None)

    assert cli.main(
        [
            "collect-everness",
            "--database",
            str(database),
        ]
    ) == 2

    assert calls == []
    error = capsys.readouterr().err
    assert "uv sync --group browser" in error
    assert "uv run playwright install chromium" in error
