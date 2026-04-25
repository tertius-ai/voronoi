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
    """Return ``noether.api.lattice.AutomorphismGroup`` of Stab(σ) using
    the centroid Gram ``M^T M``.

    **Warning (OQ1):** for non-perfect cells, ``M^T M`` may have additional
    short vectors beyond ``±cell.min_vectors``, in which case the
    qfauto-with-shv subgroup is a proper subgroup of the true Stab(σ) —
    notably collapsing to ``{±I}`` for some (N=8, n=8) cells. Prefer
    :func:`cell_stabilizer` (uses the realizability LP witness Gram) for
    Voronoi-cell-correct results.
    """
    from noether.api.lattice import automorphism_group

    return automorphism_group(
        gram_of_min_vectors(cell),
        min_vectors=[list(v) for v in cell.min_vectors],
    )


def cell_stabilizer(cell: VoronoiCell):
    """Return Stab(σ) ⊆ GL_N(Z) for cell σ via the realizability LP
    Gram witness.

    **WARNING (OQ1, partially resolved):** PARI's ``qfauto`` with an
    SHV hint expects the SHV list to be **all** vectors of norm
    ≤ max(diag(G)), not the cell's chosen min vectors. With our cell's
    M as SHV, PARI's qfisom backtrack starts the pivot search from
    M[0], giving order-sensitive output: cell 6 of (N=8, n=8) returns
    |Stab|=2 with M[0]=v_messy versus 1440 with M[7]=v_messy. The
    correct path is to call ``qfauto(G)`` (no SHV) to get Aut(G), then
    extract SetStab(±V) ∩ Aut(G) via coset enumeration / Schreier-Sims
    over the Aut(G) generators. Source: PARI 2.15 ``qfisom.c:197``.

    Args:
        cell: a :class:`VoronoiCell`.

    Returns:
        :class:`noether.api.lattice.AutomorphismGroup` — possibly a
        proper subgroup of the true Stab(σ).
    """
    from noether.api.lattice import automorphism_group, realize_min_vector_set

    V = [list(v) for v in cell.min_vectors]
    A_int = realize_min_vector_set(V, max_iterations=200)
    if A_int is None:
        raise ValueError(
            f"cell's min-vector set is not realizable as Min(A) for any "
            f"PD form A — σ may not be a valid Voronoi cell"
        )
    return automorphism_group(A_int, min_vectors=V)


def cell_stabilizer_brute_force(cell: VoronoiCell):
    """Compute Stab(σ) by enumerating signed-permutation candidates.

    For each (π, ε) ∈ S_n × {±1}^n, attempt to solve

        g · v_i = ε_i · v_{π(i)}    for all i ∈ {0, ..., n-1}

    for ``g ∈ GL_N(Z)``. When the candidate ``g = W · V^{-1}`` (where
    V's columns are ``cell.min_vectors`` and W's columns are
    ``ε_i v_{π(i)}``) is integer with ``|det g| = 1``, it's an element
    of Stab(σ).

    Returns a synthesized :class:`noether.api.lattice.AutomorphismGroup`
    with ``order`` = exact ``|Stab(σ)|`` and ``generators`` = all
    elements of Stab found.

    Time complexity: ``O(n! · 2^n · N^3)``. For n = N = 8 this is
    ~5M iterations × 512 ops ≈ 2.5G ops — minutes per cell with numpy
    vectorization. Not viable beyond n ≈ 10.
    """
    import itertools

    import numpy as np
    from fractions import Fraction

    from noether.api.lattice import AutomorphismGroup

    n = cell.dim
    N = cell.lattice_rank
    if n != N:
        raise ValueError(
            f"brute force is only correct for n = N (square M); got "
            f"n={n}, N={N}"
        )

    V = np.array(cell.min_vectors, dtype=np.int64)  # (n, N)
    V_T = V.T  # columns = min vectors, shape (N, n)

    # Precompute V^{-1} in exact rationals via numpy (float, then
    # round-and-verify for integrality of g).
    V_T_f = V_T.astype(np.float64)
    detV = round(float(np.linalg.det(V_T_f)))
    if detV == 0:
        raise ValueError("V is singular — cell's min vectors aren't LI")
    V_T_inv_float = np.linalg.inv(V_T_f)

    found: list[np.ndarray] = []

    for pi in itertools.permutations(range(n)):
        for sign_bits in range(2 ** n):
            eps = np.array(
                [1 if (sign_bits >> i) & 1 else -1 for i in range(n)],
                dtype=np.int64,
            )
            # W's columns are eps[i] * v_pi[i].
            W = (eps[None, :] * V[list(pi)].T).astype(np.float64)  # (N, n)
            g_f = W @ V_T_inv_float  # (N, N)
            g_int = np.round(g_f).astype(np.int64)
            if not np.allclose(g_f, g_int.astype(np.float64), atol=1e-6):
                continue
            # Verify exactly: g · V == W (integer mat mul).
            if not np.array_equal(g_int @ V_T, (eps[None, :] * V[list(pi)].T)):
                continue
            # |det g| = 1 (unimodular).
            det_g = round(float(np.linalg.det(g_int.astype(np.float64))))
            if abs(det_g) != 1:
                continue
            found.append(g_int)

    if not found:
        raise RuntimeError(
            f"brute force found 0 stabilizer elements — at minimum I "
            f"should be in Stab"
        )

    return AutomorphismGroup(
        order=len(found),
        generators=[g.tolist() for g in found],
    )
