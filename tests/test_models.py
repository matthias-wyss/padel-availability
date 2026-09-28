import pytest

from padel_availability import __version__
from padel_availability.models import (
    CourtGroup,
    LocationRecord,
    ModelError,
    SourceEvidence,
    VerificationRun,
)


def test_package_exposes_version() -> None:
    assert __version__ == "0.1.0"


def location_record(**overrides: object) -> LocationRecord:
    values: dict[str, object] = {
        "location_id": "example-geneve",
        "canonical_name": "Example Padel",
        "municipality": "Geneva",
        "candidate_ids": ("example",),
        "access_kind": "public",
        "membership_required": "unknown",
        "public_booking": "unknown",
        "racket_rental": "unknown",
        "locker_rooms": "unknown",
        "booking_account_required": "unknown",
        "verification_status": "to_verify",
        "court_groups": (),
        "aliases": (),
        "evidence": (),
        "notes": "",
    }
    values.update(overrides)
    return LocationRecord(**values)  # type: ignore[arg-type]


def test_unknown_is_valid_but_other_tri_state_values_are_rejected() -> None:
    record = location_record()
    assert record.membership_required == "unknown"

    with pytest.raises(ModelError):
        LocationRecord.from_mapping({**record.to_mapping(), "public_booking": "maybe"})


def test_confirmed_location_requires_evidence() -> None:
    with pytest.raises(ModelError):
        location_record(verification_status="confirmed")


def test_probable_location_requires_evidence() -> None:
    with pytest.raises(ModelError):
        location_record(verification_status="probable")


def test_court_group_count_must_be_positive() -> None:
    with pytest.raises(ModelError):
        location_record(court_groups=(CourtGroup("Indoor", 0, None, "indoor"),))


def test_location_mapping_round_trips_json_compatible_values() -> None:
    record = location_record(
        court_groups=(CourtGroup("Indoor", 2, "double", "indoor"),),
        aliases=("Example",),
        official_url="https://example.test/",
    )

    assert LocationRecord.from_mapping(record.to_mapping()) == record


def test_location_mapping_rejects_missing_required_key_and_malformed_url() -> None:
    record = location_record()
    mapping = record.to_mapping()
    mapping.pop("municipality")
    with pytest.raises(ModelError):
        LocationRecord.from_mapping(mapping)

    with pytest.raises(ModelError):
        location_record(official_url="not-a-url")


def test_timestamps_require_iso8601_utc_z_suffix() -> None:
    valid = SourceEvidence(
        "https://example.test/",
        "official",
        "Example",
        "2026-09-21T10:00:00Z",
        "name",
        "supports",
        "Example.",
        "confirmed",
    )
    assert valid.checked_at.endswith("Z")
    for timestamp in ("2026-09-21T10:00:00", "2026-09-21T10:00:00+01:00", "invalid"):
        with pytest.raises(ModelError):
            SourceEvidence(
                "https://example.test/",
                "official",
                "Example",
                timestamp,
                "name",
                "supports",
                "Example.",
                "confirmed",
            )

    for timestamp in ("2026-09-21T10:00:00", "2026-09-21T10:00:00+01:00", "invalid"):
        with pytest.raises(ModelError):
            VerificationRun("run-1", timestamp, "2026-09-21T10:01:00Z", 1, 0, "ok")


def test_malformed_url_port_raises_model_error() -> None:
    for url in ("https://host:bad/", "http://:80/"):
        with pytest.raises(ModelError):
            SourceEvidence(
                url,
                "official",
                "Example",
                "2026-09-21T10:00:00Z",
                "name",
                "supports",
                "Example.",
                "confirmed",
            )


def test_direct_tuple_fields_reject_lists_and_duplicates() -> None:
    with pytest.raises(ModelError):
        location_record(candidate_ids=["example"])
    with pytest.raises(ModelError):
        location_record(candidate_ids=("example", "example"))
    with pytest.raises(ModelError):
        location_record(aliases=["Example"])
    with pytest.raises(ModelError):
        location_record(aliases=("Example", "Example"))
