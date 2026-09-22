import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Sequence

from .collector import collect_playtomic
from .connectors.playtomic import load_playtomic_sources
from .database import (
    connect,
    get_availability_snapshot,
    initialize,
    list_candidate_matches,
    list_locations,
)
from .inventory import build_catalog, import_candidates, load_candidates, load_locations
from .models import VerificationRun
from .report import render_json_report, render_markdown_report


def _positive_days(value: str) -> int:
    days = int(value)
    if days <= 0:
        raise argparse.ArgumentTypeError("days must be positive")
    return days


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="padel-availability",
        description="Build and inspect the verified padel inventory.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    init_db = commands.add_parser("init-db", help="initialize a SQLite catalog")
    init_db.add_argument("--database", required=True, type=Path)

    import_command = commands.add_parser("import-candidates", help="import candidate entries")
    import_command.add_argument("--database", required=True, type=Path)
    import_command.add_argument("--input", required=True, type=Path)

    build_command = commands.add_parser("build-catalog", help="build the verified catalog")
    build_command.add_argument("--database", required=True, type=Path)
    build_command.add_argument("--candidates", required=True, type=Path)
    build_command.add_argument("--verified", required=True, type=Path)
    build_command.add_argument("--run-id", required=True)

    report_command = commands.add_parser("report", help="render a persisted catalog report")
    report_command.add_argument("--database", required=True, type=Path)
    report_command.add_argument("--output", required=True, type=Path)

    collect_command = commands.add_parser(
        "collect-playtomic", help="collect public Playtomic availability manually"
    )
    collect_command.add_argument("--database", required=True, type=Path)
    collect_command.add_argument(
        "--sources", type=Path, default=Path("data/playtomic_sources.json")
    )
    collect_command.add_argument("--location-id")
    collect_command.add_argument("--days", type=_positive_days, default=14)
    return parser


def _timestamp(verified_at: str) -> str:
    return f"{verified_at}T00:00:00Z"


def _run_command(arguments: argparse.Namespace) -> None:
    if arguments.command == "init-db":
        connection = connect(arguments.database)
        try:
            initialize(connection)
        finally:
            connection.close()
        return

    connection = connect(arguments.database)
    try:
        initialize(connection)
        if arguments.command == "import-candidates":
            import_candidates(connection, load_candidates(arguments.input))
            return
        if arguments.command == "build-catalog":
            candidates = load_candidates(arguments.candidates)
            locations = load_locations(arguments.verified)
            verified_at = json.loads(
                arguments.verified.read_text(encoding="utf-8")
            )["verified_at"]
            timestamp = _timestamp(verified_at)
            build_catalog(
                connection,
                candidates,
                locations,
                VerificationRun(arguments.run_id, timestamp, timestamp, len(candidates), 0, "ok"),
            )
            return
        if arguments.command == "report":
            row = connection.execute(
                "SELECT run_id, started_at, ended_at, candidate_count, error_count, summary "
                "FROM verification_runs ORDER BY ended_at DESC, run_id DESC LIMIT 1"
            ).fetchone()
            if row is None:
                raise ValueError("database contains no verification run")
            run = VerificationRun(
                run_id=row["run_id"],
                started_at=row["started_at"],
                ended_at=row["ended_at"],
                candidate_count=row["candidate_count"],
                error_count=row["error_count"],
                summary=row["summary"],
            )
            locations = list_locations(connection)
            matches = list_candidate_matches(connection)
            if arguments.output.suffix.lower() == ".json":
                report = render_json_report(locations, matches, run)
            else:
                report = render_markdown_report(locations, matches, run)
            arguments.output.parent.mkdir(parents=True, exist_ok=True)
            arguments.output.write_text(report, encoding="utf-8")
            return
        if arguments.command == "collect-playtomic":
            outcomes = collect_playtomic(
                connection,
                list_locations(connection),
                load_playtomic_sources(arguments.sources),
                horizon_days=arguments.days,
                location_id=arguments.location_id,
            )
            for outcome in outcomes:
                error = " ".join((outcome.error or "none").split())[:160]
                snapshot = get_availability_snapshot(connection, outcome.location_id)
                last_success = snapshot.last_success_at if snapshot is not None else None
                print(
                    f"{outcome.location_id} status={outcome.status} slots={outcome.slot_count} "
                    f"window={outcome.window_start}..{outcome.window_end} error={error} "
                    f"last_success={last_success or 'none'}"
                )
            return
        raise ValueError(f"unsupported command: {arguments.command}")
    finally:
        connection.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    try:
        arguments = parser.parse_args(argv)
    except SystemExit as error:
        return int(error.code)
    try:
        _run_command(arguments)
    except (OSError, ValueError, sqlite3.Error) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0
