"""Bounded invariant partitioning and exact GL_N(Z) orbit artifacts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, BinaryIO

from noether import Z
from noether.linalg import IntegralLineConfiguration, Matrix

from voronoi.enumerate.census_engine import (
    DEFAULT_MEMORY_LIMIT_BYTES,
    DEFAULT_TIMEOUT_SECONDS,
    ENGINE_NOETHER_CONTRACT,
    _decode_json_line,
    _run_engine_task,
)

ORBIT_KEY_TASK_SCHEMA = "voronoi/orbit-key-task@1"
ORBIT_KEY_REPORT_SCHEMA = "voronoi/orbit-key-report@1"
ORBIT_FINGERPRINT_SCHEMA = "voronoi/maximal-minor-incidence@1"
KEYED_ARTIFACT_SCHEMA = "voronoi/keyed-candidate-artifact@1"
KEYED_RECORD_SCHEMA = "voronoi/keyed-candidate-record@1"
KEYED_FOOTER_SCHEMA = "voronoi/keyed-candidate-footer@1"
ORBIT_REDUCTION_TASK_SCHEMA = "voronoi/orbit-reduction-task@1"
ORBIT_REDUCTION_REPORT_SCHEMA = "voronoi/orbit-reduction-report@1"
ORBIT_ARTIFACT_SCHEMA = "voronoi/orbit-artifact@1"
ORBIT_RECORD_SCHEMA = "voronoi/orbit-record@1"
ORBIT_FOOTER_SCHEMA = "voronoi/orbit-footer@1"

_CANDIDATE_FIELDS = {
    "candidate_id",
    "vectors",
    "occurrence_count",
    "first_event_index",
    "witness_left_incidence_id",
    "witness_right_incidence_id",
    "witness_representative",
}


def _sha256_identifier(vectors: object) -> str:
    body = json.dumps(vectors, ensure_ascii=True, separators=(",", ":")).encode()
    return f"sha256:{hashlib.sha256(body).hexdigest()}"


def _validate_new_absolute_path(path: Path, *, description: str) -> Path:
    resolved = path.expanduser().resolve()
    if resolved.exists():
        raise FileExistsError(f"{description} already exists: {resolved}")
    if not resolved.parent.is_dir():
        raise FileNotFoundError(
            f"{description} parent does not exist: {resolved.parent}"
        )
    return resolved


def _candidate_summary(pair_report: Mapping[str, Any]) -> Mapping[str, Any]:
    summary = pair_report.get("candidate_artifact")
    if not isinstance(summary, dict):
        raise TypeError("pair report omitted its candidate artifact summary")
    return summary


def build_orbit_key_task(
    candidate_path: Path,
    pair_report: Mapping[str, Any],
    keyed_path: Path,
    *,
    buffer_cap: int = 50_000,
) -> dict[str, object]:
    """Build a non-overwriting external invariant-partition task."""

    if not 1 <= buffer_cap <= 100_000:
        raise ValueError("orbit-key buffer cap must lie in 1..100000")
    candidate = candidate_path.expanduser().resolve()
    if not candidate.is_file():
        raise FileNotFoundError(candidate)
    destination = _validate_new_absolute_path(
        keyed_path, description="keyed candidate artifact"
    )
    summary = _candidate_summary(pair_report)
    return {
        "type": ORBIT_KEY_TASK_SCHEMA,
        "noether_contract": dict(ENGINE_NOETHER_CONTRACT),
        "candidate_artifact_path": str(candidate),
        "keyed_artifact_path": str(destination),
        "candidate_content_sha256": str(summary["content_sha256"]),
        "candidate_count": int(summary["distinct_candidate_count"]),
        "candidate_occurrence_count": int(summary["candidate_occurrence_count"]),
        "buffer_cap": buffer_cap,
    }


def run_orbit_key_task(
    task: Mapping[str, object],
    *,
    engine: Path | None = None,
    memory_limit_bytes: int = DEFAULT_MEMORY_LIMIT_BYTES,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Run and validate one bounded external invariant partition."""

    payload = _run_engine_task(
        task,
        engine=engine,
        memory_limit_bytes=memory_limit_bytes,
        timeout_seconds=timeout_seconds,
    )
    if payload.get("type") != ORBIT_KEY_REPORT_SCHEMA:
        raise RuntimeError("orbit-key engine returned an unsupported report")
    if payload.get("noether_contract") != dict(ENGINE_NOETHER_CONTRACT):
        raise RuntimeError("orbit-key report uses a different Noether contract")
    for key in (
        "candidate_content_sha256",
        "candidate_count",
        "candidate_occurrence_count",
        "keyed_artifact_path",
    ):
        if str(payload.get(key)) != str(task.get(key)):
            raise RuntimeError(f"orbit-key report disagrees with its task on {key}")
    if payload.get("fingerprint_schema") != ORBIT_FINGERPRINT_SCHEMA:
        raise RuntimeError("orbit-key report used an unsupported fingerprint")
    verify_keyed_artifact(Path(str(task["keyed_artifact_path"])), payload)
    return payload


def _validate_candidate(candidate: Mapping[str, Any], ambient_rank: int) -> None:
    if set(candidate) != _CANDIDATE_FIELDS:
        raise ValueError("orbit artifact contains malformed candidate provenance")
    vectors = candidate.get("vectors")
    if not isinstance(vectors, list):
        raise TypeError("orbit candidate omitted its vectors")
    configuration = IntegralLineConfiguration(ambient_rank, vectors)
    if [list(row) for row in configuration.vectors] != vectors:
        raise ValueError("orbit candidate vectors are not canonical")
    if candidate.get("candidate_id") != _sha256_identifier(vectors):
        raise ValueError("orbit candidate has the wrong identifier")
    if int(candidate.get("occurrence_count", 0)) <= 0:
        raise ValueError("orbit candidate has a nonpositive occurrence count")


def _keyed_candidate(record: Mapping[str, Any]) -> dict[str, Any]:
    return {key: record[key] for key in _CANDIDATE_FIELDS}


def verify_keyed_artifact(path: Path, key_report: Mapping[str, Any]) -> dict[str, Any]:
    """Verify keyed-artifact provenance, order, digest, and candidate coverage."""

    digest = hashlib.sha256()
    count = 0
    occurrences = 0
    groups = 0
    previous: tuple[str, list[list[int]]] | None = None
    previous_fingerprint: str | None = None
    with path.open("rb") as source:
        header_line = source.readline()
        header = _decode_json_line(header_line, description="keyed artifact header")
        expected_header = {
            "type": KEYED_ARTIFACT_SCHEMA,
            "noether_contract": dict(ENGINE_NOETHER_CONTRACT),
            "fingerprint_schema": ORBIT_FINGERPRINT_SCHEMA,
            "candidate_content_sha256": key_report["candidate_content_sha256"],
        }
        for key, value in expected_header.items():
            if header.get(key) != value:
                raise ValueError(f"keyed artifact header disagrees on {key}")
        ambient_rank = int(header["ambient_rank"])
        digest.update(header_line)
        footer: dict[str, Any] | None = None
        while line := source.readline():
            record = _decode_json_line(line, description="keyed artifact line")
            if record.get("type") == KEYED_FOOTER_SCHEMA:
                footer = record
                if source.read(1):
                    raise ValueError("keyed artifact has data after its footer")
                break
            if record.get("type") != KEYED_RECORD_SCHEMA:
                raise ValueError("keyed artifact contains an unsupported record")
            fingerprint = record.get("fingerprint_sha256")
            if (
                not isinstance(fingerprint, str)
                or len(fingerprint) != 64
                or any(character not in "0123456789abcdef" for character in fingerprint)
            ):
                raise ValueError("keyed artifact contains an invalid fingerprint")
            candidate = _keyed_candidate(record)
            _validate_candidate(candidate, ambient_rank)
            vectors = candidate["vectors"]
            current = (fingerprint, vectors)
            if previous is not None and previous >= current:
                raise ValueError("keyed artifact records are not strictly ordered")
            if fingerprint != previous_fingerprint:
                groups += 1
                previous_fingerprint = fingerprint
            previous = current
            count += 1
            occurrences += int(candidate["occurrence_count"])
            digest.update(line)
    if footer is None:
        raise ValueError("keyed artifact omitted its footer")
    expected = {
        "content_sha256": digest.hexdigest(),
        "candidate_count": count,
        "candidate_occurrence_count": occurrences,
        "fingerprint_group_count": groups,
    }
    for key, value in expected.items():
        if footer.get(key) != value:
            raise ValueError(f"keyed artifact footer disagrees on {key}")
    for key, value in expected.items():
        report_key = "keyed_content_sha256" if key == "content_sha256" else key
        if key_report.get(report_key) != value:
            raise ValueError(f"orbit-key report disagrees on {report_key}")
    return footer


def build_orbit_reduction_task(
    keyed_path: Path,
    key_report: Mapping[str, Any],
    orbit_path: Path,
    *,
    max_fingerprint_group_size: int = 10_000,
) -> dict[str, object]:
    """Build one exact, non-overwriting orbit-reduction task."""

    if max_fingerprint_group_size <= 0:
        raise ValueError("max_fingerprint_group_size must be positive")
    keyed = keyed_path.expanduser().resolve()
    if not keyed.is_file():
        raise FileNotFoundError(keyed)
    destination = _validate_new_absolute_path(orbit_path, description="orbit artifact")
    return {
        "type": ORBIT_REDUCTION_TASK_SCHEMA,
        "noether_contract": dict(ENGINE_NOETHER_CONTRACT),
        "keyed_artifact_path": str(keyed),
        "orbit_artifact_path": str(destination),
        "candidate_content_sha256": str(key_report["candidate_content_sha256"]),
        "keyed_content_sha256": str(key_report["keyed_content_sha256"]),
        "candidate_count": int(key_report["candidate_count"]),
        "candidate_occurrence_count": int(key_report["candidate_occurrence_count"]),
        "fingerprint_group_count": int(key_report["fingerprint_group_count"]),
        "max_fingerprint_group_size": max_fingerprint_group_size,
    }


def run_orbit_reduction_task(
    task: Mapping[str, object],
    key_report: Mapping[str, Any],
    *,
    engine: Path | None = None,
    memory_limit_bytes: int = DEFAULT_MEMORY_LIMIT_BYTES,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Run exact collision resolution and verify every returned witness."""

    payload = _run_engine_task(
        task,
        engine=engine,
        memory_limit_bytes=memory_limit_bytes,
        timeout_seconds=timeout_seconds,
    )
    if payload.get("type") != ORBIT_REDUCTION_REPORT_SCHEMA:
        raise RuntimeError("orbit reducer returned an unsupported report")
    if payload.get("noether_contract") != dict(ENGINE_NOETHER_CONTRACT):
        raise RuntimeError("orbit-reduction report uses a different Noether contract")
    for key in (
        "candidate_content_sha256",
        "keyed_content_sha256",
        "candidate_count",
        "candidate_occurrence_count",
        "fingerprint_group_count",
        "orbit_artifact_path",
    ):
        if str(payload.get(key)) != str(task.get(key)):
            raise RuntimeError(f"orbit-reduction report disagrees on {key}")
    verify_orbit_artifact(
        Path(str(task["orbit_artifact_path"])),
        Path(str(task["keyed_artifact_path"])),
        key_report,
        payload,
    )
    return payload


def _read_keyed_groups(source: BinaryIO) -> Iterator[tuple[str, list[dict[str, Any]]]]:
    next(source)
    fingerprint: str | None = None
    group: list[dict[str, Any]] = []
    for line in source:
        payload = _decode_json_line(line, description="keyed candidate line")
        if payload.get("type") == KEYED_FOOTER_SCHEMA:
            break
        current = str(payload["fingerprint_sha256"])
        if fingerprint is not None and current != fingerprint:
            yield fingerprint, group
            group = []
        fingerprint = current
        group.append(payload)
    if fingerprint is not None:
        yield fingerprint, group


def verify_orbit_artifact(
    path: Path,
    keyed_path: Path,
    key_report: Mapping[str, Any],
    reduction_report: Mapping[str, Any],
) -> dict[str, Any]:
    """Verify orbit coverage against keyed groups and every unimodular witness."""

    verify_keyed_artifact(keyed_path, key_report)
    digest = hashlib.sha256()
    candidate_count = 0
    occurrences = 0
    orbit_count = 0
    equivalence_count = 0
    previous_orbit: tuple[str, list[list[int]]] | None = None
    with keyed_path.open("rb") as keyed, path.open("rb") as source:
        header_line = source.readline()
        header = _decode_json_line(header_line, description="orbit artifact header")
        expected_header = {
            "type": ORBIT_ARTIFACT_SCHEMA,
            "noether_contract": dict(ENGINE_NOETHER_CONTRACT),
            "fingerprint_schema": ORBIT_FINGERPRINT_SCHEMA,
            "candidate_content_sha256": key_report["candidate_content_sha256"],
            "keyed_content_sha256": key_report["keyed_content_sha256"],
        }
        for key, value in expected_header.items():
            if header.get(key) != value:
                raise ValueError(f"orbit artifact header disagrees on {key}")
        ambient_rank = int(header["ambient_rank"])
        digest.update(header_line)
        line = source.readline()
        footer: dict[str, Any] | None = None
        for fingerprint, keyed_group in _read_keyed_groups(keyed):
            expected_candidates = {
                str(record["candidate_id"]): _keyed_candidate(record)
                for record in keyed_group
            }
            actual_candidates: dict[str, dict[str, Any]] = {}
            while line:
                payload = _decode_json_line(line, description="orbit artifact line")
                if payload.get("type") == ORBIT_FOOTER_SCHEMA:
                    footer = payload
                    break
                if payload.get("type") != ORBIT_RECORD_SCHEMA:
                    raise ValueError("orbit artifact contains an unsupported record")
                current_fingerprint = str(payload.get("fingerprint_sha256"))
                if current_fingerprint != fingerprint:
                    break
                representative = payload.get("representative")
                members = payload.get("equivalent_members")
                if not isinstance(representative, dict) or not isinstance(
                    members, list
                ):
                    raise TypeError(
                        "orbit record omitted its representative or members"
                    )
                _validate_candidate(representative, ambient_rank)
                current_orbit = (fingerprint, representative["vectors"])
                if previous_orbit is not None and previous_orbit >= current_orbit:
                    raise ValueError("orbit artifact records are not strictly ordered")
                previous_orbit = current_orbit
                representative_id = str(representative["candidate_id"])
                if representative_id in actual_candidates:
                    raise ValueError("candidate appears in more than one orbit")
                actual_candidates[representative_id] = representative
                target = IntegralLineConfiguration(
                    ambient_rank, representative["vectors"]
                )
                orbit_occurrences = int(representative["occurrence_count"])
                for member in members:
                    if not isinstance(member, dict) or set(member) != {
                        "candidate",
                        "transformation_to_representative",
                        "line_permutation",
                    }:
                        raise ValueError(
                            "orbit record contains a malformed equivalence"
                        )
                    candidate = member["candidate"]
                    if not isinstance(candidate, dict):
                        raise TypeError(
                            "orbit equivalence omitted candidate provenance"
                        )
                    _validate_candidate(candidate, ambient_rank)
                    candidate_id = str(candidate["candidate_id"])
                    if candidate_id in actual_candidates:
                        raise ValueError("candidate appears in more than one orbit")
                    transformation_rows = member["transformation_to_representative"]
                    if not isinstance(transformation_rows, list):
                        raise TypeError("orbit equivalence omitted its transformation")
                    transformation = Matrix.from_rows(
                        Z,
                        [[int(entry) for entry in row] for row in transformation_rows],
                    )
                    source_configuration = IntegralLineConfiguration(
                        ambient_rank, candidate["vectors"]
                    )
                    if source_configuration.transform(transformation) != target:
                        raise ValueError(
                            "orbit transformation does not reach its representative"
                        )
                    target_vectors = list(target.vectors)
                    line_images = [
                        target_vectors.index(
                            IntegralLineConfiguration(ambient_rank, [vector])
                            .transform(transformation)
                            .vectors[0]
                        )
                        for vector in source_configuration.vectors
                    ]
                    if line_images != member["line_permutation"]:
                        raise ValueError(
                            "orbit transformation has the wrong line permutation"
                        )
                    actual_candidates[candidate_id] = candidate
                    orbit_occurrences += int(candidate["occurrence_count"])
                    equivalence_count += 1
                if int(payload.get("member_count", -1)) != 1 + len(members):
                    raise ValueError("orbit record has the wrong member count")
                if (
                    int(payload.get("candidate_occurrence_count", -1))
                    != orbit_occurrences
                ):
                    raise ValueError("orbit record has the wrong occurrence count")
                candidate_count += 1 + len(members)
                occurrences += orbit_occurrences
                orbit_count += 1
                digest.update(line)
                line = source.readline()
            if actual_candidates != expected_candidates:
                raise ValueError(
                    "orbit records do not exactly cover their fingerprint group"
                )
        if footer is None and line:
            footer = _decode_json_line(line, description="orbit footer")
        if footer is None or footer.get("type") != ORBIT_FOOTER_SCHEMA:
            raise ValueError("orbit artifact omitted its footer")
        if source.read(1):
            raise ValueError("orbit artifact has data after its footer")
    expected_footer = {
        "content_sha256": digest.hexdigest(),
        "candidate_count": candidate_count,
        "candidate_occurrence_count": occurrences,
        "fingerprint_group_count": int(key_report["fingerprint_group_count"]),
        "orbit_count": orbit_count,
        "duplicate_candidate_count": candidate_count - orbit_count,
        "exact_equivalence_count": equivalence_count,
    }
    for key, value in expected_footer.items():
        if footer.get(key) != value:
            raise ValueError(f"orbit artifact footer disagrees on {key}")
    for key, value in expected_footer.items():
        report_key = "orbit_content_sha256" if key == "content_sha256" else key
        if reduction_report.get(report_key) != value:
            raise ValueError(f"orbit-reduction report disagrees on {report_key}")
    return footer


def iter_orbit_representatives(
    path: Path,
    keyed_path: Path,
    key_report: Mapping[str, Any],
    reduction_report: Mapping[str, Any],
) -> Iterator[dict[str, Any]]:
    """Verify an orbit artifact fully, then stream its representatives."""

    verify_orbit_artifact(path, keyed_path, key_report, reduction_report)
    yield from _iter_orbit_representative_records(path)


def _iter_orbit_representative_records(path: Path) -> Iterator[dict[str, Any]]:
    """Stream representatives after the caller has verified the full artifact."""

    with path.open("rb") as source:
        source.readline()
        for line in source:
            payload = _decode_json_line(line, description="orbit artifact line")
            if payload.get("type") == ORBIT_FOOTER_SCHEMA:
                return
            yield payload["representative"]


__all__ = [
    "KEYED_ARTIFACT_SCHEMA",
    "KEYED_FOOTER_SCHEMA",
    "KEYED_RECORD_SCHEMA",
    "ORBIT_ARTIFACT_SCHEMA",
    "ORBIT_FINGERPRINT_SCHEMA",
    "ORBIT_FOOTER_SCHEMA",
    "ORBIT_KEY_REPORT_SCHEMA",
    "ORBIT_KEY_TASK_SCHEMA",
    "ORBIT_RECORD_SCHEMA",
    "ORBIT_REDUCTION_REPORT_SCHEMA",
    "ORBIT_REDUCTION_TASK_SCHEMA",
    "build_orbit_key_task",
    "build_orbit_reduction_task",
    "iter_orbit_representatives",
    "run_orbit_key_task",
    "run_orbit_reduction_task",
    "verify_keyed_artifact",
    "verify_orbit_artifact",
]
