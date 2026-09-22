import json
from dataclasses import replace
from pathlib import Path
from time import sleep

import pytest

from padel_availability.cli import main
from padel_availability.database import connect, initialize, list_candidate_matches, list_locations
from padel_availability.inventory import build_catalog
from padel_availability.models import (
    CandidateEntry,
    CandidateMatch,
    LocationRecord,
    SourceEvidence,
    VerificationRun,
)
from padel_availability.report import render_json_report, render_markdown_report


def sample_locations() -> tuple[LocationRecord, ...]:
    return (
        LocationRecord(
            location_id="location-one",
            canonical_name="Example Padel",
            municipality="Geneva",
            candidate_ids=("one",),
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
                    url="https://example.test/booking",
                    source_type="official",
                    title="Example booking",
                    checked_at="2026-09-21T00:00:00Z",
                    fact_key="booking.url",
                    relation="supports",
                    evidence="The official page links to booking.",
                    confidence="probable",
                ),
            ),
            notes="",
        ),
    )


def sample_matches() -> tuple[CandidateMatch, ...]:
    return (CandidateMatch("one", "location-one", "matched", "Official match"),)


def sample_run() -> VerificationRun:
    return VerificationRun("run-1", "2026-09-21T08:00:00Z", "2026-09-21T08:01:00Z", 1, 0, "ok")


def test_markdown_report_has_stable_sections_and_unknown_values() -> None:
    report = render_markdown_report(sample_locations(), sample_matches(), sample_run())

    assert report.index("## Summary") < report.index("## Locations")
    assert "Unknown" in report
    assert "Inconnu" in report
    assert "https://example.test/booking" in report
    assert "[Example booking](<https://example.test/booking>)" in report
    assert render_markdown_report(sample_locations(), sample_matches(), sample_run()) == report


def test_markdown_report_renders_unknown_access_and_cover_as_french_labels() -> None:
    location = replace(sample_locations()[0], access_kind="unknown", overall_cover_status="unknown")

    report = render_markdown_report((location,), sample_matches(), sample_run())

    assert "- Accès: Inconnu" in report
    assert "- Couverture: Inconnu" in report


def test_markdown_report_lists_every_candidate_decision() -> None:
    matches = (
        CandidateMatch("one", "location-one", "matched", "Official match"),
        CandidateMatch("four", None, "unresolved", "Pending review."),
        CandidateMatch("three", None, "not_confirmed", "No current evidence."),
        CandidateMatch("two", "location-one", "duplicate", "Same venue."),
    )

    report = render_markdown_report(sample_locations(), matches, sample_run())

    assert "### Candidate decisions" in report
    assert "- Candidate four: unresolved -> none (Pending review.)" in report
    assert "- Candidate one: matched -> location-one (Official match)" in report
    assert r"- Candidate three: not\_confirmed -> none (No current evidence.)" in report
    assert "- Candidate two: duplicate -> location-one (Same venue.)" in report
    assert report.index("Candidate decisions") < report.index("## Missing or unknown facts")


def test_markdown_report_uses_required_section_order() -> None:
    report = render_markdown_report(sample_locations(), sample_matches(), sample_run())
    sections = (
        "## Summary",
        "## Locations",
        "## Locations to verify or closed",
        "## Duplicate and alias decisions",
        "## Missing or unknown facts",
        "## Source evidence and contradictions",
    )

    positions = [report.index(section) for section in sections]

    assert positions == sorted(positions)


def test_markdown_report_lists_aliases_contradictions_and_unresolved_candidates() -> None:
    evidence = sample_locations()[0].evidence
    location = replace(
        sample_locations()[0],
        aliases=("Example Geneva",),
        evidence=evidence
        + (
            SourceEvidence(
                url="https://example.test/directory",
                source_type="directory",
                title="Directory listing",
                checked_at="2026-09-21T00:00:00Z",
                fact_key="location.courts",
                relation="contradicts",
                evidence="The directory lists a different court count.",
                confidence="to_verify",
            ),
        ),
    )
    matches = (
        sample_matches()[0],
        CandidateMatch("two", None, "not_confirmed", "No current public evidence."),
    )

    report = render_markdown_report((location,), matches, sample_run())

    assert "## Duplicate and alias decisions" in report
    assert "Example Geneva" in report
    assert "## Source evidence and contradictions" in report
    assert "Warnings and contradictions" in report
    assert "different court count" in report
    assert "Unresolved candidates" in report
    assert "two" in report
    assert r"Example Padel \(Geneva\)" in report
    assert report.count(r"Example Padel \(Geneva\)") >= 2


def test_markdown_report_escapes_special_text_and_parenthesized_urls() -> None:
    evidence = SourceEvidence(
        url="https://example.test/path)",
        source_type="official",
        title="Club [Official] *",
        checked_at="2026-09-21T00:00:00Z",
        fact_key="location.note",
        relation="supports",
        evidence="Check [this](bad) *now*.",
        confidence="probable",
    )
    location = replace(
        sample_locations()[0],
        canonical_name="Club [One]",
        evidence=(evidence,),
    )

    report = render_markdown_report((location,), sample_matches(), sample_run())

    assert "### Club \\[One\\] \\(Geneva\\)" in report
    assert "[Club \\[Official\\] \\*](<https://example.test/path)>)" in report
    assert "Check \\[this\\]\\(bad\\) \\*now\\*." in report


def test_evidence_sorting_breaks_all_ties_deterministically() -> None:
    first = SourceEvidence(
        "https://example.test/source", "z-source", "Z title", "2026-09-21T00:00:00Z",
        "location.fact", "supports", "same evidence", "probable",
    )
    second = SourceEvidence(
        "https://example.test/source", "a-source", "A title", "2026-09-21T00:00:00Z",
        "location.fact", "supports", "same evidence", "confirmed",
    )
    location = replace(sample_locations()[0], evidence=(first, second))
    reverse = replace(sample_locations()[0], evidence=(second, first))

    assert render_markdown_report((location,), sample_matches(), sample_run()) == (
        render_markdown_report((reverse,), sample_matches(), sample_run())
    )
    assert render_json_report((location,), sample_matches(), sample_run()) == (
        render_json_report((reverse,), sample_matches(), sample_run())
    )


def test_json_report_keeps_machine_values_and_is_deterministic() -> None:
    location = replace(sample_locations()[0], public_booking="yes")

    first = render_json_report((location,), sample_matches(), sample_run())
    second = render_json_report((location,), sample_matches(), sample_run())
    payload = json.loads(first)

    assert first == second
    assert payload["locations"][0]["public_booking"] == "yes"
    assert payload["verification_run"]["run_id"] == "run-1"


def test_cli_builds_and_reports_from_persisted_database(tmp_path: Path) -> None:
    database = tmp_path / "catalog.sqlite3"
    output = tmp_path / "inventory.md"
    json_output = tmp_path / "inventory.json"
    root = Path(__file__).parents[1]

    assert main(["init-db", "--database", str(database)]) == 0
    assert main(
        [
            "import-candidates",
            "--database",
            str(database),
            "--input",
            str(root / "data/candidates.json"),
        ]
    ) == 0
    assert main(
        [
            "build-catalog",
            "--database",
            str(database),
            "--candidates",
            str(root / "data/candidates.json"),
            "--verified",
            str(root / "data/verified_locations.json"),
            "--run-id",
            "inventory-2026-09-21",
        ]
    ) == 0
    assert main(["report", "--database", str(database), "--output", str(output)]) == 0
    assert main(["report", "--database", str(database), "--output", str(json_output)]) == 0
    report = output.read_text(encoding="utf-8")
    json_report = json.loads(json_output.read_text(encoding="utf-8"))

    assert "inventory-2026-09-21" in report
    assert "29" in report
    assert "AIRPAD Les Acacias" in report
    assert json_report["verification_run"]["run_id"] == "inventory-2026-09-21"
    assert len(json_report["locations"]) == 29


def test_cli_rebuilds_identical_report_for_unchanged_inputs(tmp_path: Path) -> None:
    database = tmp_path / "catalog.sqlite3"
    output = tmp_path / "inventory.md"
    root = Path(__file__).parents[1]
    reports: list[bytes] = []

    for iteration in range(2):
        assert main(["init-db", "--database", str(database)]) == 0
        assert main(
            [
                "import-candidates",
                "--database",
                str(database),
                "--input",
                str(root / "data/candidates.json"),
            ]
        ) == 0
        assert main(
            [
                "build-catalog",
                "--database",
                str(database),
                "--candidates",
                str(root / "data/candidates.json"),
                "--verified",
                str(root / "data/verified_locations.json"),
                "--run-id",
                "inventory-2026-09-21",
            ]
        ) == 0
        assert main(["report", "--database", str(database), "--output", str(output)]) == 0
        reports.append(output.read_bytes())
        if iteration == 0:
            sleep(1.1)

    assert reports[0] == reports[1]


def test_rebuilding_catalog_removes_stale_locations_and_matches(tmp_path: Path) -> None:
    connection = connect(tmp_path / "catalog.sqlite3")
    initialize(connection)
    first_candidate = CandidateEntry("one", "One", "Geneva", None, None, None)
    second_candidate = CandidateEntry("two", "Two", "Geneva", None, None, None)
    first_location = sample_locations()[0]
    second_location = replace(
        first_location,
        location_id="location-two",
        canonical_name="Example Two",
        candidate_ids=("two",),
        evidence=tuple(
            replace(item, url="https://example.test/second") for item in first_location.evidence
        ),
    )
    try:
        build_catalog(
            connection,
            (first_candidate, second_candidate),
            (first_location, second_location),
            sample_run(),
        )
        build_catalog(
            connection,
            (first_candidate,),
            (first_location,),
            replace(sample_run(), run_id="run-2", candidate_count=1),
        )

        assert tuple(location.location_id for location in list_locations(connection)) == (
            "location-one",
        )
        assert list_candidate_matches(connection) == (
            CandidateMatch("one", "location-one", "matched", "Catalog match."),
        )
        assert connection.execute("SELECT COUNT(*) FROM candidate_entries").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM sources WHERE url = ?", ("https://example.test/second",)
        ).fetchone()[0] == 0
    finally:
        connection.close()


def test_cli_returns_two_for_validation_errors(tmp_path: Path) -> None:
    assert main(["init-db", "--database", str(tmp_path / "missing" / "catalog.sqlite3")]) == 0
    assert main(
        [
            "build-catalog",
            "--database",
            str(tmp_path / "catalog.sqlite3"),
            "--candidates",
            str(tmp_path / "missing.json"),
            "--verified",
            str(tmp_path / "verified.json"),
            "--run-id",
            "run-1",
        ]
    ) == 2


def test_cli_returns_two_for_missing_arguments(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["report", "--database", "catalog.sqlite3"]) == 2
    assert "required" in capsys.readouterr().err
