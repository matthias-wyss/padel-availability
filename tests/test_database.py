import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from padel_availability.database import (
    connect,
    create_verification_run,
    initialize,
    insert_candidates,
    list_candidate_matches,
    list_locations,
    record_candidate_match,
    upsert_location,
)
from padel_availability.models import (
    CandidateEntry,
    CandidateMatch,
    CourtGroup,
    LocationRecord,
    SourceEvidence,
    VerificationRun,
)


def location_record() -> LocationRecord:
    return LocationRecord(
        location_id="example-geneve",
        canonical_name="Example Padel",
        municipality="Geneva",
        candidate_ids=("example",),
        access_kind="public",
        membership_required="unknown",
        public_booking="yes",
        racket_rental="no",
        locker_rooms="unknown",
        booking_account_required="unknown",
        verification_status="confirmed",
        court_groups=(CourtGroup("Indoor", 2, "double", "indoor"),),
        aliases=("Example Geneva",),
        evidence=(
            SourceEvidence(
                url="https://example.test/club",
                source_type="official",
                title="Example Padel",
                checked_at="2026-09-21T10:00:00Z",
                fact_key="public_booking",
                relation="supports",
                evidence="Public booking is available.",
                confidence="confirmed",
            ),
        ),
        notes="Verified.",
        brand="Example",
        address="1 Example Street",
        latitude=46.2044,
        longitude=6.1432,
        overall_cover_status="indoor",
        official_url="https://example.test/club",
        booking_url="https://example.test/book",
        booking_platform="ExampleBook",
    )


def test_schema_and_evidence_round_trip_after_reopen(tmp_path: Path) -> None:
    database_path = tmp_path / "nested" / "inventory.sqlite3"
    connection = connect(database_path)
    initialize(connection)
    insert_candidates(
        connection,
        (CandidateEntry("example", "Example Padel", "Geneva", "2", "club", "public"),),
    )
    upsert_location(connection, location_record())
    connection.close()

    reopened = connect(database_path)
    try:
        assert list_locations(reopened) == (location_record(),)
        assert reopened.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 1
        assert reopened.execute("SELECT COUNT(*) FROM location_evidence").fetchone()[0] == 1
    finally:
        reopened.close()


def test_evidence_observations_keep_same_url_and_fact_when_observed_differently() -> None:
    connection = connect(Path(":memory:"))
    initialize(connection)
    first = SourceEvidence(
        url="https://example.test/club",
        source_type="official",
        title="Example Padel",
        checked_at="2026-09-21T10:00:00Z",
        fact_key="public_booking",
        relation="supports",
        evidence="Booking is available.",
        confidence="probable",
    )
    second = replace(
        first,
        checked_at="2026-09-22T10:00:00Z",
        evidence="Booking is available for members.",
    )
    location = replace(location_record(), evidence=(first, second))
    try:
        insert_candidates(
            connection,
            (CandidateEntry("example", "Example Padel", "Geneva", "2", "club", "public"),),
        )
        upsert_location(connection, location)

        loaded = list_locations(connection)[0]
        assert set(loaded.evidence) == {first, second}
        assert connection.execute("SELECT COUNT(*) FROM location_evidence").fetchone()[0] == 2
        assert {
            tuple(row)
            for row in connection.execute(
                "SELECT checked_at, evidence FROM location_evidence"
            ).fetchall()
        } == {
            (first.checked_at, first.evidence),
            (second.checked_at, second.evidence),
        }
    finally:
        connection.close()


def test_evidence_round_trip_preserves_same_url_source_metadata() -> None:
    connection = connect(Path(":memory:"))
    initialize(connection)
    first = SourceEvidence(
        url="https://example.test/shared",
        source_type="official",
        title="Official venue page",
        checked_at="2026-09-21T10:00:00Z",
        fact_key="location.address",
        relation="supports",
        evidence="The official page lists the venue address.",
        confidence="confirmed",
    )
    second = replace(
        first,
        source_type="directory",
        title="Directory listing",
        checked_at="2026-09-22T10:00:00Z",
        evidence="The directory lists the venue address.",
    )
    try:
        insert_candidates(
            connection,
            (CandidateEntry("example", "Example Padel", "Geneva", "2", "club", "public"),),
        )
        upsert_location(connection, replace(location_record(), evidence=(first, second)))

        assert set(list_locations(connection)[0].evidence) == {first, second}
        assert connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 2
    finally:
        connection.close()


def test_sqlite_constraints_reject_invalid_tri_state_and_court_count(tmp_path: Path) -> None:
    connection = connect(tmp_path / "inventory.sqlite3")
    initialize(connection)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO locations (
                    location_id, canonical_name, municipality, access_kind,
                    membership_required, public_booking, racket_rental,
                    locker_rooms, booking_account_required, verification_status,
                    overall_cover_status, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "bad",
                    "Bad",
                    "Geneva",
                    "public",
                    "unknown",
                    "maybe",
                    "unknown",
                    "unknown",
                    "unknown",
                    "to_verify",
                    "unknown",
                    "",
                ),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO court_groups "
                "(location_id, label, count, cover_status) VALUES (?, ?, ?, ?)",
                ("missing", "Indoor", 0, "indoor"),
            )
    finally:
        connection.close()


def test_candidate_matches_and_verification_runs_round_trip(tmp_path: Path) -> None:
    connection = connect(tmp_path / "inventory.sqlite3")
    initialize(connection)
    try:
        connection.execute(
            "INSERT INTO candidate_entries (candidate_id, raw_name, municipality) VALUES (?, ?, ?)",
            ("example", "Example Padel", "Geneva"),
        )
        connection.commit()
        record_candidate_match(
            connection,
            CandidateMatch("example", None, "unresolved", "Pending review."),
        )
        assert list_candidate_matches(connection) == (
            CandidateMatch("example", None, "unresolved", "Pending review."),
        )
        create_verification_run(
            connection,
            VerificationRun(
                "run-1", "2026-09-21T10:00:00Z", "2026-09-21T10:01:00Z", 1, 0, "ok"
            ),
        )
        assert connection.execute("SELECT run_id FROM verification_runs").fetchone()[0] == "run-1"
    finally:
        connection.close()


def test_reassigning_candidate_removes_old_location_association(tmp_path: Path) -> None:
    connection = connect(tmp_path / "inventory.sqlite3")
    initialize(connection)
    try:
        insert_candidates(
            connection,
            (CandidateEntry("example", "Example Padel", "Geneva", "2", "club", "public"),),
        )
        first = location_record()
        upsert_location(connection, first)
        record_candidate_match(
            connection,
            CandidateMatch("example", "example-geneve", "matched", "Initial match."),
        )
        second = replace(
            first,
            location_id="other-geneve",
            canonical_name="Other Padel",
            candidate_ids=("example",),
        )
        upsert_location(connection, second)

        locations = {location.location_id: location for location in list_locations(connection)}
        assert locations["example-geneve"].candidate_ids == ()
        assert locations["other-geneve"].candidate_ids == ("example",)
        assert connection.execute(
            "SELECT matched_location_id FROM candidate_entries WHERE candidate_id = ?",
            ("example",),
        ).fetchone()[0] == "other-geneve"
        assert connection.execute(
            "SELECT COUNT(*) FROM location_candidates WHERE candidate_id = ?",
            ("example",),
        ).fetchone()[0] == 1
        assert list_candidate_matches(connection) == (
            CandidateMatch("example", "other-geneve", "matched", "Initial match."),
        )
    finally:
        connection.close()
