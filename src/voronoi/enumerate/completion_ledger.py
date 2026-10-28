"""Transactional completion shards for raw candidates or exact orbit representatives."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from voronoi.enumerate.census_engine import (
    COMPLETION_NOETHER_CONTRACT,
    DEFAULT_MEMORY_LIMIT_BYTES,
    DEFAULT_TIMEOUT_SECONDS,
    ENGINE_NOETHER_CONTRACT,
    CensusEngineTimeout,
    CompletionStrategy,
    _decode_json_line,
    _iter_candidate_artifact_records,
    build_completion_batch_task,
    run_completion_batch_task,
    verify_candidate_artifact,
)
from voronoi.enumerate.orbit_reduction import (
    ORBIT_ARTIFACT_SCHEMA,
    ORBIT_FINGERPRINT_SCHEMA,
    ORBIT_REDUCTION_REPORT_SCHEMA,
    _iter_orbit_representative_records,
    verify_orbit_artifact,
)

COMPLETION_SHARD_SCHEMA = "voronoi/completion-shard@2"
COMPLETION_RECORD_SCHEMA = "voronoi/completion-record@2"
COMPLETION_FOOTER_SCHEMA = "voronoi/completion-footer@2"
_LEGACY_COMPLETION_SHARD_SCHEMA = "voronoi/completion-shard@1"


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _metadata(
    pair_report: Mapping[str, Any],
    *,
    shard_index: int,
    shard_count: int,
    batch_size: int,
    strategy: CompletionStrategy,
) -> dict[str, str]:
    candidate_summary = pair_report.get("candidate_artifact")
    if not isinstance(candidate_summary, dict):
        raise TypeError("pair report omitted its candidate artifact")
    return {
        "type": COMPLETION_SHARD_SCHEMA,
        "candidate_content_sha256": str(candidate_summary["content_sha256"]),
        "candidate_count": str(candidate_summary["distinct_candidate_count"]),
        "pair_input_sha256": str(pair_report["input_sha256"]),
        "pair_event_stream_sha256": str(pair_report["event_stream_sha256"]),
        "candidate_noether_contract": _canonical_json(dict(ENGINE_NOETHER_CONTRACT)),
        "completion_noether_contract": _canonical_json(
            dict(COMPLETION_NOETHER_CONTRACT)
        ),
        "shard_index": str(shard_index),
        "shard_count": str(shard_count),
        "batch_size": str(batch_size),
        "work_limit_policy": "monotone-per-candidate",
        "strategy": strategy,
    }


def _orbit_metadata(
    pair_report: Mapping[str, Any],
    orbit_report: Mapping[str, Any],
    *,
    shard_index: int,
    shard_count: int,
    batch_size: int,
    strategy: CompletionStrategy,
) -> dict[str, str]:
    candidate_summary = pair_report.get("candidate_artifact")
    if not isinstance(candidate_summary, dict):
        raise TypeError("pair report omitted its candidate artifact")
    if orbit_report.get("type") != ORBIT_REDUCTION_REPORT_SCHEMA:
        raise ValueError("unsupported orbit-reduction report schema")
    if orbit_report.get("fingerprint_schema") != ORBIT_FINGERPRINT_SCHEMA:
        raise ValueError("orbit-reduction report uses an unsupported fingerprint")
    if orbit_report.get("noether_contract") != dict(ENGINE_NOETHER_CONTRACT):
        raise ValueError("orbit-reduction report uses a different Noether contract")
    if orbit_report.get("candidate_content_sha256") != candidate_summary.get(
        "content_sha256"
    ):
        raise ValueError("orbit-reduction report belongs to different candidates")
    if int(orbit_report["candidate_count"]) != int(
        candidate_summary["distinct_candidate_count"]
    ) or int(orbit_report["candidate_occurrence_count"]) != int(
        candidate_summary["candidate_occurrence_count"]
    ):
        raise ValueError("orbit-reduction coverage disagrees with the pair report")
    orbit_count = int(orbit_report["orbit_count"])
    if orbit_count <= 0 or orbit_count > int(orbit_report["candidate_count"]):
        raise ValueError("orbit-reduction report has an invalid orbit count")
    return {
        "type": COMPLETION_SHARD_SCHEMA,
        "completion_input_type": ORBIT_ARTIFACT_SCHEMA,
        "completion_input_sha256": str(orbit_report["orbit_content_sha256"]),
        "keyed_content_sha256": str(orbit_report["keyed_content_sha256"]),
        "fingerprint_schema": ORBIT_FINGERPRINT_SCHEMA,
        "candidate_content_sha256": str(candidate_summary["content_sha256"]),
        "candidate_count": str(orbit_count),
        "embedded_candidate_count": str(orbit_report["candidate_count"]),
        "pair_input_sha256": str(pair_report["input_sha256"]),
        "pair_event_stream_sha256": str(pair_report["event_stream_sha256"]),
        "candidate_noether_contract": _canonical_json(dict(ENGINE_NOETHER_CONTRACT)),
        "completion_noether_contract": _canonical_json(
            dict(COMPLETION_NOETHER_CONTRACT)
        ),
        "shard_index": str(shard_index),
        "shard_count": str(shard_count),
        "batch_size": str(batch_size),
        "work_limit_policy": "monotone-per-candidate",
        "strategy": strategy,
    }


def _verify_orbit_pair_provenance(
    orbit_path: Path, pair_report: Mapping[str, Any]
) -> None:
    candidate_summary = pair_report.get("candidate_artifact")
    if not isinstance(candidate_summary, dict):
        raise TypeError("pair report omitted its candidate artifact")
    with orbit_path.open("rb") as source:
        header = _decode_json_line(
            source.readline(), description="orbit completion source header"
        )
    expected = {
        "type": ORBIT_ARTIFACT_SCHEMA,
        "candidate_content_sha256": candidate_summary["content_sha256"],
        "lower_index": pair_report["lower_index"],
        "ambient_rank": pair_report["ambient_rank"],
        "target_dimension": pair_report["target_dimension"],
        "input_sha256": pair_report["input_sha256"],
        "event_stream_sha256": pair_report["event_stream_sha256"],
    }
    for key, value in expected.items():
        if header.get(key) != value:
            raise ValueError(
                f"orbit completion source disagrees with pair report on {key}"
            )


def _open_workspace(path: Path, metadata: Mapping[str, str]) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=30)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute(
        "CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS results (
            candidate_index INTEGER PRIMARY KEY,
            batch_index INTEGER NOT NULL,
            candidate_id TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL,
            max_iterations INTEGER NOT NULL,
            payload_json TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS attempts (
            candidate_index INTEGER PRIMARY KEY,
            batch_index INTEGER NOT NULL,
            candidate_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            detail TEXT NOT NULL,
            attempt_count INTEGER NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS checkpoints (
            candidate_index INTEGER NOT NULL,
            batch_index INTEGER NOT NULL,
            candidate_id TEXT NOT NULL,
            max_iterations INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            PRIMARY KEY(candidate_index, max_iterations)
        )
        """
    )
    actual = dict(connection.execute("SELECT key, value FROM metadata"))
    if not actual:
        with connection:
            connection.executemany(
                "INSERT INTO metadata(key, value) VALUES (?, ?)", metadata.items()
            )
    elif actual.get("type") == _LEGACY_COMPLETION_SHARD_SCHEMA:
        legacy_limit = int(actual.get("max_iterations", "-1"))
        legacy_identity = {
            key: value
            for key, value in actual.items()
            if key not in {"type", "max_iterations"}
        }
        current_identity = {
            key: value
            for key, value in metadata.items()
            if key not in {"type", "work_limit_policy"}
        }
        if legacy_limit < 0 or legacy_identity != current_identity:
            connection.close()
            raise ValueError(
                "completion workspace belongs to different inputs or shard settings"
            )
        columns = {row[1] for row in connection.execute("PRAGMA table_info(results)")}
        with connection:
            if "max_iterations" not in columns:
                connection.execute(
                    "ALTER TABLE results ADD COLUMN max_iterations "
                    f"INTEGER NOT NULL DEFAULT {legacy_limit}"
                )
            connection.execute(
                """
                INSERT OR IGNORE INTO checkpoints(
                    candidate_index, batch_index, candidate_id,
                    max_iterations, payload_json
                )
                SELECT candidate_index, batch_index, candidate_id,
                       max_iterations, payload_json
                FROM results WHERE status = 'inconclusive'
                """
            )
            connection.execute("DELETE FROM metadata")
            connection.executemany(
                "INSERT INTO metadata(key, value) VALUES (?, ?)", metadata.items()
            )
    elif actual != dict(metadata):
        connection.close()
        raise ValueError(
            "completion workspace belongs to different inputs or shard settings"
        )
    return connection


def _record_batches(
    records: Iterator[dict[str, Any]], batch_size: int
) -> Iterator[tuple[int, list[tuple[int, dict[str, Any]]]]]:
    batch: list[tuple[int, dict[str, Any]]] = []
    batch_index = 0
    for candidate_index, record in enumerate(records):
        batch.append((candidate_index, record))
        if len(batch) == batch_size:
            yield batch_index, batch
            batch_index += 1
            batch = []
    if batch:
        yield batch_index, batch


def _batch_state(
    connection: sqlite3.Connection,
    batch: list[tuple[int, dict[str, Any]]],
    *,
    max_iterations: int,
    retry_timeouts: bool,
    retry_unresolved_only: bool,
) -> tuple[list[tuple[int, dict[str, Any]]], int]:
    indices = [candidate_index for candidate_index, _ in batch]
    placeholders = ",".join("?" for _ in indices)
    result_rows = {
        candidate_index: (candidate_id, status, result_limit)
        for candidate_index, candidate_id, status, result_limit in connection.execute(
            f"SELECT candidate_index, candidate_id, status, max_iterations "
            f"FROM results WHERE candidate_index IN ({placeholders})",
            indices,
        )
    }
    attempt_rows = dict(
        connection.execute(
            f"SELECT candidate_index, candidate_id FROM attempts "
            f"WHERE candidate_index IN ({placeholders})",
            indices,
        )
    )
    missing: list[tuple[int, dict[str, Any]]] = []
    unresolved = 0
    for candidate_index, candidate in batch:
        candidate_id = str(candidate["candidate_id"])
        if candidate_index in result_rows:
            result_id, status, result_limit = result_rows[candidate_index]
            if result_id != candidate_id:
                raise ValueError("completion workspace changed a candidate identity")
            if status != "inconclusive" or int(result_limit) >= max_iterations:
                continue
            missing.append((candidate_index, candidate))
            continue
        if candidate_index in attempt_rows:
            if attempt_rows[candidate_index] != candidate_id:
                raise ValueError("completion attempt changed a candidate identity")
            if not retry_timeouts:
                unresolved += 1
                continue
            missing.append((candidate_index, candidate))
            continue
        if not retry_unresolved_only:
            missing.append((candidate_index, candidate))
    return missing, unresolved


def _store_timeout(
    connection: sqlite3.Connection,
    batch_index: int,
    indexed_candidate: tuple[int, dict[str, Any]],
    error: CensusEngineTimeout,
) -> None:
    candidate_index, candidate = indexed_candidate
    with connection:
        connection.execute(
            """
            INSERT INTO attempts(
                candidate_index, batch_index, candidate_id, kind, detail, attempt_count
            ) VALUES (?, ?, ?, 'timeout', ?, 1)
            ON CONFLICT(candidate_index) DO UPDATE SET
                detail = excluded.detail,
                attempt_count = attempts.attempt_count + 1
            """,
            (candidate_index, batch_index, str(candidate["candidate_id"]), str(error)),
        )


def _store_batch(
    connection: sqlite3.Connection,
    batch_index: int,
    indexed_candidates: list[tuple[int, dict[str, Any]]],
    report: Mapping[str, Any],
) -> None:
    results = report["results"]
    max_iterations = int(report["max_iterations"])
    rows = []
    checkpoints = []
    for (candidate_index, candidate), result in zip(
        indexed_candidates, results, strict=True
    ):
        if result["candidate_id"] != candidate["candidate_id"]:
            raise ValueError("completion result changed candidate identity")
        rows.append(
            (
                candidate_index,
                batch_index,
                str(result["candidate_id"]),
                str(result["status"]),
                max_iterations,
                _canonical_json(result),
            )
        )
        if result["status"] == "inconclusive":
            checkpoints.append(
                (
                    candidate_index,
                    batch_index,
                    str(result["candidate_id"]),
                    max_iterations,
                    _canonical_json(result),
                )
            )
    with connection:
        connection.executemany(
            """
            INSERT INTO results(
                candidate_index, batch_index, candidate_id, status,
                max_iterations, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(candidate_index) DO UPDATE SET
                batch_index = excluded.batch_index,
                candidate_id = excluded.candidate_id,
                status = excluded.status,
                max_iterations = excluded.max_iterations,
                payload_json = excluded.payload_json
            WHERE results.status = 'inconclusive'
              AND excluded.max_iterations > results.max_iterations
            """,
            rows,
        )
        connection.executemany(
            """
            INSERT OR IGNORE INTO checkpoints(
                candidate_index, batch_index, candidate_id,
                max_iterations, payload_json
            ) VALUES (?, ?, ?, ?, ?)
            """,
            checkpoints,
        )


def _write_hashed_line(output: Any, digest: Any, payload: object) -> None:
    line = (_canonical_json(payload) + "\n").encode()
    output.write(line)
    digest.update(line)


def _expected_shard_record_count(metadata: Mapping[str, str]) -> int:
    candidate_count = int(metadata["candidate_count"])
    batch_size = int(metadata["batch_size"])
    shard_index = int(metadata["shard_index"])
    shard_count = int(metadata["shard_count"])
    batch_count = (candidate_count + batch_size - 1) // batch_size
    return sum(
        min(batch_size, candidate_count - batch_index * batch_size)
        for batch_index in range(shard_index, batch_count, shard_count)
    )


def _publish_shard(
    connection: sqlite3.Connection,
    output_path: Path,
    metadata: Mapping[str, str],
) -> dict[str, Any]:
    if output_path.exists():
        return _verify_completion_shard(output_path, metadata)
    temporary = output_path.with_name(f".{output_path.name}.partial-{os.getpid()}")
    digest = hashlib.sha256()
    status_counts = {"completed": 0, "nonrealizable": 0, "inconclusive": 0}
    record_count = 0
    try:
        with temporary.open("xb") as output:
            header = {
                "type": COMPLETION_SHARD_SCHEMA,
                **metadata,
            }
            _write_hashed_line(output, digest, header)
            previous_index = -1
            for (
                candidate_index,
                batch_index,
                max_iterations,
                payload_json,
            ) in connection.execute(
                "SELECT candidate_index, batch_index, max_iterations, payload_json "
                "FROM results ORDER BY candidate_index"
            ):
                if candidate_index <= previous_index:
                    raise ValueError("completion workspace is not strictly ordered")
                result = json.loads(payload_json)
                status = result["status"]
                status_counts[status] += 1
                record = {
                    "type": COMPLETION_RECORD_SCHEMA,
                    "candidate_index": candidate_index,
                    "batch_index": batch_index,
                    "max_iterations": max_iterations,
                    **result,
                }
                _write_hashed_line(output, digest, record)
                record_count += 1
                previous_index = candidate_index
            content_sha256 = digest.hexdigest()
            footer = {
                "type": COMPLETION_FOOTER_SCHEMA,
                "content_sha256": content_sha256,
                "record_count": record_count,
                **status_counts,
            }
            output.write((_canonical_json(footer) + "\n").encode())
            output.flush()
            os.fsync(output.fileno())
        os.link(temporary, output_path)
    finally:
        temporary.unlink(missing_ok=True)
    return footer


def _verify_completion_shard(
    path: Path, expected_metadata: Mapping[str, str]
) -> dict[str, Any]:
    """Verify a terminal completion shard and every canonical evidence digest."""

    digest = hashlib.sha256()
    record_count = 0
    status_counts = {"completed": 0, "nonrealizable": 0, "inconclusive": 0}
    previous_index = -1
    with path.open("rb") as shard:
        header_line = shard.readline()
        if not header_line:
            raise ValueError("completion shard is empty")
        header = _decode_json_line(header_line, description="completion shard header")
        if header.get("type") != COMPLETION_SHARD_SCHEMA:
            raise ValueError("unsupported completion shard schema")
        for key, value in expected_metadata.items():
            if header.get(key) != value:
                raise ValueError(f"completion shard header disagrees on {key}")
        digest.update(header_line)
        footer: dict[str, Any] | None = None
        while line := shard.readline():
            payload = _decode_json_line(line, description="completion shard line")
            if payload.get("type") == COMPLETION_FOOTER_SCHEMA:
                footer = payload
                if shard.read(1):
                    raise ValueError("completion shard has data after its footer")
                break
            if payload.get("type") != COMPLETION_RECORD_SCHEMA:
                raise ValueError("completion shard contains an unsupported record")
            digest.update(line)
            candidate_index = int(payload["candidate_index"])
            batch_index = int(payload["batch_index"])
            if candidate_index <= previous_index:
                raise ValueError("completion shard records are not strictly ordered")
            if not 0 <= candidate_index < int(expected_metadata["candidate_count"]):
                raise ValueError(
                    "completion shard candidate index is outside the artifact"
                )
            if batch_index != candidate_index // int(expected_metadata["batch_size"]):
                raise ValueError("completion shard record has the wrong batch index")
            if batch_index % int(expected_metadata["shard_count"]) != int(
                expected_metadata["shard_index"]
            ):
                raise ValueError("completion shard record belongs to another shard")
            max_iterations = payload.get("max_iterations")
            if not isinstance(max_iterations, int) or max_iterations < 0:
                raise ValueError("completion shard record has an invalid work limit")
            status = payload.get("status")
            if status not in status_counts:
                raise ValueError("completion shard contains an unknown status")
            canonical = payload.get("evidence_canonical_json")
            if not isinstance(canonical, str):
                raise TypeError("completion shard omitted canonical Noether evidence")
            if hashlib.sha256(canonical.encode()).hexdigest() != payload.get(
                "evidence_sha256"
            ):
                raise ValueError("completion shard evidence digest does not verify")
            status_counts[status] += 1
            record_count += 1
            previous_index = candidate_index
    if footer is None:
        raise ValueError("completion shard omitted its footer")
    expected_footer = {
        "content_sha256": digest.hexdigest(),
        "record_count": record_count,
        **status_counts,
    }
    if record_count != _expected_shard_record_count(expected_metadata):
        raise ValueError("completion shard does not cover every assigned candidate")
    for key, value in expected_footer.items():
        if footer.get(key) != value:
            raise ValueError(f"completion shard footer disagrees on {key}")
    return footer


def verify_completion_shard(
    path: Path,
    pair_report: Mapping[str, Any],
    *,
    shard_index: int = 0,
    shard_count: int = 1,
    batch_size: int = 1,
    strategy: CompletionStrategy = "fixed_rank",
) -> dict[str, Any]:
    """Verify a terminal shard against its candidate artifact identity and settings."""

    metadata = _metadata(
        pair_report,
        shard_index=shard_index,
        shard_count=shard_count,
        batch_size=batch_size,
        strategy=strategy,
    )
    return _verify_completion_shard(path, metadata)


def _run_completion_records(
    records: Iterator[dict[str, Any]],
    metadata: Mapping[str, str],
    *,
    workspace_path: Path,
    output_path: Path,
    shard_index: int = 0,
    shard_count: int = 1,
    batch_size: int = 1,
    max_iterations: int = 50,
    strategy: CompletionStrategy = "fixed_rank",
    max_new_batches: int | None = None,
    engine: Path | None = None,
    memory_limit_bytes: int = DEFAULT_MEMORY_LIMIT_BYTES,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    retry_timeouts: bool = False,
    retry_unresolved_only: bool = False,
) -> dict[str, Any]:
    """Resume a digest-bound record stream and publish it only when terminal."""

    if shard_count < 1 or not 0 <= shard_index < shard_count:
        raise ValueError("shard_index must lie in range(shard_count)")
    if batch_size != 1:
        raise ValueError(
            "transactional completion currently requires batch_size=1 so one hard "
            "candidate cannot strand neighboring results"
        )
    if max_iterations < 0:
        raise ValueError("max_iterations cannot be negative")
    if max_new_batches is not None and max_new_batches < 0:
        raise ValueError("max_new_batches cannot be negative")
    if output_path.exists():
        footer = _verify_completion_shard(output_path, metadata)
        return {"complete": True, "footer": footer, "new_batches": 0}

    connection = _open_workspace(workspace_path, metadata)
    new_batches = 0
    assigned_batches = 0
    try:
        for batch_index, indexed_candidates in _record_batches(records, batch_size):
            if batch_index % shard_count != shard_index:
                continue
            assigned_batches += 1
            missing_candidates, _ = _batch_state(
                connection,
                indexed_candidates,
                max_iterations=max_iterations,
                retry_timeouts=retry_timeouts,
                retry_unresolved_only=retry_unresolved_only,
            )
            if not missing_candidates:
                continue
            if max_new_batches is not None and new_batches == max_new_batches:
                return {
                    "complete": False,
                    "new_batches": new_batches,
                    "assigned_batches_seen": assigned_batches,
                    "stored_results": connection.execute(
                        "SELECT COUNT(*) FROM results"
                    ).fetchone()[0],
                }
            task = build_completion_batch_task(
                [candidate for _, candidate in missing_candidates],
                max_iterations=max_iterations,
                strategy=strategy,
            )
            try:
                report = run_completion_batch_task(
                    task,
                    engine=engine,
                    memory_limit_bytes=memory_limit_bytes,
                    timeout_seconds=timeout_seconds,
                )
            except CensusEngineTimeout as error:
                _store_timeout(
                    connection,
                    batch_index,
                    missing_candidates[0],
                    error,
                )
                new_batches += 1
                print(
                    f"completion shard {shard_index}/{shard_count}: "
                    f"candidate={missing_candidates[0][0]} timeout",
                    flush=True,
                )
                continue
            _store_batch(connection, batch_index, missing_candidates, report)
            new_batches += 1
            print(
                f"completion shard {shard_index}/{shard_count}: "
                f"batch={batch_index} stored={len(missing_candidates)}",
                flush=True,
            )
        unresolved = connection.execute(
            """
            SELECT COUNT(*) FROM attempts
            LEFT JOIN results USING(candidate_index)
            WHERE results.candidate_index IS NULL
            """
        ).fetchone()[0]
        if unresolved:
            return {
                "complete": False,
                "new_batches": new_batches,
                "assigned_batches": assigned_batches,
                "unresolved_timeouts": unresolved,
                "stored_results": connection.execute(
                    "SELECT COUNT(*) FROM results"
                ).fetchone()[0],
            }
        inconclusive_results = connection.execute(
            "SELECT COUNT(*) FROM results WHERE status = 'inconclusive'"
        ).fetchone()[0]
        if retry_unresolved_only:
            return {
                "complete": False,
                "retry_unresolved_only": True,
                "new_batches": new_batches,
                "assigned_batches": assigned_batches,
                "unresolved_timeouts": unresolved,
                "inconclusive_results": inconclusive_results,
                "stored_results": connection.execute(
                    "SELECT COUNT(*) FROM results"
                ).fetchone()[0],
            }
        if inconclusive_results:
            return {
                "complete": False,
                "new_batches": new_batches,
                "assigned_batches": assigned_batches,
                "inconclusive_results": inconclusive_results,
                "stored_results": connection.execute(
                    "SELECT COUNT(*) FROM results"
                ).fetchone()[0],
            }
        footer = _publish_shard(connection, output_path, metadata)
        return {
            "complete": True,
            "footer": footer,
            "new_batches": new_batches,
            "assigned_batches": assigned_batches,
        }
    finally:
        connection.close()


def run_completion_shard(
    candidate_path: Path,
    pair_report: Mapping[str, Any],
    *,
    workspace_path: Path,
    output_path: Path,
    shard_index: int = 0,
    shard_count: int = 1,
    batch_size: int = 1,
    max_iterations: int = 50,
    strategy: CompletionStrategy = "fixed_rank",
    max_new_batches: int | None = None,
    engine: Path | None = None,
    memory_limit_bytes: int = DEFAULT_MEMORY_LIMIT_BYTES,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    retry_timeouts: bool = False,
    retry_unresolved_only: bool = False,
) -> dict[str, Any]:
    """Resume completion over every embedded candidate in a pair artifact."""

    verify_candidate_artifact(candidate_path, pair_report)
    metadata = _metadata(
        pair_report,
        shard_index=shard_index,
        shard_count=shard_count,
        batch_size=batch_size,
        strategy=strategy,
    )
    return _run_completion_records(
        _iter_candidate_artifact_records(candidate_path),
        metadata,
        workspace_path=workspace_path,
        output_path=output_path,
        shard_index=shard_index,
        shard_count=shard_count,
        batch_size=batch_size,
        max_iterations=max_iterations,
        strategy=strategy,
        max_new_batches=max_new_batches,
        engine=engine,
        memory_limit_bytes=memory_limit_bytes,
        timeout_seconds=timeout_seconds,
        retry_timeouts=retry_timeouts,
        retry_unresolved_only=retry_unresolved_only,
    )


def verify_orbit_completion_shard(
    path: Path,
    orbit_path: Path,
    keyed_path: Path,
    pair_report: Mapping[str, Any],
    key_report: Mapping[str, Any],
    orbit_report: Mapping[str, Any],
    *,
    shard_index: int = 0,
    shard_count: int = 1,
    batch_size: int = 1,
    strategy: CompletionStrategy = "fixed_rank",
) -> dict[str, Any]:
    """Verify an orbit-based shard against its exact representative source."""

    _verify_orbit_pair_provenance(orbit_path, pair_report)
    verify_orbit_artifact(
        orbit_path,
        keyed_path,
        key_report,
        orbit_report,
    )
    metadata = _orbit_metadata(
        pair_report,
        orbit_report,
        shard_index=shard_index,
        shard_count=shard_count,
        batch_size=batch_size,
        strategy=strategy,
    )
    return _verify_completion_shard(path, metadata)


def run_orbit_completion_shard(
    orbit_path: Path,
    keyed_path: Path,
    pair_report: Mapping[str, Any],
    key_report: Mapping[str, Any],
    orbit_report: Mapping[str, Any],
    *,
    workspace_path: Path,
    output_path: Path,
    shard_index: int = 0,
    shard_count: int = 1,
    batch_size: int = 1,
    max_iterations: int = 50,
    strategy: CompletionStrategy = "fixed_rank",
    max_new_batches: int | None = None,
    engine: Path | None = None,
    memory_limit_bytes: int = DEFAULT_MEMORY_LIMIT_BYTES,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    retry_timeouts: bool = False,
    retry_unresolved_only: bool = False,
) -> dict[str, Any]:
    """Resume completion over verified exact orbit representatives only."""

    _verify_orbit_pair_provenance(orbit_path, pair_report)
    verify_orbit_artifact(
        orbit_path,
        keyed_path,
        key_report,
        orbit_report,
    )
    metadata = _orbit_metadata(
        pair_report,
        orbit_report,
        shard_index=shard_index,
        shard_count=shard_count,
        batch_size=batch_size,
        strategy=strategy,
    )
    return _run_completion_records(
        _iter_orbit_representative_records(orbit_path),
        metadata,
        workspace_path=workspace_path,
        output_path=output_path,
        shard_index=shard_index,
        shard_count=shard_count,
        batch_size=batch_size,
        max_iterations=max_iterations,
        strategy=strategy,
        max_new_batches=max_new_batches,
        engine=engine,
        memory_limit_bytes=memory_limit_bytes,
        timeout_seconds=timeout_seconds,
        retry_timeouts=retry_timeouts,
        retry_unresolved_only=retry_unresolved_only,
    )


__all__ = [
    "COMPLETION_FOOTER_SCHEMA",
    "COMPLETION_RECORD_SCHEMA",
    "COMPLETION_SHARD_SCHEMA",
    "run_completion_shard",
    "run_orbit_completion_shard",
    "verify_completion_shard",
    "verify_orbit_completion_shard",
]
