import importlib
import json
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, date, datetime
from operator import attrgetter
from pathlib import Path
from typing import cast
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import pytest

from padel_availability.availability import (
    AvailabilityResult,
    AvailabilityRun,
    AvailabilityRunStatus,
    AvailabilitySlot,
    local_window,
)
from padel_availability.collector import (
    CollectionOutcome,
    collect_airpad,
    collect_everness,
    collect_padelfirst,
    collect_playtomic,
    collect_plugin,
)
from padel_availability.connectors.airpad import (
    AirpadSource,
    AirpadSourceError,
    load_airpad_sources,
)
from padel_availability.connectors.airpad_browser import (
    AirpadBrowserConnectorFactory,
    AirpadBrowserError,
)
from padel_availability.connectors.everness import (
    EvernessSource,
    EvernessSourceError,
    load_everness_sources,
)
from padel_availability.connectors.everness_browser import (
    EvernessBrowserConnectorFactory,
    EvernessBrowserError,
)
from padel_availability.connectors.matchpoint import (
    MatchpointSource,
    load_matchpoint_sources,
)
from padel_availability.connectors.matchpoint_browser import (
    MatchpointBrowserConnectorFactory,
    MatchpointBrowserError,
)
from padel_availability.connectors.padelfirst import (
    PadelFirstSource,
    load_padelfirst_sources,
)
from padel_availability.connectors.padelfirst_browser import (
    PadelFirstBrowserConnectorFactory,
    PadelFirstBrowserError,
)
from padel_availability.connectors.playtomic import (
    PlaytomicSource,
    PlaytomicSourceError,
    load_playtomic_sources,
)
from padel_availability.connectors.playtomic_browser import (
    BrowserConnectorFactory,
    PlaytomicBrowserError,
)
from padel_availability.connectors.plugin import (
    PLUGIN_LOCATION_IDS,
    PluginSource,
    load_plugin_sources,
)
from padel_availability.connectors.plugin_browser import (
    PluginBrowserConnectorFactory,
    PluginBrowserError,
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
AIRPAD_IDS = (
    "airpad-la-praille",
    "airpad-les-acacias",
    "airpad-meyrin",
    "airpad-plan-les-ouates",
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
            transport="json",
            availability_url_template=(
                f"https://fixtures.example/{source.location_id}"
                "?from={window_start}&to={window_end}"
            ),
            status="public",
        )
        for source in manifest_sources
    )


def four_airpad_locations() -> tuple[LocationRecord, ...]:
    locations = load_locations(ROOT / "data/verified_locations.json")
    by_id = {location.location_id: location for location in locations}
    return tuple(by_id[location_id] for location_id in AIRPAD_IDS)


def four_airpad_sources() -> tuple[AirpadSource, ...]:
    return load_airpad_sources(ROOT / "data/airpad_sources.json")


def everness_location() -> LocationRecord:
    return next(
        location
        for location in load_locations(ROOT / "data/verified_locations.json")
        if location.location_id == "everness"
    )


def everness_sources() -> tuple[EvernessSource, ...]:
    return load_everness_sources(ROOT / "data/everness_sources.json")


def mixed_playtomic_sources() -> tuple[PlaytomicSource, ...]:
    browser_ids = {"gva-palexpo", "padel-parc-etoy", "padel-station"}
    return tuple(
        replace(
            source,
            transport="browser_dom",
            availability_url_template=None,
        )
        if source.location_id in browser_ids
        else source
        for source in five_playtomic_sources()
    )


def browser_result(
    location: LocationRecord,
    source: PlaytomicSource,
    *,
    run_id: str,
    window_start: date,
    window_end: date,
    collected_at: str,
    status: AvailabilityRunStatus = "success",
    slots: tuple[AvailabilitySlot, ...] = (),
    error: str | None = None,
) -> AvailabilityResult:
    return AvailabilityResult(
        AvailabilityRun(
            run_id,
            location.location_id,
            "playtomic_browser",
            source.booking_url,
            window_start.isoformat(),
            window_end.isoformat(),
            (window_end - window_start).days,
            collected_at,
            status,
            error,
        ),
        slots,
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


def ready_airpad_database(tmp_path: Path) -> sqlite3.Connection:
    connection = connect(tmp_path / "catalog.sqlite3")
    initialize(connection)
    locations = four_airpad_locations()
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


def ready_everness_database(tmp_path: Path) -> sqlite3.Connection:
    connection = connect(tmp_path / "catalog.sqlite3")
    initialize(connection)
    candidates = load_candidates(ROOT / "data/candidates.json")
    insert_candidates(
        connection,
        tuple(candidate for candidate in candidates if candidate.candidate_id == "everness"),
    )
    upsert_location(connection, everness_location())
    return connection


def padelfirst_location() -> LocationRecord:
    return next(
        location
        for location in load_locations(ROOT / "data/verified_locations.json")
        if location.location_id == "vernier"
    )


def padelfirst_sources() -> tuple[PadelFirstSource, ...]:
    return load_padelfirst_sources(ROOT / "data/padelfirst_sources.json")


def ready_padelfirst_database(tmp_path: Path) -> sqlite3.Connection:
    connection = connect(tmp_path / "catalog.sqlite3")
    initialize(connection)
    candidates = load_candidates(ROOT / "data/candidates.json")
    insert_candidates(
        connection,
        tuple(candidate for candidate in candidates if candidate.candidate_id == "vernier"),
    )
    upsert_location(connection, padelfirst_location())
    return connection


def matchpoint_locations() -> tuple[LocationRecord, ...]:
    locations = load_locations(ROOT / "data/verified_locations.json")
    by_id = {location.location_id: location for location in locations}
    return tuple(
        by_id[location_id]
        for location_id in (
            "asphalte-jonction",
            "bernex",
            "evaux",
            "urban-padel-lausanne",
        )
    )


def matchpoint_sources() -> tuple[MatchpointSource, ...]:
    return load_matchpoint_sources(ROOT / "data/matchpoint_sources.json")


def ready_matchpoint_database(tmp_path: Path) -> sqlite3.Connection:
    connection = connect(tmp_path / "catalog.sqlite3")
    initialize(connection)
    locations = matchpoint_locations()
    candidate_ids = {
        candidate_id for location in locations for candidate_id in location.candidate_ids
    }
    candidates = load_candidates(ROOT / "data/candidates.json")
    insert_candidates(
        connection,
        tuple(candidate for candidate in candidates if candidate.candidate_id in candidate_ids),
    )
    for location in locations:
        upsert_location(connection, location)
    return connection


def plugin_locations() -> tuple[LocationRecord, ...]:
    locations = load_locations(ROOT / "data/verified_locations.json")
    by_id = {location.location_id: location for location in locations}
    return tuple(by_id[location_id] for location_id in sorted(PLUGIN_LOCATION_IDS))


def plugin_sources() -> tuple[PluginSource, ...]:
    return load_plugin_sources(ROOT / "data/plugin_sources.json")


def ready_plugin_database(tmp_path: Path) -> sqlite3.Connection:
    connection = connect(tmp_path / "catalog.sqlite3")
    initialize(connection)
    locations = plugin_locations()
    candidate_ids = {
        candidate_id for location in locations for candidate_id in location.candidate_ids
    }
    candidates = load_candidates(ROOT / "data/candidates.json")
    insert_candidates(
        connection,
        tuple(candidate for candidate in candidates if candidate.candidate_id in candidate_ids),
    )
    for location in locations:
        upsert_location(connection, location)
    return connection


def _plugin_result(
    location: LocationRecord,
    source: PluginSource,
    *,
    run_id: str,
    window_start: date,
    window_end: date,
    collected_at: str,
    status: AvailabilityRunStatus = "success",
    slots: tuple[AvailabilitySlot, ...] = (),
    error: str | None = None,
) -> AvailabilityResult:
    return AvailabilityResult(
        AvailabilityRun(
            run_id,
            location.location_id,
            "plugin_browser",
            source.booking_url,
            window_start.isoformat(),
            window_end.isoformat(),
            (window_end - window_start).days,
            collected_at,
            status,
            error,
        ),
        slots,
    )


def _collect_matchpoint(
    connection: sqlite3.Connection,
    locations: Sequence[LocationRecord],
    sources: Sequence[MatchpointSource],
    *,
    now: datetime | None = None,
    horizon_days: int = 14,
    location_id: str | None = None,
    browser_connector_factory: MatchpointBrowserConnectorFactory | None = None,
) -> tuple[CollectionOutcome, ...]:
    collector_module = importlib.import_module("padel_availability.collector")
    collect = cast(
        Callable[..., tuple[CollectionOutcome, ...]],
        attrgetter("collect_matchpoint")(collector_module),
    )
    return collect(
        connection,
        locations,
        sources,
        now=now,
        horizon_days=horizon_days,
        location_id=location_id,
        browser_connector_factory=browser_connector_factory,
    )


def _matchpoint_result(
    location: LocationRecord,
    source: MatchpointSource,
    *,
    run_id: str,
    window_start: date,
    window_end: date,
    collected_at: str,
    status: AvailabilityRunStatus = "success",
    slots: tuple[AvailabilitySlot, ...] = (),
    error: str | None = None,
) -> AvailabilityResult:
    return AvailabilityResult(
        AvailabilityRun(
            run_id,
            location.location_id,
            "matchpoint_browser",
            source.booking_url,
            window_start.isoformat(),
            window_end.isoformat(),
            (window_end - window_start).days,
            collected_at,
            status,
            error,
        ),
        slots,
    )


def fixture_fetch_json(url: str) -> object:
    location_id = urlparse(url).path.rsplit("/", 1)[-1]
    return read_fixture(location_id)


def airpad_result(
    location: LocationRecord,
    source: AirpadSource,
    *,
    run_id: str,
    window_start: date,
    window_end: date,
    collected_at: str,
    status: AvailabilityRunStatus = "success",
    slots: tuple[AvailabilitySlot, ...] = (),
    error: str | None = None,
) -> AvailabilityResult:
    return AvailabilityResult(
        AvailabilityRun(
            run_id,
            location.location_id,
            "airpad_browser",
            source.booking_url,
            window_start.isoformat(),
            window_end.isoformat(),
            (window_end - window_start).days,
            collected_at,
            status,
            error,
        ),
        slots,
    )


def test_airpad_collection_runs_all_four_sites(tmp_path: Path) -> None:
    connection = ready_airpad_database(tmp_path)
    locations = four_airpad_locations()
    sources = four_airpad_sources()
    sources_by_id = {source.location_id: source for source in sources}
    browser_calls: list[str] = []
    lifecycle: list[str] = []

    def browser_factory(received_sources: Sequence[AirpadSource]):
        assert received_sources == sources

        class FakeBrowserConnector:
            def open(self) -> None:
                lifecycle.append("open")

            def close(self) -> None:
                lifecycle.append("close")

            def collect(
                self,
                location: LocationRecord,
                *,
                run_id: str,
                window_start: date,
                window_end: date,
                collected_at: str,
            ) -> AvailabilityResult:
                browser_calls.append(location.location_id)
                return airpad_result(
                    location,
                    sources_by_id[location.location_id],
                    run_id=run_id,
                    window_start=window_start,
                    window_end=window_end,
                    collected_at=collected_at,
                )

        return FakeBrowserConnector()

    try:
        outcomes = collect_airpad(
            connection,
            locations,
            sources,
            now=datetime(2026, 9, 22, 9, 0, tzinfo=ZURICH),
            browser_connector_factory=cast(AirpadBrowserConnectorFactory, browser_factory),
        )

        assert [outcome.location_id for outcome in outcomes] == list(AIRPAD_IDS)
        assert [outcome.status for outcome in outcomes] == ["success"] * 4
        assert browser_calls == list(AIRPAD_IDS)
        assert lifecycle == ["open", "close"]
        assert len(list_availability_runs(connection)) == 4
    finally:
        connection.close()


def test_airpad_collection_rejects_missing_catalog_location(tmp_path: Path) -> None:
    connection = ready_airpad_database(tmp_path)
    locations = tuple(
        location for location in four_airpad_locations() if location.location_id != "airpad-meyrin"
    )

    try:
        with pytest.raises(
            ValueError,
            match="catalog is missing AIRPAD locations: airpad-meyrin",
        ):
            collect_airpad(connection, locations, four_airpad_sources())
    finally:
        connection.close()


def test_airpad_collection_rejects_unknown_location_id(tmp_path: Path) -> None:
    connection = ready_airpad_database(tmp_path)

    try:
        with pytest.raises(ValueError, match="unknown AIRPAD location: padel-station"):
            collect_airpad(
                connection,
                four_airpad_locations(),
                four_airpad_sources(),
                location_id="padel-station",
            )
    finally:
        connection.close()


def test_airpad_collection_selects_one_site_and_uses_zurich_window(tmp_path: Path) -> None:
    connection = ready_airpad_database(tmp_path)
    locations = four_airpad_locations()
    sources = four_airpad_sources()
    calls: list[str] = []

    def browser_factory(_: Sequence[AirpadSource]):
        class FakeBrowserConnector:
            def open(self) -> None:
                pass

            def close(self) -> None:
                pass

            def collect(
                self,
                location: LocationRecord,
                *,
                run_id: str,
                window_start: date,
                window_end: date,
                collected_at: str,
            ) -> AvailabilityResult:
                calls.append(location.location_id)
                return airpad_result(
                    location,
                    next(
                        source for source in sources if source.location_id == location.location_id
                    ),
                    run_id=run_id,
                    window_start=window_start,
                    window_end=window_end,
                    collected_at=collected_at,
                )

        return FakeBrowserConnector()

    try:
        outcomes = collect_airpad(
            connection,
            locations,
            sources,
            now=datetime(2026, 9, 22, 23, 30, tzinfo=UTC),
            horizon_days=2,
            location_id="airpad-meyrin",
            browser_connector_factory=cast(AirpadBrowserConnectorFactory, browser_factory),
        )

        assert calls == ["airpad-meyrin"]
        assert len(outcomes) == 1
        assert outcomes[0].window_start == "2026-09-23"
        assert outcomes[0].window_end == "2026-09-25"
    finally:
        connection.close()


def test_airpad_error_is_persisted_and_other_sites_continue(tmp_path: Path) -> None:
    connection = ready_airpad_database(tmp_path)
    locations = four_airpad_locations()
    sources = four_airpad_sources()
    sources_by_id = {source.location_id: source for source in sources}

    def browser_factory(_: Sequence[AirpadSource]):
        class FakeBrowserConnector:
            def open(self) -> None:
                pass

            def close(self) -> None:
                pass

            def collect(
                self,
                location: LocationRecord,
                *,
                run_id: str,
                window_start: date,
                window_end: date,
                collected_at: str,
            ) -> AvailabilityResult:
                if location.location_id == "airpad-meyrin":
                    assert len(list_availability_runs(connection)) == 2
                    raise AirpadBrowserError("DOM failed")
                return airpad_result(
                    location,
                    sources_by_id[location.location_id],
                    run_id=run_id,
                    window_start=window_start,
                    window_end=window_end,
                    collected_at=collected_at,
                )

        return FakeBrowserConnector()

    try:
        outcomes = collect_airpad(
            connection,
            locations,
            sources,
            now=datetime(2026, 9, 22, 9, 0, tzinfo=ZURICH),
            browser_connector_factory=cast(AirpadBrowserConnectorFactory, browser_factory),
        )

        failed = next(outcome for outcome in outcomes if outcome.location_id == "airpad-meyrin")
        assert failed.status == "error"
        assert failed.error == "DOM failed"
        assert len(list_availability_runs(connection)) == 4
        assert len(list_availability_runs(connection, "airpad-plan-les-ouates")) == 1
    finally:
        connection.close()


def test_airpad_failed_run_keeps_previous_snapshot_stale(tmp_path: Path) -> None:
    connection = ready_airpad_database(tmp_path)
    locations = four_airpad_locations()
    sources = four_airpad_sources()
    source = next(source for source in sources if source.location_id == "airpad-meyrin")
    attempts = 0

    def browser_factory(_: Sequence[AirpadSource]):
        class FakeBrowserConnector:
            def open(self) -> None:
                pass

            def close(self) -> None:
                pass

            def collect(
                self,
                location: LocationRecord,
                *,
                run_id: str,
                window_start: date,
                window_end: date,
                collected_at: str,
            ) -> AvailabilityResult:
                nonlocal attempts
                attempts += 1
                if attempts == 2:
                    raise AirpadSourceError("temporary source failure")
                slot = AvailabilitySlot(
                    run_id,
                    location.location_id,
                    "meyrin-slot",
                    "meyrin-slot",
                    "Court 1",
                    "2026-09-22T08:00:00Z",
                    "2026-09-22T09:00:00Z",
                    "Europe/Zurich",
                    "available",
                )
                return airpad_result(
                    location,
                    source,
                    run_id=run_id,
                    window_start=window_start,
                    window_end=window_end,
                    collected_at=collected_at,
                    slots=(slot,),
                )

        return FakeBrowserConnector()

    try:
        collect_airpad(
            connection,
            (next(location for location in locations if location.location_id == "airpad-meyrin"),),
            (source,),
            now=datetime(2026, 9, 22, 9, 0, tzinfo=ZURICH),
            location_id="airpad-meyrin",
            browser_connector_factory=cast(AirpadBrowserConnectorFactory, browser_factory),
        )
        outcomes = collect_airpad(
            connection,
            locations,
            sources,
            now=datetime(2026, 9, 22, 10, 0, tzinfo=ZURICH),
            location_id="airpad-meyrin",
            browser_connector_factory=cast(AirpadBrowserConnectorFactory, browser_factory),
        )

        assert outcomes[0].status == "error"
        snapshot = get_availability_snapshot(connection, "airpad-meyrin")
        assert snapshot is not None
        assert snapshot.status == "stale"
        assert len(snapshot.slots) == 1
        assert snapshot.latest_run.status == "error"
    finally:
        connection.close()


def test_airpad_browser_opens_once_and_closes_after_collection(tmp_path: Path) -> None:
    connection = ready_airpad_database(tmp_path)
    locations = four_airpad_locations()
    sources = four_airpad_sources()
    lifecycle: list[str] = []

    def browser_factory(_: Sequence[AirpadSource]):
        class FakeBrowserConnector:
            def open(self) -> None:
                lifecycle.append("open")

            def close(self) -> None:
                lifecycle.append("close")

            def collect(
                self,
                location: LocationRecord,
                *,
                run_id: str,
                window_start: date,
                window_end: date,
                collected_at: str,
            ) -> AvailabilityResult:
                assert lifecycle == ["open"]
                source = next(
                    source for source in sources if source.location_id == location.location_id
                )
                return airpad_result(
                    location,
                    source,
                    run_id=run_id,
                    window_start=window_start,
                    window_end=window_end,
                    collected_at=collected_at,
                )

        return FakeBrowserConnector()

    try:
        collect_airpad(
            connection,
            locations,
            sources,
            now=datetime(2026, 9, 22, 9, 0, tzinfo=ZURICH),
            browser_connector_factory=cast(AirpadBrowserConnectorFactory, browser_factory),
        )
        assert lifecycle == ["open", "close"]
    finally:
        connection.close()


def test_airpad_browser_startup_error_is_persisted_for_each_site(tmp_path: Path) -> None:
    connection = ready_airpad_database(tmp_path)
    locations = four_airpad_locations()
    sources = four_airpad_sources()
    lifecycle: list[str] = []

    def browser_factory(_: Sequence[AirpadSource]):
        class FakeBrowserConnector:
            def open(self) -> None:
                lifecycle.append("open")
                raise AirpadBrowserError("browser startup failed")

            def close(self) -> None:
                lifecycle.append("close")

            def collect(
                self,
                location: LocationRecord,
                *,
                run_id: str,
                window_start: date,
                window_end: date,
                collected_at: str,
            ) -> AvailabilityResult:
                del location, run_id, window_start, window_end, collected_at
                raise AssertionError("collect should not run after browser startup failed")

        return FakeBrowserConnector()

    try:
        outcomes = collect_airpad(
            connection,
            locations,
            sources,
            now=datetime(2026, 9, 22, 9, 0, tzinfo=ZURICH),
            browser_connector_factory=cast(AirpadBrowserConnectorFactory, browser_factory),
        )

        assert lifecycle == ["open", "close"]
        assert [outcome.location_id for outcome in outcomes] == list(AIRPAD_IDS)
        assert [outcome.status for outcome in outcomes] == ["error"] * 4
        assert [outcome.error for outcome in outcomes] == ["browser startup failed"] * 4
        assert len(list_availability_runs(connection)) == 4
    finally:
        connection.close()


def everness_result(
    location: LocationRecord,
    source: EvernessSource,
    *,
    run_id: str,
    window_start: date,
    window_end: date,
    collected_at: str,
    status: AvailabilityRunStatus = "success",
    slots: tuple[AvailabilitySlot, ...] = (),
    error: str | None = None,
) -> AvailabilityResult:
    return AvailabilityResult(
        AvailabilityRun(
            run_id,
            location.location_id,
            "everness_browser",
            source.booking_url,
            window_start.isoformat(),
            window_end.isoformat(),
            (window_end - window_start).days,
            collected_at,
            status,
            error,
        ),
        slots,
    )


def padelfirst_result(
    location: LocationRecord,
    source: PadelFirstSource,
    *,
    run_id: str,
    window_start: date,
    window_end: date,
    collected_at: str,
    status: AvailabilityRunStatus = "success",
    slots: tuple[AvailabilitySlot, ...] = (),
    error: str | None = None,
) -> AvailabilityResult:
    return AvailabilityResult(
        AvailabilityRun(
            run_id,
            location.location_id,
            "padelfirst_browser",
            source.booking_url,
            window_start.isoformat(),
            window_end.isoformat(),
            (window_end - window_start).days,
            collected_at,
            status,
            error,
        ),
        slots,
    )


def test_everness_collection_runs_exact_location(tmp_path: Path) -> None:
    connection = ready_everness_database(tmp_path)
    location = everness_location()
    sources = everness_sources()
    factory_sources: list[Sequence[EvernessSource]] = []
    calls: list[str] = []

    def browser_factory(received_sources: Sequence[EvernessSource]):
        factory_sources.append(received_sources)

        class FakeBrowserConnector:
            def open(self) -> None:
                pass

            def close(self) -> None:
                pass

            def collect(
                self,
                received_location: LocationRecord,
                *,
                run_id: str,
                window_start: date,
                window_end: date,
                collected_at: str,
            ) -> AvailabilityResult:
                calls.append(received_location.location_id)
                return everness_result(
                    received_location,
                    sources[0],
                    run_id=run_id,
                    window_start=window_start,
                    window_end=window_end,
                    collected_at=collected_at,
                )

        return FakeBrowserConnector()

    try:
        outcomes = collect_everness(
            connection,
            (location,),
            sources,
            now=datetime(2026, 9, 22, 9, 0, tzinfo=ZURICH),
            browser_connector_factory=cast(EvernessBrowserConnectorFactory, browser_factory),
        )

        assert factory_sources == [sources]
        assert calls == ["everness"]
        assert [outcome.location_id for outcome in outcomes] == ["everness"]
        assert outcomes[0].status == "success"
        assert len(list_availability_runs(connection)) == 1
    finally:
        connection.close()


def test_everness_collection_uses_zurich_window(tmp_path: Path) -> None:
    connection = ready_everness_database(tmp_path)
    location = everness_location()
    sources = everness_sources()
    observed: list[tuple[date, date, str]] = []

    def browser_factory(_: Sequence[EvernessSource]):
        class FakeBrowserConnector:
            def open(self) -> None:
                pass

            def close(self) -> None:
                pass

            def collect(
                self,
                received_location: LocationRecord,
                *,
                run_id: str,
                window_start: date,
                window_end: date,
                collected_at: str,
            ) -> AvailabilityResult:
                observed.append((window_start, window_end, collected_at))
                return everness_result(
                    received_location,
                    sources[0],
                    run_id=run_id,
                    window_start=window_start,
                    window_end=window_end,
                    collected_at=collected_at,
                )

        return FakeBrowserConnector()

    try:
        collect_everness(
            connection,
            (location,),
            sources,
            now=datetime(2026, 9, 22, 23, 30, tzinfo=UTC),
            horizon_days=2,
            browser_connector_factory=cast(EvernessBrowserConnectorFactory, browser_factory),
        )
        assert observed == [(date(2026, 9, 23), date(2026, 9, 25), "2026-09-22T23:30:00Z")]
    finally:
        connection.close()


def test_everness_error_is_persisted_and_snapshot_is_stale(tmp_path: Path) -> None:
    connection = ready_everness_database(tmp_path)
    location = everness_location()
    sources = everness_sources()
    attempts = 0

    def browser_factory(_: Sequence[EvernessSource]):
        class FakeBrowserConnector:
            def open(self) -> None:
                pass

            def close(self) -> None:
                pass

            def collect(
                self,
                received_location: LocationRecord,
                *,
                run_id: str,
                window_start: date,
                window_end: date,
                collected_at: str,
            ) -> AvailabilityResult:
                nonlocal attempts
                attempts += 1
                if attempts == 2:
                    assert len(list_availability_runs(connection)) == 1
                    raise EvernessSourceError("temporary Everness failure")
                slot = AvailabilitySlot(
                    run_id,
                    received_location.location_id,
                    "everness-slot",
                    "everness-slot",
                    "Court 1",
                    "2026-09-22T08:00:00Z",
                    "2026-09-22T09:00:00Z",
                    "Europe/Zurich",
                    "available",
                )
                return everness_result(
                    received_location,
                    sources[0],
                    run_id=run_id,
                    window_start=window_start,
                    window_end=window_end,
                    collected_at=collected_at,
                    slots=(slot,),
                )

        return FakeBrowserConnector()

    try:
        collect_everness(
            connection,
            (location,),
            sources,
            now=datetime(2026, 9, 22, 9, 0, tzinfo=ZURICH),
            location_id="everness",
            browser_connector_factory=cast(EvernessBrowserConnectorFactory, browser_factory),
        )
        outcomes = collect_everness(
            connection,
            (location,),
            sources,
            now=datetime(2026, 9, 22, 10, 0, tzinfo=ZURICH),
            location_id="everness",
            browser_connector_factory=cast(EvernessBrowserConnectorFactory, browser_factory),
        )

        assert outcomes[0].status == "error"
        assert outcomes[0].error == "temporary Everness failure"
        snapshot = get_availability_snapshot(connection, "everness")
        assert snapshot is not None
        assert snapshot.status == "stale"
        assert len(snapshot.slots) == 1
        assert snapshot.latest_run.status == "error"
    finally:
        connection.close()


def test_everness_browser_opens_once_and_closes(tmp_path: Path) -> None:
    connection = ready_everness_database(tmp_path)
    location = everness_location()
    sources = everness_sources()
    lifecycle: list[str] = []

    def browser_factory(_: Sequence[EvernessSource]):
        class FakeBrowserConnector:
            def open(self) -> None:
                lifecycle.append("open")

            def close(self) -> None:
                lifecycle.append("close")

            def collect(
                self,
                received_location: LocationRecord,
                *,
                run_id: str,
                window_start: date,
                window_end: date,
                collected_at: str,
            ) -> AvailabilityResult:
                assert lifecycle == ["open"]
                return everness_result(
                    received_location,
                    sources[0],
                    run_id=run_id,
                    window_start=window_start,
                    window_end=window_end,
                    collected_at=collected_at,
                )

        return FakeBrowserConnector()

    try:
        collect_everness(
            connection,
            (location,),
            sources,
            browser_connector_factory=cast(EvernessBrowserConnectorFactory, browser_factory),
        )
        assert lifecycle == ["open", "close"]
    finally:
        connection.close()


def test_everness_collection_rejects_unknown_location(tmp_path: Path) -> None:
    connection = ready_everness_database(tmp_path)
    try:
        with pytest.raises(ValueError, match="unknown Everness location: padel-station"):
            collect_everness(
                connection,
                (everness_location(),),
                everness_sources(),
                location_id="padel-station",
            )
    finally:
        connection.close()


def test_everness_collection_persists_startup_error(tmp_path: Path) -> None:
    connection = ready_everness_database(tmp_path)
    location = everness_location()
    sources = everness_sources()
    lifecycle: list[str] = []

    def browser_factory(_: Sequence[EvernessSource]):
        class FakeBrowserConnector:
            def open(self) -> None:
                lifecycle.append("open")
                raise EvernessBrowserError("browser startup failed")

            def close(self) -> None:
                lifecycle.append("close")

            def collect(self, *args: object, **kwargs: object) -> AvailabilityResult:
                raise AssertionError("collect should not run after browser startup failed")

        return FakeBrowserConnector()

    try:
        outcomes = collect_everness(
            connection,
            (location,),
            sources,
            browser_connector_factory=cast(EvernessBrowserConnectorFactory, browser_factory),
        )

        assert lifecycle == ["open", "close"]
        assert outcomes[0].status == "error"
        assert outcomes[0].error == "browser startup failed"
        assert len(list_availability_runs(connection)) == 1
    finally:
        connection.close()


def test_padelfirst_collection_uses_exact_location_and_zurich_window(tmp_path: Path) -> None:
    connection = ready_padelfirst_database(tmp_path)
    location = padelfirst_location()
    sources = padelfirst_sources()
    observed: list[tuple[date, date, str]] = []
    factory_sources: list[Sequence[PadelFirstSource]] = []

    def browser_factory(received_sources: Sequence[PadelFirstSource]):
        factory_sources.append(received_sources)

        class FakeBrowserConnector:
            def open(self) -> None:
                pass

            def close(self) -> None:
                pass

            def collect(
                self,
                received_location: LocationRecord,
                *,
                run_id: str,
                window_start: date,
                window_end: date,
                collected_at: str,
            ) -> AvailabilityResult:
                observed.append((window_start, window_end, collected_at))
                return padelfirst_result(
                    received_location,
                    sources[0],
                    run_id=run_id,
                    window_start=window_start,
                    window_end=window_end,
                    collected_at=collected_at,
                )

        return FakeBrowserConnector()

    try:
        outcomes = collect_padelfirst(
            connection,
            (location,),
            sources,
            now=datetime(2026, 9, 22, 23, 30, tzinfo=UTC),
            horizon_days=2,
            browser_connector_factory=cast(PadelFirstBrowserConnectorFactory, browser_factory),
        )

        assert factory_sources == [sources]
        assert observed == [(date(2026, 9, 23), date(2026, 9, 25), "2026-09-22T23:30:00Z")]
        assert outcomes[0].location_id == "vernier"
        assert outcomes[0].status == "success"
        assert len(list_availability_runs(connection)) == 1
    finally:
        connection.close()


def test_padelfirst_collection_persists_startup_error(tmp_path: Path) -> None:
    connection = ready_padelfirst_database(tmp_path)
    lifecycle: list[str] = []

    def browser_factory(_: Sequence[PadelFirstSource]):
        class FakeBrowserConnector:
            def open(self) -> None:
                lifecycle.append("open")
                raise PadelFirstBrowserError("browser startup failed")

            def close(self) -> None:
                lifecycle.append("close")

            def collect(self, *args: object, **kwargs: object) -> AvailabilityResult:
                del args, kwargs
                raise AssertionError("collect should not run after browser startup failed")

        return FakeBrowserConnector()

    try:
        outcomes = collect_padelfirst(
            connection,
            (padelfirst_location(),),
            padelfirst_sources(),
            browser_connector_factory=cast(PadelFirstBrowserConnectorFactory, browser_factory),
        )

        assert lifecycle == ["open", "close"]
        assert outcomes[0].status == "error"
        assert outcomes[0].error == "browser startup failed"
        assert len(list_availability_runs(connection)) == 1
    finally:
        connection.close()


def test_padelfirst_collection_persists_playwright_startup_error(tmp_path: Path) -> None:
    try:
        from playwright.sync_api import Error as PlaywrightError
    except ImportError as error:
        pytest.skip(f"Playwright is unavailable: {error}")

    connection = ready_padelfirst_database(tmp_path)

    def browser_factory(_: Sequence[PadelFirstSource]):
        class FakeBrowserConnector:
            def open(self) -> None:
                raise PlaywrightError("browser startup failed")

            def close(self) -> None:
                pass

            def collect(self, *args: object, **kwargs: object) -> AvailabilityResult:
                del args, kwargs
                raise AssertionError("collect should not run after browser startup failed")

        return FakeBrowserConnector()

    try:
        outcomes = collect_padelfirst(
            connection,
            (padelfirst_location(),),
            padelfirst_sources(),
            browser_connector_factory=cast(PadelFirstBrowserConnectorFactory, browser_factory),
        )

        assert outcomes[0].status == "error"
        assert outcomes[0].error == "browser startup failed"
        assert len(list_availability_runs(connection)) == 1
    finally:
        connection.close()


def test_padelfirst_collection_rejects_unknown_location(tmp_path: Path) -> None:
    connection = ready_padelfirst_database(tmp_path)
    try:
        with pytest.raises(ValueError, match="unknown Padel First location: everness"):
            collect_padelfirst(
                connection,
                (padelfirst_location(),),
                padelfirst_sources(),
                location_id="everness",
            )
    finally:
        connection.close()


def test_matchpoint_collection_uses_exact_locations_and_zurich_window(tmp_path: Path) -> None:
    connection = ready_matchpoint_database(tmp_path)
    locations = matchpoint_locations()
    sources = matchpoint_sources()
    factory_sources: list[Sequence[MatchpointSource]] = []
    events: list[str] = []
    collected: list[tuple[str, date, date]] = []
    sources_by_id = {source.location_id: source for source in sources}

    def browser_factory(received_sources: Sequence[MatchpointSource]):
        factory_sources.append(received_sources)

        class FakeMatchpointConnector:
            def open(self) -> None:
                events.append("open")

            def close(self) -> None:
                events.append("close")

            def collect(
                self,
                location: LocationRecord,
                *,
                run_id: str,
                window_start: date,
                window_end: date,
                collected_at: str,
            ) -> AvailabilityResult:
                events.append(f"collect:{location.location_id}")
                collected.append((location.location_id, window_start, window_end))
                return _matchpoint_result(
                    location,
                    sources_by_id[location.location_id],
                    run_id=run_id,
                    window_start=window_start,
                    window_end=window_end,
                    collected_at=collected_at,
                )

        return FakeMatchpointConnector()

    try:
        outcomes = _collect_matchpoint(
            connection,
            locations,
            sources,
            now=datetime(2026, 9, 24, 22, 30, tzinfo=UTC),
            horizon_days=2,
            browser_connector_factory=cast(MatchpointBrowserConnectorFactory, browser_factory),
        )

        assert events == [
            "open",
            "collect:asphalte-jonction",
            "collect:bernex",
            "collect:evaux",
            "collect:urban-padel-lausanne",
            "close",
        ]
        assert factory_sources == [sources]
        assert collected == [
            ("asphalte-jonction", date(2026, 9, 25), date(2026, 9, 27)),
            ("bernex", date(2026, 9, 25), date(2026, 9, 27)),
            ("evaux", date(2026, 9, 25), date(2026, 9, 27)),
            ("urban-padel-lausanne", date(2026, 9, 25), date(2026, 9, 27)),
        ]
        assert [outcome.location_id for outcome in outcomes] == [
            "asphalte-jonction",
            "bernex",
            "evaux",
            "urban-padel-lausanne",
        ]
        assert all(outcome.status == "success" for outcome in outcomes)
        assert len(list_availability_runs(connection)) == 4
    finally:
        connection.close()


def test_matchpoint_collection_persists_browser_startup_error_and_closes(
    tmp_path: Path,
) -> None:
    connection = ready_matchpoint_database(tmp_path)
    events: list[str] = []

    def browser_factory(_: Sequence[MatchpointSource]):
        class FakeMatchpointConnector:
            def open(self) -> None:
                events.append("open")
                raise MatchpointBrowserError("browser startup failed")

            def close(self) -> None:
                events.append("close")

            def collect(self, *args: object, **kwargs: object) -> AvailabilityResult:
                del args, kwargs
                raise AssertionError("collect must not run after browser startup failure")

        return FakeMatchpointConnector()

    try:
        outcomes = _collect_matchpoint(
            connection,
            matchpoint_locations(),
            matchpoint_sources(),
            browser_connector_factory=cast(MatchpointBrowserConnectorFactory, browser_factory),
        )

        assert events == ["open", "close"]
        assert [outcome.status for outcome in outcomes] == ["error"] * 4
        assert [outcome.error for outcome in outcomes] == ["browser startup failed"] * 4
        assert len(list_availability_runs(connection)) == 4
    finally:
        connection.close()


def test_plugin_collection_uses_zurich_windows_sorts_and_persists_all_locations(
    tmp_path: Path,
) -> None:
    connection = ready_plugin_database(tmp_path)
    locations = plugin_locations()
    sources = plugin_sources()
    received_sources: list[Sequence[PluginSource]] = []
    calls: list[tuple[str, date, date]] = []

    def browser_factory(supplied_sources: Sequence[PluginSource]):
        received_sources.append(supplied_sources)

        class FakeBrowserConnector:
            def open(self) -> None:
                pass

            def close(self) -> None:
                pass

            def collect(
                self,
                location: LocationRecord,
                *,
                run_id: str,
                window_start: date,
                window_end: date,
                collected_at: str,
            ) -> AvailabilityResult:
                calls.append((location.location_id, window_start, window_end))
                source = next(item for item in sources if item.location_id == location.location_id)
                return _plugin_result(
                    location,
                    source,
                    run_id=run_id,
                    window_start=window_start,
                    window_end=window_end,
                    collected_at=collected_at,
                )

        return FakeBrowserConnector()

    try:
        outcomes = collect_plugin(
            connection,
            tuple(reversed(locations)),
            sources,
            now=datetime(2026, 9, 24, 22, 30, tzinfo=UTC),
            horizon_days=2,
            browser_connector_factory=cast(PluginBrowserConnectorFactory, browser_factory),
        )
        expected_ids = sorted(PLUGIN_LOCATION_IDS)
        assert received_sources == [sources]
        assert [item[0] for item in calls] == expected_ids
        assert all(item[1:] == (date(2026, 9, 25), date(2026, 9, 27)) for item in calls)
        assert [outcome.location_id for outcome in outcomes] == expected_ids
        assert all(
            outcome.run_id.startswith(f"plugin-{outcome.location_id}-") for outcome in outcomes
        )
        assert len(list_availability_runs(connection)) == 8
    finally:
        connection.close()


def test_plugin_collection_selects_one_location_and_validates_catalog_ids(
    tmp_path: Path,
) -> None:
    connection = ready_plugin_database(tmp_path)
    locations, sources = plugin_locations(), plugin_sources()
    selected_id = "gland"
    calls: list[str] = []

    def browser_factory(_: Sequence[PluginSource]):
        class FakeBrowserConnector:
            def open(self) -> None:
                pass

            def close(self) -> None:
                pass

            def collect(self, location: LocationRecord, **kwargs: object) -> AvailabilityResult:
                calls.append(location.location_id)
                return _plugin_result(
                    location,
                    next(
                        source for source in sources if source.location_id == location.location_id
                    ),
                    run_id=cast(str, kwargs["run_id"]),
                    window_start=cast(date, kwargs["window_start"]),
                    window_end=cast(date, kwargs["window_end"]),
                    collected_at=cast(str, kwargs["collected_at"]),
                )

        return FakeBrowserConnector()

    try:
        outcomes = collect_plugin(
            connection,
            locations,
            sources,
            location_id=selected_id,
            browser_connector_factory=cast(PluginBrowserConnectorFactory, browser_factory),
        )
        assert calls == [selected_id]
        assert [outcome.location_id for outcome in outcomes] == [selected_id]
        with pytest.raises(ValueError, match="unknown Plugin location: unknown"):
            collect_plugin(connection, locations, sources, location_id="unknown")
        with pytest.raises(ValueError, match="location is missing from catalog: gland"):
            collect_plugin(
                connection,
                tuple(location for location in locations if location.location_id != selected_id),
                sources,
                location_id=selected_id,
            )
        with pytest.raises(ValueError, match="catalog is missing Plugin locations: gland"):
            collect_plugin(
                connection,
                tuple(location for location in locations if location.location_id != selected_id),
                sources,
            )
    finally:
        connection.close()


def test_plugin_date_timeout_retries_the_location_once(tmp_path: Path) -> None:
    connection = ready_plugin_database(tmp_path)
    location = next(item for item in plugin_locations() if item.location_id == "gland")
    source = next(item for item in plugin_sources() if item.location_id == "gland")
    collect_calls = 0

    def browser_factory(_: Sequence[PluginSource]):
        class FakeBrowserConnector:
            def open(self) -> None:
                pass

            def close(self) -> None:
                pass

            def collect(
                self,
                received_location: LocationRecord,
                *,
                run_id: str,
                window_start: date,
                window_end: date,
                collected_at: str,
            ) -> AvailabilityResult:
                nonlocal collect_calls
                collect_calls += 1
                if collect_calls == 1:
                    raise PluginBrowserError("timed out waiting for the requested Plugin date")
                return _plugin_result(
                    received_location,
                    source,
                    run_id=run_id,
                    window_start=window_start,
                    window_end=window_end,
                    collected_at=collected_at,
                )

        return FakeBrowserConnector()

    try:
        outcomes = collect_plugin(
            connection,
            (location,),
            (source,),
            location_id="gland",
            browser_connector_factory=cast(PluginBrowserConnectorFactory, browser_factory),
        )

        assert collect_calls == 2
        assert len(outcomes) == 1 and outcomes[0].status == "success"
        assert len(list_availability_runs(connection, "gland")) == 1
    finally:
        connection.close()


def test_plugin_startup_error_is_bounded_persisted_for_all_and_closes(
    tmp_path: Path,
) -> None:
    connection = ready_plugin_database(tmp_path)
    lifecycle: list[str] = []

    def browser_factory(_: Sequence[PluginSource]):
        class FakeBrowserConnector:
            def open(self) -> None:
                lifecycle.append("open")
                raise PluginBrowserError("x" * 300)

            def close(self) -> None:
                lifecycle.append("close")

            def collect(self, *_args: object, **_kwargs: object) -> AvailabilityResult:
                raise AssertionError("collect should not run after startup failure")

        return FakeBrowserConnector()

    try:
        outcomes = collect_plugin(
            connection,
            plugin_locations(),
            plugin_sources(),
            browser_connector_factory=cast(PluginBrowserConnectorFactory, browser_factory),
        )
        assert lifecycle == ["open", "close"]
        assert len(outcomes) == 8
        assert all(
            outcome.status == "error" and len(outcome.error or "") <= 160 for outcome in outcomes
        )
        assert len(list_availability_runs(connection)) == 8
    finally:
        connection.close()


def test_plugin_startup_failure_never_collects_any_selected_source(tmp_path: Path) -> None:
    connection = ready_plugin_database(tmp_path)
    sources = tuple(
        replace(source, status="unavailable")
        if source.location_id == "collonge-bellerive"
        else source
        for source in plugin_sources()
    )
    sources_by_id = {source.location_id: source for source in sources}
    lifecycle: list[str] = []
    collect_calls: list[str] = []

    def browser_factory(_: Sequence[PluginSource]):
        class FakeBrowserConnector:
            def open(self) -> None:
                lifecycle.append("open")
                raise PluginBrowserError("browser startup failed")

            def close(self) -> None:
                lifecycle.append("close")

            def collect(
                self,
                location: LocationRecord,
                *,
                run_id: str,
                window_start: date,
                window_end: date,
                collected_at: str,
            ) -> AvailabilityResult:
                collect_calls.append(location.location_id)
                return _plugin_result(
                    location,
                    sources_by_id[location.location_id],
                    run_id=run_id,
                    window_start=window_start,
                    window_end=window_end,
                    collected_at=collected_at,
                    status="unavailable",
                    error="source unavailable",
                )

        return FakeBrowserConnector()

    try:
        outcomes = collect_plugin(
            connection,
            plugin_locations(),
            sources,
            browser_connector_factory=cast(PluginBrowserConnectorFactory, browser_factory),
        )
        assert collect_calls == []
        assert lifecycle == ["open", "close"]
        assert len(outcomes) == 8
        assert all(outcome.status == "error" for outcome in outcomes)
        assert all(outcome.error == "browser startup failed" for outcome in outcomes)
        assert len(list_availability_runs(connection)) == 8
    finally:
        connection.close()


def test_plugin_unavailable_source_skips_browser_startup(tmp_path: Path) -> None:
    connection = ready_plugin_database(tmp_path)
    locations = plugin_locations()
    unavailable = replace(plugin_sources()[0], status="unavailable")
    location = next(item for item in locations if item.location_id == unavailable.location_id)

    lifecycle: list[str] = []

    def browser_factory(_: Sequence[PluginSource]):
        class FakeBrowserConnector:
            def open(self) -> None:
                lifecycle.append("open")

            def close(self) -> None:
                lifecycle.append("close")

            def collect(
                self,
                received_location: LocationRecord,
                *,
                run_id: str,
                window_start: date,
                window_end: date,
                collected_at: str,
            ) -> AvailabilityResult:
                return _plugin_result(
                    received_location,
                    unavailable,
                    run_id=run_id,
                    window_start=window_start,
                    window_end=window_end,
                    collected_at=collected_at,
                    status="unavailable",
                    error="public Plugin booking diary is unavailable",
                )

        return FakeBrowserConnector()

    try:
        outcomes = collect_plugin(
            connection,
            locations,
            (unavailable,),
            location_id=unavailable.location_id,
            browser_connector_factory=cast(PluginBrowserConnectorFactory, browser_factory),
        )
        assert location.location_id == outcomes[0].location_id
        assert outcomes[0].status == "unavailable"
        assert lifecycle == ["close"]
        assert len(list_availability_runs(connection)) == 1
    finally:
        connection.close()


def test_airpad_raw_browser_startup_error_is_persisted_for_each_site(tmp_path: Path) -> None:
    try:
        from playwright.sync_api import Error as PlaywrightError
    except ImportError as error:
        pytest.skip(f"Playwright is unavailable: {error}")

    connection = ready_airpad_database(tmp_path)
    locations = four_airpad_locations()
    sources = four_airpad_sources()
    lifecycle: list[str] = []

    def browser_factory(_: Sequence[AirpadSource]):
        class FakeBrowserConnector:
            def open(self) -> None:
                lifecycle.append("open")
                raise PlaywrightError("browser launch failed")

            def close(self) -> None:
                lifecycle.append("close")

            def collect(
                self,
                location: LocationRecord,
                *,
                run_id: str,
                window_start: date,
                window_end: date,
                collected_at: str,
            ) -> AvailabilityResult:
                del location, run_id, window_start, window_end, collected_at
                raise AssertionError("collect should not run after browser startup failed")

        return FakeBrowserConnector()

    try:
        outcomes = collect_airpad(
            connection,
            locations,
            sources,
            now=datetime(2026, 9, 22, 9, 0, tzinfo=ZURICH),
            browser_connector_factory=cast(AirpadBrowserConnectorFactory, browser_factory),
        )

        assert lifecycle == ["open", "close"]
        assert [outcome.location_id for outcome in outcomes] == list(AIRPAD_IDS)
        assert [outcome.status for outcome in outcomes] == ["error"] * 4
        assert [outcome.error for outcome in outcomes] == ["browser launch failed"] * 4
        assert len(list_availability_runs(connection)) == 4
    finally:
        connection.close()


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
            now=datetime(2026, 9, 22, 23, 30, tzinfo=UTC),
            horizon_days=2,
            location_id="padel-station",
            fetch_json=fixture_fetch_json,
        )

        assert len(outcomes) == 1
        assert outcomes[0].window_start == "2026-09-23"
        assert outcomes[0].window_end == "2026-09-25"
        assert outcomes[0].slot_count == 2
        assert local_window(datetime(2026, 9, 22, 23, 30, tzinfo=UTC), 2) == (
            date(2026, 9, 23),
            date(2026, 9, 25),
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


def test_collection_selects_browser_once_saves_immediately_and_continues(
    tmp_path: Path,
) -> None:
    connection = ready_database(tmp_path)
    locations = five_playtomic_locations()
    sources = mixed_playtomic_sources()
    sources_by_id = {source.location_id: source for source in sources}
    factory_calls: list[Sequence[PlaytomicSource]] = []
    browser_calls: list[str] = []
    browser_lifecycle: list[str] = []
    fetch_calls: list[str] = []

    def browser_factory(received_sources: Sequence[PlaytomicSource]):
        factory_calls.append(received_sources)

        class FakeBrowserConnector:
            def open(self) -> None:
                browser_lifecycle.append("open")

            def close(self) -> None:
                browser_lifecycle.append("close")

            def collect(
                self,
                location: LocationRecord,
                *,
                run_id: str,
                window_start: date,
                window_end: date,
                collected_at: str,
            ) -> AvailabilityResult:
                browser_calls.append(location.location_id)
                if location.location_id == "padel-parc-etoy":
                    assert len(list_availability_runs(connection)) == 1
                    raise PlaytomicBrowserError("DOM failed")
                if location.location_id == "gva-palexpo":
                    return browser_result(
                        location,
                        sources_by_id[location.location_id],
                        status="unavailable",
                        error="public booking page is explicitly unavailable",
                        run_id=run_id,
                        window_start=window_start,
                        window_end=window_end,
                        collected_at=collected_at,
                    )
                assert location.location_id == "padel-station"
                assert len(list_availability_runs(connection)) == 3
                slots = tuple(
                    AvailabilitySlot(
                        run_id,
                        location.location_id,
                        f"station-{index}",
                        f"station-{index}",
                        f"Padel {index}",
                        f"2026-09-22T{8 + index:02d}:00:00Z",
                        f"2026-09-22T{9 + index:02d}:00:00Z",
                        "Europe/Zurich",
                        "available",
                    )
                    for index in (1, 2)
                )
                return browser_result(
                    location,
                    sources_by_id[location.location_id],
                    slots=slots,
                    run_id=run_id,
                    window_start=window_start,
                    window_end=window_end,
                    collected_at=collected_at,
                )

        return FakeBrowserConnector()

    def fetch_json(url: str) -> object:
        fetch_calls.append(url)
        return fixture_fetch_json(url)

    try:
        outcomes = collect_playtomic(
            connection,
            locations,
            sources,
            now=datetime(2026, 9, 22, 9, 0, tzinfo=ZURICH),
            fetch_json=fetch_json,
            browser_connector_factory=browser_factory,
        )

        assert len(factory_calls) == 1
        assert factory_calls[0] == sources
        assert browser_lifecycle == ["open", "close"]
        assert browser_calls == ["gva-palexpo", "padel-parc-etoy", "padel-station"]
        assert [urlparse(url).path.rsplit("/", 1)[-1] for url in fetch_calls] == [
            "padel-parc-preverenges",
            "vaudoise-arena",
        ]
        assert [outcome.location_id for outcome in outcomes] == list(PLAYTOMIC_IDS)
        assert [outcome.status for outcome in outcomes] == [
            "unavailable",
            "error",
            "success",
            "success",
            "success",
        ]
        assert [outcome.slot_count for outcome in outcomes] == [0, 0, 3, 2, 3]
        assert len(list_availability_runs(connection)) == 5
    finally:
        connection.close()


def test_browser_navigation_error_retries_once_for_public_browser_source(tmp_path: Path) -> None:
    connection = ready_database(tmp_path)
    location = next(
        item for item in five_playtomic_locations() if item.location_id == "padel-parc-etoy"
    )
    source = next(
        item for item in mixed_playtomic_sources() if item.location_id == "padel-parc-etoy"
    )
    collect_calls = 0

    def browser_factory(_: Sequence[PlaytomicSource]):
        class FakeBrowserConnector:
            def open(self) -> None:
                pass

            def close(self) -> None:
                pass

            def collect(
                self,
                received_location: LocationRecord,
                *,
                run_id: str,
                window_start: date,
                window_end: date,
                collected_at: str,
            ) -> AvailabilityResult:
                nonlocal collect_calls
                collect_calls += 1
                if collect_calls == 1:
                    raise PlaytomicSourceError("browser navigation or extraction failed")
                return browser_result(
                    received_location,
                    source,
                    run_id=run_id,
                    window_start=window_start,
                    window_end=window_end,
                    collected_at=collected_at,
                )

        return FakeBrowserConnector()

    try:
        outcomes = collect_playtomic(
            connection,
            (location,),
            (source,),
            location_id="padel-parc-etoy",
            browser_connector_factory=cast(BrowserConnectorFactory, browser_factory),
        )

        assert collect_calls == 2
        assert len(outcomes) == 1 and outcomes[0].status == "success"
        assert len(list_availability_runs(connection, "padel-parc-etoy")) == 1
    finally:
        connection.close()


def test_browser_open_error_is_persisted_and_json_sites_continue(tmp_path: Path) -> None:
    connection = ready_database(tmp_path)
    locations = five_playtomic_locations()
    sources = mixed_playtomic_sources()
    browser_lifecycle: list[str] = []
    browser_calls: list[str] = []

    def browser_factory(_: Sequence[PlaytomicSource]):
        class FakeBrowserConnector:
            def open(self) -> None:
                browser_lifecycle.append("open")
                raise PlaytomicBrowserError("browser launch failed")

            def close(self) -> None:
                browser_lifecycle.append("close")

            def collect(
                self,
                location: LocationRecord,
                *,
                run_id: str,
                window_start: date,
                window_end: date,
                collected_at: str,
            ) -> AvailabilityResult:
                del run_id, window_start, window_end, collected_at
                browser_calls.append(location.location_id)
                raise AssertionError("browser collect should not run after open failed")

        return FakeBrowserConnector()

    try:
        outcomes = collect_playtomic(
            connection,
            locations,
            sources,
            now=datetime(2026, 9, 22, 9, 0, tzinfo=ZURICH),
            fetch_json=fixture_fetch_json,
            browser_connector_factory=browser_factory,
        )

        by_id = {outcome.location_id: outcome for outcome in outcomes}
        assert browser_lifecycle == ["open", "close"]
        assert browser_calls == []
        assert [by_id[location_id].status for location_id in PLAYTOMIC_IDS] == [
            "error",
            "error",
            "success",
            "error",
            "success",
        ]
        assert by_id["gva-palexpo"].error == "browser launch failed"
        assert by_id["padel-parc-etoy"].error == "browser launch failed"
        assert by_id["padel-station"].error == "browser launch failed"
        assert len(list_availability_runs(connection)) == 5
    finally:
        connection.close()


def test_browser_error_keeps_previous_successful_snapshot_stale(tmp_path: Path) -> None:
    connection = ready_database(tmp_path)
    locations = five_playtomic_locations()
    sources = mixed_playtomic_sources()
    source = next(source for source in sources if source.location_id == "padel-station")
    attempts = 0

    def browser_factory(_: Sequence[PlaytomicSource]):
        class FakeBrowserConnector:
            def open(self) -> None:
                pass

            def close(self) -> None:
                pass

            def collect(
                self,
                location: LocationRecord,
                *,
                run_id: str,
                window_start: date,
                window_end: date,
                collected_at: str,
            ) -> AvailabilityResult:
                nonlocal attempts
                attempts += 1
                if attempts == 2:
                    raise PlaytomicBrowserError("browser unavailable")
                slots = (
                    AvailabilitySlot(
                        run_id,
                        location.location_id,
                        "station-success",
                        "station-success",
                        "Padel A",
                        "2026-09-22T08:00:00Z",
                        "2026-09-22T09:00:00Z",
                        "Europe/Zurich",
                        "available",
                    ),
                )
                return browser_result(
                    location,
                    source,
                    slots=slots,
                    run_id=run_id,
                    window_start=window_start,
                    window_end=window_end,
                    collected_at=collected_at,
                )

        return FakeBrowserConnector()

    try:
        collect_playtomic(
            connection,
            locations,
            sources,
            now=datetime(2026, 9, 22, 9, 0, tzinfo=ZURICH),
            location_id="padel-station",
            browser_connector_factory=browser_factory,
        )
        outcomes = collect_playtomic(
            connection,
            locations,
            sources,
            now=datetime(2026, 9, 22, 10, 0, tzinfo=ZURICH),
            location_id="padel-station",
            browser_connector_factory=browser_factory,
        )

        assert outcomes[0].status == "error"
        snapshot = get_availability_snapshot(connection, "padel-station")
        assert snapshot is not None
        assert snapshot.status == "stale"
        assert len(snapshot.slots) == 1
        assert snapshot.latest_run.status == "error"
    finally:
        connection.close()
