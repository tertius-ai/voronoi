"""Stream immutable historical ledgers through Voronoi's native proof checker."""

from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import os
import shutil
import signal
import sqlite3
import subprocess
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import ExitStack, closing
from pathlib import Path
from typing import Any

from voronoi.enumerate.catalog_match import canonical_sha256
from voronoi.enumerate.census_engine import (
    ENGINE_NOETHER_CONTRACT,
    CensusEngineTimeout,
    _engine_path,
)
from voronoi.enumerate.completion_ledger import _orbit_metadata
from voronoi.runtime import census_engine_runtime

TASK_SCHEMA = "voronoi/ledger-replay-task@1"
REPORT_SCHEMA = "voronoi/ledger-replay-report@1"


def _json_line(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def encode_ledger_row(row: tuple) -> bytes:
    index, batch, limit, candidate_id, status, payload_json = row
    prefix = _json_line(
        {
            "candidate_index": index,
            "batch_index": batch,
            "max_iterations": limit,
            "candidate_id": candidate_id,
            "status": status,
        }
    )
    # Embed the original JSON verbatim. No evaluation or reserialization of its
    # potentially large nested proof is needed in the Python producer.
    return prefix[:-2] + b',"payload":' + payload_json.encode() + b"}\n"


def run_ledger_stream(
    task: Mapping[str, Any],
    rows: Callable[[], Iterable[bytes]],
    *,
    engine: Path | None = None,
    timeout_seconds: int = 1800,
    memory_limit_bytes: int = 4 * 1024**3,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    """Feed a bounded child while draining its output; propagate producer failures."""
    if timeout_seconds <= 0 or memory_limit_bytes <= 0:
        raise ValueError("replay resource limits must be positive")
    executable = _engine_path(engine)
    prlimit = shutil.which("prlimit")
    if prlimit is None:
        raise RuntimeError("ledger replay requires prlimit")
    process = subprocess.Popen(
        [
            prlimit,
            f"--as={memory_limit_bytes}:{memory_limit_bytes}",
            "--",
            str(executable),
            "--replay-ledger-stream",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    pipe = process.stdin
    assert pipe is not None
    process.stdin = None  # The producer owns this pipe; communicate only drains output.
    producer_errors: list[BaseException] = []
    produced = {}

    def produce() -> None:
        try:
            with pipe:
                digest = hashlib.sha256()
                header = _json_line(task)
                pipe.write(header)
                digest.update(header)
                count = 0
                for row in rows():
                    pipe.write(row)
                    digest.update(row)
                    count += 1
                produced.update(count=count, digest=digest.hexdigest())
                pipe.write(
                    _json_line(
                        {
                            "type": "voronoi/ledger-stream-footer@1",
                            "record_count": count,
                            "content_sha256": digest.hexdigest(),
                        }
                    )
                )
        except BaseException as error:  # noqa: BLE001 -- transferred to the supervising thread
            producer_errors.append(error)

    producer = threading.Thread(target=produce, daemon=True)
    producer.start()
    deadline = time.monotonic() + timeout_seconds
    try:
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError("ledger replay cancelled; no verdict accepted")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(process.args, timeout_seconds)
            try:
                stdout, stderr = process.communicate(timeout=min(1, remaining))
                break
            except subprocess.TimeoutExpired:
                if time.monotonic() >= deadline:
                    raise
    except BaseException as error:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate()
        producer.join(timeout=5)
        if isinstance(error, subprocess.TimeoutExpired):
            raise CensusEngineTimeout(
                "ledger replay exceeded its time limit; no verdict accepted"
            ) from error
        raise
    producer.join(timeout=5)
    if process.returncode != 0:
        raise RuntimeError(f"native ledger replay failed: {stderr.decode().strip()}")
    if producer.is_alive() or producer_errors:
        raise RuntimeError("ledger replay producer failed or did not finish") from (
            producer_errors[0] if producer_errors else None
        )
    report = json.loads(stdout)
    if (
        report.get("type") != REPORT_SCHEMA
        or report.get("noether_contract") != dict(ENGINE_NOETHER_CONTRACT)
        or report.get("task_sha256") != canonical_sha256(task)
        or report.get("input_content_sha256") != produced.get("digest")
        or report.get("record_count") != produced.get("count")
        or report.get("positive") != task["expected_positive"]
        or report.get("negative") != task["expected_negative"]
    ):
        raise ValueError("ledger replay report identity or coverage disagrees")
    for key in (
        "orbit_content_sha256",
        "positive_witnesses_sha256",
        "source_metadata_sha256",
        "partition_index",
        "partition_count",
    ):
        if report.get(key) != task[key]:
            raise ValueError(f"ledger replay report disagrees on {key}")
    return report


def _write(path: Path, value: object) -> None:
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def _sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_replay_receipts(task: Mapping[str, Any], report: Mapping[str, Any]) -> None:
    """Check persisted receipt bytes and exact index coverage independently of generation."""
    digest = hashlib.sha256()
    statuses = Counter()
    kinds = Counter()
    modes = Counter()
    index = task["partition_index"]
    with Path(task["receipt_path"]).open("rb") as stream:
        raw = stream.readline()
        header = json.loads(raw)
        if (
            header.get("type") != "voronoi/ledger-replay-receipts@1"
            or header.get("task_sha256") != canonical_sha256(task)
            or header.get("orbit_content_sha256") != task["orbit_content_sha256"]
            or header.get("positive_witnesses_sha256")
            != task["positive_witnesses_sha256"]
        ):
            raise ValueError("ledger replay receipt header disagrees")
        digest.update(raw)
        while raw := stream.readline():
            row = json.loads(raw)
            if row.get("type") == "voronoi/ledger-replay-footer@1":
                if stream.read(1):
                    raise ValueError("ledger receipt has data after footer")
                break
            if (
                row.get("type") != "voronoi/ledger-proof-receipt@1"
                or row.get("candidate_index") != index
                or index >= task["orbit_count"]
                or row.get("status") not in {"completed", "nonrealizable"}
            ):
                raise ValueError("ledger receipt index or status coverage disagrees")
            statuses[row["status"]] += 1
            if row["status"] == "nonrealizable":
                kinds[row["kind"]] += 1
                modes[row["normalization"]] += 1
            digest.update(raw)
            index += task["partition_count"]
        else:
            raise ValueError("ledger receipt footer is missing")
    if (
        index < task["orbit_count"]
        or dict(kinds) != report["negative_kinds"]
        or dict(modes) != report["normalizations"]
        or statuses["completed"] != task["expected_positive"]
        or statuses["nonrealizable"] != task["expected_negative"]
        or row.get("content_sha256") != digest.hexdigest()
        or report["receipt_content_sha256"] != digest.hexdigest()
        or row.get("record_count") != sum(statuses.values())
        or row.get("positive") != statuses["completed"]
        or row.get("negative") != statuses["nonrealizable"]
    ):
        raise ValueError("ledger receipt digest or terminal counts disagree")


def replay_historical_ledger(
    artifact_root: Path,
    positive_audit: Path,
    output: Path,
    *,
    workers: int = 4,
) -> dict[str, Any]:
    if workers not in (1, 2, 4):
        raise ValueError("ledger replay supports 1, 2, or 4 workers")
    output.mkdir(parents=True, exist_ok=False)
    engine = _engine_path(None)
    runtime = output / "runtime"
    runtime.mkdir()
    frozen_engine = runtime / "voronoi-census-engine"
    shutil.copy2(engine, frozen_engine)
    pair = json.loads((artifact_root / "lower-000-report.json").read_text())
    orbit = json.loads((artifact_root / "lower-000-orbit-report.json").read_text())
    positive_summary = json.loads((positive_audit / "summary.json").read_text())
    if positive_summary.get("all_positives_recertified") is not True:
        raise ValueError("positive audit is incomplete")
    for name, digest in positive_summary["evidence_files_sha256"].items():
        if Path(name).name != name or _sha(positive_audit / name) != digest:
            raise ValueError("positive audit evidence digest disagrees")
    catalog = json.loads((positive_audit / "catalog-task.json").read_text())
    vectors = {entry["id"]: entry["vectors"] for entry in catalog["sources"]}
    positives = []
    for path in sorted(positive_audit.glob("realization-*.json")):
        record = json.loads(path.read_text())
        positives.append(
            {
                "candidate_id": record["source_id"],
                "vectors": vectors[record["source_id"]],
                **record["source_realization_witness"],
            }
        )
    positive_path = output / "positive-witnesses.json"
    _write(positive_path, positives)
    sources = []
    for shard in range(64):
        path = (
            artifact_root
            / "orbit-production-64"
            / f".completion-{shard:05d}-of-00064.sqlite"
        )
        metadata = _orbit_metadata(
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
            if dict(db.execute("SELECT key,value FROM metadata")) != metadata:
                raise ValueError("historical ledger metadata disagrees")
            counts = dict(
                db.execute("SELECT status,count(*) FROM results GROUP BY status")
            )
            if set(counts) - {"completed", "nonrealizable"}:
                raise ValueError("historical ledger contains nonterminal results")
        sources.append(
            {
                "path": str(path.resolve()),
                "metadata": metadata,
                "counts": counts,
                "shard": shard,
            }
        )
    _write(output / "source-metadata.json", sources)

    cancellation = threading.Event()

    def partition(index: int) -> dict[str, Any]:
        selected = [source for source in sources if source["shard"] % workers == index]
        counts = Counter()
        for source in selected:
            counts.update(source["counts"])
        task = {
            "type": TASK_SCHEMA,
            "noether_contract": dict(ENGINE_NOETHER_CONTRACT),
            "orbit_path": str(artifact_root / "lower-000-orbits.jsonl"),
            "orbit_content_sha256": orbit["orbit_content_sha256"],
            "positive_witnesses_path": str(positive_path),
            "positive_witnesses_sha256": _sha(positive_path),
            "source_metadata_sha256": canonical_sha256(selected),
            "receipt_path": str(output / f"receipts-{index}.jsonl"),
            "ambient_rank": pair["ambient_rank"],
            "cone_dimension": pair["target_dimension"],
            "lower_index": pair["lower_index"],
            "pair_input_sha256": pair["input_sha256"],
            "event_stream_sha256": pair["event_stream_sha256"],
            "orbit_count": orbit["orbit_count"],
            "partition_index": index,
            "partition_count": workers,
            "expected_positive": counts["completed"],
            "expected_negative": counts["nonrealizable"],
        }
        _write(output / f"task-{index}.json", task)

        def rows() -> Iterable[bytes]:
            with ExitStack() as stack:
                cursors = []
                for source in selected:
                    db = stack.enter_context(
                        closing(
                            sqlite3.connect(
                                f"{Path(source['path']).as_uri()}?mode=ro", uri=True
                            )
                        )
                    )
                    db.execute("BEGIN")
                    if (
                        dict(db.execute("SELECT key,value FROM metadata"))
                        != source["metadata"]
                    ):
                        raise ValueError("ledger source metadata changed before replay")
                    cursors.append(
                        db.execute("""SELECT candidate_index,batch_index,max_iterations,
                        candidate_id,status,payload_json FROM results ORDER BY candidate_index""")
                    )
                for row in heapq.merge(*cursors, key=lambda row: row[0]):
                    yield encode_ledger_row(row)

        report = run_ledger_stream(
            task,
            rows,
            engine=frozen_engine,
            timeout_seconds=3600,
            cancel_event=cancellation,
        )
        verify_replay_receipts(task, report)
        _write(output / f"report-{index}.json", report)
        print(
            f"Partition {index}: {report['positive']} positive and {report['negative']} negative proofs checked",
            flush=True,
        )
        return report

    with ThreadPoolExecutor(max_workers=workers) as executor:
        pending = [executor.submit(partition, index) for index in range(workers)]
        try:
            reports = [future.result() for future in as_completed(pending)]
        except BaseException:
            cancellation.set()
            for future in pending:
                future.cancel()
            raise
    positive_count = sum(report["positive"] for report in reports)
    negative_count = sum(report["negative"] for report in reports)
    if positive_count + negative_count != orbit["orbit_count"] or positive_count != len(
        positives
    ):
        raise ValueError("full ledger replay coverage disagrees")
    summary = {
        "type": "voronoi/historical-ledger-replay@1",
        "positive": positive_count,
        "negative": negative_count,
        "representatives": orbit["orbit_count"],
        "workers": workers,
        "worker_runtime": census_engine_runtime(frozen_engine),
        "worker_sha256": _sha(frozen_engine),
        "positive_audit_summary_sha256": _sha(positive_audit / "summary.json"),
        "negative_kinds": dict(
            sum((Counter(report["negative_kinds"]) for report in reports), Counter())
        ),
        "normalizations": dict(
            sum((Counter(report["normalizations"]) for report in reports), Counter())
        ),
        "all_ledger_proofs_replayed": True,
        "coface_pair_generation_replayed": False,
        "global_census_complete": False,
        "files_sha256": {p.name: _sha(p) for p in sorted(output.glob("*.json*"))},
    }
    _write(output / "summary.json", summary)
    return summary


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", type=Path, default=root / "artifacts/n8-r10")
    parser.add_argument(
        "--positive-audit",
        type=Path,
        default=root / "artifacts/n8-r10/audit-noether-0.3.2-20261028-final",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--workers", type=int, choices=(1, 2, 4), default=4)
    args = parser.parse_args()
    summary = replay_historical_ledger(
        args.artifact_root.resolve(),
        args.positive_audit.resolve(),
        args.output_dir.resolve(),
        workers=args.workers,
    )
    print(
        json.dumps(
            {key: value for key, value in summary.items() if key != "files_sha256"},
            indent=2,
        )
    )
