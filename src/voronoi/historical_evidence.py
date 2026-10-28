"""Historical proof-format inspection and the native Voronoi checking boundary."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from noether.linalg import (
    IntegralLineConfiguration,
    MinimumNonrealizabilityCertificate,
    MinimumRealization,
)

from voronoi.cells import VoronoiCell
from voronoi.enumerate.catalog_match import canonical_sha256
from voronoi.enumerate.census_engine import (
    ENGINE_NOETHER_CONTRACT,
    _candidate_identifier,
    _run_engine_task,
)

NEGATIVE_CHECK_TASK_SCHEMA = "voronoi/negative-check-task@1"
NEGATIVE_CHECK_REPORT_SCHEMA = "voronoi/negative-check-report@1"


def check_negative_certificates(
    payloads: list[Mapping[str, Any]],
    *,
    engine: Path | None = None,
    timeout_seconds: int = 1800,
) -> dict[str, Any]:
    """Check saved proof data in the native Voronoi worker using Noether algebra."""
    if not 1 <= len(payloads) <= 100:
        raise ValueError("negative check batch size must lie in 1..100")
    if any(payload.get("status") != "nonrealizable" for payload in payloads):
        raise ValueError("negative check received a nonnegative payload")
    task = {
        "type": NEGATIVE_CHECK_TASK_SCHEMA,
        "noether_contract": dict(ENGINE_NOETHER_CONTRACT),
        "proofs": [
            {
                key: payload[key]
                for key in (
                    "candidate_id",
                    "evidence_sha256",
                    "evidence_canonical_json",
                )
            }
            for payload in payloads
        ],
    }
    report = _run_engine_task(task, engine=engine, timeout_seconds=timeout_seconds)
    if (
        report.get("type") != NEGATIVE_CHECK_REPORT_SCHEMA
        or report.get("noether_contract") != dict(ENGINE_NOETHER_CONTRACT)
        or report.get("input_sha256") != canonical_sha256(task)
        or report.get("checked") != len(payloads)
        or len(report.get("proofs", [])) != len(payloads)
    ):
        raise ValueError("negative check report has wrong identity or coverage")
    for original, checked in zip(payloads, report["proofs"], strict=True):
        if (
            checked.get("candidate_id") != original["candidate_id"]
            or checked.get("evidence_sha256") != original["evidence_sha256"]
        ):
            raise ValueError("negative check changed the proof identity")
    return report


def _decode_bytes(value: object) -> object:
    if not isinstance(value, list) or any(
        type(x) is not int or not 0 <= x <= 255 for x in value
    ):
        raise ValueError("historical canonical value is not a byte array")
    return json.loads(bytes(value))


def inspect_negative_configuration(
    payload: Mapping[str, Any],
) -> tuple[VoronoiCell, str]:
    """Extract the bound source configuration and certificate-kind label.

    This checks structural provenance and its content identity. It does not
    verify a negative certificate. A separate Voronoi checker must reconstruct
    the project constraints and check the proof using public Noether exact
    operations; constructing an opaque Noether certificate is unnecessary.
    """
    canonical = payload.get("evidence_canonical_json")
    if payload.get("status") != "nonrealizable" or not isinstance(canonical, str):
        raise ValueError("historical payload is not an exact-shell negative")
    if hashlib.sha256(canonical.encode()).hexdigest() != payload.get("evidence_sha256"):
        raise ValueError("historical negative evidence digest disagrees")
    outer = json.loads(canonical)
    if (
        not isinstance(outer, list)
        or len(outer) != 3
        or outer[:2] != [MinimumRealization.type_id, "nonrealizable"]
    ):
        raise ValueError("unsupported historical realization value")
    certificate = _decode_bytes(outer[2])
    if (
        not isinstance(certificate, list)
        or len(certificate) != 5
        or certificate[0] != MinimumNonrealizabilityCertificate.type_id
        or not isinstance(certificate[2], str)
    ):
        raise ValueError("unsupported historical nonrealizability certificate")
    configuration = _decode_bytes(certificate[1])
    if (
        not isinstance(configuration, list)
        or len(configuration) != 3
        or configuration[0] != IntegralLineConfiguration.type_id
        or type(configuration[1]) is not int
    ):
        raise ValueError("unsupported historical line configuration")
    rows = [[int(x) for x in row] for row in configuration[2]]
    cell = VoronoiCell.from_rows(rows)
    if (
        cell.lattice_rank != configuration[1]
        or [list(v) for v in cell.min_vectors] != rows
        or _candidate_identifier(rows) != payload.get("candidate_id")
    ):
        raise ValueError("historical negative configuration identity disagrees")
    return cell, certificate[2]
