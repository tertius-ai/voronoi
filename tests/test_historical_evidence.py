"""Historical source extraction is an integrity check, not certificate acceptance."""

from __future__ import annotations

import copy

import pytest

from voronoi.enumerate.census_engine import (
    _candidate_identifier,
    build_completion_batch_task,
    run_completion_batch_task,
)
from voronoi.historical_evidence import inspect_negative_configuration


def test_negative_source_extraction_is_bound_to_the_native_configuration() -> None:
    vectors = [[0, 1], [1, -1], [1, 0], [1, 1]]
    candidate = {"candidate_id": _candidate_identifier(vectors), "vectors": vectors}
    report = run_completion_batch_task(
        build_completion_batch_task([candidate], strategy="exact_shell")
    )
    result = report["results"][0]
    assert result["status"] == "nonrealizable"
    cell, kind = inspect_negative_configuration(result)
    assert cell.lattice_rank == 2
    assert cell.cone_dimension == 3
    assert cell.ray_count == 4
    assert [list(v) for v in cell.min_vectors] == vectors
    assert isinstance(kind, str)
    wrong_id = {**result, "candidate_id": "sha256:" + "0" * 64}
    with pytest.raises(ValueError, match="identity disagrees"):
        inspect_negative_configuration(wrong_id)
    corrupted = copy.deepcopy(result)
    corrupted["evidence_canonical_json"] += " "
    with pytest.raises(ValueError, match="digest disagrees"):
        inspect_negative_configuration(corrupted)
    with pytest.raises(ValueError, match="not an exact-shell negative"):
        inspect_negative_configuration({**result, "status": "inconclusive"})
