"""Reject mixed Noether generations before starting census work."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import noether
import pytest

from voronoi import runtime
from voronoi.cli import main
from voronoi.runtime import (
    ENGINE_RUNTIME_SCHEMA,
    NOETHER_VERSION,
    census_engine_runtime,
    require_noether_version,
)


@pytest.mark.parametrize("version", ["0.1.0", "0.2.0", "0.3.1", "0.3.3"])
def test_unsupported_python_release_is_rejected(monkeypatch, version: str) -> None:
    monkeypatch.setattr(noether, "__version__", version)
    with pytest.raises(RuntimeError, match="Voronoi requires Noether 0.3.2"):
        require_noether_version()


def test_distribution_metadata_cannot_mask_an_older_extension(monkeypatch) -> None:
    monkeypatch.setattr(runtime, "_compiled_noether_version", lambda: "0.1.0")
    with pytest.raises(RuntimeError, match="Voronoi requires Noether 0.3.2"):
        require_noether_version()


def _worker(path: Path, version: str) -> Path:
    payload = {"type": ENGINE_RUNTIME_SCHEMA, "noether_version": version}
    path.write_text(f"#!{sys.executable}\nprint({json.dumps(payload)!r})\n")
    path.chmod(0o755)
    return path


def test_worker_release_is_checked_again_after_replacement(tmp_path: Path) -> None:
    worker = _worker(tmp_path / "worker", NOETHER_VERSION)
    assert census_engine_runtime(worker)["noether_version"] == NOETHER_VERSION
    _worker(worker, "0.1.0")
    with pytest.raises(RuntimeError, match="does not report Noether 0.3.2"):
        census_engine_runtime(worker)


def test_pre_version_worker_is_rejected(tmp_path: Path) -> None:
    worker = tmp_path / "worker"
    worker.write_text(f"#!{sys.executable}\nprint('legacy worker')\n")
    worker.chmod(0o755)
    with pytest.raises(RuntimeError, match="Cannot identify census worker"):
        census_engine_runtime(worker)


def test_doctor_reports_both_releases_and_checks_semantics(capsys) -> None:
    assert main(["doctor"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["noether_version"] == NOETHER_VERSION
    assert report["census_engine_runtime"]["noether_version"] == NOETHER_VERSION
    assert report["semantic_contract"] == "verified"


def test_controller_rejects_a_stale_worker_before_creating_a_workspace(
    tmp_path: Path,
) -> None:
    repository = Path(__file__).resolve().parents[1]
    worker = _worker(tmp_path / "old-worker", "0.1.0")
    workspace = tmp_path / "workspace"
    result = subprocess.run(
        [str(repository / "scripts/run-n8-r10-completion.sh"), "1"],
        env={
            **os.environ,
            "VORONOI_CENSUS_ENGINE": str(worker),
            "VORONOI_COMPLETION_WORKSPACE": str(workspace),
        },
        capture_output=True,
        check=False,
        text=True,
        timeout=20,
    )
    assert result.returncode != 0
    assert "does not report Noether 0.3.2" in result.stderr
    assert not workspace.exists()
