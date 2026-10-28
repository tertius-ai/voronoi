"""Independent small proofs and attacks against the native Voronoi checker."""

from __future__ import annotations

import hashlib
import json
from fractions import Fraction

import pytest

from voronoi.enumerate.census_engine import _candidate_identifier
from voronoi.historical_evidence import check_negative_certificates


def proof(vectors, kind, obstacles, multipliers):
    def encoded(value):
        return json.dumps(value, separators=(",", ":")).encode()

    configuration = [
        "noether/linalg/IntegralLineConfiguration@1",
        len(vectors[0]),
        [[str(x) for x in row] for row in vectors],
    ]
    certificate = [
        "noether/linalg/MinimumNonrealizabilityCertificate@1",
        list(encoded(configuration)),
        kind,
        [[str(x) for x in row] for row in obstacles],
        [str(x) for x in multipliers],
    ]
    wire = encoded(
        [
            "noether/linalg/MinimumRealization@1",
            "nonrealizable",
            list(encoded(certificate)),
        ]
    ).decode()
    return {
        "candidate_id": _candidate_identifier(vectors),
        "status": "nonrealizable",
        "evidence_canonical_json": wire,
        "evidence_sha256": hashlib.sha256(wire.encode()).hexdigest(),
    }


def test_three_hand_checkable_obstructions_and_a_rejected_farkas_claim():
    # q(e2)+q(e1+e2) = (q(e1)+q(e1+2e2))/2. Both outsiders
    # cannot be longer than two equal claimed minima in this index-two basis.
    source = [[1, 0], [1, 2]]
    outsiders = [[0, 1], [1, 1]]
    margin = proof(source, "nonpositive_outsider_margin", outsiders, ["1/2", "1/2"])
    # Homogeneous constraints are the +/- equalities, the two outsider cuts,
    # and -lambda<=0. Their indicated sum gives -lambda <= -2.
    homogeneous = proof(
        source,
        "homogeneous_minimum_at_least_one",
        outsiders,
        ["1/2", 0, "1/2", 0, 1, 1, 0],
    )
    equality = proof(
        [[0, 1], [1, -1], [1, 0], [1, 1]],
        "inconsistent_equal_norms",
        [],
        [-2, 1, -2, 1],
    )
    report = check_negative_certificates([margin, homogeneous, equality])
    assert report["checked"] == 3
    assert {p["normalization"] for p in report["proofs"]} == {
        "unscaled",
        "homogeneous",
        "equality",
    }
    # The affine outsider system always permits a sufficiently negative free
    # margin. Zero multipliers do not prove a strict Farkas contradiction.
    with pytest.raises(RuntimeError, match="invalid outsider dual identity"):
        check_negative_certificates(
            [proof(source, "farkas_infeasible", outsiders, [0, 0])]
        )


@pytest.mark.parametrize("outsider", [[[1, 0]], [[-1, 0]], [[0, 0]]])
def test_fake_outsiders_cannot_refute_the_realizable_coordinate_axes(outsider):
    # Without outsider validation, delta<=0 from a claimed minimum itself
    # would falsely prove that the identity Gram has no minimum shell.
    forged = proof([[0, 1], [1, 0]], "nonpositive_outsider_margin", outsider, [1])
    with pytest.raises(RuntimeError, match="outsider"):
        check_negative_certificates([forged])


def test_homogeneous_self_obstacle_is_also_rejected():
    forged = proof(
        [[0, 1], [1, 0]],
        "homogeneous_minimum_at_least_one",
        [[0, 1]],
        [1, 0, 0, 0, 1, 0],
    )
    with pytest.raises(RuntimeError, match="source minimum vector"):
        check_negative_certificates([forged])


def test_nonprimitive_and_repeated_genuine_outsiders_are_valid():
    first = proof(
        [[1, 0], [1, 2]],
        "nonpositive_outsider_margin",
        [[0, 1], [1, 1], [2, 0]],
        ["1/2", "1/2", 0],
    )
    second = proof(
        [[1, 0], [1, 2]],
        "nonpositive_outsider_margin",
        [[0, 1], [0, 1], [1, 1]],
        ["1/4", "1/4", "1/2"],
    )
    assert check_negative_certificates([first, second])["checked"] == 2


@pytest.mark.parametrize("multipliers", [["1/2"], ["-1/2", "3/2"], [0, 0], [1, 1]])
def test_altered_multipliers_fail_even_when_the_digest_is_recomputed(multipliers):
    altered = proof(
        [[1, 0], [1, 2]], "nonpositive_outsider_margin", [[0, 1], [1, 1]], multipliers
    )
    with pytest.raises(RuntimeError, match="multiplier|dual identity"):
        check_negative_certificates([altered])


def test_historical_large_row_scaling_is_checked_exactly():
    m = 10_000_000
    source = [[1, 0], [2 * m + 1, 2]]
    outsiders = [[m, 1], [m + 1, 1]]
    scaled = [Fraction((m + 1) ** 2, 2 * (2 * m + 1)), Fraction(m * m, 2 * (2 * m + 1))]
    reports = check_negative_certificates(
        [
            proof(source, "nonpositive_outsider_margin", outsiders, ["1/2", "1/2"]),
            proof(source, "nonpositive_outsider_margin", outsiders, scaled),
        ]
    )["proofs"]
    assert [r["normalization"] for r in reports] == ["unscaled", "scaled-1000000"]


def test_source_identity_and_invalid_rationals_are_rejected():
    valid = proof(
        [[1, 0], [1, 2]],
        "nonpositive_outsider_margin",
        [[0, 1], [1, 1]],
        ["1/2", "1/2"],
    )
    with pytest.raises(RuntimeError, match="identity disagrees"):
        check_negative_certificates([{**valid, "candidate_id": "sha256:" + "0" * 64}])
    with pytest.raises(RuntimeError):
        check_negative_certificates(
            [
                proof(
                    [[1, 0], [1, 2]],
                    "nonpositive_outsider_margin",
                    [[0, 1], [1, 1]],
                    ["1/0", 0],
                )
            ]
        )
