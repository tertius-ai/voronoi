"""Every streamed verdict must match its original orbit, with no skipped indices."""

from __future__ import annotations

import hashlib
import json
import sys
import threading
from pathlib import Path

import pytest

from voronoi.enumerate.census_engine import (
    ENGINE_NOETHER_CONTRACT,
    CensusEngineTimeout,
    _candidate_identifier,
    build_completion_batch_task,
    run_completion_batch_task,
)
from voronoi.negative_replay import (
    TASK_SCHEMA,
    encode_ledger_row,
    run_ledger_stream,
    verify_replay_receipts,
)


@pytest.fixture
def ledger(tmp_path: Path):
    vectors = [[[0, 1], [1, 0]], [[1, 0], [1, 2]]]
    candidates = [
        {"candidate_id": _candidate_identifier(v), "vectors": v} for v in vectors
    ]
    generated = run_completion_batch_task(
        build_completion_batch_task(candidates, strategy="exact_shell")
    )
    assert [r["status"] for r in generated["results"]] == ["completed", "nonrealizable"]
    header = {
        "type": "voronoi/orbit-artifact@1",
        "noether_contract": dict(ENGINE_NOETHER_CONTRACT),
        "ambient_rank": 2,
        "target_dimension": 2,
        "lower_index": 0,
        "input_sha256": "input",
        "event_stream_sha256": "events",
    }
    records = [
        header,
        *[{"type": "voronoi/orbit-record@1", "representative": c} for c in candidates],
    ]
    body = b"".join((json.dumps(r) + "\n").encode() for r in records)
    digest = hashlib.sha256(body).hexdigest()
    orbit = tmp_path / "orbits.jsonl"
    orbit.write_bytes(
        body
        + (
            json.dumps(
                {
                    "type": "voronoi/orbit-footer@1",
                    "orbit_count": 2,
                    "content_sha256": digest,
                }
            )
            + "\n"
        ).encode()
    )
    witness = tmp_path / "positive.json"
    witness.write_text(
        json.dumps(
            [
                {
                    "candidate_id": candidates[0]["candidate_id"],
                    "vectors": vectors[0],
                    **generated["results"][0]["realization_witness"],
                }
            ]
        )
    )
    task = {
        "type": TASK_SCHEMA,
        "noether_contract": dict(ENGINE_NOETHER_CONTRACT),
        "orbit_path": str(orbit),
        "orbit_content_sha256": digest,
        "positive_witnesses_path": str(witness),
        "positive_witnesses_sha256": hashlib.sha256(witness.read_bytes()).hexdigest(),
        "source_metadata_sha256": "metadata",
        "receipt_path": str(tmp_path / "receipts.jsonl"),
        "ambient_rank": 2,
        "cone_dimension": 2,
        "lower_index": 0,
        "pair_input_sha256": "input",
        "event_stream_sha256": "events",
        "orbit_count": 2,
        "partition_index": 0,
        "partition_count": 1,
        "expected_positive": 1,
        "expected_negative": 1,
    }
    rows = [
        (i, i, 50, c["candidate_id"], result["status"], json.dumps(result))
        for i, (c, result) in enumerate(
            zip(candidates, generated["results"], strict=True)
        )
    ]
    return task, rows


def test_native_stream_replays_both_verdicts_and_publishes_receipts(ledger):
    task, rows = ledger
    report = run_ledger_stream(task, lambda: (encode_ledger_row(row) for row in rows))
    assert (report["positive"], report["negative"], report["record_count"]) == (1, 1, 2)
    assert sum(report["negative_kinds"].values()) == 1
    verify_replay_receipts(task, report)
    receipts = [
        json.loads(line) for line in Path(task["receipt_path"]).read_text().splitlines()
    ]
    assert [r["candidate_index"] for r in receipts[1:-1]] == [0, 1]
    with pytest.raises(RuntimeError, match="destination exists"):
        run_ledger_stream(task, lambda: (encode_ledger_row(row) for row in rows))


@pytest.mark.parametrize("change", ["missing", "repeat", "wrong-id", "false-proof"])
def test_native_stream_rejects_gaps_repeated_indices_and_unbound_proofs(ledger, change):
    task, rows = ledger
    if change == "missing":
        rows = rows[:1]
    elif change == "repeat":
        rows = [rows[0], rows[0]]
    elif change == "wrong-id":
        row = list(rows[1])
        row[3] = rows[0][3]
        rows[1] = tuple(row)
    else:
        payload = json.loads(rows[1][5])
        outer = json.loads(payload["evidence_canonical_json"])
        certificate = json.loads(bytes(outer[2]))
        certificate[4] = ["0"] * len(certificate[4])
        outer[2] = list(json.dumps(certificate).encode())
        payload["evidence_canonical_json"] = json.dumps(outer)
        payload["evidence_sha256"] = hashlib.sha256(
            payload["evidence_canonical_json"].encode()
        ).hexdigest()
        row = list(rows[1])
        row[5] = json.dumps(payload)
        rows[1] = tuple(row)
    with pytest.raises(RuntimeError):
        run_ledger_stream(
            task, lambda: (encode_ledger_row(row) for row in rows), timeout_seconds=10
        )
    assert not Path(task["receipt_path"]).exists()


def test_stream_producer_failure_cannot_become_a_successful_report(ledger):
    task, rows = ledger

    def broken_rows():
        yield encode_ledger_row(rows[0])
        raise ValueError("source read failed")

    with pytest.raises(RuntimeError):
        run_ledger_stream(task, broken_rows, timeout_seconds=10)
    assert not Path(task["receipt_path"]).exists()


def test_persisted_receipt_tampering_is_detected(ledger):
    task, rows = ledger
    report = run_ledger_stream(task, lambda: (encode_ledger_row(row) for row in rows))
    path = Path(task["receipt_path"])
    encoded = path.read_bytes().replace(
        b'"normalization":"unscaled"', b'"normalization":"altered"'
    )
    path.write_bytes(encoded)
    with pytest.raises(ValueError, match="digest or terminal counts"):
        verify_replay_receipts(task, report)


def test_stream_handles_backpressure_without_buffering_the_ledger(ledger):
    task, rows = ledger
    row = list(rows[1])
    row[5] += " " * 200_000  # Valid JSON whitespace makes this exceed a pipe buffer.
    rows[1] = tuple(row)
    report = run_ledger_stream(task, lambda: (encode_ledger_row(row) for row in rows))
    verify_replay_receipts(task, report)
    assert report["record_count"] == 2


@pytest.mark.parametrize("cancel", [False, True], ids=["timeout", "cancel"])
def test_stream_timeout_kills_its_worker_and_descendants(ledger, tmp_path, cancel):
    task, rows = ledger
    row = list(rows[1])
    row[5] += " " * 200_000
    rows[1] = tuple(row)
    pid_file = tmp_path / "child.pid"
    worker = tmp_path / "hanging-worker"
    worker.write_text(
        f"#!{sys.executable}\n"
        "import json, pathlib, subprocess, sys, time\n"
        "if sys.argv[1:] == ['--version']:\n"
        " print(json.dumps({'type':'voronoi/census-engine-runtime@1','noether_version':'0.3.2'})); sys.exit(0)\n"
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])\n"
        f"pathlib.Path({str(pid_file)!r}).write_text(str(child.pid))\n"
        "time.sleep(60)\n"
    )
    worker.chmod(0o755)
    event = threading.Event() if cancel else None
    timer = threading.Timer(0.5, event.set) if event is not None else None
    if timer is not None:
        timer.start()
    with pytest.raises(RuntimeError if cancel else CensusEngineTimeout):
        run_ledger_stream(
            task,
            lambda: (encode_ledger_row(row) for row in rows),
            engine=worker,
            timeout_seconds=10 if cancel else 0.5,
            cancel_event=event,
        )
    if timer is not None:
        timer.join()
    process_stat = Path(f"/proc/{pid_file.read_text()}/stat")
    try:
        state = process_stat.read_text().rsplit(")", 1)[1].split()[0]
    except (FileNotFoundError, ProcessLookupError):
        state = None
    assert state in {None, "Z", "X"}
    assert not Path(task["receipt_path"]).exists()
