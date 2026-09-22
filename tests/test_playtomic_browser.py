from dataclasses import FrozenInstanceError
from datetime import date

import pytest

from padel_availability.availability import AvailabilitySlot
from padel_availability.connectors.playtomic import PlaytomicSourceError
from padel_availability.connectors.playtomic_browser import (
    BrowserSlotObservation,
    parse_browser_observations,
)
from padel_availability.models import ModelError


def test_browser_observation_rejects_blank_times() -> None:
    with pytest.raises(ModelError, match="starts_at"):
        BrowserSlotObservation(None, "Court 1", "", "2026-09-22T19:00:00+02:00", "available")


def test_browser_observation_is_immutable() -> None:
    observation = BrowserSlotObservation(
        "slot-1", "Court 1", "2026-09-22T18:00:00+02:00", "2026-09-22T19:00:00+02:00", "available"
    )

    with pytest.raises(FrozenInstanceError):
        observation.status = "unknown"  # type: ignore[misc]


def test_browser_observations_normalize_filter_and_sort_slots() -> None:
    observations = (
        BrowserSlotObservation(
            "slot-2",
            "Court 2",
            "2026-09-22T20:00:00+02:00",
            "2026-09-22T21:00:00+02:00",
            "unavailable",
        ),
        BrowserSlotObservation(
            "slot-1",
            "Court 1",
            "2026-09-22T18:00:00+02:00",
            "2026-09-22T19:00:00+02:00",
            "available",
        ),
        BrowserSlotObservation(
            None,
            "Court 3",
            "2026-09-23T18:00:00+02:00",
            "2026-09-23T19:00:00+02:00",
            "unknown",
        ),
        BrowserSlotObservation(
            "outside",
            "Court 4",
            "2026-09-24T18:00:00+02:00",
            "2026-09-24T19:00:00+02:00",
            "available",
        ),
    )

    slots = parse_browser_observations(
        observations,
        location_id="padel-station",
        run_id="run-browser",
        window_start=date(2026, 9, 22),
        window_end=date(2026, 9, 24),
    )

    assert all(isinstance(slot, AvailabilitySlot) for slot in slots)
    assert [slot.external_id for slot in slots] == ["slot-1", "slot-2", None]
    assert [slot.status for slot in slots] == ["available", "unavailable", "unknown"]
    assert slots[0].starts_at == "2026-09-22T16:00:00Z"
    assert len(slots[2].slot_key) == 64
    assert all(slot.timezone == "Europe/Zurich" for slot in slots)


def test_browser_observations_deduplicate_equal_slots() -> None:
    observation = BrowserSlotObservation(
        None,
        "Court 1",
        "2026-09-22T18:00:00+02:00",
        "2026-09-22T19:00:00+02:00",
        "available",
    )

    slots = parse_browser_observations(
        (observation, observation),
        location_id="padel-station",
        run_id="run-browser",
        window_start=date(2026, 9, 22),
        window_end=date(2026, 9, 23),
    )

    assert len(slots) == 1


def test_browser_observations_reject_conflicting_duplicate_ids() -> None:
    with pytest.raises(PlaytomicSourceError, match="conflicting duplicate external_id"):
        parse_browser_observations(
            (
                BrowserSlotObservation(
                    "same-id",
                    "Court 1",
                    "2026-09-22T18:00:00+02:00",
                    "2026-09-22T19:00:00+02:00",
                    "available",
                ),
                BrowserSlotObservation(
                    "same-id",
                    "Court 1",
                    "2026-09-22T18:00:00+02:00",
                    "2026-09-22T19:00:00+02:00",
                    "unavailable",
                ),
            ),
            location_id="padel-station",
            run_id="run-browser",
            window_start=date(2026, 9, 22),
            window_end=date(2026, 9, 23),
        )
