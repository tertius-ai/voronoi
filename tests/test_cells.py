"""Exact Voronoi cell semantics projected from Noether."""

from __future__ import annotations

import pytest
from noether.linalg import IntegralLineConfiguration

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
