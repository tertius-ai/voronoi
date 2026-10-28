"""Bounded native replay of saved integral orbit evidence."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from voronoi.enumerate.catalog_match import canonical_sha256
from voronoi.enumerate.census_engine import (
    CANDIDATE_SUMMARY_SCHEMA,
    DEFAULT_MEMORY_LIMIT_BYTES,
    DEFAULT_TIMEOUT_SECONDS,
    ENGINE_NOETHER_CONTRACT,
    REPORT_SCHEMA,
    _run_engine_task,
)
from voronoi.enumerate.orbit_reduction import (
    ORBIT_FINGERPRINT_SCHEMA,
    ORBIT_KEY_REPORT_SCHEMA,
    ORBIT_REDUCTION_REPORT_SCHEMA,
    _candidate_summary,
)

ORBIT_AUDIT_TASK_SCHEMA = "voronoi/orbit-audit-task@1"
ORBIT_AUDIT_REPORT_SCHEMA = "voronoi/orbit-audit-report@1"


def build_orbit_audit_task(
    keyed_path: Path,
    orbit_path: Path,
    pair_report: Mapping[str, Any],
    key_report: Mapping[str, Any],
    orbit_report: Mapping[str, Any],
    *,
    max_fingerprint_group_size: int = 10_000,
) -> dict[str, Any]:
    """Bind a read-only audit to the complete relative input and output digests."""
    candidates = _candidate_summary(pair_report)
    if (
        pair_report.get("type") != REPORT_SCHEMA
        or pair_report.get("noether_contract") != dict(ENGINE_NOETHER_CONTRACT)
        or candidates.get("type") != CANDIDATE_SUMMARY_SCHEMA
    ):
        raise ValueError(
            "orbit audit requires a supported pair report and candidate summary"
        )
    if max_fingerprint_group_size <= 0:
        raise ValueError("fingerprint group cap must be positive")
    for report, schema in [
        (key_report, ORBIT_KEY_REPORT_SCHEMA),
        (orbit_report, ORBIT_REDUCTION_REPORT_SCHEMA),
    ]:
        if (
            report.get("type") != schema
            or report.get("noether_contract") != dict(ENGINE_NOETHER_CONTRACT)
            or report.get("fingerprint_schema") != ORBIT_FINGERPRINT_SCHEMA
            or report.get("candidate_content_sha256") != candidates["content_sha256"]
            or report.get("candidate_count") != candidates["distinct_candidate_count"]
            or report.get("candidate_occurrence_count")
            != candidates["candidate_occurrence_count"]
        ):
            raise ValueError(
                "orbit audit reports disagree on schema, provenance, or coverage"
            )
    if orbit_report.get("keyed_content_sha256") != key_report.get(
        "keyed_content_sha256"
    ):
        raise ValueError("orbit audit reports belong to different keyed inputs")
    if orbit_report.get("fingerprint_group_count") != key_report.get(
        "fingerprint_group_count"
    ):
        raise ValueError("orbit audit reports disagree on fingerprint groups")
    for path in [keyed_path, orbit_path]:
        if not path.is_file():
            raise FileNotFoundError(path)
    return {
        "type": ORBIT_AUDIT_TASK_SCHEMA,
        "noether_contract": dict(ENGINE_NOETHER_CONTRACT),
        "keyed_artifact_path": str(keyed_path.resolve()),
        "orbit_artifact_path": str(orbit_path.resolve()),
        "candidate_content_sha256": candidates["content_sha256"],
        "keyed_content_sha256": key_report["keyed_content_sha256"],
        "orbit_content_sha256": orbit_report["orbit_content_sha256"],
        "pair_input_sha256": pair_report["input_sha256"],
        "event_stream_sha256": pair_report["event_stream_sha256"],
        "lower_index": pair_report["lower_index"],
        "ambient_rank": pair_report["ambient_rank"],
        "cone_dimension": pair_report["target_dimension"],
        "candidate_count": key_report["candidate_count"],
        "candidate_occurrence_count": key_report["candidate_occurrence_count"],
        "fingerprint_group_count": key_report["fingerprint_group_count"],
        "orbit_count": orbit_report["orbit_count"],
        "exact_equivalence_count": orbit_report["exact_equivalence_count"],
        "max_fingerprint_group_size": max_fingerprint_group_size,
    }


def run_orbit_audit_task(
    task: Mapping[str, Any],
    *,
    engine: Path | None = None,
    memory_limit_bytes: int = DEFAULT_MEMORY_LIMIT_BYTES,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Replay all transports in one bounded native process; write no input files."""
    report = _run_engine_task(
        task,
        engine=engine,
        memory_limit_bytes=memory_limit_bytes,
        timeout_seconds=timeout_seconds,
    )
    if (
        report.get("type") != ORBIT_AUDIT_REPORT_SCHEMA
        or report.get("noether_contract") != dict(ENGINE_NOETHER_CONTRACT)
        or report.get("input_sha256") != canonical_sha256(task)
    ):
        raise ValueError(
            "orbit audit returned a different schema, contract, or task digest"
        )
    for field in [
        "keyed_content_sha256",
        "orbit_content_sha256",
        "candidate_count",
        "candidate_occurrence_count",
        "fingerprint_group_count",
        "orbit_count",
    ]:
        if report.get(field) != task[field]:
            raise ValueError(f"orbit audit report disagrees on {field}")
    if (
        report.get("exact_transports_replayed") != task["exact_equivalence_count"]
        or report.get("representative_fingerprints_recomputed") != task["orbit_count"]
        or task["candidate_count"]
        != task["orbit_count"] + task["exact_equivalence_count"]
    ):
        raise ValueError("orbit audit mathematical coverage is incomplete")
    return report
