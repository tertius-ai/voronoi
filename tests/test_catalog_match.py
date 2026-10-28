"""Native catalog comparison and independent replay of positive witnesses."""

from __future__ import annotations

import copy

import pytest

from voronoi.cells import VoronoiCell
from voronoi.enumerate.catalog_match import (
    catalog_match_task,
    pullback_realization_witness,
    run_catalog_match,
    verify_catalog_match_report,
)


def test_native_catalog_matching_retains_transports_and_rejects_tampering() -> None:
    def cell(rows: list[list[int]]) -> VoronoiCell:
        return VoronoiCell.from_rows(rows)

    task = catalog_match_task(
        [("sheared-σ", cell([[1, 1], [1, 2]])), ("collision", cell([[1, 0], [2, 11]]))],
        [("axes", cell([[1, 0], [0, 1]])), ("index-11", cell([[1, 0], [1, 11]]))],
        ambient_rank=2,
        cone_dimension=2,
    )
    report = run_catalog_match(task)
    assert [(m["source_id"], m["reference_id"]) for m in report["matches"]] == [
        ("sheared-σ", "axes"),
    ]
    assert report["unmatched_source_ids"] == ["collision"]
    assert report["unused_reference_ids"] == ["index-11"]
    bad = copy.deepcopy(report)
    bad["matches"][0]["transformation"][0] = ["0", "0"]
    with pytest.raises(ValueError, match="not unimodular"):
        verify_catalog_match_report(task, bad)
    bad = copy.deepcopy(report)
    images = bad["matches"][0]["line_permutation"]
    bad["matches"][0]["line_permutation"] = images[::-1]
    with pytest.raises(ValueError, match="wrong line permutation"):
        verify_catalog_match_report(task, bad)
    bad = copy.deepcopy(report)
    bad["unmatched_source_ids"] = []
    with pytest.raises(ValueError, match="source accounting"):
        verify_catalog_match_report(task, bad)
    with pytest.raises(ValueError, match="input digest"):
        verify_catalog_match_report({**task, "cone_dimension": 3}, report)


def test_catalog_builder_checks_labels_and_rank() -> None:
    cell = VoronoiCell.from_rows([[1, 0], [0, 1]])
    with pytest.raises(ValueError, match="duplicate catalog ID"):
        catalog_match_task(
            [("a", cell), ("a", cell)], [], ambient_rank=2, cone_dimension=2
        )
    with pytest.raises(ValueError, match="wrong catalog"):
        catalog_match_task([("a", cell)], [], ambient_rank=3, cone_dimension=2)


def test_gram_pullback_uses_the_column_transport_and_rechecks_both_shells() -> None:
    reference = VoronoiCell.from_rows([[0, 1], [1, 0], [1, 1]])
    source = VoronoiCell.from_rows([[1, 0], [1, 1], [2, 1]])
    witness = {"gram_matrix": [["2", "-1"], ["-1", "2"]], "minimum": "2"}
    pulled = pullback_realization_witness(source, reference, [[1, -1], [0, 1]], witness)
    assert pulled == {"gram_matrix": [["2", "-3"], ["-3", "6"]], "minimum": "2"}
    with pytest.raises(ValueError, match="does not reach reference"):
        pullback_realization_witness(source, reference, [[1, 0], [0, 1]], witness)
    with pytest.raises(ValueError, match="different complete shell"):
        pullback_realization_witness(
            source,
            reference,
            [[1, -1], [0, 1]],
            {
                "gram_matrix": [["1", "0"], ["0", "1"]],
                "minimum": "1",
            },
        )
