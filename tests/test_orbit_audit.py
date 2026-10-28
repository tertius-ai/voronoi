"""Replay synthetic exact orbit partitions, including genuine invariant collisions."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from voronoi.cells import VoronoiCell
from voronoi.enumerate.census_engine import (
    ENGINE_NOETHER_CONTRACT,
    _candidate_identifier,
)
from voronoi.enumerate.orbit_audit import build_orbit_audit_task, run_orbit_audit_task
from voronoi.enumerate.orbit_reduction import (
    build_orbit_key_task,
    build_orbit_reduction_task,
    run_orbit_key_task,
    run_orbit_reduction_task,
)


def _write_artifact(path: Path, records: list[dict]) -> str:
    body = b"".join(
        (json.dumps(row, separators=(",", ":")) + "\n").encode() for row in records[:-1]
    )
    digest = hashlib.sha256(body).hexdigest()
    records[-1]["content_sha256"] = digest
    path.write_bytes(body + (json.dumps(records[-1]) + "\n").encode())
    return digest


@pytest.fixture
def partition(tmp_path: Path) -> tuple[dict, Path, Path]:
    # These are abstract candidate configurations, not a claimed census slice.
    # The two index-11 bases have the same minor fingerprint but are inequivalent.
    rows = [
        [[1, 0], [0, 1]],
        [[1, 1], [1, 2]],
        [[1, 0], [1, 11]],
        [[1, 0], [2, 11]],
    ]
    configurations = sorted(
        [list(v) for v in VoronoiCell.from_rows(r).min_vectors] for r in rows
    )
    common = {
        "noether_contract": dict(ENGINE_NOETHER_CONTRACT),
        "lower_index": 0,
        "ambient_rank": 2,
        "target_dimension": 2,
        "input_sha256": "0" * 64,
        "event_stream_sha256": "1" * 64,
    }
    records = [{"type": "voronoi/embedded-candidate-artifact@1", **common}]
    for index, vectors in enumerate(configurations):
        records.append(
            {
                "type": "voronoi/embedded-candidate-record@1",
                "candidate_id": _candidate_identifier(vectors),
                "vectors": vectors,
                "occurrence_count": 1,
                "first_event_index": index + 1,
                "witness_left_incidence_id": "synthetic-left",
                "witness_right_incidence_id": "synthetic-right",
                "witness_representative": [0, 1],
            }
        )
    records.append(
        {
            "type": "voronoi/embedded-candidate-footer@1",
            "distinct_candidate_count": 4,
            "candidate_occurrence_count": 4,
        }
    )
    candidates, keyed, orbits = [
        tmp_path / name for name in ["candidates.jsonl", "keyed.jsonl", "orbits.jsonl"]
    ]
    digest = _write_artifact(candidates, records)
    pair = {
        "type": "voronoi/coface-pair-rank-report@2",
        **common,
        "candidate_artifact": {
            "type": "voronoi/embedded-candidate-summary@1",
            "content_sha256": digest,
            "distinct_candidate_count": 4,
            "candidate_occurrence_count": 4,
        },
    }
    key = run_orbit_key_task(build_orbit_key_task(candidates, pair, keyed))
    orbit = run_orbit_reduction_task(
        build_orbit_reduction_task(keyed, key, orbits), key
    )
    for name, value in [
        ("pair-report.json", pair),
        ("key-report.json", key),
        ("orbit-report.json", orbit),
    ]:
        (tmp_path / name).write_text(json.dumps(value))
    return build_orbit_audit_task(keyed, orbits, pair, key, orbit), keyed, orbits


def test_native_audit_checks_transports_and_collision_classes_without_writes(
    partition,
) -> None:
    task, keyed, orbits = partition
    before = [path.read_bytes() for path in (keyed, orbits)]
    report = run_orbit_audit_task(task)
    assert report["candidate_count"] == 4
    assert report["orbit_count"] == 3
    assert report["fingerprint_group_count"] == 2
    assert report["exact_transports_replayed"] == 1
    assert report["representative_fingerprints_recomputed"] == 3
    assert report["representative_inequivalence_checks"] == 1
    assert before == [path.read_bytes() for path in (keyed, orbits)]


def test_cli_retains_the_audit_task_and_refuses_to_replace_evidence(partition) -> None:
    from voronoi.cli import main

    _, keyed, orbits = partition
    directory = keyed.parent
    output = directory / "audit-report.json"
    arguments = [
        "census-audit-orbits",
        "--keyed-artifact",
        str(keyed),
        "--orbit-artifact",
        str(orbits),
        "--pair-report",
        str(directory / "pair-report.json"),
        "--key-report",
        str(directory / "key-report.json"),
        "--orbit-report",
        str(directory / "orbit-report.json"),
        "--output-report",
        str(output),
    ]
    assert main(arguments) == 0
    saved = json.loads(output.read_text())
    assert saved["type"] == "voronoi/orbit-audit-run@1"
    assert saved["task"]["orbit_artifact_path"] == str(orbits)
    assert saved["report"]["exact_transports_replayed"] == 1
    before = output.read_bytes()
    with pytest.raises(FileExistsError):
        main(arguments)
    assert output.read_bytes() == before


@pytest.mark.parametrize(
    "change", ["permutation", "transformation", "provenance", "split"]
)
def test_native_audit_rejects_false_evidence_even_with_updated_digests(
    partition, change
) -> None:
    task, _, path = partition
    task = copy.deepcopy(task)
    records = [json.loads(line) for line in path.read_text().splitlines()]
    orbit = next(record for record in records[1:-1] if record["equivalent_members"])
    member = orbit["equivalent_members"][0]
    if change == "permutation":
        member["line_permutation"].reverse()
        error = "line permutation"
    elif change == "transformation":
        member["transformation_to_representative"][0] = ["0", "0"]
        error = "transformation"
    elif change == "provenance":
        member["candidate"]["first_event_index"] += 1
        error = "keyed provenance"
    else:
        extra = {
            **copy.deepcopy(orbit),
            "representative": member["candidate"],
            "equivalent_members": [],
            "member_count": 1,
            "candidate_occurrence_count": 1,
        }
        orbit.update(
            equivalent_members=[], member_count=1, candidate_occurrence_count=1
        )
        records.insert(-1, extra)
        records[1:-1] = sorted(
            records[1:-1],
            key=lambda row: (
                row["fingerprint_sha256"],
                row["representative"]["vectors"],
            ),
        )
        records[-1].update(
            orbit_count=4, duplicate_candidate_count=0, exact_equivalence_count=0
        )
        task.update(orbit_count=4, exact_equivalence_count=0)
        error = "equivalent representatives split"
    task["orbit_content_sha256"] = _write_artifact(path, records)
    with pytest.raises(RuntimeError, match=error):
        run_orbit_audit_task(task)


def test_native_audit_recomputes_fingerprints_instead_of_trusting_labels(
    partition,
) -> None:
    task, keyed, orbits = partition
    key_rows = [json.loads(line) for line in keyed.read_text().splitlines()]
    orbit_rows = [json.loads(line) for line in orbits.read_text().splitlines()]
    first = key_rows[1]["fingerprint_sha256"]
    for rows in [key_rows, orbit_rows]:
        for row in rows[1:-1]:
            if row["fingerprint_sha256"] == first:
                row["fingerprint_sha256"] = "0" * 64
    task["keyed_content_sha256"] = _write_artifact(keyed, key_rows)
    orbit_rows[0]["keyed_content_sha256"] = task["keyed_content_sha256"]
    task["orbit_content_sha256"] = _write_artifact(orbits, orbit_rows)
    with pytest.raises(RuntimeError, match="wrong equivalence fingerprint"):
        run_orbit_audit_task(task)
