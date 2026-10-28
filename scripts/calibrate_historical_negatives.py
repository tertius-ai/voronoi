"""Regenerate one stratified historical negative per shard with bounded resources."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import closing
from pathlib import Path

from voronoi.enumerate.census_engine import (
    CensusEngineTimeout,
    _engine_path,
    build_completion_batch_task,
    run_completion_batch_task,
)
from voronoi.enumerate.completion_ledger import _orbit_metadata
from voronoi.historical_evidence import inspect_negative_configuration
from voronoi.runtime import census_engine_runtime


def write(path: Path, value: object) -> None:
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def calibrate(artifact_root: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    pair = json.loads((artifact_root / "lower-000-report.json").read_text())
    orbit = json.loads((artifact_root / "lower-000-orbit-report.json").read_text())
    engine = _engine_path(None)
    count = int(orbit["orbit_count"])
    samples = []
    for shard in range(64):
        path = (
            artifact_root
            / "orbit-production-64"
            / f".completion-{shard:05d}-of-00064.sqlite"
        )
        expected = _orbit_metadata(
            pair,
            orbit,
            shard_index=shard,
            shard_count=64,
            batch_size=1,
            strategy="exact_shell",
        )
        with closing(
            sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
        ) as db:
            db.execute("BEGIN")
            if dict(db.execute("SELECT key,value FROM metadata")) != expected:
                raise ValueError("historical negative shard metadata disagrees")
            row = db.execute(
                """SELECT candidate_index,candidate_id,payload_json FROM results
                WHERE candidate_index >= ? AND status='nonrealizable'
                ORDER BY candidate_index LIMIT 1""",
                (count * shard // 64,),
            ).fetchone()
            if row is None:
                raise ValueError("historical negative stratum is empty")
            index, candidate_id, encoded = row
            payload = json.loads(encoded)
            cell, kind = inspect_negative_configuration(payload)
            if (
                payload["candidate_id"] != candidate_id
                or index % 64 != shard
                or cell.lattice_rank != 8
                or cell.cone_dimension != 10
            ):
                raise ValueError("historical negative source binding disagrees")
            samples.append(
                {
                    "candidate_index": index,
                    "candidate_id": candidate_id,
                    "vectors": [list(v) for v in cell.min_vectors],
                    "shard": shard,
                    "historical_kind": kind,
                    "historical_evidence_sha256": payload["evidence_sha256"],
                    "historical_payload_sha256": hashlib.sha256(
                        encoded.encode()
                    ).hexdigest(),
                }
            )
    write(output / "sample-inputs.json", samples)

    def regenerate(sample: dict) -> dict:
        task = build_completion_batch_task(
            [sample], max_iterations=200, strategy="exact_shell"
        )
        started = time.monotonic()
        try:
            report = run_completion_batch_task(task, engine=engine, timeout_seconds=30)
            status = report["results"][0]["status"]
        except CensusEngineTimeout:
            report = {"execution_timeout": True, "mathematical_verdict": None}
            status = "execution_timeout"
        return {
            "sample": sample,
            "task": task,
            "report": report,
            "status": status,
            "elapsed_seconds": time.monotonic() - started,
        }

    statuses = Counter()
    seconds = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(regenerate, sample): sample for sample in samples}
        try:
            for future in as_completed(futures):
                record = future.result()
                write(output / f"sample-{record['sample']['shard']:02d}.json", record)
                statuses[record["status"]] += 1
                seconds.append(record["elapsed_seconds"])
                if sum(statuses.values()) % 8 == 0:
                    print(
                        f"Negative calibration {sum(statuses.values())}/64: {dict(statuses)}",
                        flush=True,
                    )
        except BaseException:
            for future in futures:
                future.cancel()
            raise
    summary = {
        "type": "voronoi/historical-negative-calibration@1",
        "scope": {"ambient_rank": 8, "cone_dimension": 10, "lower_index": 0},
        "selection": "One negative per shard at or after floor(shard_index * orbit_count / 64).",
        "sample_count": len(samples),
        "status_counts": dict(statuses),
        "worker_runtime": census_engine_runtime(engine),
        "worker_sha256": hashlib.sha256(engine.read_bytes()).hexdigest(),
        "resource_limits": {
            "workers": 4,
            "max_iterations": 200,
            "timeout_seconds": 30,
            "memory_limit_bytes": 4 * 1024**3,
        },
        "observed_total_case_seconds": sum(seconds),
        "observed_max_case_seconds": max(seconds),
        "historical_negative_certificates_replayed": False,
        "fresh_native_certificates_verified": statuses["nonrealizable"],
        "global_negative_coverage_complete": False,
        "evidence_files_sha256": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(output.glob("*.json"))
        },
    }
    write(output / "summary.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", type=Path, default=Path("artifacts/n8-r10"))
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = calibrate(args.artifact_root.resolve(), args.output_dir.resolve())
    print(
        json.dumps(
            {k: v for k, v in result.items() if k != "evidence_files_sha256"}, indent=2
        )
    )
