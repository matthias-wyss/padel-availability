from __future__ import annotations

import os
import sqlite3
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "deploy/ct103/bootstrap-catalog.sh"


def test_catalog_bootstrap_refuses_existing_database_without_modifying_it(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "catalog.sqlite3"
    original = b"preserve this existing file"
    database_path.write_bytes(original)

    result = subprocess.run(
        ["bash", str(SCRIPT), str(database_path)],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode != 0
    assert "Refusing to overwrite existing database" in result.stderr
    assert database_path.read_bytes() == original


def test_catalog_bootstrap_builds_new_catalog_and_refuses_second_run(tmp_path: Path) -> None:
    database_path = tmp_path / "catalog.sqlite3"
    environment = os.environ.copy()
    environment["PATH"] = f"{ROOT / '.venv' / 'bin'}:{environment.get('PATH', '')}"
    environment["PYTHONPATH"] = str(ROOT / "src")

    result = subprocess.run(
        ["bash", str(SCRIPT), str(database_path)],
        capture_output=True,
        check=False,
        env=environment,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    connection = sqlite3.connect(database_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM locations").fetchone()[0] == 29
        assert connection.execute("SELECT COUNT(*) FROM availability_runs").fetchone()[0] == 0
    finally:
        connection.close()

    original = database_path.read_bytes()
    second_run = subprocess.run(
        ["bash", str(SCRIPT), str(database_path)],
        capture_output=True,
        check=False,
        env=environment,
        text=True,
    )
    assert second_run.returncode != 0
    assert database_path.read_bytes() == original


def test_catalog_bootstrap_uses_container_cli_when_host_cli_is_missing(tmp_path: Path) -> None:
    binary_directory = tmp_path / "bin"
    binary_directory.mkdir()
    docker = binary_directory / "docker"
    docker.write_text(
        '#!/bin/sh\nprintf \'%s\\n\' "$*" >> "$DOCKER_LOG"\n',
        encoding="utf-8",
    )
    docker.chmod(0o755)
    log_path = tmp_path / "docker.log"
    environment = {"PATH": f"{binary_directory}:/usr/bin:/bin", "DOCKER_LOG": str(log_path)}

    result = subprocess.run(
        ["bash", str(SCRIPT), str(tmp_path / "data" / "catalog.sqlite3")],
        capture_output=True,
        check=False,
        env=environment,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    calls = log_path.read_text(encoding="utf-8").splitlines()
    assert len(calls) == 3
    assert all("padel-availability:local" in call for call in calls)
    assert "/data/catalog.sqlite3" in calls[0]
