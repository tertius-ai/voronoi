"""VoronoiCell: a single cell σ of the Voronoi complex Vor_{GL_N(Z)}.

A cell of dimension ``dim`` is represented by its ``min_vectors``: a
``(dim × lattice_rank)`` integer matrix whose rows are the minimum
vectors of a perfect form (or of a face of the perfect-cone
decomposition) that parameterizes σ.

The representative is not canonical; two cells with different
``min_vectors`` matrices can lie in the same GL_N(Z)-orbit. Orbit
equality is checked via lattice isometry — see ``stab.py``.

Conventions (matching the DATA_pari files in the published database):

- Rows of ``min_vectors`` are lattice vectors in Z^{lattice_rank}.
- The set {± row_i} is the full minimum-vector set of the underlying
  perfect form; we only store one of each ± pair.
- ``dim`` = number of rows = dimension of the Voronoi cell in the
  space of symmetric bilinear forms on R^{lattice_rank}.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class VoronoiCell:
    lattice_rank: int
    dim: int
    min_vectors: tuple[tuple[int, ...], ...]

    def __post_init__(self) -> None:
        if len(self.min_vectors) != self.dim:
            raise ValueError(
                f"dim={self.dim} but got {len(self.min_vectors)} min vectors"
            )
        for i, row in enumerate(self.min_vectors):
            if len(row) != self.lattice_rank:
                raise ValueError(
                    f"row {i} has length {len(row)}, expected {self.lattice_rank}"
                )

    @classmethod
    def from_rows(cls, rows: Sequence[Sequence[int]]) -> "VoronoiCell":
        mv = tuple(tuple(int(x) for x in row) for row in rows)
        if not mv:
            raise ValueError("cannot build a cell with zero min vectors")
        lattice_rank = len(mv[0])
        return cls(lattice_rank=lattice_rank, dim=len(mv), min_vectors=mv)
