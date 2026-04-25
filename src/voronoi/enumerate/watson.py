"""Watson code enumeration for cells with kissing number s = n.

Per DSEKM19 §2.2: every well-rounded lattice (Λ, m(Λ)) with s = n in
dim n corresponds, after a unimodular change of basis, to a sublattice
extension Λ ⊃ Λ' = Z^n parameterized by a Z/dZ-code c ∈ Z^n where
d = [Λ : Λ']. The code is determined up to the action of signed
permutations of coordinates (the "B_n action") which corresponds to
unimodular automorphisms of Λ' = Z^n that permute the basis.

References:
    [DSEKM19] arXiv:1910.11598 §2.2 "Watson's index theory and very
              small cells".
    [DSEKM19] Table 2: orbit counts by index for n ≤ 9.
"""

from __future__ import annotations

from voronoi.cells import VoronoiCell


def enumerate_index_1_cells(n: int) -> list[VoronoiCell]:
    """Index-1 cells in Z^n with s = n.

    There is exactly one such cell: the lattice is Λ = Z^n itself,
    with min vectors ±e_i. The cell is the convex hull of the n rank-1
    forms ê_i = e_i e_i^T inside Sym²(R^n).

    Args:
        n: lattice rank (= cell dimension since s = n).

    Returns:
        A list of one :class:`VoronoiCell` whose min-vector matrix is
        the n × n identity.
    """
    if n < 1:
        raise ValueError(f"n must be >= 1, got {n}")
    rows = tuple(tuple(1 if i == j else 0 for j in range(n)) for i in range(n))
    return [VoronoiCell(lattice_rank=n, dim=n, min_vectors=rows)]
