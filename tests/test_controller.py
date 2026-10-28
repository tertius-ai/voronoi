"""Exercise the production snapshot controller on a hand-checkable census."""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

from voronoi.cells import VoronoiCell
from voronoi.enumerate.census import build_coface_pair_task, build_incidence_shard
from voronoi.enumerate.census_engine import run_coface_pair_task
from voronoi.enumerate.orbit_reduction import (
    build_orbit_key_task,
    build_orbit_reduction_task,
    run_orbit_key_task,
    run_orbit_reduction_task,
)


@pytest.mark.slow
def test_controller_freezes_current_runtime_and_completes_small_census(
    tmp_path: Path,
) -> None:
    repository = Path(__file__).resolve().parents[1]
    axes = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    lower = [VoronoiCell.from_rows(axes)]
    upper = [
        VoronoiCell.from_rows([*axes, [1, 1, 0]]),
        VoronoiCell.from_rows([*axes, [1, 1, 1]]),
    ]
    incidence = build_incidence_shard(
        lower,
        upper,
        lower_catalog_claim="coordinate axes",
        upper_catalog_claim="two hand-checked cofaces",
    )
    pair_report = run_coface_pair_task(
        build_coface_pair_task(
            lower,
            upper,
            incidence,
            lower_index=0,
            candidate_artifact_path=tmp_path / "lower-000-candidates.jsonl",
        )
    )
    keyed_path = tmp_path / "lower-000-keyed.jsonl"
    key_report = run_orbit_key_task(
        build_orbit_key_task(
            tmp_path / "lower-000-candidates.jsonl", pair_report, keyed_path
        )
    )
    orbit_report = run_orbit_reduction_task(
        build_orbit_reduction_task(
            keyed_path, key_report, tmp_path / "lower-000-orbits.jsonl"
        ),
        key_report,
    )
    assert orbit_report["orbit_count"] > 0
    for name, payload in (
        ("lower-000-report.json", pair_report),
        ("lower-000-orbit-key-report.json", key_report),
        ("lower-000-orbit-report.json", orbit_report),
    ):
        (tmp_path / name).write_text(json.dumps(payload))

    workspace = tmp_path / "orbit-production-64-noether-0.3.2"
    run_directory = workspace / "logs/controller-test"
    runtime = run_directory / "runtime"
    try:
        result = subprocess.run(
            [str(repository / "scripts/run-n8-r10-completion.sh"), "2"],
            env={
                **os.environ,
                "VORONOI_ARTIFACT_ROOT": str(tmp_path),
                "VORONOI_COMPLETION_RUN_ID": "controller-test",
            },
            capture_output=True,
            check=False,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        status = (run_directory / "status").read_text()
        assert "state=complete\n" in status
        assert "failures=0\n" in status
        assert "noether_version=0.3.2\n" in status
        assert not (tmp_path / "orbit-production-64").exists()
        assert (runtime / "python/voronoi/runtime.py").is_file()
        libraries = runtime / "python/tertius_noether.libs"
        for name in ("libflint.so.24", "libgmp.so.10", "libmpfr.so.6"):
            assert (libraries / name).is_file()
        subprocess.run(
            ["sha256sum", "--check", "--quiet", str(run_directory / "runtime.sha256")],
            cwd=runtime,
            check=True,
        )
        reports = [
            json.loads(path.read_text().splitlines()[-1])
            for path in workspace.glob("completion-*.jsonl")
        ]
        assert len(reports) == 64
        assert (
            sum(report["record_count"] for report in reports)
            == orbit_report["orbit_count"]
        )
        assert sum(report["inconclusive"] for report in reports) == 0
    finally:
        # The controller deliberately freezes its snapshot; allow pytest's
        # temporary-directory cleanup to remove these test-owned copies.
        if runtime.exists():
            for path in [runtime, *runtime.rglob("*")]:
                path.chmod(path.stat().st_mode | stat.S_IWUSR)
