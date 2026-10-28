"""Voronoi cells as problem-specific wrappers around Noether configurations.

The mathematical input is a finite set of primitive integral lines in
``Z^N``. Noether owns their canonical sign convention, exact spanning rank,
rank-one forms, perfection rank, and barycenter. This module adds only the
interpretation of that configuration as a cell of a Voronoi complex.

The cone dimension ``r`` and number of rays ``s`` are distinct. Published
low-dimensional files happen to use simplicial configurations with ``r=s``;
that equality is verified rather than built into the representation.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from noether.linalg import IntegralLineConfiguration


@dataclass(frozen=True)
class VoronoiCell:
    """One embedded perfect-cone/minimal-class representative.

    ``configuration`` retains its coordinates in ``Z^N``. Orbit equivalence
    is an exact operation and is not implicit object identity.
    """

    configuration: IntegralLineConfiguration

    @classmethod
    def from_rows(
        cls,
        rows: Sequence[Sequence[int]],
        *,
        expected_dimension: int | None = None,
    ) -> VoronoiCell:
        """Construct from primitive vector representatives modulo sign.

        ``expected_dimension`` is an assertion supplied by a corpus or census
        layer. It is checked against the exact rank of the forms ``v v^t``.
        """

        materialized = tuple(
            tuple(int(coordinate) for coordinate in row) for row in rows
        )
        if not materialized:
            raise ValueError("cannot build a Voronoi cell with zero rays")
        ambient_rank = len(materialized[0])
        configuration = IntegralLineConfiguration(ambient_rank, materialized)
        cell = cls(configuration=configuration)
        if expected_dimension is not None and cell.cone_dimension != expected_dimension:
            raise ValueError(
                f"computed cone dimension {cell.cone_dimension} disagrees with "
                f"declared dimension {expected_dimension}"
            )
        return cell

    @property
    def lattice_rank(self) -> int:
        """Ambient lattice rank ``N``."""

        return self.configuration.ambient_rank

    @property
    def cone_dimension(self) -> int:
        """Perfection rank ``r = rank{v v^t}``."""

        return self.configuration.perfection_rank

    @property
    def dim(self) -> int:
        """Compatibility alias for :attr:`cone_dimension`."""

        return self.cone_dimension

    @property
    def ray_count(self) -> int:
        """Number ``s`` of minimum-vector pairs/rays."""

        return self.configuration.line_count

    @property
    def is_simplicial(self) -> bool:
        """Whether the rank-one ray generators are linearly independent."""

        return self.configuration.is_rank_one_independent

    @property
    def min_vectors(self) -> tuple[tuple[int, ...], ...]:
        """Canonical primitive representatives retained for legacy callers."""

        return self.configuration.vectors
