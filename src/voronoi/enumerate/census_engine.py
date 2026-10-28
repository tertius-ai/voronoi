"""Bounded subprocess boundary for the Rust coface-pair census engine."""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import signal
import subprocess
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from noether import Z
from noether.groups import DoubleCoset, Permutation
from noether.linalg import (
    IntegralLineConfiguration,
    Lattice,
    Matrix,
    MinimumCompletion,
    MinimumCompletionCertificate,
    MinimumRealization,
)

from voronoi.runtime import census_engine_runtime

DEFAULT_MEMORY_LIMIT_BYTES = 4 * 1024**3
DEFAULT_TIMEOUT_SECONDS = 30 * 60
REPORT_SCHEMA = "voronoi/coface-pair-rank-report@2"
COMPLETION_TASK_SCHEMA = "voronoi/completion-batch-task@2"
COMPLETION_REPORT_SCHEMA = "voronoi/completion-batch-report@4"
CANDIDATE_ARTIFACT_SCHEMA = "voronoi/embedded-candidate-artifact@1"
CANDIDATE_RECORD_SCHEMA = "voronoi/embedded-candidate-record@1"
CANDIDATE_FOOTER_SCHEMA = "voronoi/embedded-candidate-footer@1"
CANDIDATE_SUMMARY_SCHEMA = "voronoi/embedded-candidate-summary@1"
MAX_CANDIDATE_CAP = 100_000
MAX_COMPLETION_BATCH_SIZE = 10
ENGINE_NOETHER_CONTRACT: Mapping[str, str] = {
    "DoubleCoset": DoubleCoset.type_id,
    "IntegralLineConfiguration": IntegralLineConfiguration.type_id,
    "MinimumCompletion": MinimumCompletion.type_id,
    "MinimumCompletionCertificate": MinimumCompletionCertificate.type_id,
    "Permutation": Permutation.type_id,
}
COMPLETION_NOETHER_CONTRACT: Mapping[str, str] = {
    **ENGINE_NOETHER_CONTRACT,
    "MinimumRealization": MinimumRealization.type_id,
}
CompletionStrategy = Literal["fixed_rank", "exact_shell"]


class CensusEngineTimeout(RuntimeError):
    """A subprocess work limit, never a mathematical completion verdict."""


def _engine_path(explicit: Path | None) -> Path:
    if explicit is not None:
        candidates = [explicit]
    elif configured := os.environ.get("VORONOI_CENSUS_ENGINE"):
        candidates = [Path(configured)]
    else:
        root = Path(__file__).resolve().parents[3]
        candidates = [
            root / "target" / "release" / "voronoi-census-engine",
            root / "target" / "debug" / "voronoi-census-engine",
        ]
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            census_engine_runtime(candidate)
            return candidate
    rendered = ", ".join(str(candidate) for candidate in candidates)
    raise RuntimeError(
        "the bounded Voronoi census engine is not built; tried "
        f"{rendered}. Run `cargo build -p voronoi-census-engine --release` "
        "from the Voronoi repository or set VORONOI_CENSUS_ENGINE."
    )


def _verify_report(payload: Mapping[str, Any]) -> None:
    if payload.get("type") != REPORT_SCHEMA:
        raise RuntimeError("the census engine returned an unsupported report schema")
    if payload.get("noether_contract") != dict(ENGINE_NOETHER_CONTRACT):
        raise RuntimeError("the census engine returned a different Noether contract")
    input_sha256 = payload.get("input_sha256")
    if (
        not isinstance(input_sha256, str)
        or len(input_sha256) != 64
        or any(character not in "0123456789abcdef" for character in input_sha256)
    ):
        raise RuntimeError("the census engine returned an invalid input digest")
    pairs = payload.get("pairs")
    if not isinstance(pairs, list):
        raise TypeError("the census engine report omitted pair summaries")
    raw = 0
    candidates = 0
    for pair in pairs:
        if not isinstance(pair, dict):
            raise TypeError("the census engine returned a malformed pair summary")
        pair_raw = int(pair["raw_double_cosets"])
        terminal = sum(
            int(pair[key])
            for key in (
                "diagonal",
                "transpose_duplicates",
                "duplicate_line",
                "wrong_dimension",
                "candidate_occurrences",
            )
        )
        if pair_raw != terminal:
            raise RuntimeError("a census-engine pair summary lacks terminal coverage")
        raw += pair_raw
        candidates += int(pair["candidate_occurrences"])
    if raw != int(payload["raw_double_coset_count"]):
        raise RuntimeError("the census-engine raw coverage count does not balance")
    retained = sum(
        int(candidate["occurrence_count"]) for candidate in payload["candidates"]
    )
    overflow = int(payload["overflow_candidate_occurrences"])
    artifact = payload.get("candidate_artifact")
    artifact_occurrences = 0
    if artifact is not None:
        if not isinstance(artifact, dict):
            raise TypeError("the census engine returned a malformed candidate artifact")
        if artifact.get("type") != CANDIDATE_SUMMARY_SCHEMA:
            raise RuntimeError(
                "the census engine returned an unsupported candidate summary"
            )
        artifact_occurrences = int(artifact["candidate_occurrence_count"])
        if retained != 0 or overflow != 0:
            raise RuntimeError(
                "a disk-backed candidate report also retained or overflowed candidates"
            )
    if retained + overflow + artifact_occurrences != candidates:
        raise RuntimeError("the census-engine candidate counts do not balance")
    expected_complete = artifact is not None or overflow == 0
    if bool(payload["candidate_aggregation_complete"]) != expected_complete:
        raise RuntimeError("the census-engine aggregation status is inconsistent")
    completion = payload.get("completion")
    if not isinstance(completion, dict):
        raise TypeError("the census-engine report omitted completion totals")
    attempted = int(completion["attempted"])
    terminal = sum(
        int(completion[key]) for key in ("completed", "nonrealizable", "inconclusive")
    )
    if attempted != terminal or attempted > int(completion["candidate_limit"]):
        raise RuntimeError("the census-engine completion totals do not balance")


def _run_engine_task(
    task: Mapping[str, object],
    *,
    engine: Path | None = None,
    memory_limit_bytes: int = DEFAULT_MEMORY_LIMIT_BYTES,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    if memory_limit_bytes <= 0:
        raise ValueError("memory_limit_bytes must be positive")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    executable = _engine_path(engine)
    prlimit = shutil.which("prlimit")
    if prlimit is None:
        raise RuntimeError("the bounded census engine requires the `prlimit` command")
    process = subprocess.Popen(
        [
            prlimit,
            f"--as={memory_limit_bytes}:{memory_limit_bytes}",
            "--",
            str(executable),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(
            json.dumps(task, sort_keys=True, separators=(",", ":")),
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate()
        raise CensusEngineTimeout(
            f"the bounded census engine exceeded its {timeout_seconds}s time limit"
        ) from error
    except BaseException:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate()
        raise
    if process.returncode != 0:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        stderr = stderr.strip()
        if process.returncode < 0:
            detail = f"terminated by signal {-process.returncode}"
        else:
            detail = f"exited with status {process.returncode}"
        raise RuntimeError(
            f"the bounded census engine {detail}: {stderr or 'no diagnostic'}"
        )
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError("the census engine returned invalid JSON") from error
    if not isinstance(payload, dict):
        raise TypeError("the census engine returned a non-object report")
    return payload


def run_coface_pair_task(
    task: Mapping[str, object],
    *,
    engine: Path | None = None,
    memory_limit_bytes: int = DEFAULT_MEMORY_LIMIT_BYTES,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Run one lower-cell shard with an OS-enforced memory and time ceiling."""

    candidate_cap = int(task.get("candidate_cap", 0))
    if not 1 <= candidate_cap <= MAX_CANDIDATE_CAP:
        raise ValueError(f"task candidate_cap must lie in 1..{MAX_CANDIDATE_CAP}")
    completion_limit = int(task.get("completion_candidate_limit", 0))
    if not 0 <= completion_limit <= MAX_COMPLETION_BATCH_SIZE:
        raise ValueError(
            "inline completion_candidate_limit must lie in "
            f"0..{MAX_COMPLETION_BATCH_SIZE}"
        )
    artifact_value = task.get("candidate_artifact_path")
    artifact_path: Path | None = None
    if artifact_value is not None:
        artifact_path = Path(str(artifact_value))
        if not artifact_path.is_absolute():
            raise ValueError("candidate_artifact_path must be absolute")
        if artifact_path.exists():
            raise FileExistsError(
                f"candidate artifact destination already exists: {artifact_path}"
            )
        if not artifact_path.parent.is_dir():
            raise ValueError("candidate artifact parent must be an existing directory")
        if completion_limit != 0:
            raise ValueError(
                "disk-backed aggregation requires process-isolated completion batches"
            )
    payload = _run_engine_task(
        task,
        engine=engine,
        memory_limit_bytes=memory_limit_bytes,
        timeout_seconds=timeout_seconds,
    )
    _verify_report(payload)
    if payload.get("input_sha256") != task.get("input_sha256"):
        raise RuntimeError("the census engine report belongs to different task inputs")
    if artifact_path is None:
        if payload.get("candidate_artifact") is not None:
            raise RuntimeError(
                "the census engine produced an unrequested candidate artifact"
            )
    else:
        verify_candidate_artifact(artifact_path, payload)
    return payload


def _decode_json_line(line: bytes, *, description: str) -> dict[str, Any]:
    if not line.endswith(b"\n"):
        raise ValueError(f"{description} is not newline terminated")
    try:
        payload = json.loads(line)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{description} is not valid UTF-8 JSON") from error
    if not isinstance(payload, dict):
        raise TypeError(f"{description} is not a JSON object")
    return payload


def _verify_candidate_vectors(vectors: object, ambient_rank: int) -> list[list[int]]:
    if not isinstance(vectors, list) or not vectors:
        raise TypeError("candidate vectors must be a nonempty list")
    checked: list[list[int]] = []
    for row in vectors:
        if (
            not isinstance(row, list)
            or len(row) != ambient_rank
            or any(type(entry) is not int for entry in row)
        ):
            raise TypeError("candidate artifact contains a malformed integral line")
        if not any(row):
            raise ValueError("candidate artifact contains the zero line")
        if math.gcd(*(abs(entry) for entry in row)) != 1:
            raise ValueError("candidate artifact contains a nonprimitive line")
        first_nonzero = next(entry for entry in row if entry != 0)
        if first_nonzero < 0:
            raise ValueError("candidate artifact contains a noncanonical line sign")
        checked.append(row)
    expected = [list(row) for row in sorted({tuple(row) for row in checked})]
    if checked != expected:
        raise ValueError("candidate artifact vectors are not sorted and duplicate-free")
    return checked


def _candidate_identifier(vectors: list[list[int]]) -> str:
    encoded = json.dumps(vectors, ensure_ascii=True, separators=(",", ":")).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def verify_candidate_artifact(path: Path, report: Mapping[str, Any]) -> dict[str, Any]:
    """Verify a complete disk-backed candidate artifact against its pair report."""

    summary = report.get("candidate_artifact")
    if not isinstance(summary, dict) or summary.get("type") != CANDIDATE_SUMMARY_SCHEMA:
        raise ValueError("pair report omitted its candidate-artifact summary")
    digest = hashlib.sha256()
    distinct_count = 0
    occurrence_count = 0
    previous_vectors: list[list[int]] | None = None
    with path.open("rb") as artifact:
        header_line = artifact.readline()
        if not header_line:
            raise ValueError("candidate artifact is empty")
        header = _decode_json_line(header_line, description="candidate artifact header")
        if header.get("type") != CANDIDATE_ARTIFACT_SCHEMA:
            raise ValueError("unsupported candidate artifact schema")
        if header.get("noether_contract") != dict(ENGINE_NOETHER_CONTRACT):
            raise ValueError("candidate artifact uses a different Noether contract")
        for key in ("lower_index", "ambient_rank", "target_dimension"):
            if int(header[key]) != int(report[key]):
                raise ValueError(f"candidate artifact header disagrees on {key}")
        if header.get("event_stream_sha256") != report.get("event_stream_sha256"):
            raise ValueError("candidate artifact belongs to a different event stream")
        if header.get("input_sha256") != report.get("input_sha256"):
            raise ValueError(
                "candidate artifact belongs to different mathematical inputs"
            )
        digest.update(header_line)
        ambient_rank = int(header["ambient_rank"])

        footer: dict[str, Any] | None = None
        while line := artifact.readline():
            payload = _decode_json_line(line, description="candidate artifact line")
            if payload.get("type") == CANDIDATE_FOOTER_SCHEMA:
                footer = payload
                if artifact.read(1):
                    raise ValueError("candidate artifact has data after its footer")
                break
            if payload.get("type") != CANDIDATE_RECORD_SCHEMA:
                raise ValueError("candidate artifact contains an unsupported record")
            digest.update(line)
            vectors = _verify_candidate_vectors(payload.get("vectors"), ambient_rank)
            if previous_vectors is not None and previous_vectors >= vectors:
                raise ValueError("candidate artifact records are not strictly sorted")
            if payload.get("candidate_id") != _candidate_identifier(vectors):
                raise ValueError(
                    "candidate artifact record has the wrong content identity"
                )
            occurrences = int(payload["occurrence_count"])
            event_index = int(payload["first_event_index"])
            if occurrences <= 0 or not 1 <= event_index <= int(
                report["raw_double_coset_count"]
            ):
                raise ValueError(
                    "candidate artifact record has invalid coverage counts"
                )
            if not isinstance(
                payload.get("witness_left_incidence_id"), str
            ) or not isinstance(payload.get("witness_right_incidence_id"), str):
                raise TypeError(
                    "candidate artifact record has malformed witness identifiers"
                )
            representative = payload.get("witness_representative")
            if not isinstance(representative, list) or any(
                type(image) is not int or image < 0 for image in representative
            ):
                raise TypeError(
                    "candidate artifact record has a malformed representative"
                )
            distinct_count += 1
            occurrence_count += occurrences
            previous_vectors = vectors

    if footer is None:
        raise ValueError("candidate artifact omitted its terminal footer")
    content_sha256 = digest.hexdigest()
    expected = {
        "content_sha256": content_sha256,
        "distinct_candidate_count": distinct_count,
        "candidate_occurrence_count": occurrence_count,
    }
    for key, value in expected.items():
        if footer.get(key) != value or summary.get(key) != value:
            raise ValueError(f"candidate artifact coverage disagrees on {key}")
    return footer


def iter_candidate_artifact(
    path: Path, report: Mapping[str, Any]
) -> Iterator[dict[str, Any]]:
    """Yield verified candidate records in stable lexical order.

    Verification is completed before the first record is exposed. The second
    pass holds only one decoded record at a time.
    """

    verify_candidate_artifact(path, report)
    yield from _iter_candidate_artifact_records(path)


def _iter_candidate_artifact_records(path: Path) -> Iterator[dict[str, Any]]:
    """Reread records after the caller has verified the complete artifact."""

    with path.open("rb") as artifact:
        artifact.readline()
        for line in artifact:
            payload = _decode_json_line(line, description="candidate artifact line")
            if payload.get("type") == CANDIDATE_FOOTER_SCHEMA:
                break
            yield payload


def iter_completion_batch_tasks(
    path: Path,
    report: Mapping[str, Any],
    *,
    max_iterations: int = 50,
    batch_size: int = MAX_COMPLETION_BATCH_SIZE,
    strategy: CompletionStrategy = "fixed_rank",
) -> Iterator[dict[str, object]]:
    """Build independently runnable completion tasks from a verified artifact."""

    if not 1 <= batch_size <= MAX_COMPLETION_BATCH_SIZE:
        raise ValueError(f"batch_size must lie in 1..{MAX_COMPLETION_BATCH_SIZE}")
    batch: list[dict[str, Any]] = []
    for record in iter_candidate_artifact(path, report):
        batch.append(record)
        if len(batch) == batch_size:
            yield build_completion_batch_task(
                batch, max_iterations=max_iterations, strategy=strategy
            )
            batch = []
    if batch:
        yield build_completion_batch_task(
            batch, max_iterations=max_iterations, strategy=strategy
        )


def build_completion_batch_task(
    candidates: Sequence[Mapping[str, object]],
    *,
    max_iterations: int = 50,
    strategy: CompletionStrategy = "fixed_rank",
) -> dict[str, object]:
    """Build a small process-isolated completion task from retained candidates."""

    if not 1 <= len(candidates) <= MAX_COMPLETION_BATCH_SIZE:
        raise ValueError(
            f"completion batch size must lie in 1..{MAX_COMPLETION_BATCH_SIZE}"
        )
    if max_iterations < 0:
        raise ValueError("max_iterations cannot be negative")
    if strategy not in ("fixed_rank", "exact_shell"):
        raise ValueError("unknown completion strategy")
    return {
        "type": COMPLETION_TASK_SCHEMA,
        "noether_contract": dict(COMPLETION_NOETHER_CONTRACT),
        "strategy": strategy,
        "max_iterations": max_iterations,
        "candidates": [
            {
                "candidate_id": str(candidate["candidate_id"]),
                "vectors": candidate["vectors"],
            }
            for candidate in candidates
        ],
    }


def run_completion_batch_task(
    task: Mapping[str, object],
    *,
    engine: Path | None = None,
    memory_limit_bytes: int = DEFAULT_MEMORY_LIMIT_BYTES,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Run a small completion batch in its own capped process."""

    candidates = task.get("candidates")
    if not isinstance(candidates, list):
        raise TypeError("completion task omitted its candidate list")
    if not 1 <= len(candidates) <= MAX_COMPLETION_BATCH_SIZE:
        raise ValueError(
            f"completion batch size must lie in 1..{MAX_COMPLETION_BATCH_SIZE}"
        )
    payload = _run_engine_task(
        task,
        engine=engine,
        memory_limit_bytes=memory_limit_bytes,
        timeout_seconds=timeout_seconds,
    )
    if payload.get("type") != COMPLETION_REPORT_SCHEMA:
        raise RuntimeError(
            "the census engine returned an unsupported completion schema"
        )
    if payload.get("noether_contract") != dict(COMPLETION_NOETHER_CONTRACT):
        raise RuntimeError("the completion report uses a different Noether contract")
    if payload.get("strategy") != task.get("strategy"):
        raise RuntimeError(
            "the completion report used a different mathematical strategy"
        )
    results = payload.get("results")
    if not isinstance(results, list) or len(results) != len(candidates):
        raise RuntimeError("the completion report does not cover its input batch")
    counts = {"completed": 0, "nonrealizable": 0, "inconclusive": 0}
    for candidate, result in zip(candidates, results, strict=True):
        if not isinstance(candidate, dict) or not isinstance(result, dict):
            raise TypeError("the completion task or report contains a malformed record")
        if result.get("candidate_id") != candidate.get("candidate_id"):
            raise RuntimeError(
                "the completion report changed candidate order or identity"
            )
        status = result.get("status")
        if status not in counts:
            raise RuntimeError("the completion report returned an unknown status")
        counts[status] += 1
        canonical = result.get("evidence_canonical_json")
        if not isinstance(canonical, str):
            raise TypeError("the completion report omitted canonical Noether evidence")
        try:
            json.loads(canonical)
        except json.JSONDecodeError as error:
            raise ValueError("canonical completion evidence is not JSON") from error
        if hashlib.sha256(canonical.encode()).hexdigest() != result.get(
            "evidence_sha256"
        ):
            raise ValueError("canonical completion evidence has the wrong digest")
        completed_vectors = result.get("completed_vectors")
        if (status == "completed") != (completed_vectors is not None):
            raise RuntimeError("completion status and completed shell disagree")
        verify_positive_completion_witness(result)
        if status == "completed":
            seed_rows = candidate["vectors"]
            seed = IntegralLineConfiguration(len(seed_rows[0]), seed_rows)
            shell = IntegralLineConfiguration(seed.ambient_rank, completed_vectors)
            if task.get("strategy") == "exact_shell":
                if shell != seed:
                    raise ValueError(
                        "exact-shell realization changed its input configuration"
                    )
            elif shell.perfection_rank != seed.perfection_rank or not set(
                seed.vectors
            ).issubset(shell.vectors):
                raise ValueError("fixed-rank completion changed its seed or cone rank")
    if any(int(payload[key]) != counts[key] for key in counts):
        raise RuntimeError("the completion report terminal counts do not balance")
    return payload


def verify_positive_completion_witness(result: Mapping[str, Any]) -> None:
    """Re-enumerate the saved Gram's full minimum shell through public Noether."""
    witness = result.get("realization_witness")
    if result.get("status") != "completed":
        if witness is not None:
            raise ValueError("nonpositive completion carries a positive witness")
        return
    if not isinstance(witness, dict) or set(witness) != {"gram_matrix", "minimum"}:
        raise ValueError("positive completion omitted its Gram witness")
    gram = Matrix.from_rows(
        Z, [[int(x) for x in row] for row in witness["gram_matrix"]]
    )
    shell = Lattice(gram).minimum_vector_configuration()
    shell.verify()
    if shell.minimum != int(witness["minimum"]):
        raise ValueError("positive Gram witness has the wrong minimum")
    vectors = result["completed_vectors"]
    target = IntegralLineConfiguration(gram.shape[0], vectors)
    if shell.configuration != target or [list(v) for v in target.vectors] != vectors:
        raise ValueError("positive Gram witness has a different complete shell")


__all__ = [
    "CANDIDATE_ARTIFACT_SCHEMA",
    "CANDIDATE_FOOTER_SCHEMA",
    "CANDIDATE_RECORD_SCHEMA",
    "CANDIDATE_SUMMARY_SCHEMA",
    "COMPLETION_NOETHER_CONTRACT",
    "COMPLETION_REPORT_SCHEMA",
    "COMPLETION_TASK_SCHEMA",
    "DEFAULT_MEMORY_LIMIT_BYTES",
    "DEFAULT_TIMEOUT_SECONDS",
    "ENGINE_NOETHER_CONTRACT",
    "MAX_CANDIDATE_CAP",
    "MAX_COMPLETION_BATCH_SIZE",
    "REPORT_SCHEMA",
    "CensusEngineTimeout",
    "build_completion_batch_task",
    "iter_candidate_artifact",
    "iter_completion_batch_tasks",
    "run_coface_pair_task",
    "run_completion_batch_task",
    "verify_candidate_artifact",
    "verify_positive_completion_witness",
]
