"""The reference-data fetcher must preserve both provenance and local edits."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest


def _git(repository: Path, *arguments: str) -> str:
    return subprocess.check_output(
        [
            "git",
            "-c",
            "user.name=Test Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "-C",
            str(repository),
            *arguments,
        ],
        text=True,
        stderr=subprocess.PIPE,
    ).strip()


@pytest.fixture
def database_fixture(tmp_path: Path) -> tuple[Path, Path, str]:
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    _git(upstream, "init", "--quiet")
    (upstream / "DATA_pari").mkdir()
    (upstream / "LICENSE").write_text("Test fixture license\n")
    vectors = upstream / "DATA_pari/example"
    vectors.write_text("locked data\n")
    _git(upstream, "add", ".")
    _git(upstream, "commit", "--quiet", "-m", "locked reference")
    revision = _git(upstream, "rev-parse", "HEAD")
    vectors.write_text("new upstream data\n")
    _git(upstream, "commit", "--quiet", "-am", "later upstream data")

    project = tmp_path / "consumer"
    (project / "scripts").mkdir(parents=True)
    (project / "validation").mkdir()
    source = Path(__file__).resolve().parents[1] / "scripts/fetch_database.sh"
    shutil.copy2(source, project / "scripts/fetch_database.sh")
    lock = {
        "repository": upstream.as_uri(),
        "revision": revision,
        "license_file": "LICENSE",
        "files": {"example": hashlib.sha256(b"locked data\n").hexdigest()},
    }
    (project / "validation/reference-database.json").write_text(json.dumps(lock))
    return project, upstream, revision


def _fetch(project: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(project / "scripts/fetch_database.sh"), *arguments],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )


def test_fetch_pins_an_older_revision_and_is_repeatable(database_fixture) -> None:
    project, upstream, revision = database_fixture
    database = project / "data/elbazvip-Voronoi-complexes-database"
    result = _fetch(project)
    assert result.returncode == 0, result.stdout + result.stderr
    assert _git(database, "rev-parse", "HEAD") == revision
    assert (database / "DATA_pari/example").read_text() == "locked data\n"

    (upstream / "DATA_pari/example").write_text("another upstream change\n")
    _git(upstream, "commit", "--quiet", "-am", "advance upstream again")
    assert _fetch(project).returncode == 0
    assert _fetch(project, "--check").returncode == 0
    assert _git(database, "rev-parse", "HEAD") == revision


def test_fetch_preserves_local_changes(database_fixture) -> None:
    project, _, revision = database_fixture
    assert _fetch(project).returncode == 0
    database = project / "data/elbazvip-Voronoi-complexes-database"
    vectors = database / "DATA_pari/example"
    vectors.write_text("local research notes\n")
    result = _fetch(project)
    assert result.returncode != 0
    assert "local changes" in result.stderr
    assert vectors.read_text() == "local research notes\n"
    assert _git(database, "rev-parse", "HEAD") == revision


def test_check_verifies_hashes_when_git_does_not_report_a_change(
    database_fixture,
) -> None:
    project, _, _ = database_fixture
    assert _fetch(project).returncode == 0
    database = project / "data/elbazvip-Voronoi-complexes-database"
    _git(database, "update-index", "--assume-unchanged", "DATA_pari/example")
    (database / "DATA_pari/example").write_text("silently changed\n")
    assert _git(database, "status", "--porcelain") == ""
    result = _fetch(project, "--check")
    assert result.returncode != 0
    assert "does not match the lock" in result.stderr
