import sqlite3
from collections.abc import Sequence
from contextlib import nullcontext
from pathlib import Path

from .availability import (
    AvailabilityResult,
    AvailabilityRun,
    AvailabilitySlot,
    AvailabilitySnapshot,
)
from .models import (
    CandidateEntry,
    CandidateMatch,
    CourtGroup,
    LocationRecord,
    SourceEvidence,
    VerificationRun,
)


def connect(path: Path) -> sqlite3.Connection:
    path_text = str(path)
    if path_text != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS locations (
            location_id TEXT PRIMARY KEY,
            canonical_name TEXT NOT NULL,
            municipality TEXT NOT NULL,
            brand TEXT,
            address TEXT,
            latitude REAL,
            longitude REAL,
            access_kind TEXT NOT NULL CHECK (access_kind IN ('public', 'members', 'university', 'conditions', 'unknown')),
            membership_required TEXT NOT NULL CHECK (membership_required IN ('yes', 'no', 'unknown')),
            public_booking TEXT NOT NULL CHECK (public_booking IN ('yes', 'no', 'unknown')),
            racket_rental TEXT NOT NULL CHECK (racket_rental IN ('yes', 'no', 'unknown')),
            locker_rooms TEXT NOT NULL CHECK (locker_rooms IN ('yes', 'no', 'unknown')),
            booking_account_required TEXT NOT NULL CHECK (booking_account_required IN ('yes', 'no', 'unknown')),
            verification_status TEXT NOT NULL CHECK (verification_status IN ('confirmed', 'probable', 'to_verify', 'not_confirmed', 'closed')),
            overall_cover_status TEXT NOT NULL CHECK (overall_cover_status IN ('indoor', 'outdoor', 'partially_covered', 'seasonal', 'unknown')),
            official_url TEXT,
            booking_url TEXT,
            booking_platform TEXT,
            first_verified_at TEXT,
            last_verified_at TEXT,
            notes TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS availability_runs (
            run_id TEXT PRIMARY KEY,
            location_id TEXT NOT NULL REFERENCES locations(location_id) ON DELETE CASCADE,
            connector TEXT NOT NULL,
            source_url TEXT NOT NULL,
            window_start TEXT NOT NULL,
            window_end TEXT NOT NULL,
            horizon_days INTEGER NOT NULL CHECK (horizon_days > 0),
            collected_at TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('success', 'error', 'unavailable')),
            error TEXT
        );

        CREATE TABLE IF NOT EXISTS availability_slots (
            run_id TEXT NOT NULL REFERENCES availability_runs(run_id) ON DELETE CASCADE,
            location_id TEXT NOT NULL REFERENCES locations(location_id) ON DELETE CASCADE,
            slot_key TEXT NOT NULL,
            external_id TEXT,
            court_label TEXT,
            starts_at TEXT NOT NULL,
            ends_at TEXT NOT NULL,
            timezone TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('available', 'unavailable', 'unknown')),
            PRIMARY KEY (run_id, slot_key)
        );

        CREATE TABLE IF NOT EXISTS court_groups (
            court_group_id INTEGER PRIMARY KEY,
            location_id TEXT NOT NULL REFERENCES locations(location_id) ON DELETE CASCADE,
            label TEXT NOT NULL,
            count INTEGER NOT NULL CHECK (count > 0),
            format TEXT,
            cover_status TEXT NOT NULL CHECK (cover_status IN ('indoor', 'outdoor', 'partially_covered', 'seasonal', 'unknown')),
            UNIQUE (location_id, label)
        );

        CREATE TABLE IF NOT EXISTS location_aliases (
            location_id TEXT NOT NULL REFERENCES locations(location_id) ON DELETE CASCADE,
            alias TEXT NOT NULL,
            PRIMARY KEY (location_id, alias)
        );

        CREATE TABLE IF NOT EXISTS sources (
            source_id INTEGER PRIMARY KEY,
            url TEXT NOT NULL,
            source_type TEXT NOT NULL,
            title TEXT NOT NULL,
            checked_at TEXT NOT NULL,
            UNIQUE (url, source_type, title, checked_at)
        );

        CREATE TABLE IF NOT EXISTS location_evidence (
            location_id TEXT NOT NULL REFERENCES locations(location_id) ON DELETE CASCADE,
            source_id INTEGER NOT NULL REFERENCES sources(source_id),
            fact_key TEXT NOT NULL,
            checked_at TEXT NOT NULL,
            relation TEXT NOT NULL CHECK (relation IN ('supports', 'contradicts', 'discovery')),
            evidence TEXT NOT NULL,
            confidence TEXT NOT NULL CHECK (confidence IN ('confirmed', 'probable', 'to_verify')),
            PRIMARY KEY (location_id, source_id, fact_key, checked_at, evidence)
        );

        CREATE TABLE IF NOT EXISTS candidate_entries (
            candidate_id TEXT PRIMARY KEY,
            raw_name TEXT NOT NULL,
            municipality TEXT NOT NULL,
            courts_text TEXT,
            type_text TEXT,
            access_text TEXT,
            matched_location_id TEXT REFERENCES locations(location_id)
        );

        CREATE TABLE IF NOT EXISTS location_candidates (
            location_id TEXT NOT NULL REFERENCES locations(location_id) ON DELETE CASCADE,
            candidate_id TEXT NOT NULL REFERENCES candidate_entries(candidate_id) ON DELETE CASCADE,
            PRIMARY KEY (location_id, candidate_id),
            UNIQUE (candidate_id)
        );

        CREATE TABLE IF NOT EXISTS candidate_matches (
            candidate_id TEXT PRIMARY KEY REFERENCES candidate_entries(candidate_id) ON DELETE CASCADE,
            location_id TEXT REFERENCES locations(location_id),
            status TEXT NOT NULL CHECK (status IN ('matched', 'duplicate', 'not_confirmed', 'unresolved')),
            note TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS verification_runs (
            run_id TEXT PRIMARY KEY,
            started_at TEXT NOT NULL,
            ended_at TEXT NOT NULL,
            candidate_count INTEGER NOT NULL CHECK (candidate_count >= 0),
            error_count INTEGER NOT NULL CHECK (error_count >= 0),
            summary TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS availability_refresh_jobs (
            job_id TEXT PRIMARY KEY,
            trigger TEXT NOT NULL CHECK (trigger IN ('manual', 'scheduled')),
            status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'success', 'partial', 'error')),
            requested_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            completed_locations INTEGER NOT NULL DEFAULT 0 CHECK (completed_locations >= 0),
            total_locations INTEGER NOT NULL CHECK (total_locations >= 0),
            error TEXT
        );

        CREATE INDEX IF NOT EXISTS availability_refresh_jobs_recent
            ON availability_refresh_jobs(requested_at DESC, job_id DESC);

        CREATE TABLE IF NOT EXISTS availability_refresh_control (
            singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
            last_started_at TEXT,
            last_scheduled_tick TEXT
        );

        INSERT OR IGNORE INTO availability_refresh_control (singleton_id)
        VALUES (1);
        """
    )
    connection.commit()


def insert_candidates(
    connection: sqlite3.Connection, entries: Sequence[CandidateEntry], *, commit: bool = True
) -> None:
    context = connection if commit else nullcontext()
    with context:
        connection.executemany(
            """
            INSERT INTO candidate_entries (
                candidate_id, raw_name, municipality, courts_text, type_text, access_text
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(candidate_id) DO UPDATE SET
                raw_name = excluded.raw_name,
                municipality = excluded.municipality,
                courts_text = excluded.courts_text,
                type_text = excluded.type_text,
                access_text = excluded.access_text
            """,
            [
                (
                    entry.candidate_id,
                    entry.raw_name,
                    entry.municipality,
                    entry.courts_text,
                    entry.type_text,
                    entry.access_text,
                )
                for entry in entries
            ],
        )


def _insert_evidence(
    connection: sqlite3.Connection, location_id: str, evidence: SourceEvidence
) -> None:
    connection.execute(
        """
        INSERT INTO sources (url, source_type, title, checked_at) VALUES (?, ?, ?, ?)
        ON CONFLICT(url, source_type, title, checked_at) DO NOTHING
        """,
        (evidence.url, evidence.source_type, evidence.title, evidence.checked_at),
    )
    source_id = connection.execute(
        "SELECT source_id FROM sources "
        "WHERE url = ? AND source_type = ? AND title = ? AND checked_at = ?",
        (evidence.url, evidence.source_type, evidence.title, evidence.checked_at),
    ).fetchone()[0]
    connection.execute(
        """
        INSERT INTO location_evidence (
            location_id, source_id, fact_key, checked_at, relation, evidence, confidence
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(location_id, source_id, fact_key, checked_at, evidence) DO UPDATE SET
            relation = excluded.relation,
            evidence = excluded.evidence,
            confidence = excluded.confidence
        """,
        (
            location_id,
            source_id,
            evidence.fact_key,
            evidence.checked_at,
            evidence.relation,
            evidence.evidence,
            evidence.confidence,
        ),
    )


def upsert_location(
    connection: sqlite3.Connection, location: LocationRecord, *, commit: bool = True
) -> None:
    checked_at = sorted(item.checked_at for item in location.evidence)
    context = connection if commit else nullcontext()
    with context:
        connection.execute(
            """
            INSERT INTO locations (
                location_id, canonical_name, municipality, brand, address, latitude, longitude,
                access_kind, membership_required, public_booking, racket_rental, locker_rooms,
                booking_account_required, verification_status, overall_cover_status,
                official_url, booking_url, booking_platform, first_verified_at, last_verified_at, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(location_id) DO UPDATE SET
                canonical_name = excluded.canonical_name,
                municipality = excluded.municipality,
                brand = excluded.brand,
                address = excluded.address,
                latitude = excluded.latitude,
                longitude = excluded.longitude,
                access_kind = excluded.access_kind,
                membership_required = excluded.membership_required,
                public_booking = excluded.public_booking,
                racket_rental = excluded.racket_rental,
                locker_rooms = excluded.locker_rooms,
                booking_account_required = excluded.booking_account_required,
                verification_status = excluded.verification_status,
                overall_cover_status = excluded.overall_cover_status,
                official_url = excluded.official_url,
                booking_url = excluded.booking_url,
                booking_platform = excluded.booking_platform,
                first_verified_at = excluded.first_verified_at,
                last_verified_at = excluded.last_verified_at,
                notes = excluded.notes
            """,
            (
                location.location_id,
                location.canonical_name,
                location.municipality,
                location.brand,
                location.address,
                location.latitude,
                location.longitude,
                location.access_kind,
                location.membership_required,
                location.public_booking,
                location.racket_rental,
                location.locker_rooms,
                location.booking_account_required,
                location.verification_status,
                location.overall_cover_status,
                location.official_url,
                location.booking_url,
                location.booking_platform,
                checked_at[0] if checked_at else None,
                checked_at[-1] if checked_at else None,
                location.notes,
            ),
        )
        connection.execute(
            "DELETE FROM court_groups WHERE location_id = ?", (location.location_id,)
        )
        connection.execute(
            "DELETE FROM location_aliases WHERE location_id = ?", (location.location_id,)
        )
        connection.execute(
            "DELETE FROM location_evidence WHERE location_id = ?", (location.location_id,)
        )
        connection.execute(
            "DELETE FROM location_candidates WHERE location_id = ?", (location.location_id,)
        )
        connection.execute(
            "UPDATE candidate_entries SET matched_location_id = NULL WHERE matched_location_id = ?",
            (location.location_id,),
        )
        for candidate_id in location.candidate_ids:
            connection.execute(
                "DELETE FROM location_candidates WHERE candidate_id = ? AND location_id != ?",
                (candidate_id, location.location_id),
            )
            connection.execute(
                """
                UPDATE candidate_entries
                SET matched_location_id = NULL
                WHERE candidate_id = ? AND matched_location_id != ?
                """,
                (candidate_id, location.location_id),
            )
            connection.execute(
                "UPDATE candidate_matches SET location_id = ? WHERE candidate_id = ?",
                (location.location_id, candidate_id),
            )
        connection.executemany(
            "INSERT INTO court_groups "
            "(location_id, label, count, format, cover_status) VALUES (?, ?, ?, ?, ?)",
            [
                (location.location_id, group.label, group.count, group.format, group.cover_status)
                for group in location.court_groups
            ],
        )
        connection.executemany(
            "INSERT INTO location_aliases (location_id, alias) VALUES (?, ?)",
            [(location.location_id, alias) for alias in location.aliases],
        )
        connection.executemany(
            "INSERT INTO location_candidates (location_id, candidate_id) VALUES (?, ?)",
            [(location.location_id, candidate_id) for candidate_id in location.candidate_ids],
        )
        connection.execute(
            "UPDATE candidate_entries SET matched_location_id = ? WHERE candidate_id IN ({})".format(
                ",".join("?" for _ in location.candidate_ids) or "NULL"
            ),
            (location.location_id, *location.candidate_ids),
        )
        for evidence in location.evidence:
            _insert_evidence(connection, location.location_id, evidence)


def insert_evidence(
    connection: sqlite3.Connection, location_id: str, evidence: SourceEvidence
) -> None:
    with connection:
        _insert_evidence(connection, location_id, evidence)


def _location_from_row(connection: sqlite3.Connection, row: sqlite3.Row) -> LocationRecord:
    groups = connection.execute(
        "SELECT label, count, format, cover_status FROM court_groups "
        "WHERE location_id = ? ORDER BY court_group_id",
        (row["location_id"],),
    ).fetchall()
    aliases = connection.execute(
        "SELECT alias FROM location_aliases WHERE location_id = ? ORDER BY alias",
        (row["location_id"],),
    ).fetchall()
    candidate_ids = connection.execute(
        "SELECT candidate_id FROM location_candidates WHERE location_id = ? ORDER BY candidate_id",
        (row["location_id"],),
    ).fetchall()
    evidence = connection.execute(
        """
        SELECT s.url, s.source_type, s.title, e.checked_at,
               e.fact_key, e.relation, e.evidence, e.confidence
        FROM location_evidence AS e
        JOIN sources AS s ON s.source_id = e.source_id
        WHERE e.location_id = ?
        ORDER BY e.fact_key, s.url, s.source_type, s.title, e.checked_at, e.evidence
        """,
        (row["location_id"],),
    ).fetchall()
    return LocationRecord(
        location_id=row["location_id"],
        canonical_name=row["canonical_name"],
        municipality=row["municipality"],
        candidate_ids=tuple(item["candidate_id"] for item in candidate_ids),
        access_kind=row["access_kind"],
        membership_required=row["membership_required"],
        public_booking=row["public_booking"],
        racket_rental=row["racket_rental"],
        locker_rooms=row["locker_rooms"],
        booking_account_required=row["booking_account_required"],
        verification_status=row["verification_status"],
        court_groups=tuple(
            CourtGroup(item["label"], item["count"], item["format"], item["cover_status"])
            for item in groups
        ),
        aliases=tuple(item["alias"] for item in aliases),
        evidence=tuple(
            SourceEvidence(
                item["url"],
                item["source_type"],
                item["title"],
                item["checked_at"],
                item["fact_key"],
                item["relation"],
                item["evidence"],
                item["confidence"],
            )
            for item in evidence
        ),
        notes=row["notes"],
        brand=row["brand"],
        address=row["address"],
        latitude=row["latitude"],
        longitude=row["longitude"],
        overall_cover_status=row["overall_cover_status"],
        official_url=row["official_url"],
        booking_url=row["booking_url"],
        booking_platform=row["booking_platform"],
    )


def list_locations(connection: sqlite3.Connection) -> tuple[LocationRecord, ...]:
    rows = connection.execute(
        "SELECT * FROM locations ORDER BY municipality, canonical_name"
    ).fetchall()
    return tuple(_location_from_row(connection, row) for row in rows)


def _availability_run_from_row(row: sqlite3.Row) -> AvailabilityRun:
    return AvailabilityRun(
        row["run_id"],
        row["location_id"],
        row["connector"],
        row["source_url"],
        row["window_start"],
        row["window_end"],
        row["horizon_days"],
        row["collected_at"],
        row["status"],
        row["error"],
    )


def _availability_slot_from_row(row: sqlite3.Row) -> AvailabilitySlot:
    return AvailabilitySlot(
        row["run_id"],
        row["location_id"],
        row["slot_key"],
        row["external_id"],
        row["court_label"],
        row["starts_at"],
        row["ends_at"],
        row["timezone"],
        row["status"],
    )


def _save_availability_result(connection: sqlite3.Connection, result: AvailabilityResult) -> None:
    run = result.run
    connection.execute(
        """
        INSERT INTO availability_runs (
            run_id, location_id, connector, source_url, window_start, window_end,
            horizon_days, collected_at, status, error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run.run_id,
            run.location_id,
            run.connector,
            run.source_url,
            run.window_start,
            run.window_end,
            run.horizon_days,
            run.collected_at,
            run.status,
            run.error,
        ),
    )
    connection.executemany(
        """
        INSERT INTO availability_slots (
            run_id, location_id, slot_key, external_id, court_label,
            starts_at, ends_at, timezone, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                slot.run_id,
                slot.location_id,
                slot.slot_key,
                slot.external_id,
                slot.court_label,
                slot.starts_at,
                slot.ends_at,
                slot.timezone,
                slot.status,
            )
            for slot in result.slots
        ],
    )


def save_availability_result(
    connection: sqlite3.Connection,
    result: AvailabilityResult,
    *,
    commit: bool = True,
) -> None:
    if commit:
        with connection:
            _save_availability_result(connection, result)
        return

    connection.execute("SAVEPOINT save_availability_result")
    try:
        _save_availability_result(connection, result)
    except BaseException:
        connection.execute("ROLLBACK TO save_availability_result")
        connection.execute("RELEASE save_availability_result")
        raise
    connection.execute("RELEASE save_availability_result")


def list_availability_runs(
    connection: sqlite3.Connection, location_id: str | None = None
) -> tuple[AvailabilityRun, ...]:
    if location_id is None:
        rows = connection.execute(
            "SELECT * FROM availability_runs ORDER BY collected_at, run_id"
        ).fetchall()
    else:
        rows = connection.execute(
            "SELECT * FROM availability_runs WHERE location_id = ? ORDER BY collected_at, run_id",
            (location_id,),
        ).fetchall()
    return tuple(_availability_run_from_row(row) for row in rows)


def get_latest_successful_availability_run(
    connection: sqlite3.Connection, location_id: str
) -> AvailabilityRun | None:
    row = connection.execute(
        """
        SELECT * FROM availability_runs
        WHERE location_id = ? AND status = 'success'
        ORDER BY collected_at DESC, run_id DESC
        LIMIT 1
        """,
        (location_id,),
    ).fetchone()
    return _availability_run_from_row(row) if row is not None else None


def list_availability_slots(
    connection: sqlite3.Connection, run_id: str
) -> tuple[AvailabilitySlot, ...]:
    rows = connection.execute(
        "SELECT * FROM availability_slots WHERE run_id = ? ORDER BY slot_key",
        (run_id,),
    ).fetchall()
    return tuple(_availability_slot_from_row(row) for row in rows)


def get_availability_snapshot(
    connection: sqlite3.Connection, location_id: str
) -> AvailabilitySnapshot | None:
    latest_row = connection.execute(
        """
        SELECT * FROM availability_runs
        WHERE location_id = ?
        ORDER BY collected_at DESC, run_id DESC
        LIMIT 1
        """,
        (location_id,),
    ).fetchone()
    if latest_row is None:
        return None

    latest_run = _availability_run_from_row(latest_row)
    successful_row = connection.execute(
        """
        SELECT * FROM availability_runs
        WHERE location_id = ? AND status = 'success'
        ORDER BY collected_at DESC, run_id DESC
        LIMIT 1
        """,
        (location_id,),
    ).fetchone()
    successful_run = (
        _availability_run_from_row(successful_row) if successful_row is not None else None
    )
    if latest_run.status == "success":
        slots = list_availability_slots(connection, latest_run.run_id)
        status = "success"
    elif successful_run is not None:
        slots = list_availability_slots(connection, successful_run.run_id)
        status = "stale"
    else:
        slots = ()
        status = latest_run.status
    return AvailabilitySnapshot(
        location_id,
        latest_run,
        slots,
        status,
        successful_run.collected_at if successful_run is not None else None,
    )


def record_candidate_match(
    connection: sqlite3.Connection, match: CandidateMatch, *, commit: bool = True
) -> None:
    context = connection if commit else nullcontext()
    with context:
        connection.execute(
            """
            INSERT INTO candidate_matches (candidate_id, location_id, status, note)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(candidate_id) DO UPDATE SET
                location_id = excluded.location_id,
                status = excluded.status,
                note = excluded.note
            """,
            (match.candidate_id, match.location_id, match.status, match.note),
        )


def list_candidate_matches(connection: sqlite3.Connection) -> tuple[CandidateMatch, ...]:
    rows = connection.execute(
        "SELECT candidate_id, location_id, status, note FROM candidate_matches ORDER BY candidate_id"
    ).fetchall()
    return tuple(
        CandidateMatch(row["candidate_id"], row["location_id"], row["status"], row["note"])
        for row in rows
    )


def create_verification_run(
    connection: sqlite3.Connection, run: VerificationRun, *, commit: bool = True
) -> None:
    context = connection if commit else nullcontext()
    with context:
        connection.execute(
            """
            INSERT INTO verification_runs (
                run_id, started_at, ended_at, candidate_count, error_count, summary
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                started_at = excluded.started_at,
                ended_at = excluded.ended_at,
                candidate_count = excluded.candidate_count,
                error_count = excluded.error_count,
                summary = excluded.summary
            """,
            (
                run.run_id,
                run.started_at,
                run.ended_at,
                run.candidate_count,
                run.error_count,
                run.summary,
            ),
        )
