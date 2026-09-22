import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from .availability import (
    AvailabilityResult,
    AvailabilityRun,
    AvailabilityRunStatus,
    local_window,
)
from .connectors.playtomic import (
    JsonFetcher,
    PlaytomicConnector,
    PlaytomicSource,
    PlaytomicSourceError,
    fetch_public_json,
)
from .connectors.playtomic_browser import (
    BrowserConnector,
    BrowserConnectorFactory,
    PlaytomicBrowserConnector,
)
from .database import save_availability_result
from .models import LocationRecord


@dataclass(frozen=True, slots=True)
class CollectionOutcome:
    location_id: str
    run_id: str
    status: AvailabilityRunStatus
    slot_count: int
    window_start: str
    window_end: str
    error: str | None


_PLAYTOMIC_LOCATION_IDS = frozenset(
    {
        "padel-station",
        "gva-palexpo",
        "padel-parc-etoy",
        "padel-parc-preverenges",
        "vaudoise-arena",
    }
)


def _error_result(
    location: LocationRecord,
    *,
    source_url: str,
    run_id: str,
    window_start: str,
    window_end: str,
    horizon_days: int,
    collected_at: str,
    error: BaseException,
) -> AvailabilityResult:
    message = str(error).strip()[:160] or type(error).__name__
    return AvailabilityResult(
        AvailabilityRun(
            run_id,
            location.location_id,
            "playtomic",
            source_url,
            window_start,
            window_end,
            horizon_days,
            collected_at,
            "error",
            message,
        ),
        (),
    )


def collect_playtomic(
    connection: sqlite3.Connection,
    locations: Sequence[LocationRecord],
    sources: Sequence[PlaytomicSource],
    *,
    now: datetime | None = None,
    horizon_days: int = 14,
    location_id: str | None = None,
    fetch_json: JsonFetcher = fetch_public_json,
    browser_connector_factory: BrowserConnectorFactory | None = None,
) -> tuple[CollectionOutcome, ...]:
    if now is None:
        now = datetime.now(UTC)
    window_start, window_end = local_window(now, horizon_days)
    collected_at = now.astimezone(UTC).isoformat().replace("+00:00", "Z")

    locations_by_id = {location.location_id: location for location in locations}
    if location_id is not None:
        if location_id not in _PLAYTOMIC_LOCATION_IDS:
            raise ValueError(f"unknown Playtomic location: {location_id}")
        try:
            selected = (locations_by_id[location_id],)
        except KeyError as error:
            raise ValueError(f"location is missing from catalog: {location_id}") from error
    else:
        missing = _PLAYTOMIC_LOCATION_IDS - locations_by_id.keys()
        if missing:
            raise ValueError(
                "catalog is missing Playtomic locations: " + ", ".join(sorted(missing))
            )
        selected = tuple(locations_by_id[item] for item in sorted(_PLAYTOMIC_LOCATION_IDS))

    sources_by_id = {source.location_id: source for source in sources}
    json_connector = PlaytomicConnector(sources, fetch_json=fetch_json)
    selected_ids = {location.location_id for location in selected}
    browser_connector: BrowserConnector | None = None
    browser_session_needed = False
    if any(
        source.location_id in selected_ids and source.transport == "browser_dom"
        for source in sources
    ):
        browser_session_needed = any(
            source.location_id in selected_ids
            and source.transport == "browser_dom"
            and source.status == "public"
            for source in sources
        )
        browser_connector = (
            browser_connector_factory(sources)
            if browser_connector_factory is not None
            else PlaytomicBrowserConnector(sources)
        )
    outcomes: list[CollectionOutcome] = []
    try:
        if browser_connector is not None and browser_session_needed:
            browser_connector.open()
        for location in selected:
            source = sources_by_id.get(location.location_id)
            source_url = source.booking_url if source is not None else location.booking_url
            if source_url is None:
                source_url = f"https://playtomic.com/locations/{location.location_id}"
            run_id = f"playtomic-{location.location_id}-{collected_at}"
            if source is not None and source.transport == "browser_dom":
                assert browser_connector is not None
                connector = browser_connector
            else:
                connector = json_connector
            try:
                result = connector.collect(
                    location,
                    run_id=run_id,
                    window_start=window_start,
                    window_end=window_end,
                    collected_at=collected_at,
                )
            except (PlaytomicSourceError, OSError, TimeoutError, json.JSONDecodeError) as error:
                result = _error_result(
                    location,
                    source_url=source_url,
                    run_id=run_id,
                    window_start=window_start.isoformat(),
                    window_end=window_end.isoformat(),
                    horizon_days=horizon_days,
                    collected_at=collected_at,
                    error=error,
                )

            save_availability_result(connection, result)
            outcomes.append(
                CollectionOutcome(
                    location.location_id,
                    result.run.run_id,
                    result.run.status,
                    len(result.slots),
                    result.run.window_start,
                    result.run.window_end,
                    result.run.error,
                )
            )
    finally:
        if browser_connector is not None:
            browser_connector.close()
    return tuple(sorted(outcomes, key=lambda outcome: outcome.location_id))
