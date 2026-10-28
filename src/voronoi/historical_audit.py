"""Bounded read-only audit of the recovered N=8, cone-rank-10 positives.

Run with ``python -m voronoi.historical_audit --output-dir artifacts/NEW-RUN``.
Historical negatives are counted, not mathematically replayed by this audit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import subprocess
from collections import Counter
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import noether

from voronoi.cells import VoronoiCell
from voronoi.enumerate.catalog_match import (
    canonical_sha256,
    catalog_match_task,
    pullback_realization_witness,
    run_catalog_match,
)
from voronoi.enumerate.census_engine import (
    CensusEngineTimeout,
    _candidate_identifier,
    _decode_json_line,
    _engine_path,
    build_completion_batch_task,
    run_completion_batch_task,
    verify_positive_completion_witness,
)
from voronoi.enumerate.completion_ledger import _orbit_metadata
from voronoi.enumerate.orbit_reduction import ORBIT_FOOTER_SCHEMA, ORBIT_RECORD_SCHEMA
from voronoi.parse import parse_list_shv_file
from voronoi.runtime import NOETHER_VERSION, census_engine_runtime


def read_terminal_shard(
    path: Path,
    expected_metadata: Mapping[str, str],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Check ledger coverage in a read transaction; fetch only positive payloads.

    Neither status counts nor stored evidence hashes replay negative certificates.
    """
    count = int(expected_metadata["candidate_count"])
    shard = int(expected_metadata["shard_index"])
    shards = int(expected_metadata["shard_count"])
    if (
        expected_metadata["batch_size"] != "1"
        or expected_metadata["strategy"] != "exact_shell"
    ):
        raise ValueError("this audit requires single-candidate exact-shell ledgers")
    with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as db:
        db.execute("BEGIN")
        metadata = dict(db.execute("SELECT key,value FROM metadata"))
        if metadata != dict(expected_metadata):
            raise ValueError(f"historical shard metadata disagrees: {path.name}")
        statuses = {}
        for status, total, invalid in db.execute(
            """
            SELECT status, count(*), sum(CASE WHEN
                candidate_index < 0 OR candidate_index >= ? OR
                batch_index != candidate_index OR candidate_index % ? != ? OR
                max_iterations < 0 THEN 1 ELSE 0 END)
            FROM results GROUP BY status
        """,
            (count, shards, shard),
        ):
            if status not in {"completed", "nonrealizable"} or invalid:
                raise ValueError(
                    "historical shard is nonterminal or has invalid indices"
                )
            statuses[status] = total
        expected_count = len(range(shard, count, shards))
        if sum(statuses.values()) != expected_count:
            raise ValueError("historical shard lacks terminal index coverage")
        positives = []
        for index, candidate_id, limit, raw in db.execute("""
            SELECT candidate_index,candidate_id,max_iterations,payload_json
            FROM results WHERE status='completed' ORDER BY candidate_index
        """):
            payload = json.loads(raw)
            if (
                payload["status"] != "completed"
                or payload["candidate_id"] != candidate_id
            ):
                raise ValueError("positive payload disagrees with its ledger row")
            if (
                hashlib.sha256(payload["evidence_canonical_json"].encode()).hexdigest()
                != payload["evidence_sha256"]
            ):
                raise ValueError("historical positive evidence digest disagrees")
            vectors = payload["completed_vectors"]
            if _candidate_identifier(vectors) != candidate_id:
                raise ValueError("historical exact-shell identity disagrees")
            positives.append(
                {
                    "candidate_index": index,
                    "candidate_id": candidate_id,
                    "max_iterations": limit,
                    "vectors": vectors,
                    "historical_evidence_sha256": payload["evidence_sha256"],
                    "historical_payload_sha256": canonical_sha256(payload),
                }
            )
        if len(positives) != statuses.get("completed", 0):
            raise ValueError("historical positive count disagrees")
    return {
        "path": str(path),
        "metadata": metadata,
        "status_counts": statuses,
        "positive_rows_sha256": canonical_sha256(positives),
    }, positives


def bind_positive_rows_to_orbit_artifact(
    path: Path,
    positives: list[dict[str, Any]],
    pair: Mapping[str, Any],
    orbit: Mapping[str, Any],
) -> None:
    """Check original byte digest and positive parentage, without replaying all orbits."""
    by_index = {p["candidate_index"]: p for p in positives}
    if len(by_index) != len(positives):
        raise ValueError("repeated positive candidate index")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        header_line = stream.readline()
        header = _decode_json_line(header_line, description="historical orbit header")
        expected = {
            "type": "voronoi/orbit-artifact@1",
            "noether_contract": orbit["noether_contract"],
            "candidate_content_sha256": orbit["candidate_content_sha256"],
            "keyed_content_sha256": orbit["keyed_content_sha256"],
            "ambient_rank": pair["ambient_rank"],
            "target_dimension": pair["target_dimension"],
            "lower_index": pair["lower_index"],
            "input_sha256": pair["input_sha256"],
            "event_stream_sha256": pair["event_stream_sha256"],
        }
        if any(header.get(k) != v for k, v in expected.items()):
            raise ValueError("historical orbit header disagrees")
        digest.update(header_line)
        for index in range(int(orbit["orbit_count"])):
            line = stream.readline()
            if not line.endswith(b"\n"):
                raise ValueError("historical orbit artifact is truncated")
            digest.update(line)
            if positive := by_index.pop(index, None):
                record = _decode_json_line(
                    line, description="historical positive parent"
                )
                representative = record["representative"]
                if (
                    record["type"] != ORBIT_RECORD_SCHEMA
                    or representative["candidate_id"] != positive["candidate_id"]
                    or representative["vectors"] != positive["vectors"]
                ):
                    raise ValueError(
                        "historical positive does not match original orbit"
                    )
        footer = _decode_json_line(
            stream.readline(), description="historical orbit footer"
        )
        if (
            by_index
            or stream.read(1)
            or footer.get("type") != ORBIT_FOOTER_SCHEMA
            or footer.get("orbit_count") != int(orbit["orbit_count"])
            or digest.hexdigest() != orbit["orbit_content_sha256"]
            or footer.get("content_sha256") != digest.hexdigest()
        ):
            raise ValueError("historical orbit content digest or coverage disagrees")


def _write_json(path: Path, value: object) -> None:
    with path.open("x") as output:
        json.dump(value, output, indent=2, sort_keys=True)
        output.write("\n")


def _file_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def audit(
    root: Path,
    artifact_root: Path,
    output: Path,
    *,
    workers: int = 4,
    reuse_audits: Sequence[Path] = (),
) -> dict[str, Any]:
    if not 1 <= workers <= 4:
        raise ValueError("audit worker count must lie in 1..4")
    output.mkdir(parents=True, exist_ok=False)
    pair = json.loads((artifact_root / "lower-000-report.json").read_text())
    orbit = json.loads((artifact_root / "lower-000-orbit-report.json").read_text())
    history = json.loads((root / "validation/historical-n8-r10.json").read_text())
    if (pair["ambient_rank"], pair["target_dimension"], pair["lower_index"]) != (
        8,
        10,
        0,
    ):
        raise ValueError("unexpected historical census scope")
    if (
        orbit["orbit_content_sha256"] != history["content_sha256"]["orbits"]
        or orbit["keyed_content_sha256"] != history["content_sha256"]["keyed"]
        or orbit["candidate_content_sha256"] != history["content_sha256"]["candidates"]
    ):
        raise ValueError("historical report does not match retained provenance")
    sources = []
    shards = []
    for shard in range(64):
        metadata = _orbit_metadata(
            pair,
            orbit,
            shard_index=shard,
            shard_count=64,
            batch_size=1,
            strategy="exact_shell",
        )
        path = (
            artifact_root
            / "orbit-production-64"
            / f".completion-{shard:05d}-of-00064.sqlite"
        )
        summary, positives = read_terminal_shard(path, metadata)
        shards.append(summary)
        sources.extend(positives)
    sources.sort(key=lambda p: p["candidate_index"])
    counts = Counter()
    for shard in shards:
        counts.update(shard["status_counts"])
    if (
        counts["completed"] != history["completion"]["realized"]
        or counts["nonrealizable"] != history["completion"]["nonrealizable"]
    ):
        raise ValueError("historical status totals disagree with retained summary")
    print(f"Read-only ledger coverage: {dict(counts)}", flush=True)
    bind_positive_rows_to_orbit_artifact(
        artifact_root / "lower-000-orbits.jsonl",
        sources,
        pair,
        orbit,
    )
    _write_json(
        output / "source-snapshot.json", {"shards": shards, "positives": sources}
    )
    print("Original orbit digest and all positive parentages verified", flush=True)

    lock = json.loads((root / "validation/reference-database.json").read_text())
    reference = (
        root / "data/elbazvip-Voronoi-complexes-database/DATA_pari/ListSHV_n8_rank10"
    )
    if _file_sha256(reference) != lock["files"][reference.name]:
        raise ValueError("reference catalog does not match database lock")
    references = parse_list_shv_file(reference)
    task = catalog_match_task(
        [
            (
                p["candidate_id"],
                VoronoiCell.from_rows(p["vectors"], expected_dimension=10),
            )
            for p in sources
        ],
        [(f"U{i}", cell) for i, cell in enumerate(references, start=1)],
        ambient_rank=8,
        cone_dimension=10,
    )
    _write_json(output / "catalog-task.json", task)
    engine = _engine_path(None)
    worker_sha256 = _file_sha256(engine)
    noether_python = Path(noether.__file__).resolve().parent.parent
    runtime_paths = [
        p
        for directory in (
            noether_python / "noether",
            noether_python / "tertius_noether.libs",
        )
        for p in directory.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    ]
    runtime_sha256 = {
        str(p.relative_to(noether_python)): _file_sha256(p)
        for p in sorted(runtime_paths)
    }
    report = run_catalog_match(task, engine=engine)
    _write_json(output / "catalog-report.json", report)
    print(f"Exact catalog matches: {len(report['matches'])}/{len(sources)}", flush=True)
    recertified = Counter()
    freshly_solved = Counter()
    reused = 0
    cached_witnesses = {}
    source_ids = {source["candidate_id"] for source in sources}
    for directory in reuse_audits:
        if not directory.is_dir():
            raise FileNotFoundError(f"audit cache is not a directory: {directory}")
        for path in sorted(directory.glob("realization-*.json")):
            encoded = path.read_bytes()
            record = json.loads(encoded)
            source_id = record.get("source_id")
            witness = record.get("source_realization_witness")
            if witness is None:
                # Earlier direct-coordinate reports retained the source witness
                # inside their native result. Canonical identity bytes do not suffice.
                results = (record.get("report") or {}).get("results", [])
                if len(results) == 1 and results[0].get("status") == "completed":
                    source_id = results[0]["candidate_id"]
                    witness = results[0].get("realization_witness")
            if source_id in source_ids and witness is not None:
                cached_witnesses.setdefault(
                    source_id, (witness, path, hashlib.sha256(encoded).hexdigest())
                )

    matches = {match["source_id"]: match for match in report["matches"]}
    reference_by_id = dict(
        zip((f"U{i}" for i in range(1, len(references) + 1)), references, strict=True)
    )

    def realize(source: dict[str, Any]) -> dict[str, Any]:
        source_cell = VoronoiCell.from_rows(source["vectors"], expected_dimension=10)
        if cached := cached_witnesses.get(source["candidate_id"]):
            witness, path, digest = cached
            verify_positive_completion_witness(
                {
                    "status": "completed",
                    "completed_vectors": source["vectors"],
                    "realization_witness": witness,
                }
            )
            return {
                "source_id": source["candidate_id"],
                "source_realization_witness": witness,
                "reused_from": {"path": str(path), "sha256": digest},
                "task": None,
                "report": None,
            }
        match = matches.get(source["candidate_id"])
        reference_cell = (
            reference_by_id[match["reference_id"]] if match else source_cell
        )
        completion = build_completion_batch_task(
            [
                {
                    "candidate_id": match["reference_id"]
                    if match
                    else source["candidate_id"],
                    "vectors": [list(v) for v in reference_cell.min_vectors],
                }
            ],
            max_iterations=200,
            strategy="exact_shell",
        )
        pulled_witness = None
        try:
            result = run_completion_batch_task(
                completion, engine=engine, timeout_seconds=60
            )
            item = result["results"][0]
            if item["status"] == "completed":
                pulled_witness = pullback_realization_witness(
                    source_cell,
                    reference_cell,
                    match["transformation"]
                    if match
                    else [[int(i == j) for j in range(8)] for i in range(8)],
                    item["realization_witness"],
                )
        except CensusEngineTimeout:
            result = {"execution_timeout": True, "mathematical_verdict": None}
        return {
            "source_id": source["candidate_id"],
            "reference_id": match["reference_id"] if match else None,
            "task": completion,
            "report": result,
            "source_realization_witness": pulled_witness,
        }

    with ThreadPoolExecutor(max_workers=workers) as executor:
        pending = {
            executor.submit(realize, source): start
            for start, source in enumerate(sources)
        }
        try:
            for future in as_completed(pending):
                start = pending[future]
                record = future.result()
                result = record["report"] or {}
                if record.get("reused_from"):
                    recertified["completed"] += 1
                    reused += 1
                elif result.get("execution_timeout"):
                    recertified["execution_timeout"] += 1
                    freshly_solved["execution_timeout"] += 1
                else:
                    recertified.update(item["status"] for item in result["results"])
                    freshly_solved.update(item["status"] for item in result["results"])
                _write_json(output / f"realization-{start:05d}.json", record)
                done = sum(recertified.values())
                if (
                    done % 10 == 0
                    or done == len(sources)
                    or result.get("execution_timeout")
                ):
                    print(
                        f"Fresh realization {done}/{len(sources)}: {dict(recertified)}",
                        flush=True,
                    )
        except BaseException:
            for future in pending:
                future.cancel()
            raise

    def git(*args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=root, text=True).strip()

    source_paths = [
        *root.glob("src/**/*.py"),
        *root.glob("rust/**/*.rs"),
        root / "Cargo.lock",
        root / "rust/census-engine/Cargo.toml",
        root / "pyproject.toml",
        root / "uv.lock",
    ]
    summary = {
        "type": "voronoi/historical-positive-audit@1",
        "date": datetime.now(UTC).isoformat(),
        "scope": {
            "ambient_rank": 8,
            "cone_dimension": 10,
            "projective_degree": 9,
            "lower_index": 0,
        },
        "noether_version": NOETHER_VERSION,
        "noether_python_root": str(noether_python),
        "noether_runtime_files_sha256": runtime_sha256,
        "resource_limits": {
            "workers": workers,
            "batch_size": 1,
            "batch_timeout_seconds": 60,
            "worker_memory_limit_bytes": 4 * 1024**3,
        },
        "worker_runtime": census_engine_runtime(engine),
        "worker_sha256": worker_sha256,
        "voronoi_commit": git("rev-parse", "HEAD"),
        "voronoi_worktree_status": git("status", "--porcelain"),
        "source_sha256": {
            str(p.relative_to(root)): _file_sha256(p) for p in sorted(source_paths)
        },
        "reference_revision": lock["revision"],
        "reference_file_sha256": lock["files"][reference.name],
        "historical_orbit_content_sha256": orbit["orbit_content_sha256"],
        "historical_status_counts": dict(counts),
        "source_count": len(sources),
        "reference_count": len(references),
        "matched_sources": len(report["matches"]),
        "distinct_references_hit": len({m["reference_id"] for m in report["matches"]}),
        "unmatched_sources": len(report["unmatched_source_ids"]),
        "unused_references": len(report["unused_reference_ids"]),
        "fresh_realization_status_counts": dict(freshly_solved),
        "source_witness_status_counts": dict(recertified),
        "cached_witnesses_replayed": reused,
        "all_positives_recertified": recertified["completed"] == len(sources),
        "realization_coordinates": "published reference with checked Gram pullback; original coordinates for unmatched sources",
        "historical_negative_certificates_replayed": False,
        "global_census_complete": False,
        "evidence_files_sha256": {
            p.name: _file_sha256(p) for p in sorted(output.glob("*.json"))
        },
    }
    if _file_sha256(engine) != worker_sha256:
        raise ValueError("worker changed during audit")
    if any(
        _file_sha256(noether_python / name) != digest
        for name, digest in runtime_sha256.items()
    ):
        raise ValueError("Noether runtime changed during audit")
    _write_json(output / "summary.json", summary)
    return summary


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", type=Path, default=root / "artifacts/n8-r10")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--workers", type=int, choices=range(1, 5), default=4)
    parser.add_argument(
        "--reuse-audit",
        type=Path,
        action="append",
        default=[],
        help="reuse saved positive Gram witnesses after exact native replay (repeatable)",
    )
    args = parser.parse_args()
    summary = audit(
        root,
        args.artifact_root.resolve(),
        args.output_dir.resolve(),
        workers=args.workers,
        reuse_audits=[path.resolve() for path in args.reuse_audit],
    )
    print(
        json.dumps(
            {
                k: v
                for k, v in summary.items()
                if k
                not in {
                    "source_sha256",
                    "evidence_files_sha256",
                    "voronoi_worktree_status",
                    "noether_runtime_files_sha256",
                }
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
