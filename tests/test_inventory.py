import json
import sqlite3
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from padel_availability.database import (
    connect,
    initialize,
    list_candidate_matches,
    list_locations,
)
from padel_availability.inventory import (
    build_catalog,
    import_candidates,
    load_candidates,
    load_locations,
    validate_candidate_set,
    validate_verified_catalog,
)
from padel_availability.models import (
    CandidateEntry,
    CourtGroup,
    LocationRecord,
    ModelError,
    SourceEvidence,
    VerificationRun,
    VerificationStatus,
)


def candidate(candidate_id: str) -> CandidateEntry:
    return CandidateEntry(candidate_id, f"Example {candidate_id}", "Geneva", None, None, None)


def location_with_candidate(candidate_id: str) -> LocationRecord:
    return LocationRecord(
        location_id=f"location-{candidate_id}",
        canonical_name=f"Example {candidate_id}",
        municipality="Geneva",
        candidate_ids=(candidate_id,),
        access_kind="public",
        membership_required="unknown",
        public_booking="unknown",
        racket_rental="unknown",
        locker_rooms="unknown",
        booking_account_required="unknown",
        verification_status="probable",
        court_groups=(),
        aliases=(),
        evidence=(
            SourceEvidence(
                url="https://example.test/location",
                source_type="official",
                title="Example location",
                checked_at="2026-09-21T00:00:00Z",
                fact_key="location.exists",
                relation="supports",
                evidence="The official page names the location.",
                confidence="probable",
            ),
            SourceEvidence(
                url="https://example.test/location",
                source_type="official",
                title="Example location",
                checked_at="2026-09-21T00:00:00Z",
                fact_key="location.municipality",
                relation="supports",
                evidence="The official page places the location in Geneva.",
                confidence="probable",
            ),
            SourceEvidence(
                url="https://example.test/location",
                source_type="official",
                title="Example location",
                checked_at="2026-09-21T00:00:00Z",
                fact_key="location.access_kind",
                relation="supports",
                evidence="The official page describes public access.",
                confidence="probable",
            ),
            SourceEvidence(
                url="https://example.test/location",
                source_type="official",
                title="Example location",
                checked_at="2026-09-21T00:00:00Z",
                fact_key="location.courts",
                relation="supports",
                evidence="The official page lists the courts.",
                confidence="probable",
            ),
        ),
        notes="",
    )


def location_with_status(
    status: VerificationStatus, evidence: tuple[SourceEvidence, ...]
) -> LocationRecord:
    return LocationRecord(
        location_id="location-one",
        canonical_name="Example one",
        municipality="Geneva",
        candidate_ids=("one",),
        access_kind="unknown",
        membership_required="unknown",
        public_booking="unknown",
        racket_rental="unknown",
        locker_rooms="unknown",
        booking_account_required="unknown",
        verification_status=status,
        court_groups=(),
        aliases=(),
        evidence=evidence,
        notes="",
    )


def verification_run(run_id: str = "run-1") -> VerificationRun:
    return VerificationRun(
        run_id,
        "2026-09-21T00:00:00Z",
        "2026-09-21T00:01:00Z",
        1,
        0,
        "catalog built",
    )


def assert_catalog_empty(connection: sqlite3.Connection) -> None:
    for table in (
        "candidate_entries",
        "locations",
        "court_groups",
        "location_aliases",
        "location_candidates",
        "sources",
        "location_evidence",
        "candidate_matches",
        "verification_runs",
    ):
        assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_catalog_requires_each_candidate_to_be_matched_or_explicitly_unconfirmed() -> None:
    candidates = (candidate("one"), candidate("two"))
    locations = (location_with_candidate("one"),)

    with pytest.raises(ModelError, match="two"):
        validate_verified_catalog(candidates, locations)


def test_confirmed_location_requires_external_evidence() -> None:
    evidence: tuple[SourceEvidence, ...] = ()

    with pytest.raises(ModelError, match="evidence"):
        validate_verified_catalog(
            (candidate("one"),), (location_with_status("confirmed", evidence),)
        )


def test_known_fact_requires_supporting_evidence_with_exact_fact_key() -> None:
    location = replace(
        location_with_status(
            "probable",
            (
                SourceEvidence(
                    url="https://example.test/location",
                    source_type="official",
                    title="Example location",
                    checked_at="2026-09-21T00:00:00Z",
                    fact_key="location.exists",
                    relation="supports",
                    evidence="The official page names the location.",
                    confidence="probable",
                ),
            ),
        ),
        public_booking="yes",
    )

    with pytest.raises(ModelError, match="public_booking"):
        validate_verified_catalog((candidate("one"),), (location,))


def test_load_locations_validates_catalog_metadata_and_candidate_assignments(
    tmp_path: Path,
) -> None:
    path = tmp_path / "locations.json"
    path.write_text(
        json.dumps(
            {
                "format_version": 1,
                "verified_at": "2026-09-21",
                "locations": [location_with_candidate("one").to_mapping()],
            }
        ),
        encoding="utf-8",
    )

    assert load_locations(path) == (location_with_candidate("one"),)

    invalid = json.loads(path.read_text(encoding="utf-8"))
    invalid["format_version"] = 2
    path.write_text(json.dumps(invalid), encoding="utf-8")
    with pytest.raises(ModelError, match="format_version"):
        load_locations(path)


def test_location_mapping_rejects_unknown_fields() -> None:
    mapping = location_with_candidate("one").to_mapping()
    mapping["unexpected"] = "reject me"

    with pytest.raises(ModelError, match="unknown location keys"):
        LocationRecord.from_mapping(mapping)


def test_supplied_verified_catalog_accounts_for_all_candidates() -> None:
    candidates = load_candidates(Path("data/candidates.json"))
    locations = load_locations(Path("data/verified_locations.json"))

    validate_verified_catalog(candidates, locations)
    assert len(locations) == 29
    assigned = [candidate_id for location in locations for candidate_id in location.candidate_ids]
    assert len(assigned) == len(set(assigned)) == 29
    assert set(assigned) == {entry.candidate_id for entry in candidates}
    assert {location.verification_status for location in locations} == {
        "confirmed",
        "probable",
        "to_verify",
    }
    assert sum(location.verification_status == "confirmed" for location in locations) == 13
    assert sum(location.verification_status == "probable" for location in locations) == 3
    assert sum(location.verification_status == "to_verify" for location in locations) == 13
    assert {
        location.location_id for location in locations if location.verification_status == "probable"
    } == {"asphalte-jonction", "maisonnex", "vernier"}
    assert all(location.evidence for location in locations)

    for location in locations:
        fact_keys = {item.fact_key for item in location.evidence if item.relation == "supports"}
        for field, fact_key in (
            ("access_kind", "location.access_kind"),
            ("membership_required", "location.membership_required"),
            ("public_booking", "location.public_booking"),
            ("racket_rental", "location.racket_rental"),
            ("locker_rooms", "location.locker_rooms"),
            ("booking_account_required", "location.booking_account_required"),
        ):
            if getattr(location, field) != "unknown":
                assert fact_key in fact_keys
        if location.municipality != "unknown":
            assert "location.municipality" in fact_keys
        if location.court_groups:
            assert "location.courts" in fact_keys
            for group in location.court_groups:
                if group.format is not None:
                    assert "location.court_format" in fact_keys
                    assert any(
                        group.format.lower() in item.evidence.lower()
                        for item in location.evidence
                        if item.relation == "supports" and item.fact_key == "location.court_format"
                    )
        if location.address is not None:
            assert "location.address" in fact_keys
        if location.overall_cover_status != "unknown":
            assert "location.cover_status" in fact_keys
        if location.official_url is not None:
            assert "location.official_url" in fact_keys
        if location.booking_url is not None:
            assert "location.booking_url" in fact_keys
        if location.booking_platform is not None:
            assert "location.booking_platform" in fact_keys
        if location.aliases:
            assert "location.aliases" in fact_keys


def test_matchpoint_locations_have_current_booking_evidence() -> None:
    locations = {
        location.location_id: location
        for location in load_locations(Path("data/verified_locations.json"))
    }

    expected = {
        "asphalte-jonction": (
            "https://padelgeneva.matchpoint.com.es/Booking/Grid.aspx?id=9",
            "Padel Connect",
        ),
        "bernex": (
            "https://padelgeneva.matchpoint.com.es/Booking/Grid.aspx",
            "Padel Connect",
        ),
        "evaux": (
            "https://padelgeneva.matchpoint.com.es/Booking/Grid.aspx?id=8",
            "Padel Connect",
        ),
        "urban-padel-lausanne": (
            "https://urbanpadellausanne.matchpoint.com.es/Booking/Grid.aspx",
            "Matchpoint",
        ),
    }
    for location_id, (booking_url, booking_platform) in expected.items():
        location = locations[location_id]
        assert location.booking_url == booking_url
        assert location.booking_platform == booking_platform
        supporting_facts = {
            item.fact_key for item in location.evidence if item.relation == "supports"
        }
        assert {"location.booking_url", "location.booking_platform"} <= supporting_facts


def test_plugin_locations_have_current_booking_evidence() -> None:
    locations = {
        location.location_id: location
        for location in load_locations(Path("data/verified_locations.json"))
    }
    expected = {
        "cologny": ("https://reservation.cs-cologny.ch/diary", "Plugin.ch"),
        "collonge-bellerive": ("https://reservation.tccb.ch/diary", "Plugin.ch"),
        "crans-vd": ("https://tccrans.plugin.ch/user/diary", "Plugin.ch"),
        "csu-champel": ("https://unige.plugin.ch/", "Plugin.ch"),
        "drizia-miremont": ("https://tcdrizia.plugin.ch/", "Plugin.ch"),
        "fraisiers": ("https://tcfraisiers.plugin.ch/?sport=301", "Plugin.ch"),
        "gland": ("https://tcgland.plugin.ch/user/diary", "Plugin.ch"),
        "mies-tannay": ("https://tcmt.plugin.ch/user/diary", "Plugin.ch"),
    }
    for location_id, (booking_url, booking_platform) in expected.items():
        location = locations[location_id]
        assert location.booking_url == booking_url
        assert location.booking_platform == booking_platform
        assert {
            "location.booking_url",
            "location.booking_platform",
        } <= {
            item.fact_key
            for item in location.evidence
            if item.relation == "supports"
            and item.url == booking_url
            and item.checked_at == "2026-09-26T00:00:00Z"
        }


def test_published_price_and_duration_evidence_is_source_backed() -> None:
    locations = {
        location.location_id: location
        for location in load_locations(Path("data/verified_locations.json"))
    }
    airpad_facts = {
        "location.price": "The operator publishes standard prices of CHF 13 for 60 minutes, CHF 15 for 90 minutes, and CHF 18 for 120 minutes, plus off-peak prices of CHF 8, CHF 10, and CHF 13 for those durations.",
        "location.duration": "The operator publishes booking durations of 60, 90, and 120 minutes for its standard and off-peak padel tariffs.",
    }
    expected = {
        "airpad-les-acacias": ("https://www.airpad.ch/airpad", airpad_facts),
        "airpad-la-praille": ("https://www.airpad.ch/airpad", airpad_facts),
        "airpad-meyrin": ("https://www.airpad.ch/airpad", airpad_facts),
        "airpad-plan-les-ouates": ("https://www.airpad.ch/airpad", airpad_facts),
        "padel-station": (
            "https://padelstation.ch/",
            {
                "location.price": "The operator publishes weekday prices: early bird CHF 36/1h, standard CHF 50/1.5h, premium CHF 56/1h, and afterwork CHF 56/1.5h; weekend CHF 56/1.5h.",
                "location.duration": "The operator publishes weekday durations of 1h (early bird and premium) and 1.5h (standard and afterwork), plus 1.5h on weekends.",
            },
        ),
        "maisonnex": (
            "https://shop.bookinea.app/fr/meyrin-sports",
            {
                "location.price": "The portal lists Padel 90 minutes at CHF 60.00 and Entrée individuelle Invité Padel at CHF 15.00.",
                "location.duration": "The portal lists Padel 90 minutes.",
            },
        ),
        "vernier": (
            "https://www.vernier.ch/vie-pratique/demarches/courts-de-padel-reservations",
            {
                "location.price": "The page publishes a unique tariff of CHF 48.– / 1h30.",
                "location.duration": "The page publishes the padel booking duration as 1h30.",
            },
        ),
        "vaudoise-arena": (
            "https://vaudoisearena.ch/centres-sportifs/padel",
            {
                "location.price": "The operator publishes off-peak CHF 42.- / h and peak CHF 52.- / h for padel.",
                "location.duration": "The operator publishes both padel rates per hour.",
            },
        ),
    }

    for location_id, (url, fact_evidence) in expected.items():
        location = locations[location_id]
        for fact_key, evidence_text in fact_evidence.items():
            assert any(
                item.url == url
                and item.checked_at == "2026-09-21T00:00:00Z"
                and item.fact_key == fact_key
                and item.relation == "supports"
                and item.evidence == evidence_text
                for item in location.evidence
            )


def test_build_catalog_is_atomic_and_idempotent(tmp_path: Path) -> None:
    connection = connect(tmp_path / "inventory.sqlite3")
    initialize(connection)
    entries = (candidate("one"),)
    locations = (location_with_candidate("one"),)
    try:
        build_catalog(connection, entries, locations, verification_run())
        first_locations = list_locations(connection)
        first_matches = list_candidate_matches(connection)
        first_counts = tuple(
            connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("sources", "location_evidence", "candidate_matches")
        )

        build_catalog(connection, entries, locations, verification_run())

        assert list_locations(connection) == first_locations
        assert list_candidate_matches(connection) == first_matches
        assert (
            tuple(
                connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("sources", "location_evidence", "candidate_matches")
            )
            == first_counts
        )
        assert connection.execute("SELECT COUNT(*) FROM verification_runs").fetchone()[0] == 1
    finally:
        connection.close()


def test_slash_name_without_confirmed_aliases_is_unresolved(tmp_path: Path) -> None:
    candidates = load_candidates(Path("data/candidates.json"))
    locations = load_locations(Path("data/verified_locations.json"))
    connection = connect(tmp_path / "inventory.sqlite3")
    initialize(connection)
    try:
        build_catalog(connection, candidates, locations, verification_run())
        matches = {match.candidate_id: match for match in list_candidate_matches(connection)}

        assert matches["fraisiers"].status == "unresolved"
        assert matches["fraisiers"].location_id == "fraisiers"
        assert matches["drizia-miremont"].status == "unresolved"
        assert matches["drizia-miremont"].location_id == "drizia-miremont"
        assert matches["asphalte-jonction"].status == "matched"
    finally:
        connection.close()


def test_build_catalog_rolls_back_all_writes_on_failure(tmp_path: Path) -> None:
    connection = connect(tmp_path / "inventory.sqlite3")
    initialize(connection)
    entries = (candidate("one"),)
    locations = (
        replace(
            location_with_candidate("one"),
            court_groups=(
                CourtGroup("same", 1, None, "unknown"),
                CourtGroup("same", 2, None, "unknown"),
            ),
        ),
    )
    try:
        with pytest.raises(sqlite3.IntegrityError):
            build_catalog(connection, entries, locations, verification_run())
        assert_catalog_empty(connection)
    finally:
        connection.close()


def test_build_catalog_rolls_back_all_writes_in_autocommit_mode() -> None:
    connection = sqlite3.connect(":memory:", isolation_level=None)
    initialize(connection)
    entries = (candidate("one"),)
    locations = (
        replace(
            location_with_candidate("one"),
            court_groups=(
                CourtGroup("same", 1, None, "unknown"),
                CourtGroup("same", 2, None, "unknown"),
            ),
        ),
    )
    try:
        with pytest.raises(sqlite3.IntegrityError):
            build_catalog(connection, entries, locations, verification_run())
        assert_catalog_empty(connection)
    finally:
        connection.close()


def test_build_catalog_uses_savepoint_inside_existing_transaction() -> None:
    connection = connect(Path(":memory:"))
    initialize(connection)
    connection.execute(
        "INSERT INTO candidate_entries (candidate_id, raw_name, municipality) VALUES (?, ?, ?)",
        ("outside", "Outside", "Geneva"),
    )
    try:
        build_catalog(
            connection,
            (candidate("one"),),
            (location_with_candidate("one"),),
            verification_run(),
        )
        assert connection.in_transaction
        connection.rollback()
        assert_catalog_empty(connection)
    finally:
        connection.close()


def test_supplied_candidate_set_contains_29_entries() -> None:
    entries = load_candidates(Path("data/candidates.json"))

    assert len(entries) == 29
    assert entries[0].raw_name == "AIRPAD Les Acacias"
    assert any(entry.raw_name == "L'Asphalte / Pointe de la Jonction" for entry in entries)
    assert any(entry.raw_name == "Vaudoise aréna" for entry in entries)
    entries_by_id = {entry.candidate_id: entry for entry in entries}
    assert entries_by_id["airpad-les-acacias"].courts_text == "2"
    assert entries_by_id["airpad-les-acacias"].type_text == "couvert/indoor"
    assert entries_by_id["fraisiers"].access_text == "À vérifier"
    assert entries_by_id["padel-parc-etoy"].access_text is None


def test_validate_candidate_set_rejects_duplicate_ids_and_blank_municipalities() -> None:
    duplicate = CandidateEntry("same", "One", "Genève", None, None, None)
    with pytest.raises(ValueError, match="duplicate candidate_id"):
        validate_candidate_set((duplicate, duplicate))

    with pytest.raises(ValueError, match="municipality"):
        validate_candidate_set((CandidateEntry("one", "One", " ", None, None, None),))


def test_validate_candidate_set_rejects_non_candidate_objects() -> None:
    with pytest.raises(TypeError, match="CandidateEntry"):
        validate_candidate_set(cast(Sequence[CandidateEntry], (object(),)))


@pytest.mark.parametrize(
    "payload",
    [
        [],
        [{"candidate_id": "one"}],
        [
            {
                "candidate_id": "one",
                "raw_name": " ",
                "municipality": "Genève",
                "courts_text": None,
                "type_text": None,
                "access_text": None,
            }
        ],
        [
            {
                "candidate_id": "one",
                "raw_name": "One",
                "municipality": "Genève",
                "courts_text": None,
                "type_text": None,
                "access_text": None,
                "unexpected": "reject me",
            }
        ],
    ],
)
def test_load_candidates_rejects_invalid_json_payloads(tmp_path: Path, payload: object) -> None:
    path = tmp_path / "candidates.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError):
        load_candidates(path)


@pytest.mark.parametrize("payload", [{}, ["not an object"]])
def test_load_candidates_rejects_wrong_json_types(tmp_path: Path, payload: object) -> None:
    path = tmp_path / "candidates.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(TypeError):
        load_candidates(path)


def test_import_candidates_is_idempotent_and_preserves_existing_match() -> None:
    connection = connect(Path(":memory:"))
    initialize(connection)
    try:
        entry = CandidateEntry("one", "One", "Genève", "2", "indoor", "public")
        import_candidates(connection, (entry,))
        connection.execute(
            """
            INSERT INTO locations (
                location_id, canonical_name, municipality, access_kind,
                membership_required, public_booking, racket_rental, locker_rooms,
                booking_account_required, verification_status, overall_cover_status, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "location-1",
                "Location 1",
                "Genève",
                "unknown",
                "unknown",
                "unknown",
                "unknown",
                "unknown",
                "unknown",
                "to_verify",
                "unknown",
                "",
            ),
        )
        connection.commit()
        connection.execute(
            "UPDATE candidate_entries SET matched_location_id = ? WHERE candidate_id = ?",
            ("location-1", "one"),
        )
        connection.commit()

        import_candidates(
            connection,
            (CandidateEntry("one", "Updated", "Lancy", None, None, None),),
        )

        row = connection.execute(
            "SELECT raw_name, municipality, courts_text, type_text, access_text, "
            "matched_location_id FROM candidate_entries WHERE candidate_id = ?",
            ("one",),
        ).fetchone()
        assert tuple(row) == ("Updated", "Lancy", None, None, None, "location-1")
        assert connection.execute("SELECT COUNT(*) FROM candidate_entries").fetchone()[0] == 1
    finally:
        connection.close()


def test_fixture_import_round_trips_all_29_candidates(tmp_path: Path) -> None:
    entries = load_candidates(Path("data/candidates.json"))
    connection = connect(tmp_path / "inventory.sqlite3")
    initialize(connection)
    try:
        import_candidates(connection, entries)

        rows = connection.execute(
            "SELECT candidate_id, raw_name, municipality, courts_text, type_text, access_text "
            "FROM candidate_entries ORDER BY candidate_id"
        ).fetchall()
        assert len(rows) == 29
        assert {row["candidate_id"]: tuple(row[1:]) for row in rows} == {
            entry.candidate_id: (
                entry.raw_name,
                entry.municipality,
                entry.courts_text,
                entry.type_text,
                entry.access_text,
            )
            for entry in entries
        }
        assert (
            connection.execute(
                "SELECT access_text FROM candidate_entries WHERE candidate_id = ?",
                ("fraisiers",),
            ).fetchone()[0]
            == "À vérifier"
        )
        assert (
            connection.execute(
                "SELECT access_text FROM candidate_entries WHERE candidate_id = ?",
                ("padel-parc-etoy",),
            ).fetchone()[0]
            is None
        )
    finally:
        connection.close()
