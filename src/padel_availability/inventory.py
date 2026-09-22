import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Sequence

from .database import (
    create_verification_run,
    insert_candidates,
    record_candidate_match,
    upsert_location,
)
from .models import (
    CandidateEntry,
    CandidateMatch,
    LocationRecord,
    MatchStatus,
    ModelError,
    VerificationRun,
)


_CANDIDATE_FIELDS = {
    "candidate_id",
    "raw_name",
    "municipality",
    "courts_text",
    "type_text",
    "access_text",
}
_CATALOG_FIELDS = {"format_version", "verified_at", "locations"}


@contextmanager
def _catalog_transaction(connection: sqlite3.Connection) -> Iterator[None]:
    if connection.in_transaction:
        savepoint = "catalog_build"
        connection.execute(f"SAVEPOINT {savepoint}")
        try:
            yield
        except BaseException:
            connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            connection.execute(f"RELEASE SAVEPOINT {savepoint}")
            raise
        else:
            connection.execute(f"RELEASE SAVEPOINT {savepoint}")
        return

    connection.execute("BEGIN")
    try:
        yield
    except BaseException:
        connection.rollback()
        raise
    else:
        connection.commit()


def validate_candidate_set(entries: Sequence[CandidateEntry]) -> None:
    if not entries:
        raise ValueError("candidate set must not be empty")
    candidate_ids: set[str] = set()
    for entry in entries:
        if not isinstance(entry, CandidateEntry):
            raise ValueError("entries must contain CandidateEntry values")
        if not entry.raw_name.strip():
            raise ValueError("raw_name must not be blank")
        if not entry.municipality.strip():
            raise ValueError("municipality must not be blank")
        if entry.candidate_id in candidate_ids:
            raise ValueError(f"duplicate candidate_id: {entry.candidate_id}")
        candidate_ids.add(entry.candidate_id)


def load_candidates(path: Path) -> tuple[CandidateEntry, ...]:
    with path.open(encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, list):
        raise ValueError("candidate JSON must contain a list")

    entries: list[CandidateEntry] = []
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise ValueError(f"candidate at index {index} must be an object")
        missing = _CANDIDATE_FIELDS - item.keys()
        unknown = item.keys() - _CANDIDATE_FIELDS
        if missing:
            raise ValueError(
                f"candidate at index {index} is missing fields: {', '.join(sorted(missing))}"
            )
        if unknown:
            raise ValueError(
                f"candidate at index {index} has unknown fields: {', '.join(sorted(unknown))}"
            )
        try:
            entries.append(
                CandidateEntry(
                    candidate_id=item["candidate_id"],
                    raw_name=item["raw_name"],
                    municipality=item["municipality"],
                    courts_text=item["courts_text"],
                    type_text=item["type_text"],
                    access_text=item["access_text"],
                )
            )
        except (TypeError, ValueError) as error:
            raise ValueError(f"invalid candidate at index {index}") from error
    validate_candidate_set(entries)
    return tuple(entries)


def load_locations(path: Path) -> tuple[LocationRecord, ...]:
    with path.open(encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        raise ModelError("verified catalog JSON must contain an object")
    missing = _CATALOG_FIELDS - payload.keys()
    unknown = payload.keys() - _CATALOG_FIELDS
    if missing:
        raise ModelError(f"catalog is missing fields: {', '.join(sorted(missing))}")
    if unknown:
        raise ModelError(f"catalog has unknown fields: {', '.join(sorted(unknown))}")
    if (
        not isinstance(payload["format_version"], int)
        or isinstance(payload["format_version"], bool)
        or payload["format_version"] != 1
    ):
        raise ModelError("format_version must be 1")
    verified_at = payload["verified_at"]
    if not isinstance(verified_at, str):
        raise ModelError("verified_at must be an ISO date")
    try:
        parsed_date = date.fromisoformat(verified_at)
    except ValueError as error:
        raise ModelError("verified_at must be an ISO date") from error
    if parsed_date.isoformat() != verified_at:
        raise ModelError("verified_at must be an ISO date")
    raw_locations = payload["locations"]
    if not isinstance(raw_locations, list):
        raise ModelError("locations must be a list")

    locations: list[LocationRecord] = []
    location_ids: set[str] = set()
    candidate_ids: set[str] = set()
    for index, item in enumerate(raw_locations):
        if not isinstance(item, dict):
            raise ModelError(f"location at index {index} must be an object")
        try:
            location = LocationRecord.from_mapping(item)
        except (TypeError, ValueError) as error:
            raise ModelError(f"invalid location at index {index}") from error
        if location.location_id in location_ids:
            raise ModelError(f"duplicate location_id: {location.location_id}")
        location_ids.add(location.location_id)
        duplicate_candidates = candidate_ids.intersection(location.candidate_ids)
        if duplicate_candidates:
            raise ModelError(
                "candidate assigned to multiple locations: "
                + ", ".join(sorted(duplicate_candidates))
            )
        candidate_ids.update(location.candidate_ids)
        locations.append(location)
    return tuple(locations)


def validate_verified_catalog(
    candidates: Sequence[CandidateEntry], locations: Sequence[LocationRecord]
) -> None:
    try:
        validate_candidate_set(candidates)
    except ValueError as error:
        raise ModelError(str(error)) from error
    candidate_ids: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, CandidateEntry):
            raise ModelError("candidates must contain CandidateEntry values")
        if candidate.candidate_id in candidate_ids:
            raise ModelError(f"duplicate candidate_id: {candidate.candidate_id}")
        candidate_ids.add(candidate.candidate_id)

    assigned: dict[str, LocationRecord] = {}
    location_ids: set[str] = set()
    for location in locations:
        if not isinstance(location, LocationRecord):
            raise ModelError("locations must contain LocationRecord values")
        if location.location_id in location_ids:
            raise ModelError(f"duplicate location_id: {location.location_id}")
        location_ids.add(location.location_id)
        if location.verification_status not in {
            "confirmed",
            "probable",
            "to_verify",
            "not_confirmed",
            "closed",
        }:
            raise ModelError(f"unsupported verification status: {location.verification_status}")
        if location.verification_status in {"confirmed", "probable"} and not location.evidence:
            raise ModelError(
                f"location {location.location_id} with status "
                f"{location.verification_status} requires evidence"
            )
        supporting_fact_keys = {
            item.fact_key for item in location.evidence if item.relation == "supports"
        }
        required_fact_keys = {"location.municipality"}
        if location.access_kind != "unknown":
            required_fact_keys.add("location.access_kind")
        required_fact_keys.update(
            f"location.{field}"
            for field in (
                "membership_required",
                "public_booking",
                "racket_rental",
                "locker_rooms",
                "booking_account_required",
            )
            if getattr(location, field) != "unknown"
        )
        if location.court_groups:
            required_fact_keys.add("location.courts")
            if any(group.format is not None for group in location.court_groups):
                required_fact_keys.add("location.court_format")
            if any(group.cover_status != "unknown" for group in location.court_groups):
                required_fact_keys.add("location.cover_status")
        if location.overall_cover_status != "unknown":
            required_fact_keys.add("location.cover_status")
        for field in (
            "address",
            "aliases",
            "official_url",
            "booking_url",
            "booking_platform",
            "brand",
            "latitude",
            "longitude",
        ):
            if getattr(location, field) is not None and getattr(location, field) != ():
                required_fact_keys.add(f"location.{field}")
        missing_fact_keys = required_fact_keys - supporting_fact_keys
        if missing_fact_keys:
            raise ModelError(
                f"location {location.location_id} is missing supporting evidence for: "
                + ", ".join(sorted(missing_fact_keys))
            )
        for candidate_id in location.candidate_ids:
            previous = assigned.get(candidate_id)
            if previous is not None:
                raise ModelError(
                    f"candidate {candidate_id} is ambiguously assigned to "
                    f"{previous.location_id} and {location.location_id}"
                )
            assigned[candidate_id] = location

    missing = candidate_ids - assigned.keys()
    if missing:
        raise ModelError(
            "candidates missing from verified catalog: " + ", ".join(sorted(missing))
        )
    unexpected = assigned.keys() - candidate_ids
    if unexpected:
        raise ModelError(
            "verified catalog contains unknown candidates: " + ", ".join(sorted(unexpected))
        )


def import_candidates(connection: sqlite3.Connection, entries: Sequence[CandidateEntry]) -> None:
    validate_candidate_set(entries)
    insert_candidates(connection, entries)


def build_catalog(
    connection: sqlite3.Connection,
    candidates: Sequence[CandidateEntry],
    locations: Sequence[LocationRecord],
    run: VerificationRun,
) -> None:
    validate_verified_catalog(candidates, locations)
    with _catalog_transaction(connection):
        insert_candidates(connection, candidates, commit=False)
        location_ids = tuple(location.location_id for location in locations)
        candidate_ids = tuple(candidate.candidate_id for candidate in candidates)
        connection.execute("DELETE FROM candidate_matches")
        if location_ids:
            location_placeholders = ",".join("?" for _ in location_ids)
            connection.execute(
                "UPDATE candidate_entries SET matched_location_id = NULL "
                f"WHERE matched_location_id NOT IN ({location_placeholders})",
                location_ids,
            )
            connection.execute(
                f"DELETE FROM locations WHERE location_id NOT IN ({location_placeholders})",
                location_ids,
            )
        else:
            connection.execute("UPDATE candidate_entries SET matched_location_id = NULL")
            connection.execute("DELETE FROM locations")
        candidate_placeholders = ",".join("?" for _ in candidate_ids)
        connection.execute(
            f"DELETE FROM candidate_entries WHERE candidate_id NOT IN ({candidate_placeholders})",
            candidate_ids,
        )
        for location in locations:
            upsert_location(connection, location, commit=False)
        connection.execute(
            "DELETE FROM sources WHERE NOT EXISTS "
            "(SELECT 1 FROM location_evidence WHERE location_evidence.source_id = sources.source_id)"
        )
        candidates_by_id = {candidate.candidate_id: candidate for candidate in candidates}
        for location in locations:
            for index, candidate_id in enumerate(location.candidate_ids):
                if location.verification_status == "not_confirmed":
                    status: MatchStatus = "not_confirmed"
                elif index == 0:
                    candidate_name = candidates_by_id[candidate_id].raw_name
                    slash_parts = tuple(part.strip() for part in candidate_name.split("/"))
                    status = (
                        "matched"
                        if len(slash_parts) == 1
                        or all(part in location.aliases for part in slash_parts)
                        else "unresolved"
                    )
                else:
                    status = "duplicate"
                note = location.notes or "Catalog match."
                record_candidate_match(
                    connection,
                    CandidateMatch(candidate_id, location.location_id, status, note),
                    commit=False,
                )
        create_verification_run(connection, run, commit=False)
