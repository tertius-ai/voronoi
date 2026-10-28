"""Historical ledgers are inspected without writes or inferred negative proofs."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from voronoi.enumerate.census_engine import _candidate_identifier
from voronoi.historical_audit import (
    bind_positive_rows_to_orbit_artifact,
    read_terminal_shard,
)


@pytest.fixture
def ledger(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    path = tmp_path / "historical.sqlite"
    metadata = {
        "candidate_count": "2",
        "shard_index": "0",
        "shard_count": "1",
        "batch_size": "1",
        "strategy": "exact_shell",
    }
    vectors = [[0, 1], [1, 0]]
    candidate_id = _candidate_identifier(vectors)
    evidence = "{}"
    payload = {
        "candidate_id": candidate_id,
        "status": "completed",
        "completed_vectors": vectors,
        "evidence_canonical_json": evidence,
        "evidence_sha256": hashlib.sha256(evidence.encode()).hexdigest(),
    }
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
        db.executemany("INSERT INTO metadata VALUES (?,?)", metadata.items())
        db.execute("""CREATE TABLE results(candidate_index INTEGER PRIMARY KEY,
            batch_index INTEGER, candidate_id TEXT UNIQUE, status TEXT,
            max_iterations INTEGER, payload_json TEXT)""")
        db.execute(
            "INSERT INTO results VALUES (0,0,?,'completed',50,?)",
            (candidate_id, json.dumps(payload)),
        )
        db.execute(
            "INSERT INTO results VALUES (1,1,'negative','nonrealizable',50,'{}')"
        )
    return path, metadata


def test_historical_read_is_unchanged_and_binds_positive_evidence(ledger) -> None:
    path, metadata = ledger
    before = path.read_bytes()
    summary, positives = read_terminal_shard(path, metadata)
    assert path.read_bytes() == before
    assert summary["status_counts"] == {"completed": 1, "nonrealizable": 1}
    assert len(positives) == 1
    assert positives[0]["candidate_index"] == 0
    assert positives[0]["vectors"] == [[0, 1], [1, 0]]
    with pytest.raises(ValueError, match="metadata disagrees"):
        read_terminal_shard(path, {**metadata, "candidate_count": "3"})


@pytest.mark.parametrize(
    "change",
    [
        "DELETE FROM results WHERE candidate_index=1",
        "UPDATE results SET candidate_index=2 WHERE candidate_index=1",
        "UPDATE results SET status='inconclusive' WHERE candidate_index=1",
        "UPDATE results SET payload_json=replace(payload_json,'{}','[]') WHERE candidate_index=0",
    ],
)
def test_historical_audit_rejects_missing_nonterminal_and_corrupt_rows(
    ledger, change
) -> None:
    path, metadata = ledger
    with sqlite3.connect(path) as db:
        db.execute(change)
    with pytest.raises(ValueError):
        read_terminal_shard(path, metadata)


def test_positive_parentage_and_full_orbit_digest_are_both_checked(
    ledger, tmp_path
) -> None:
    path, metadata = ledger
    _, positives = read_terminal_shard(path, metadata)
    pair = {
        "ambient_rank": 2,
        "target_dimension": 2,
        "lower_index": 0,
        "input_sha256": "input",
        "event_stream_sha256": "events",
    }
    orbit = {
        "noether_contract": {},
        "candidate_content_sha256": "candidates",
        "keyed_content_sha256": "keyed",
        "orbit_count": 2,
    }
    header = {
        "type": "voronoi/orbit-artifact@1",
        **pair,
        **{k: v for k, v in orbit.items() if k != "orbit_count"},
    }
    rows = [
        header,
        {
            "type": "voronoi/orbit-record@1",
            "representative": {
                "candidate_id": positives[0]["candidate_id"],
                "vectors": positives[0]["vectors"],
            },
        },
        {
            "type": "voronoi/orbit-record@1",
            "representative": {"candidate_id": "negative"},
        },
    ]
    body = b"".join((json.dumps(row) + "\n").encode() for row in rows)
    digest = hashlib.sha256(body).hexdigest()
    orbit["orbit_content_sha256"] = digest
    footer = {
        "type": "voronoi/orbit-footer@1",
        "orbit_count": 2,
        "content_sha256": digest,
    }
    artifact = tmp_path / "orbits.jsonl"
    artifact.write_bytes(body + (json.dumps(footer) + "\n").encode())
    bind_positive_rows_to_orbit_artifact(artifact, positives, pair, orbit)
    bad = [{**positives[0], "candidate_id": "wrong"}]
    with pytest.raises(ValueError, match="does not match original orbit"):
        bind_positive_rows_to_orbit_artifact(artifact, bad, pair, orbit)
    artifact.write_bytes(artifact.read_bytes().replace(b"negative", b"tampered"))
    with pytest.raises(ValueError, match="content digest"):
        bind_positive_rows_to_orbit_artifact(artifact, positives, pair, orbit)
