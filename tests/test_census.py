"""Hand-checkable tests for M4 incidence coverage and artifacts."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from voronoi.cells import VoronoiCell
from voronoi.enumerate.census import (
    CertifiedCellRecord,
    CofacePairLayer,
    IncidenceShard,
    build_coface_pair_layer,
    build_coface_pair_task,
    build_incidence_shard,
    compare_coface_pairs_to_catalog,
    merge_incidence_shards,
    verify_noether_contract,
)
from voronoi.enumerate.census_engine import (
    CensusEngineTimeout,
    build_completion_batch_task,
    iter_candidate_artifact,
    iter_completion_batch_tasks,
    run_coface_pair_task,
    run_completion_batch_task,
    verify_candidate_artifact,
)
from voronoi.enumerate.completion_ledger import (
    run_completion_shard,
    run_orbit_completion_shard,
    verify_completion_shard,
    verify_orbit_completion_shard,
)
from voronoi.enumerate.orbit_reduction import (
    build_orbit_key_task,
    build_orbit_reduction_task,
    iter_orbit_representatives,
    run_orbit_key_task,
    run_orbit_reduction_task,
    verify_orbit_artifact,
)
from voronoi.parse import parse_list_shv_file

_DATA = (
    Path(__file__).parent.parent
    / "data"
    / "elbazvip-Voronoi-complexes-database"
    / "DATA_pari"
)


def _identity_cell(rank: int) -> VoronoiCell:
    return VoronoiCell.from_rows(
        [[int(i == j) for j in range(rank)] for i in range(rank)],
        expected_dimension=rank,
    )


def _small_catalogs() -> tuple[list[VoronoiCell], list[VoronoiCell]]:
    lower = [_identity_cell(3)]
    upper = [
        VoronoiCell.from_rows(
            [[1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 1, 0]],
            expected_dimension=4,
        ),
        VoronoiCell.from_rows(
            [[1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 1, 1]],
            expected_dimension=4,
        ),
    ]
    return lower, upper


def test_frozen_noether_contract_and_cell_evidence_round_trip() -> None:
    verify_noether_contract()
    cell = _identity_cell(3)
    record = CertifiedCellRecord.certify(cell)

    rebuilt = CertifiedCellRecord.from_payload(record.to_payload())

    assert rebuilt == record
    assert rebuilt.verify() == cell
    assert rebuilt.identifier == record.identifier


def test_incidence_shard_records_every_ray_orbit_terminally(tmp_path: Path) -> None:
    lower, upper = _small_catalogs()
    shard = build_incidence_shard(
        lower,
        upper[:1],
        lower_catalog_claim="hand-checked singleton",
        upper_catalog_claim="hand-checked singleton",
    )

    assert shard.relative_complete
    assert {outcome.status for outcome in shard.outcomes} == {
        "matched",
        "non_well_rounded",
    }
    assert sum(len(outcome.upper_ray_orbit) for outcome in shard.outcomes) == 4
    assert len(shard.incidences) == 1
    shard.verify(lower, upper[:1])

    path = tmp_path / "incidence-shard.json"
    shard.write(path)
    decoded = IncidenceShard.read(path)
    assert decoded == shard
    assert decoded.to_json() == shard.to_json()
    decoded.verify(lower, upper[:1])


def test_shard_merge_is_order_independent_and_requires_full_coverage() -> None:
    lower, upper = _small_catalogs()
    shards = [
        build_incidence_shard(
            lower,
            upper,
            lower_catalog_claim="hand-checked singleton",
            upper_catalog_claim="two hand-checked cells",
            shard_index=index,
            shard_count=2,
        )
        for index in range(2)
    ]

    forward = merge_incidence_shards(shards)
    reverse = merge_incidence_shards(reversed(shards))

    assert forward.identifier == reverse.identifier
    assert forward.to_json() == reverse.to_json()
    assert forward.relative_complete
    with pytest.raises(ValueError, match="missing"):
        merge_incidence_shards(shards[:1])


def test_artifact_tampering_is_rejected() -> None:
    lower, upper = _small_catalogs()
    shard = build_incidence_shard(
        lower,
        upper[:1],
        lower_catalog_claim="hand-checked singleton",
        upper_catalog_claim="hand-checked singleton",
    )
    payload = json.loads(shard.to_json())
    payload["specification_id"] = "sha256:not-the-content-hash"

    with pytest.raises(ValueError, match="hash"):
        IncidenceShard.from_json(json.dumps(payload))


def test_coface_pair_layer_is_exact_bounded_and_round_trips() -> None:
    lower, middle = _small_catalogs()
    incidence = build_incidence_shard(
        lower,
        middle,
        lower_catalog_claim="hand-checked singleton",
        upper_catalog_claim="two hand-checked cells",
    )

    pairs = build_coface_pair_layer(lower, middle, incidence)

    assert pairs.relative_complete
    assert pairs.raw_double_coset_count == (
        len(pairs.records) + pairs.diagonal_count + pairs.transpose_duplicate_count
    )
    assert pairs.records
    assert all(record.lower_index == 0 for record in pairs.records)
    assert all(record.double_coset_size > 0 for record in pairs.records)
    assert all(record.right_coset_count > 0 for record in pairs.records)
    decoded = CofacePairLayer.from_json(pairs.to_json())
    assert decoded == pairs
    assert decoded.identifier == pairs.identifier

    candidate_record = next(
        record for record in pairs.records if record.status == "candidate"
    )
    target = VoronoiCell.from_rows(
        candidate_record.candidate_vectors,
        expected_dimension=pairs.target_dimension,
    )
    report = compare_coface_pairs_to_catalog(pairs, [target])
    assert report.target_complete
    assert report.covered_target_indices == (0,)


def test_bounded_rust_coface_task_has_terminal_coverage(tmp_path: Path) -> None:
    engine_root = Path(__file__).parent.parent / "target"
    if not any(
        (engine_root / profile / "voronoi-census-engine").exists()
        for profile in ("release", "debug")
    ):
        pytest.skip("build voronoi-census-engine to run the subprocess boundary test")
    lower, middle = _small_catalogs()
    incidence = build_incidence_shard(
        lower,
        middle,
        lower_catalog_claim="hand-checked singleton",
        upper_catalog_claim="two hand-checked cells",
    )
    task = build_coface_pair_task(
        lower,
        middle,
        incidence,
        lower_index=0,
        candidate_cap=1,
        candidate_artifact_path=tmp_path / "candidates.jsonl",
    )
    assert len(task["cofaces"]) == len(incidence.incidences)

    report = run_coface_pair_task(
        task,
        memory_limit_bytes=512 * 1024**2,
        timeout_seconds=60,
    )

    assert report["raw_double_coset_count"] > 0
    assert report["candidate_aggregation_complete"]
    assert report["candidates"] == []
    assert report["candidate_artifact"]["distinct_candidate_count"] > 1

    artifact_path = Path(task["candidate_artifact_path"])
    verify_candidate_artifact(artifact_path, report)
    candidates = list(iter_candidate_artifact(artifact_path, report))
    assert len(candidates) == report["candidate_artifact"]["distinct_candidate_count"]
    completion_tasks = list(
        iter_completion_batch_tasks(
            artifact_path, report, max_iterations=20, batch_size=2
        )
    )
    assert sum(len(batch["candidates"]) for batch in completion_tasks) == len(
        candidates
    )

    keyed_path = tmp_path / "keyed.jsonl"
    key_report = run_orbit_key_task(
        build_orbit_key_task(
            artifact_path,
            report,
            keyed_path,
            buffer_cap=1,
        ),
        memory_limit_bytes=512 * 1024**2,
        timeout_seconds=60,
    )
    assert key_report["candidate_count"] == len(candidates)
    orbit_path = tmp_path / "orbits.jsonl"
    orbit_report = run_orbit_reduction_task(
        build_orbit_reduction_task(
            keyed_path,
            key_report,
            orbit_path,
            max_fingerprint_group_size=100,
        ),
        key_report,
        memory_limit_bytes=512 * 1024**2,
        timeout_seconds=60,
    )
    assert orbit_report["orbit_count"] < len(candidates)
    assert (
        orbit_report["duplicate_candidate_count"]
        == orbit_report["exact_equivalence_count"]
    )
    assert (
        len(
            list(
                iter_orbit_representatives(
                    orbit_path,
                    keyed_path,
                    key_report,
                    orbit_report,
                )
            )
        )
        == orbit_report["orbit_count"]
    )

    tampered_orbits = tmp_path / "tampered-orbits.jsonl"
    orbit_lines = orbit_path.read_text().splitlines()
    for index, line in enumerate(orbit_lines):
        orbit_record = json.loads(line)
        if orbit_record.get("equivalent_members"):
            transformation = orbit_record["equivalent_members"][0][
                "transformation_to_representative"
            ]
            transformation[0][0] = str(int(transformation[0][0]) + 1)
            orbit_lines[index] = json.dumps(
                orbit_record, sort_keys=True, separators=(",", ":")
            )
            break
    tampered_orbits.write_text("\n".join(orbit_lines) + "\n")
    with pytest.raises(ValueError, match="transformation"):
        verify_orbit_artifact(
            tampered_orbits,
            keyed_path,
            key_report,
            orbit_report,
        )

    orbit_workspace = tmp_path / "orbit-completion.sqlite"
    orbit_completion_path = tmp_path / "orbit-completion.jsonl"
    orbit_checkpoint = run_orbit_completion_shard(
        orbit_path,
        keyed_path,
        report,
        key_report,
        orbit_report,
        workspace_path=orbit_workspace,
        output_path=orbit_completion_path,
        shard_index=0,
        shard_count=2,
        batch_size=1,
        max_iterations=20,
        max_new_batches=1,
        memory_limit_bytes=512 * 1024**2,
        timeout_seconds=60,
    )
    assert not orbit_checkpoint["complete"]
    assert orbit_workspace.exists()
    assert not orbit_completion_path.exists()

    orbit_retry_audit = run_orbit_completion_shard(
        orbit_path,
        keyed_path,
        report,
        key_report,
        orbit_report,
        workspace_path=orbit_workspace,
        output_path=orbit_completion_path,
        shard_index=0,
        shard_count=2,
        batch_size=1,
        max_iterations=20,
        retry_unresolved_only=True,
        memory_limit_bytes=512 * 1024**2,
        timeout_seconds=60,
    )
    assert orbit_retry_audit["retry_unresolved_only"]
    assert orbit_retry_audit["new_batches"] == 0
    assert orbit_retry_audit["stored_results"] == 1

    orbit_audit = run_orbit_completion_shard(
        orbit_path,
        keyed_path,
        report,
        key_report,
        orbit_report,
        workspace_path=orbit_workspace,
        output_path=orbit_completion_path,
        shard_index=0,
        shard_count=2,
        batch_size=1,
        max_iterations=20,
        max_new_batches=0,
        memory_limit_bytes=512 * 1024**2,
        timeout_seconds=60,
    )
    assert not orbit_audit["complete"]
    assert orbit_audit["new_batches"] == 0
    assert orbit_audit["stored_results"] == 1

    orbit_resumed = run_orbit_completion_shard(
        orbit_path,
        keyed_path,
        report,
        key_report,
        orbit_report,
        workspace_path=orbit_workspace,
        output_path=orbit_completion_path,
        shard_index=0,
        shard_count=2,
        batch_size=1,
        max_iterations=20,
        memory_limit_bytes=512 * 1024**2,
        timeout_seconds=60,
    )
    assert orbit_resumed["complete"]
    assert (
        orbit_resumed["footer"]["record_count"]
        == (int(orbit_report["orbit_count"]) + 1) // 2
    )
    assert (
        verify_orbit_completion_shard(
            orbit_completion_path,
            orbit_path,
            keyed_path,
            report,
            key_report,
            orbit_report,
            shard_index=0,
            shard_count=2,
            batch_size=1,
        )
        == orbit_resumed["footer"]
    )
    orbit_completion_header = json.loads(
        orbit_completion_path.read_text().splitlines()[0]
    )
    assert (
        orbit_completion_header["completion_input_sha256"]
        == orbit_report["orbit_content_sha256"]
    )
    assert orbit_completion_header["candidate_count"] == str(
        orbit_report["orbit_count"]
    )
    assert orbit_completion_header["embedded_candidate_count"] == str(len(candidates))

    with pytest.raises(ValueError, match="transformation"):
        run_orbit_completion_shard(
            tampered_orbits,
            keyed_path,
            report,
            key_report,
            orbit_report,
            workspace_path=tmp_path / "tampered-orbit-completion.sqlite",
            output_path=tmp_path / "tampered-orbit-completion.jsonl",
            max_new_batches=1,
            memory_limit_bytes=512 * 1024**2,
            timeout_seconds=60,
        )
    assert not (tmp_path / "tampered-orbit-completion.sqlite").exists()

    completion_task = completion_tasks[0]
    completion = run_completion_batch_task(
        completion_task,
        memory_limit_bytes=512 * 1024**2,
        timeout_seconds=60,
    )
    assert len(completion["results"]) == len(completion_task["candidates"])
    assert completion["completed"] + completion["nonrealizable"] + completion[
        "inconclusive"
    ] == len(completion["results"])

    tampered = tmp_path / "tampered.jsonl"
    lines = artifact_path.read_text().splitlines()
    record = json.loads(lines[1])
    record["occurrence_count"] += 1
    lines[1] = json.dumps(record, sort_keys=True, separators=(",", ":"))
    tampered.write_text("\n".join(lines) + "\n")
    with pytest.raises(ValueError, match="coverage disagrees"):
        verify_candidate_artifact(tampered, report)

    workspace = tmp_path / "completion.sqlite"
    completion_path = tmp_path / "completion.jsonl"
    checkpoint = run_completion_shard(
        artifact_path,
        report,
        workspace_path=workspace,
        output_path=completion_path,
        batch_size=1,
        max_iterations=20,
        max_new_batches=1,
        memory_limit_bytes=512 * 1024**2,
        timeout_seconds=60,
    )
    assert not checkpoint["complete"]
    assert workspace.exists()
    assert not completion_path.exists()

    resumed = run_completion_shard(
        artifact_path,
        report,
        workspace_path=workspace,
        output_path=completion_path,
        batch_size=1,
        max_iterations=20,
        memory_limit_bytes=512 * 1024**2,
        timeout_seconds=60,
    )
    assert resumed["complete"]
    assert resumed["footer"]["record_count"] == len(candidates)
    assert (
        verify_completion_shard(
            completion_path,
            report,
            batch_size=1,
        )
        == resumed["footer"]
    )

    call_log = tmp_path / "fake-completion-calls.jsonl"
    upgrade_engine = tmp_path / "upgrade-engine"
    first_candidate_id = str(candidates[0]["candidate_id"])
    upgrade_engine.write_text(
        "#!/usr/bin/env python3\n"
        "import hashlib\n"
        "import json\n"
        "import pathlib\n"
        "import sys\n"
        "if sys.argv[1:] == ['--version']:\n"
        "    print(json.dumps({'type': 'voronoi/census-engine-runtime@1', 'noether_version': '0.3.2'}))\n"
        "    sys.exit(0)\n"
        "task = json.load(sys.stdin)\n"
        "limit = task['max_iterations']\n"
        "results = []\n"
        "for candidate in task['candidates']:\n"
        f"    with pathlib.Path({str(call_log)!r}).open('a') as log:\n"
        "        log.write(json.dumps(candidate['candidate_id']) + '\\n')\n"
        f"    completed = candidate['candidate_id'] == {first_candidate_id!r} or limit >= 2\n"
        "    status = 'completed' if completed else 'inconclusive'\n"
        "    evidence = json.dumps(['test-evidence', candidate['candidate_id'], limit], separators=(',', ':'))\n"
        "    results.append({'candidate_id': candidate['candidate_id'], 'status': status, 'detail': None if completed else 'test work limit', 'evidence_sha256': hashlib.sha256(evidence.encode()).hexdigest(), 'evidence_canonical_json': evidence, 'completed_vectors': candidate['vectors'] if completed else None})\n"
        "payload = {'type': 'voronoi/completion-batch-report@3', 'noether_contract': task['noether_contract'], 'strategy': task['strategy'], 'max_iterations': limit, 'results': results, 'completed': sum(row['status'] == 'completed' for row in results), 'nonrealizable': 0, 'inconclusive': sum(row['status'] == 'inconclusive' for row in results)}\n"
        "json.dump(payload, sys.stdout, separators=(',', ':'))\n"
    )
    upgrade_engine.chmod(0o755)

    retry_only_workspace = tmp_path / "retry-only.sqlite"
    retry_only_path = tmp_path / "retry-only.jsonl"
    retry_seed = run_completion_shard(
        artifact_path,
        report,
        workspace_path=retry_only_workspace,
        output_path=retry_only_path,
        batch_size=1,
        max_iterations=1,
        max_new_batches=2,
        engine=upgrade_engine,
        memory_limit_bytes=128 * 1024**2,
        timeout_seconds=5,
    )
    assert retry_seed["stored_results"] == 2
    retry_calls_before = call_log.read_text().splitlines()
    retry_only = run_completion_shard(
        artifact_path,
        report,
        workspace_path=retry_only_workspace,
        output_path=retry_only_path,
        batch_size=1,
        max_iterations=2,
        retry_unresolved_only=True,
        engine=upgrade_engine,
        memory_limit_bytes=128 * 1024**2,
        timeout_seconds=5,
    )
    retry_calls_after = call_log.read_text().splitlines()
    assert retry_only["retry_unresolved_only"]
    assert retry_only["new_batches"] == 1
    assert retry_only["stored_results"] == 2
    assert len(retry_calls_after) == len(retry_calls_before) + 1
    assert json.loads(retry_calls_after[-1]) == str(candidates[1]["candidate_id"])
    assert not retry_only_path.exists()
    call_log.unlink()

    upgrade_workspace = tmp_path / "upgrade.sqlite"
    upgrade_path = tmp_path / "upgrade.jsonl"
    first_pass = run_completion_shard(
        artifact_path,
        report,
        workspace_path=upgrade_workspace,
        output_path=upgrade_path,
        batch_size=1,
        max_iterations=1,
        engine=upgrade_engine,
        memory_limit_bytes=128 * 1024**2,
        timeout_seconds=5,
    )
    assert not first_pass["complete"]
    assert first_pass["inconclusive_results"] == len(candidates) - 1
    assert not upgrade_path.exists()

    upgraded = run_completion_shard(
        artifact_path,
        report,
        workspace_path=upgrade_workspace,
        output_path=upgrade_path,
        batch_size=1,
        max_iterations=2,
        engine=upgrade_engine,
        memory_limit_bytes=128 * 1024**2,
        timeout_seconds=5,
    )
    assert upgraded["complete"]
    call_ids = [json.loads(line) for line in call_log.read_text().splitlines()]
    assert call_ids.count(first_candidate_id) == 1
    assert all(call_ids.count(str(row["candidate_id"])) == 2 for row in candidates[1:])


@pytest.mark.parametrize("version_probe", [False, True], ids=["completion", "version-probe"])
def test_completion_timeout_kills_solver_descendants(
    tmp_path: Path, monkeypatch, version_probe: bool
) -> None:
    from voronoi import runtime

    if version_probe:
        monkeypatch.setattr(runtime, "ENGINE_VERSION_TIMEOUT_SECONDS", 0.5)
    child_pid_path = tmp_path / "child.pid"
    engine = tmp_path / "hanging-engine"
    engine.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        "import pathlib\n"
        "import subprocess\n"
        "import sys\n"
        f"if not {version_probe!r} and sys.argv[1:] == ['--version']:\n"
        "    print(json.dumps({'type': 'voronoi/census-engine-runtime@1', 'noether_version': '0.3.2'}))\n"
        "    sys.exit(0)\n"
        "child = subprocess.Popen(['sleep', '600'])\n"
        f"pathlib.Path({str(child_pid_path)!r}).write_text(str(child.pid))\n"
        "child.wait()\n"
    )
    engine.chmod(0o755)
    task = build_completion_batch_task(
        [{"candidate_id": "test-candidate", "vectors": [[1]]}],
        max_iterations=1,
    )

    expected_error = RuntimeError if version_probe else CensusEngineTimeout
    message = "Cannot identify census worker" if version_probe else "exceeded"
    with pytest.raises(expected_error, match=message):
        run_completion_batch_task(
            task,
            engine=engine,
            memory_limit_bytes=128 * 1024**2,
            timeout_seconds=1,
        )

    child_pid = int(child_pid_path.read_text())
    process_stat = Path(f"/proc/{child_pid}/stat")
    for _ in range(100):
        try:
            state = process_stat.read_text().split()[2]
        except (FileNotFoundError, ProcessLookupError):
            break
        if state == "Z":
            break
        time.sleep(0.01)
    else:
        pytest.fail("the timed-out engine left its solver descendant running")


@pytest.mark.slow
@pytest.mark.skipif(
    os.environ.get("VORONOI_RUN_CENSUS_REGRESSION") != "1",
    reason="set VORONOI_RUN_CENSUS_REGRESSION=1 for the full N=8 incidence pass",
)
@pytest.mark.corpus
def test_published_n8_r8_r9_incidence_baseline() -> None:
    lower_path = _DATA / "ListSHV_n8_rank8"
    upper_path = _DATA / "ListSHV_n8_rank9"
    if not lower_path.exists() or not upper_path.exists():
        pytest.skip("published N=8 catalogs not fetched")
    lower = parse_list_shv_file(lower_path)
    upper = parse_list_shv_file(upper_path)

    shard = build_incidence_shard(
        lower,
        upper,
        lower_catalog_claim="DSEKM19 published orbit catalog (13)",
        upper_catalog_claim="DSEKM19 published orbit catalog (106)",
    )

    assert len(shard.outcomes) == 345
    assert len(shard.incidences) == 255
    assert sum(outcome.status == "non_well_rounded" for outcome in shard.outcomes) == 90
    assert {record.lower_index for record in shard.incidences} == set(range(13))
