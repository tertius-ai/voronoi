"""Compare named catalogs with native exact equivalences and replay transports."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from noether import Z
from noether.linalg import IntegralLineConfiguration, Matrix

from voronoi.cells import VoronoiCell
from voronoi.enumerate.census_engine import (
    DEFAULT_MEMORY_LIMIT_BYTES,
    DEFAULT_TIMEOUT_SECONDS,
    ENGINE_NOETHER_CONTRACT,
    _run_engine_task,
    verify_positive_completion_witness,
)

CATALOG_MATCH_TASK_SCHEMA = "voronoi/catalog-match-task@1"
CATALOG_MATCH_REPORT_SCHEMA = "voronoi/catalog-match-report@1"


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def catalog_match_task(
    sources: Sequence[tuple[str, VoronoiCell]],
    references: Sequence[tuple[str, VoronoiCell]],
    *,
    ambient_rank: int,
    cone_dimension: int,
) -> dict[str, Any]:
    """Bind named embedded configurations without implying census provenance."""

    def entries(cells: Sequence[tuple[str, VoronoiCell]]) -> list[dict[str, Any]]:
        result = []
        ids = set()
        for name, cell in cells:
            if not isinstance(name, str) or not name or name in ids:
                raise ValueError("empty or duplicate catalog ID")
            ids.add(name)
            if (
                cell.lattice_rank != ambient_rank
                or cell.cone_dimension != cone_dimension
            ):
                raise ValueError("wrong catalog ambient rank or cone dimension")
            result.append({"id": name, "vectors": [list(v) for v in cell.min_vectors]})
        return result

    return {
        "type": CATALOG_MATCH_TASK_SCHEMA,
        "noether_contract": dict(ENGINE_NOETHER_CONTRACT),
        "ambient_rank": ambient_rank,
        "cone_dimension": cone_dimension,
        "sources": entries(sources),
        "references": entries(references),
    }


def verify_catalog_match_report(
    task: Mapping[str, Any],
    report: Mapping[str, Any],
) -> None:
    """Replay every reported unimodular transport and check complete accounting.

    Reference distinctness and unmatched comparisons are native worker verdicts;
    this replay checks positive witnesses, not global census completeness.
    """
    if (
        report.get("type") != CATALOG_MATCH_REPORT_SCHEMA
        or report.get("noether_contract") != dict(ENGINE_NOETHER_CONTRACT)
        or report.get("input_sha256") != canonical_sha256(task)
    ):
        raise ValueError("catalog report schema, contract, or input digest disagrees")
    if report.get("reference_orbits_verified_distinct") is not True:
        raise ValueError("native matcher did not check reference orbit distinctness")
    sources = {entry["id"]: entry["vectors"] for entry in task["sources"]}
    references = {entry["id"]: entry["vectors"] for entry in task["references"]}
    if report.get("source_count") != len(sources) or report.get(
        "reference_count"
    ) != len(references):
        raise ValueError("catalog report counts disagree")
    seen = set()
    used = set()
    rank = task["ambient_rank"]
    for match in report["matches"]:
        source_id, reference_id = match["source_id"], match["reference_id"]
        if (
            source_id not in sources
            or source_id in seen
            or reference_id not in references
        ):
            raise ValueError("catalog report contains an unknown or repeated match")
        seen.add(source_id)
        used.add(reference_id)
        transformation = Matrix.from_rows(
            Z,
            [[int(x) for x in row] for row in match["transformation"]],
        )
        if transformation.shape != (rank, rank) or abs(transformation.det()) != 1:
            raise ValueError("catalog transport is not unimodular")
        source = IntegralLineConfiguration(rank, sources[source_id])
        target = IntegralLineConfiguration(rank, references[reference_id])
        if source.transform(transformation) != target:
            raise ValueError("catalog transport does not reach reference")
        positions = {v: i for i, v in enumerate(target.vectors)}
        images = [
            positions[
                IntegralLineConfiguration(rank, [v])
                .transform(transformation)
                .vectors[0]
            ]
            for v in source.vectors
        ]
        if images != match["line_permutation"]:
            raise ValueError("catalog transport has wrong line permutation")
    unmatched = report["unmatched_source_ids"]
    if (
        len(unmatched) != len(set(unmatched))
        or seen.intersection(unmatched)
        or seen.union(unmatched) != set(sources)
    ):
        raise ValueError("catalog source accounting is incomplete or repeated")
    unused = report["unused_reference_ids"]
    if len(unused) != len(set(unused)) or set(unused) != set(references) - used:
        raise ValueError("catalog reference accounting is incomplete or repeated")


def run_catalog_match(
    task: Mapping[str, Any],
    *,
    engine: Path | None = None,
    memory_limit_bytes: int = DEFAULT_MEMORY_LIMIT_BYTES,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    report = _run_engine_task(
        task,
        engine=engine,
        memory_limit_bytes=memory_limit_bytes,
        timeout_seconds=timeout_seconds,
    )
    verify_catalog_match_report(task, report)
    return report


def pullback_realization_witness(
    source: VoronoiCell,
    reference: VoronoiCell,
    transformation_rows: Sequence[Sequence[int | str]],
    witness: Mapping[str, Any],
) -> dict[str, Any]:
    """Transfer a reference Gram through column transport T using T^t G T.

    Noether checks the unimodular transport and re-enumerates both complete
    minimum shells. Neither a matching fingerprint nor a matrix alone suffices.
    """
    transformation = Matrix.from_rows(
        Z, [[int(x) for x in row] for row in transformation_rows]
    )
    if source.configuration.transform(transformation) != reference.configuration:
        raise ValueError("Gram pullback transport does not reach reference")
    verify_positive_completion_witness(
        {
            "status": "completed",
            "completed_vectors": [list(v) for v in reference.min_vectors],
            "realization_witness": witness,
        }
    )
    gram = Matrix.from_rows(
        Z, [[int(x) for x in row] for row in witness["gram_matrix"]]
    )
    pulled = transformation.transpose() @ gram @ transformation
    result = {
        "gram_matrix": [[str(x) for x in row] for row in pulled.to_rows()],
        "minimum": witness["minimum"],
    }
    verify_positive_completion_witness(
        {
            "status": "completed",
            "completed_vectors": [list(v) for v in source.min_vectors],
            "realization_witness": result,
        }
    )
    return result
