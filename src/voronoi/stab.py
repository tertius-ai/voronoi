"""Exact integral stabilizers of Voronoi-cell ray configurations."""

from __future__ import annotations

from noether.linalg import IntegralLineAutomorphismGroup

from voronoi.cells import VoronoiCell


def gram_of_min_vectors(cell: VoronoiCell) -> list[list[int]]:
    """Return the exact barycenter form ``sum_v v v^t``.

    Noether owns its computation. The row-list conversion is retained only for
    compatibility with research scripts that serialize the matrix.
    """

    return cell.configuration.barycenter_form.to_rows()


def stabilizer(cell: VoronoiCell) -> IntegralLineAutomorphismGroup:
    """Return the complete finite stabilizer in ``GL_N(Z)``.

    The result contains verified unimodular matrix generators, the induced
    permutation group on the rays, its faithful signed-action order, and the
    orientation character on the generators.
    """

    return cell.configuration.automorphism_group()


def cell_stabilizer(cell: VoronoiCell) -> IntegralLineAutomorphismGroup:
    """Compatibility name for :func:`stabilizer`."""

    return stabilizer(cell)
