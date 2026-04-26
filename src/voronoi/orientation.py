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

    Currently delegates to the brute-force exact path
    :func:`has_orientation_reversing_exact`, which is correct but
    scales poorly for n > 10.

    The faster :func:`has_orientation_reversing_via_aut` (BFS over
    Aut(G_centroid)) is correct in principle (Stab ⊂ left-action Aut)
    but empirically gives false negatives on (N=8, n=11) cells —
    PARI's qfauto(G) appears to under-count Aut for those cells, or
    there is a subtle convention mismatch. Investigation pending.
    """
    return has_orientation_reversing_exact(cell)


def _check_via_aut_bfs(cell: VoronoiCell, aut) -> bool:
    """Helper: BFS over Aut(G) filtering to SetStab. ``aut`` is a
    pre-computed :class:`AutomorphismGroup`.

    Convention: PARI's ``qfauto`` returns ``g`` with ``g^T G g = G``
    (right action). Stab(σ) acts left: ``g · v_i ∈ ±V`` and
    correspondingly ``g · G · g^T = G``. Transposing flips between
    the two conventions: ``h = g^T`` satisfies ``h G h^T = G`` exactly
    when ``g`` satisfies ``g^T G g = G``. So we transpose PARI's
    generators before BFS — the left-action group is generated by the
    transposes.
    """
    import numpy as np

    n = cell.dim
    N = cell.lattice_rank
    V = np.array(cell.min_vectors, dtype=np.int64)
    # Transpose PARI's generators: convert right-action Aut → left-action Stab.
    gens = [np.array(g, dtype=np.int64).T for g in aut.generators]

    v_pair_idx: dict[bytes, int] = {}
    for i in range(n):
        v_pair_idx[V[i].tobytes()] = i
        v_pair_idx[(-V[i]).tobytes()] = i

    I = np.eye(N, dtype=np.int64)
    seen: set[bytes] = {I.tobytes()}
    frontier: list[np.ndarray] = [I]
    while frontier:
        h = frontier.pop()
        images = h @ V.T
        pi: list[int] = []
        ok = True
        for j in range(n):
            idx = v_pair_idx.get(images[:, j].tobytes())
            if idx is None:
                ok = False
                break
            pi.append(idx)
        if ok and len(set(pi)) == n:
            inv = 0
            for i in range(n):
                for j in range(i + 1, n):
                    if pi[i] > pi[j]:
                        inv += 1
            if inv % 2 == 1:
                return True
        for g in gens:
            h_new = h @ g
            key = h_new.tobytes()
            if key not in seen:
                seen.add(key)
                frontier.append(h_new)
    return False


def _gram_centroid_int(cell: VoronoiCell) -> list[list[int]]:
    """Centroid Gram form A_σ = Σ_v v v^T (integer)."""
    n = cell.lattice_rank
    g = [[0] * n for _ in range(n)]
    for v in cell.min_vectors:
        for i in range(n):
            for j in range(n):
                g[i][j] += v[i] * v[j]
    return g


def has_orientation_reversing_via_aut(
    cell: VoronoiCell,
    *,
    max_aut_size: int = 5_000_000,
) -> bool:
    """BFS over Aut(G_centroid) (which contains SetStab(±V) ⊃ Stab(σ))
    looking for an orientation-reversing element.

    Used as the inner of two algorithms behind
    :func:`has_orientation_reversing`. Raises :class:`RuntimeError`
    when ``|Aut(G)| > max_aut_size``.
    """
    from noether.api.lattice import automorphism_group

    aut = automorphism_group(_gram_centroid_int(cell))
    if int(aut.order) > max_aut_size:
        raise RuntimeError(
            f"|Aut(G)| = {int(aut.order)} > max_aut_size={max_aut_size}"
        )
    return _check_via_aut_bfs(cell, aut)


def has_orientation_reversing_exact(cell: VoronoiCell) -> bool:
    """Exact check via signed-permutation enumeration. Handles both
    ``n = N`` (square M, basis cells) and ``n > N`` (over-determined M,
    cells with more min vectors than lattice rank).

    For each candidate signed permutation `(π, ε)`, attempt to solve
    `g · v_i = ε_i v_{π(i)}` with `g ∈ GL_N(Z)`. Return ``True`` on
    finding any such `g` with `sign(π) = -1` (orientation-reversing).

    Algorithm:

    1. Find ``N`` linearly-independent rows of ``V`` (pivots).
    2. Enumerate ordered ``N``-tuples of distinct positions in
       ``{0, ..., n-1}`` (the image of pivots under π) and 2^N sign
       choices for the pivots. ``g`` is uniquely determined by these.
    3. Verify ``g`` is integer + unimodular.
    4. For each non-pivot ``v_i``, compute ``g · v_i`` and look up
       which ``±v_l`` it equals (if any). If consistent → full π
       and ε determined; check ``sign(π)``.

    For ``n = N``: no non-pivots; reduces to the simpler enumeration.
    For ``n > N``: most candidates are pruned by the consistency check.

    Runtime is roughly ``O((n!/(n-N)!) · 2^N · N^3)`` with vectorization
    over the 2^N sign axis. n=N=8: <1s. n=9, N=8: ~10s per cell with
    early termination. n=12 needs Schreier-Sims (out of scope here).
    """
    import itertools

    import numpy as np

    n = cell.dim
    N = cell.lattice_rank
    if n < N:
        raise ValueError(f"n < N not supported (got n={n}, N={N})")

    V = np.array(cell.min_vectors, dtype=np.int64)        # (n, N)

    # Find N linearly-independent rows of V (greedy from index 0).
    pivot_indices: list[int] = []
    chosen: list[np.ndarray] = []
    for i in range(n):
        trial = chosen + [V[i]]
        if np.linalg.matrix_rank(np.array(trial, dtype=np.float64)) > len(chosen):
            pivot_indices.append(i)
            chosen.append(V[i])
            if len(pivot_indices) == N:
                break
    if len(pivot_indices) != N:
        raise ValueError(
            f"V doesn't span Z^N: rank < N. n={n}, N={N}, found "
            f"{len(pivot_indices)} LI rows"
        )

    V_pivot = V[pivot_indices].T                          # (N, N), cols = pivot vectors
    det_V = int(round(float(np.linalg.det(V_pivot.astype(np.float64)))))
    if det_V == 0:
        raise RuntimeError("V_pivot singular")
    abs_det = abs(det_V)
    sign_det = 1 if det_V > 0 else -1

    V_inv_float = np.linalg.inv(V_pivot.astype(np.float64))
    adj_V = np.round(det_V * V_inv_float).astype(np.int64)
    if not np.array_equal(V_pivot @ adj_V, det_V * np.eye(N, dtype=np.int64)):
        raise RuntimeError("adj(V_pivot) integerization failed")

    # Lookup for "is u = ±v_l for some l?".
    v_lookup: dict[tuple[int, ...], tuple[int, int]] = {}
    for i in range(n):
        v_lookup[tuple(V[i].tolist())] = (i, 1)
        v_lookup[tuple((-V[i]).tolist())] = (i, -1)

    # All 2^N sign vectors for pivot signs.
    eps_all = np.empty((2 ** N, N), dtype=np.int64)
    for k in range(2 ** N):
        for i in range(N):
            eps_all[k, i] = 1 if (k >> i) & 1 else -1

    pivot_set = set(pivot_indices)

    # Enumerate ordered N-tuples (image of pivots under π).
    for image_tuple in itertools.permutations(range(n), N):
        V_image = V[list(image_tuple)].T                   # (N, N), cols = v_{image[k]}
        W_batch = V_image[None, :, :] * eps_all[:, None, :]
        g_num = W_batch @ adj_V[None, :, :]                 # (2^N, N, N)
        divisibility_ok = np.all(g_num % abs_det == 0, axis=(1, 2))
        if not divisibility_ok.any():
            continue
        valid_k = np.where(divisibility_ok)[0]
        for k in valid_k:
            g = sign_det * (g_num[k] // abs_det)
            if not np.array_equal(g @ V_pivot, W_batch[k]):
                continue
            det_g = int(round(float(np.linalg.det(g.astype(np.float64)))))
            if abs(det_g) != 1:
                continue

            # Build full (π, ε) including non-pivots.
            full_pi: list[int] = [-1] * n
            full_eps: list[int] = [0] * n
            for j in range(N):
                full_pi[pivot_indices[j]] = image_tuple[j]
                full_eps[pivot_indices[j]] = int(eps_all[k, j])

            consistent = True
            for i in range(n):
                if i in pivot_set:
                    continue
                u = (g @ V[i]).tolist()
                lookup = v_lookup.get(tuple(u))
                if lookup is None:
                    consistent = False
                    break
                full_pi[i], full_eps[i] = lookup

            if not consistent or len(set(full_pi)) != n:
                continue

            inversions = 0
            for i in range(n):
                for j in range(i + 1, n):
                    if full_pi[i] > full_pi[j]:
                        inversions += 1
            if inversions % 2 == 1:
                return True
    return False
