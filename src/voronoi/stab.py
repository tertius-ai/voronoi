"""Stabilizer Stab(σ) of a Voronoi cell σ in GL_N(Z).

For a cell σ of dim n given by min-vector matrix M ∈ Z^{n × N}
(rows = min vectors of a perfect form parameterizing σ), the Gram
matrix ``G = M^T · M`` on Z^N has the property that

    {v ∈ Z^N : v^T G v = min(G)} = {± rows of M}

(for perfect-form cells the min-vector set is exactly the generating
set). Hence

    Stab(σ) = { g ∈ GL_N(Z) : g^T G g = G } = Aut(G) ⊂ GL_N(Z).

We compute Aut(G) via ``noether.api.lattice.automorphism_group``,
which wraps PARI's Plesken-Pohst qfauto.
"""

from __future__ import annotations

from voronoi.cells import VoronoiCell


def gram_of_min_vectors(cell: VoronoiCell) -> list[list[int]]:
    """G = M^T · M  ∈ Z^{N × N} where M has rows = min vectors."""
    n = cell.lattice_rank
    g = [[0] * n for _ in range(n)]
    for row in cell.min_vectors:
        for i in range(n):
            v_i = row[i]
            if v_i == 0:
                continue
            for j in range(n):
                g[i][j] += v_i * row[j]
    return g


def stabilizer(cell: VoronoiCell):
    """Return ``noether.api.lattice.AutomorphismGroup`` of Stab(σ).

    The result's ``order`` is |Stab(σ)|; ``generators`` are n × n
    integer matrices in GL_N(Z), each satisfying ``g^T G g = G`` and
    additionally permuting ``{± cell.min_vectors}`` as a set.
    """
    from noether.api.lattice import automorphism_group

    return automorphism_group(
        gram_of_min_vectors(cell),
        min_vectors=[list(v) for v in cell.min_vectors],
    )
