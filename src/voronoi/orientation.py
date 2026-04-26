"""Orientation character χ_σ : Stab(σ) → {±1}.

The convention is from [DSEKM19] §1.2.1 / [EVGS13] §3.1: an orientation
of σ is an orientation of the real vector space R(σ) ⊂ Sym²(R^N) of
symmetric matrices spanned by the rank-1 forms v̂ = v vᵀ for v ∈ m(σ).
A natural basis is { v̂ : v ∈ m(σ) / {±1} }.

For g ∈ Stab(σ): g · v̂ = (g v)(g v)ᵀ = v̂_{π(j)}, where π is the
permutation of *unordered* min-vector pairs induced by g. The εⱼ ∈ {±1}
sign on g·v_j is irrelevant because v̂ is sign-blind (v̂ = (−v)̂ ).
Therefore

    χ_σ(g) = sign(π)   ∈ {±1}.

A cell σ contributes 0 to C_n(Vor_{GL_N}; Z) mod 2-torsion iff χ_σ is
NOT identically +1 on Stab(σ) — iff *some* g ∈ Stab(σ) has χ_σ(g) = −1.
Equivalently σ ∉ Σ_n in the [DSEKM19] notation.

This module has two entry points:

- :func:`orientation_signs`: compute χ_σ(g) for each given generator g.
- :func:`has_orientation_reversing`: True iff ∃ g ∈ Stab(σ) with
  χ_σ(g) = −1 (i.e. σ vanishes mod 2-torsion in C_n).
"""

from __future__ import annotations

from voronoi.cells import VoronoiCell


def _apply_g_to_row(g: list[list[int]], v: tuple[int, ...]) -> list[int]:
    """Compute g · v (matrix times column vector), returning a list of
    length N. ``g`` is N × N, ``v`` is N-long."""
    n = len(g)
    return [sum(g[i][k] * v[k] for k in range(n)) for i in range(n)]


def _signed_permutation_of(
    g: list[list[int]], min_vectors: tuple[tuple[int, ...], ...]
) -> tuple[list[int], list[int]] | None:
    """For g acting on {± min vectors}, return (perm, signs) with
    ``g · (min_vectors[j]) = signs[j] · min_vectors[perm[j]]``.

    Returns ``None`` if g does not preserve the signed set — indicates
    the Gram-matrix-based Aut captured a vector not in our min-vector
    set (in which case the stabilizer-of-set is a proper subgroup of
    Aut(G), and the caller should handle this case explicitly).
    """
    dim = len(min_vectors)
    perm = [-1] * dim
    signs = [0] * dim
    # Build lookup: row tuple → j.  We need to match g·v against ± rows.
    lookup: dict[tuple[int, ...], tuple[int, int]] = {}
    for j, row in enumerate(min_vectors):
        lookup[row] = (j, 1)
        lookup[tuple(-x for x in row)] = (j, -1)
    for j, row in enumerate(min_vectors):
        gv = tuple(_apply_g_to_row(g, row))
        hit = lookup.get(gv)
        if hit is None:
            return None
        target, sign = hit
        perm[j] = target
        signs[j] = sign
    # Must be a permutation — no repeats.
    if sorted(perm) != list(range(dim)):
        return None
    return perm, signs


def _perm_sign(perm: list[int]) -> int:
    """Sign of a permutation, via inversion count."""
    n = len(perm)
    inversions = 0
    for i in range(n):
        for j in range(i + 1, n):
            if perm[i] > perm[j]:
                inversions += 1
    return -1 if inversions % 2 else 1


def orientation_signs(
    cell: VoronoiCell, generators: list[list[list[int]]]
) -> list[int]:
    """χ_σ(g) for each g in ``generators``.

    Entries are ±1. Raises ``ValueError`` if any generator does not
    preserve the signed min-vector set (should not happen for
    perfect-form cells with a correctly computed Aut(G)).
    """
    out: list[int] = []
    for g in generators:
        spd = _signed_permutation_of(g, cell.min_vectors)
        if spd is None:
            raise ValueError(
                "generator does not permute the signed min-vector set; "
                "Aut(G) may include isometries that move vectors outside "
                "the cell's designated min-vector set. This needs a "
                "qfminim verification step — see voronoi.stab."
            )
        perm, _signs = spd
        out.append(_perm_sign(perm))
    return out


def has_orientation_reversing(cell: VoronoiCell) -> bool:
    """True iff ∃ g ∈ Stab(σ) with χ_σ(g) = −1.

    Equivalently: σ contributes 0 to C_n(Vor_{GL_N}) mod 2-torsion.

    Uses :func:`voronoi.stab.cell_stabilizer` which constructs Stab(σ)
    via the realizability LP witness Gram (resolves OQ1 via the
    LP-witness path; but see :func:`has_orientation_reversing_exact`
    for the exact, brute-force-but-correct alternative when the
    qfauto-with-shv subgroup undercounts Stab).
    """
    from voronoi.stab import cell_stabilizer

    stab = cell_stabilizer(cell)
    signs = orientation_signs(cell, stab.generators)
    return any(s == -1 for s in signs)


def has_orientation_reversing_exact(cell: VoronoiCell) -> bool:
    """Exact check via signed-permutation enumeration.

    For each (π, ε) ∈ S_n × {±1}^n with sign(π) = -1, check whether
    there exists ``g ∈ GL_N(Z)`` with ``g · v_i = ε_i v_{π(i)}`` for
    all i. If yes, return True (orientation-reversing element exists).
    If no odd permutation yields a valid g, return False.

    Algorithm (vectorized): for each odd permutation π,

        W = V[:, π] · diag(ε)        (over all 2^n sign vectors, batched)
        g_num = W · adj(V)           (integer)
        g = g_num / det(V)           (integer iff divisible everywhere)

    Uses exact integer arithmetic (no FP rounding step beyond np.round
    for adj(V), which is verified by V·adj(V) = det(V)·I).

    Runtime: ``O(n!/2 · 2^n · N^3)`` arithmetic ops, fully vectorized
    over the 2^n sign axis. For n=N=8 this is ≤ ~1 sec per cell with
    early termination.

    Args:
        cell: a :class:`VoronoiCell` with ``cell.dim == cell.lattice_rank``.

    Returns:
        ``True`` iff some odd signed permutation lifts to ``g ∈ Stab(σ)``.
    """
    import itertools

    import numpy as np

    n = cell.dim
    N = cell.lattice_rank
    if n != N:
        raise ValueError(
            f"exact orientation check requires n = N (square M); got "
            f"n={n}, N={N}"
        )

    # V: (N, n), columns = min vectors v_i (column form).
    V = np.array(cell.min_vectors, dtype=np.int64).T

    det_V = int(round(float(np.linalg.det(V.astype(np.float64)))))
    if det_V == 0:
        raise ValueError("V is singular — cell's min vectors aren't LI")

    # adj(V) = det(V) · V^{-1}, integer.
    V_inv_float = np.linalg.inv(V.astype(np.float64))
    adj_V = np.round(det_V * V_inv_float).astype(np.int64)
    if not np.array_equal(V @ adj_V, det_V * np.eye(n, dtype=np.int64)):
        raise RuntimeError("adj(V) integerization failed (FP precision issue)")

    abs_det = abs(det_V)
    sign_det = 1 if det_V > 0 else -1

    # Pre-build all 2^n sign vectors as a (2^n, n) int64 matrix.
    eps_all = np.empty((2 ** n, n), dtype=np.int64)
    for k in range(2 ** n):
        for i in range(n):
            eps_all[k, i] = 1 if (k >> i) & 1 else -1

    # Pre-build odd permutations as a list.
    odd_perms: list[tuple[int, ...]] = []
    for pi in itertools.permutations(range(n)):
        inversions = 0
        for i in range(n):
            for j in range(i + 1, n):
                if pi[i] > pi[j]:
                    inversions += 1
        if inversions % 2 == 1:
            odd_perms.append(pi)

    eye_n = np.eye(n, dtype=np.int64)

    for pi in odd_perms:
        V_pi = V[:, list(pi)]                        # (N, n)
        # W_batch[k, :, j] = eps_all[k, j] * V_pi[:, j]
        W_batch = V_pi[None, :, :] * eps_all[:, None, :]    # (2^n, N, n)
        g_num = W_batch @ adj_V[None, :, :]                  # (2^n, N, N)
        # Divisibility: g_num % abs_det == 0 entrywise.
        divisibility_ok = np.all(g_num % abs_det == 0, axis=(1, 2))
        if not divisibility_ok.any():
            continue
        valid = np.where(divisibility_ok)[0]
        # For valid k's: g_int = sign_det * (g_num[k] // abs_det).
        for k in valid:
            g_int = sign_det * (g_num[k] // abs_det)
            # Verify exact: g_int · V == W_batch[k].
            if not np.array_equal(g_int @ V, W_batch[k]):
                continue
            # |det g_int| must be 1 (unimodular).
            det_g = int(round(float(np.linalg.det(g_int.astype(np.float64)))))
            if abs(det_g) == 1:
                return True
    return False
