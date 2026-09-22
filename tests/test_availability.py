from dataclasses import FrozenInstanceError
from datetime import date, datetime, timezone

import pytest

from padel_availability.availability import (
    AvailabilityResult,
    AvailabilityRun,
    AvailabilitySlot,
    AvailabilitySnapshot,
    ModelError,
    local_to_utc,
    local_window,
)


def test_local_window_is_half_open_and_uses_zurich_date() -> None:
    now = datetime(2026, 9, 22, 23, 30, tzinfo=timezone.utc)

    assert local_window(now, 14) == (date(2026, 9, 23), date(2026, 10, 7))


def test_local_time_is_normalized_to_utc() -> None:
    assert local_to_utc("2026-09-23T20:00:00+02:00") == "2026-09-23T18:00:00Z"


def test_slot_rejects_non_increasing_utc_interval() -> None:
    with pytest.raises(ModelError, match="ends_at"):
        AvailabilitySlot(
            "run-1",
            "padel-station",
            "slot-1",
            None,
            None,
            "2026-09-23T18:00:00Z",
            "2026-09-23T18:00:00Z",
            "Europe/Zurich",
            "available",
        )


def test_run_requires_error_for_error_status() -> None:
    with pytest.raises(ModelError, match="error"):
        AvailabilityRun(
            "run-1",
            "padel-station",
            "playtomic",
            "https://example.test/slots",
            "2026-09-23",
            "2026-10-07",
            14,
            "2026-09-22T08:00:00Z",
            "error",
            None,
        )


def test_run_rejects_reversed_window() -> None:
    with pytest.raises(ModelError, match="window_end"):
        AvailabilityRun(
            "run-1",
            "padel-station",
            "playtomic",
            "https://example.test/slots",
            "2026-09-23",
            "2026-09-22",
            14,
            "2026-09-22T08:00:00Z",
            "success",
            None,
        )


def test_run_rejects_horizon_that_disagrees_with_window() -> None:
    with pytest.raises(ModelError, match="horizon_days"):
        AvailabilityRun(
            "run-1",
            "padel-station",
            "playtomic",
            "https://example.test/slots",
            "2026-09-23",
            "2026-10-08",
            14,
            "2026-09-22T08:00:00Z",
            "success",
            None,
        )


def test_run_rejects_invalid_source_url() -> None:
    with pytest.raises(ModelError, match="source_url"):
        AvailabilityRun(
            "run-1",
            "padel-station",
            "playtomic",
            "not-a-url",
            "2026-09-23",
            "2026-10-07",
            14,
            "2026-09-22T08:00:00Z",
            "success",
            None,
        )


def test_success_run_rejects_error_message() -> None:
    with pytest.raises(ModelError, match="null for success"):
        AvailabilityRun(
            "run-1",
            "padel-station",
            "playtomic",
            "https://example.test/slots",
            "2026-09-23",
            "2026-10-07",
            14,
            "2026-09-22T08:00:00Z",
            "success",
            "unexpected",
        )


def test_slot_rejects_blank_external_id() -> None:
    for external_id in ("", "   "):
        with pytest.raises(ModelError, match="external_id"):
            AvailabilitySlot(
                "run-1",
                "padel-station",
                "slot-1",
                external_id,
                None,
                "2026-09-23T18:00:00Z",
                "2026-09-23T19:00:00Z",
                "Europe/Zurich",
                "available",
            )


def test_result_and_snapshot_accept_matching_values() -> None:
    run = AvailabilityRun(
        "run-1",
        "padel-station",
        "playtomic",
        "https://example.test/slots",
        "2026-09-23",
        "2026-10-07",
        14,
        "2026-09-22T08:00:00Z",
        "success",
        None,
    )
    slot = AvailabilitySlot(
        "run-1",
        "padel-station",
        "slot-1",
        "external-1",
        "Court 1",
        "2026-09-23T18:00:00Z",
        "2026-09-23T19:00:00Z",
        "Europe/Zurich",
        "available",
    )

    result = AvailabilityResult(run, (slot,))
    snapshot = AvailabilitySnapshot("padel-station", run, (slot,), "success", run.collected_at)

    assert result.run == run
    assert result.slots == (slot,)
    assert snapshot.latest_run == run
    assert snapshot.slots == (slot,)


def test_availability_value_objects_are_immutable() -> None:
    run = AvailabilityRun(
        "run-1",
        "padel-station",
        "playtomic",
        "https://example.test/slots",
        "2026-09-23",
        "2026-10-07",
        14,
        "2026-09-22T08:00:00Z",
        "success",
        None,
    )

    with pytest.raises(FrozenInstanceError):
        setattr(run, "status", "error")


def test_models_reject_invalid_values() -> None:
    with pytest.raises(ModelError):
        AvailabilitySlot(
            "run-1",
            "padel-station",
            "slot-1",
            None,
            None,
            "2026-09-23T18:00:00+02:00",
            "2026-09-23T19:00:00Z",
            "Europe/Zurich",
            "maybe",
        )

    with pytest.raises(ModelError):
        local_window(datetime(2026, 9, 22, tzinfo=timezone.utc), 0)
