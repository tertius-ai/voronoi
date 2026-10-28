"""Exact Voronoi cell semantics projected from Noether."""

from __future__ import annotations

from fractions import Fraction

import pytest
from noether import Q, Z
from noether.linalg import IntegralLineConfiguration, Lattice, Matrix

from voronoi.cells import VoronoiCell
from voronoi.enumerate import enumerate_all_n_eq_N_cells
from voronoi.enumerate.lp_extend import extend_cell_by_one


@pytest.mark.parametrize("rank", [9, 11])
def test_partial_watson_families_are_not_reported_as_an_exhaustive_base(
    rank: int,
) -> None:
    with pytest.raises(ValueError, match="supported only for n=8"):
        enumerate_all_n_eq_N_cells(rank)


def test_cell_uses_noethers_integral_line_identity() -> None:
    cell = VoronoiCell.from_rows([[-1, 0], [0, -1]])

    assert isinstance(cell.configuration, IntegralLineConfiguration)
    assert cell.lattice_rank == 2
    assert cell.cone_dimension == 2
    assert cell.dim == 2
    assert cell.ray_count == 2
    assert cell.is_simplicial
    assert cell.min_vectors == ((0, 1), (1, 0))


def test_ray_count_and_cone_dimension_are_not_identical_fields() -> None:
    cell = VoronoiCell.from_rows(
        [[1, 0], [0, 1], [1, 1], [1, -1]],
        expected_dimension=3,
    )

    assert cell.ray_count == 4
    assert cell.cone_dimension == 3
    assert not cell.is_simplicial

    with pytest.raises(ValueError, match="computed cone dimension 3"):
        VoronoiCell.from_rows(
            [[1, 0], [0, 1], [1, 1], [1, -1]],
            expected_dimension=4,
        )


def test_cell_rejects_nonprimitive_or_zero_rays() -> None:
    with pytest.raises(ValueError, match="nonprimitive"):
        VoronoiCell.from_rows([[2, 0]])
    with pytest.raises(ValueError, match="zero vector"):
        VoronoiCell.from_rows([[0, 0]])


def test_diagnostic_extension_uses_certified_noether_surface() -> None:
    cell = VoronoiCell.from_rows(((1, 0), (0, 1)))
    assert extend_cell_by_one(cell, norm_excess_factor=1) == []


def test_diagnostic_extension_rejects_invalid_radius() -> None:
    cell = VoronoiCell.from_rows(((1, 0), (0, 1)))
    with pytest.raises(ValueError, match="norm_excess_factor"):
        extend_cell_by_one(cell, norm_excess_factor=0)


@pytest.mark.parametrize(
    ("rows", "degree"),
    [
        ([[1]], 0),
        ([[1, 0], [0, 1]], 1),
        ([[1, 0], [0, 1], [1, 1]], 2),
        ([[1, 0], [0, 1], [1, 1], [1, -1]], 2),
        ([[1, 0, 0], [0, 1, 0], [0, 0, 1], [1, -1, 0], [1, 0, -1], [0, 1, -1]], 5),
    ],
)
def test_projective_degree_matches_affine_rank_of_trace_one_slice(
    rows: list[list[int]],
    degree: int,
) -> None:
    cell = VoronoiCell.from_rows(rows)
    normalized = [
        [
            Fraction(v[i] * v[j], sum(x * x for x in v))
            for i in range(len(v))
            for j in range(i, len(v))
        ]
        for v in rows
    ]
    differences = [
        [x - y for x, y in zip(point, normalized[0], strict=True)]
        for point in normalized[1:]
    ]
    affine_rank = Matrix.from_rows(Q, differences).rank() if differences else 0
    assert affine_rank == degree == cell.projective_dimension
    assert cell.dim == cell.cone_dimension == degree + 1


def test_distinct_seeds_force_the_same_nonsimplicial_fixed_rank_completion() -> None:
    # D4 plus a rank-one orthogonal summand: 13 rays of perfection rank 11.
    shell = Lattice(
        Matrix.from_rows(
            Z,
            [
                [2, -1, 0, 0, 0],
                [-1, 2, -1, -1, 0],
                [0, -1, 2, 0, 0],
                [0, -1, 0, 2, 0],
                [0, 0, 0, 0, 2],
            ],
        )
    ).minimum_vector_configuration()
    shell.verify()
    target = shell.configuration
    assert target.line_count == 13
    assert target.perfection_rank == 11
    for indices in [(*range(11),), (*range(10), 11)]:
        seed = IntegralLineConfiguration(5, [target.vectors[i] for i in indices])
        assert seed.perfection_rank == seed.line_count == 11
        result = seed.complete_minimum(max_iterations=100)
        result.verify()
        assert result.status == "completed"
        assert result.realization is not None
        assert result.realization.configuration == target
