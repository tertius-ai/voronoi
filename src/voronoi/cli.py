"""Census stage commands and runtime verification."""

from __future__ import annotations

import argparse
import json
import os
import resource
import sys
from pathlib import Path
from typing import Any


def _cmd_doctor(args: argparse.Namespace) -> int:
    """Check the installed release and the independently built census worker."""

    import noether

    from voronoi.enumerate.census import verify_pair_noether_contract
    from voronoi.enumerate.census_engine import _engine_path
    from voronoi.runtime import census_engine_runtime

    verify_pair_noether_contract()
    engine = _engine_path(args.engine)
    print(
        json.dumps(
            {
                "noether_version": noether.__version__,
                "noether_python": noether.__file__,
                "census_engine": str(engine.resolve()),
                "census_engine_runtime": census_engine_runtime(engine),
                "semantic_contract": "verified",
            },
            sort_keys=True,
        )
    )
    return 0


def _write_json_noclobber(path: Path, payload: Any) -> None:
    """Durably publish compact JSON without replacing prior evidence."""

    temporary = path.with_name(f".{path.name}.partial-{os.getpid()}")
    try:
        with temporary.open("x", encoding="utf-8") as output:
            json.dump(payload, output, sort_keys=True, separators=(",", ":"))
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _cmd_census_pairs(args: argparse.Namespace) -> int:
    """Build one exact, disk-backed lower-cell pair-orbit artifact."""

    from voronoi.enumerate.census import (
        build_coface_pair_task,
        build_incidence_shard,
    )
    from voronoi.enumerate.census_engine import run_coface_pair_task
    from voronoi.parse import parse_list_shv_file

    if args.memory_gib <= 0 or args.timeout_seconds <= 0:
        raise ValueError("memory and timeout limits must be positive")
    memory_limit_bytes = args.memory_gib * 1024**3
    resource.setrlimit(resource.RLIMIT_AS, (memory_limit_bytes, memory_limit_bytes))
    data_dir = args.data_dir.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"lower-{args.lower_index:03d}"
    artifact_path = output_dir / f"{stem}-candidates.jsonl"
    report_path = output_dir / f"{stem}-report.json"
    existing = [path for path in (artifact_path, report_path) if path.exists()]
    if existing:
        rendered = ", ".join(str(path) for path in existing)
        raise FileExistsError(
            f"refusing to replace existing census evidence: {rendered}"
        )

    lower_path = data_dir / f"ListSHV_n{args.N}_rank{args.lower_dimension}"
    middle_path = data_dir / f"ListSHV_n{args.N}_rank{args.lower_dimension + 1}"
    lower = parse_list_shv_file(lower_path)
    middle = parse_list_shv_file(middle_path)
    incidence = build_incidence_shard(
        lower,
        middle,
        lower_catalog_claim=f"published N={args.N},r={args.lower_dimension} catalog",
        upper_catalog_claim=(
            f"published N={args.N},r={args.lower_dimension + 1} catalog"
        ),
    )
    task = build_coface_pair_task(
        lower,
        middle,
        incidence,
        lower_index=args.lower_index,
        candidate_cap=args.candidate_buffer_cap,
        candidate_artifact_path=artifact_path,
    )
    report = run_coface_pair_task(
        task,
        memory_limit_bytes=memory_limit_bytes,
        timeout_seconds=args.timeout_seconds,
    )
    _write_json_noclobber(report_path, report)
    summary = report["candidate_artifact"]
    print(
        json.dumps(
            {
                "artifact": str(artifact_path),
                "report": str(report_path),
                "input_sha256": report["input_sha256"],
                "event_stream_sha256": report["event_stream_sha256"],
                "raw_double_cosets": report["raw_double_coset_count"],
                "distinct_candidates": summary["distinct_candidate_count"],
                "candidate_occurrences": summary["candidate_occurrence_count"],
            },
            sort_keys=True,
        )
    )
    return 0


def _cmd_census_complete(args: argparse.Namespace) -> int:
    """Resume one transactional shard of candidate completion."""

    from voronoi.enumerate.completion_ledger import run_completion_shard

    if args.memory_gib <= 0 or args.timeout_seconds <= 0:
        raise ValueError("memory and timeout limits must be positive")
    memory_limit_bytes = args.memory_gib * 1024**3
    resource.setrlimit(resource.RLIMIT_AS, (memory_limit_bytes, memory_limit_bytes))
    candidate_path = args.candidate_artifact.expanduser().resolve()
    report_path = args.pair_report.expanduser().resolve()
    with report_path.open(encoding="utf-8") as source:
        pair_report = json.load(source)
    strategy = args.strategy
    if strategy == "auto":
        strategy = (
            "exact_shell"
            if int(pair_report["target_dimension"])
            <= int(pair_report["ambient_rank"]) + 2
            else "fixed_rank"
        )
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"completion-{args.shard_index:05d}-of-{args.shard_count:05d}"
    workspace_path = output_dir / f".{stem}.sqlite"
    output_path = output_dir / f"{stem}.jsonl"
    result = run_completion_shard(
        candidate_path,
        pair_report,
        workspace_path=workspace_path,
        output_path=output_path,
        shard_index=args.shard_index,
        shard_count=args.shard_count,
        batch_size=args.batch_size,
        max_iterations=args.max_iterations,
        strategy=strategy,
        max_new_batches=args.max_new_batches,
        retry_timeouts=args.retry_timeouts,
        retry_unresolved_only=args.retry_unresolved_only,
        memory_limit_bytes=memory_limit_bytes,
        timeout_seconds=args.timeout_seconds,
    )
    print(
        json.dumps(
            {
                **result,
                "workspace": str(workspace_path),
                "output": str(output_path) if output_path.exists() else None,
                "strategy": strategy,
            },
            sort_keys=True,
        )
    )
    return 0


def _cmd_census_complete_orbits(args: argparse.Namespace) -> int:
    """Resume one transactional shard of verified orbit representatives."""

    from voronoi.enumerate.completion_ledger import run_orbit_completion_shard

    if args.memory_gib <= 0 or args.timeout_seconds <= 0:
        raise ValueError("memory and timeout limits must be positive")
    memory_limit_bytes = args.memory_gib * 1024**3
    resource.setrlimit(resource.RLIMIT_AS, (memory_limit_bytes, memory_limit_bytes))
    orbit_path = args.orbit_artifact.expanduser().resolve()
    keyed_path = args.keyed_artifact.expanduser().resolve()
    with args.pair_report.expanduser().resolve().open(encoding="utf-8") as source:
        pair_report = json.load(source)
    with args.key_report.expanduser().resolve().open(encoding="utf-8") as source:
        key_report = json.load(source)
    with args.orbit_report.expanduser().resolve().open(encoding="utf-8") as source:
        orbit_report = json.load(source)
    strategy = args.strategy
    if strategy == "auto":
        strategy = (
            "exact_shell"
            if int(pair_report["target_dimension"])
            <= int(pair_report["ambient_rank"]) + 2
            else "fixed_rank"
        )
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"completion-{args.shard_index:05d}-of-{args.shard_count:05d}"
    workspace_path = output_dir / f".{stem}.sqlite"
    output_path = output_dir / f"{stem}.jsonl"
    result = run_orbit_completion_shard(
        orbit_path,
        keyed_path,
        pair_report,
        key_report,
        orbit_report,
        workspace_path=workspace_path,
        output_path=output_path,
        shard_index=args.shard_index,
        shard_count=args.shard_count,
        batch_size=args.batch_size,
        max_iterations=args.max_iterations,
        strategy=strategy,
        max_new_batches=args.max_new_batches,
        retry_timeouts=args.retry_timeouts,
        retry_unresolved_only=args.retry_unresolved_only,
        memory_limit_bytes=memory_limit_bytes,
        timeout_seconds=args.timeout_seconds,
    )
    print(
        json.dumps(
            {
                **result,
                "workspace": str(workspace_path),
                "output": str(output_path) if output_path.exists() else None,
                "strategy": strategy,
                "completion_input": "orbit_representatives",
                "orbit_content_sha256": orbit_report["orbit_content_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


def _cmd_census_orbit_key(args: argparse.Namespace) -> int:
    """Build the externally sorted exact-invariant partition."""

    from voronoi.enumerate.orbit_reduction import (
        build_orbit_key_task,
        run_orbit_key_task,
    )

    if args.memory_gib <= 0 or args.timeout_seconds <= 0:
        raise ValueError("memory and timeout limits must be positive")
    memory_limit_bytes = args.memory_gib * 1024**3
    resource.setrlimit(resource.RLIMIT_AS, (memory_limit_bytes, memory_limit_bytes))
    candidate_path = args.candidate_artifact.expanduser().resolve()
    with args.pair_report.expanduser().resolve().open(encoding="utf-8") as source:
        pair_report = json.load(source)
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = candidate_path.name.removesuffix("-candidates.jsonl")
    keyed_path = output_dir / f"{stem}-keyed.jsonl"
    report_path = output_dir / f"{stem}-orbit-key-report.json"
    if keyed_path.exists() or report_path.exists():
        raise FileExistsError("refusing to replace existing orbit-key evidence")
    task = build_orbit_key_task(
        candidate_path,
        pair_report,
        keyed_path,
        buffer_cap=args.buffer_cap,
    )
    report = run_orbit_key_task(
        task,
        memory_limit_bytes=memory_limit_bytes,
        timeout_seconds=args.timeout_seconds,
    )
    _write_json_noclobber(report_path, report)
    print(json.dumps({**report, "report": str(report_path)}, sort_keys=True))
    return 0


def _cmd_census_orbits(args: argparse.Namespace) -> int:
    """Resolve invariant collisions with verified unimodular equivalences."""

    from voronoi.enumerate.orbit_reduction import (
        build_orbit_reduction_task,
        run_orbit_reduction_task,
    )

    if args.memory_gib <= 0 or args.timeout_seconds <= 0:
        raise ValueError("memory and timeout limits must be positive")
    memory_limit_bytes = args.memory_gib * 1024**3
    resource.setrlimit(resource.RLIMIT_AS, (memory_limit_bytes, memory_limit_bytes))
    keyed_path = args.keyed_artifact.expanduser().resolve()
    with args.key_report.expanduser().resolve().open(encoding="utf-8") as source:
        key_report = json.load(source)
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = keyed_path.name.removesuffix("-keyed.jsonl")
    orbit_path = output_dir / f"{stem}-orbits.jsonl"
    report_path = output_dir / f"{stem}-orbit-report.json"
    if orbit_path.exists() or report_path.exists():
        raise FileExistsError("refusing to replace existing orbit-reduction evidence")
    task = build_orbit_reduction_task(
        keyed_path,
        key_report,
        orbit_path,
        max_fingerprint_group_size=args.max_fingerprint_group_size,
    )
    report = run_orbit_reduction_task(
        task,
        key_report,
        memory_limit_bytes=memory_limit_bytes,
        timeout_seconds=args.timeout_seconds,
    )
    _write_json_noclobber(report_path, report)
    print(json.dumps({**report, "report": str(report_path)}, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="voronoi")
    sub = p.add_subparsers(dest="cmd", required=True)

    doctor = sub.add_parser("doctor", help="check Noether 0.3.2 and the census worker")
    doctor.add_argument("--engine", type=Path)
    doctor.set_defaults(func=_cmd_doctor)

    c = sub.add_parser(
        "census-pairs", help="build one bounded disk-backed coface-pair artifact"
    )
    c.add_argument("--N", type=int, required=True, help="ambient lattice rank")
    c.add_argument("--lower-dimension", type=int, required=True)
    c.add_argument("--lower-index", type=int, required=True)
    c.add_argument("--output-dir", type=Path, required=True)
    c.add_argument(
        "--data-dir",
        type=Path,
        default=Path(__file__).resolve().parents[2]
        / "data"
        / "elbazvip-Voronoi-complexes-database"
        / "DATA_pari",
    )
    c.add_argument("--candidate-buffer-cap", type=int, default=100_000)
    c.add_argument("--memory-gib", type=int, default=4)
    c.add_argument("--timeout-seconds", type=int, default=30 * 60)
    c.set_defaults(func=_cmd_census_pairs)

    cc = sub.add_parser(
        "census-complete", help="resume one process-isolated completion shard"
    )
    cc.add_argument("--candidate-artifact", type=Path, required=True)
    cc.add_argument("--pair-report", type=Path, required=True)
    cc.add_argument("--output-dir", type=Path, required=True)
    cc.add_argument("--shard-index", type=int, default=0)
    cc.add_argument("--shard-count", type=int, default=1)
    cc.add_argument("--batch-size", type=int, default=1)
    cc.add_argument("--max-iterations", type=int, default=50)
    cc.add_argument(
        "--strategy",
        choices=("auto", "exact_shell", "fixed_rank"),
        default="auto",
    )
    cc.add_argument("--max-new-batches", type=int)
    cc.add_argument(
        "--retry-timeouts",
        action="store_true",
        help="retry recorded execution timeouts instead of leaving them unresolved",
    )
    cc.add_argument(
        "--retry-unresolved-only",
        action="store_true",
        help="skip fresh candidates and revisit only timeouts or weaker checkpoints",
    )
    cc.add_argument("--memory-gib", type=int, default=4)
    cc.add_argument("--timeout-seconds", type=int, default=30 * 60)
    cc.set_defaults(func=_cmd_census_complete)

    co = sub.add_parser(
        "census-complete-orbits",
        help="resume completion over verified exact orbit representatives",
    )
    co.add_argument("--orbit-artifact", type=Path, required=True)
    co.add_argument("--keyed-artifact", type=Path, required=True)
    co.add_argument("--pair-report", type=Path, required=True)
    co.add_argument("--key-report", type=Path, required=True)
    co.add_argument("--orbit-report", type=Path, required=True)
    co.add_argument("--output-dir", type=Path, required=True)
    co.add_argument("--shard-index", type=int, default=0)
    co.add_argument("--shard-count", type=int, default=1)
    co.add_argument("--batch-size", type=int, default=1)
    co.add_argument("--max-iterations", type=int, default=50)
    co.add_argument(
        "--strategy",
        choices=("auto", "exact_shell", "fixed_rank"),
        default="auto",
    )
    co.add_argument("--max-new-batches", type=int)
    co.add_argument(
        "--retry-timeouts",
        action="store_true",
        help="retry recorded execution timeouts instead of leaving them unresolved",
    )
    co.add_argument(
        "--retry-unresolved-only",
        action="store_true",
        help="skip fresh candidates and revisit only timeouts or weaker checkpoints",
    )
    co.add_argument("--memory-gib", type=int, default=4)
    co.add_argument("--timeout-seconds", type=int, default=30 * 60)
    co.set_defaults(func=_cmd_census_complete_orbits)

    ok = sub.add_parser(
        "census-orbit-key",
        help="partition a candidate artifact by an exact orbit invariant",
    )
    ok.add_argument("--candidate-artifact", type=Path, required=True)
    ok.add_argument("--pair-report", type=Path, required=True)
    ok.add_argument("--output-dir", type=Path, required=True)
    ok.add_argument("--buffer-cap", type=int, default=50_000)
    ok.add_argument("--memory-gib", type=int, default=4)
    ok.add_argument("--timeout-seconds", type=int, default=2 * 60 * 60)
    ok.set_defaults(func=_cmd_census_orbit_key)

    oo = sub.add_parser(
        "census-orbits",
        help="resolve keyed candidates into verified GL_N(Z) orbits",
    )
    oo.add_argument("--keyed-artifact", type=Path, required=True)
    oo.add_argument("--key-report", type=Path, required=True)
    oo.add_argument("--output-dir", type=Path, required=True)
    oo.add_argument("--max-fingerprint-group-size", type=int, default=10_000)
    oo.add_argument("--memory-gib", type=int, default=4)
    oo.add_argument("--timeout-seconds", type=int, default=2 * 60 * 60)
    oo.set_defaults(func=_cmd_census_orbits)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
