"""Orientation character of a Voronoi cell's exact stabilizer.

An orientation is an orientation of the rank-one span
``R(cell) = span{v v^t}``. Noether computes the determinant of each induced
rational action on that span. For simplicial cells this agrees with the sign of
the ray permutation; for non-simplicial cells it deliberately does not assume
that shortcut.
"""

from __future__ import annotations

from collections.abc import Sequence

from noether import Z
from noether.linalg import Matrix

from voronoi.cells import VoronoiCell
from voronoi.stab import stabilizer


def orientation_signs(
    cell: VoronoiCell,
    generators: Sequence[Sequence[Sequence[int]]],
) -> list[int]:
    """Return the exact orientation character for supplied matrix generators."""

    signs: list[int] = []
    for generator in generators:
        matrix = Matrix.from_rows(Z, generator)
        signs.append(cell.configuration.orientation_sign(matrix))
    return signs


def has_orientation_reversing(cell: VoronoiCell) -> bool:
    """Whether ``Stab(cell)`` contains an orientation-reversing element."""

    return stabilizer(cell).has_orientation_reversing


def has_orientation_reversing_exact(cell: VoronoiCell) -> bool:
    """Compatibility name for the native exact stabilizer computation."""

    return has_orientation_reversing(cell)
