"""LP-based cell enumeration: extend cells by one min-vector dimension.

Implements [DSEKM19] §3 in concrete form. Given a cell σ at (N, n) with
min-vector set V, enumerate cells at (N, n+1) that are formed by adding
one more vector u to V's set. Each extension V ∪ {u} is tested for
realizability via :func:`noether.api.lattice.is_realizable_min_vector_set`.

This is the basic building block for enumerating cells beyond the
Watson `n = N` case — particularly the (N, n=12) cells we need at
N ∈ {9, 10, 11} for the K_12(Z) program.

**Status: WIP**, validated only on cell 0 of (N=8, n=8) (extends to 56
candidate cells at n=9). Cells 1+ trigger an uncatchable PARI error
``domain error in minim0: form is not positive definite`` from inside
the realizability LP loop on certain candidate extensions. The float
Cholesky PD check in :func:`noether.api.lattice.realize_min_vector_set`
passes for forms that PARI's exact arithmetic rejects. Need either
(a) a stricter integer PD check (Sylvester via Bareiss) before calling
qfminim, or (b) Rust-side catching of PARI domain errors.

References:
    [DSEKM19] arXiv:1910.11598 §3 "Enumeration of configurations of vectors"
"""

from __future__ import annotations

from typing import Iterable

from voronoi.cells import VoronoiCell


def extend_cell_by_one(
    cell: VoronoiCell,
    *,
    norm_excess_factor: int = 2,
    realizability_max_iterations: int = 100,
) -> list[VoronoiCell]:
    """Enumerate (N, n+1) candidate cells obtained by extending ``cell``
    (at (N, n)) with one new min vector ``u``.

    Algorithm:

    1. Compute a Gram witness ``A`` with ``Min(A) = ±V`` exactly via
       the realizability LP (``realize_min_vector_set``). The integer
       ``denom`` (the LP-scaled common norm) is `A[v]` for v ∈ V.
    2. Enumerate short vectors of ``A`` up to norm
       ``norm_excess_factor · denom`` via ``qfminim``. These are
       candidate "next-shortest" vectors u.
    3. Filter: drop any u with ``u ∈ ±V`` (already in V).
    4. For each remaining candidate u, test
       ``is_realizable_min_vector_set(V ∪ {u})``. Realizable
       extensions are returned as new cells.

    The ``norm_excess_factor`` controls search breadth. Most candidates
    fail the realizability LP; the successful ones are the legitimate
    Voronoi face-extensions of σ.

    Args:
        cell: input cell at (N, n).
        norm_excess_factor: bound for candidate u's norm relative to
            min(A). Default 2 covers common cases; higher catches more
            extensions but costs more LP calls.
        realizability_max_iterations: passed through to the LP loop.

    Returns:
        A list of :class:`VoronoiCell` instances, each at (N, n+1).
        Ordering is the order qfminim returned the candidates; downstream
        you typically want to qfisom-dedupe across all extensions.
    """
    import numpy as np

    from noether.api.lattice import (
        is_realizable_min_vector_set,
        realize_min_vector_set,
        short_vectors,
    )

    n = cell.dim
    N = cell.lattice_rank
    V = [list(v) for v in cell.min_vectors]

    A = realize_min_vector_set(V, max_iterations=realizability_max_iterations)
    if A is None:
        raise ValueError(
            "input cell's min-vector set is not realizable as Min(A) for any "
            "PD form A — σ may not be a valid Voronoi cell"
        )

    # denom = A[v_0] (constant across v ∈ V by construction).
    A_np = np.array(A, dtype=np.int64)
    v0 = np.array(V[0], dtype=np.int64)
    denom = int(v0 @ A_np @ v0)
    if denom <= 0:
        raise RuntimeError(f"witness Gram has non-positive A[v]: {denom}")

    # PARI's qfminim crashes uncatchably on non-PD or near-degenerate
    # input. Use noether's exact integer PD test (FLINT-backed
    # Sylvester) before calling.
    from noether.api.lattice import is_positive_definite

    if not is_positive_definite(A):
        return []

    sv = short_vectors(A, bound=norm_excess_factor * denom)

    v_set: set[tuple[int, ...]] = set()
    for v in V:
        v_set.add(tuple(v))
        v_set.add(tuple(-x for x in v))

    extensions: list[VoronoiCell] = []
    for u in sv.vectors:
        if tuple(u) in v_set or tuple(-x for x in u) in v_set:
            continue
        V_extended = V + [u]
        if is_realizable_min_vector_set(
            V_extended, max_iterations=realizability_max_iterations
        ):
            extensions.append(VoronoiCell.from_rows(V_extended))
    return extensions


def _gram_centroid(cell: VoronoiCell) -> list[list[int]]:
    """Centroid Gram form A_σ = Σ_v v v^T (used as an orbit invariant
    via qfisom)."""
    n = cell.lattice_rank
    g = [[0] * n for _ in range(n)]
    for v in cell.min_vectors:
        for i in range(n):
            for j in range(n):
                g[i][j] += v[i] * v[j]
    return g


def extend_layer(
    seeds: Iterable[VoronoiCell],
    *,
    norm_excess_factor: int = 2,
    realizability_max_iterations: int = 100,
) -> list[VoronoiCell]:
    """Extend a layer of cells at (N, n) to a layer at (N, n+1) and
    qfisom-dedupe the result.

    For each ``cell`` in ``seeds``, calls :func:`extend_cell_by_one` to
    produce candidate (N, n+1) cells, then deduplicates the union via
    :func:`noether.api.lattice.isometry` on centroid Gram forms.

    Returns the distinct (N, n+1) orbit representatives.
    """
    from noether.api.lattice import isometry

    raw: list[VoronoiCell] = []
    for cell in seeds:
        raw.extend(
            extend_cell_by_one(
                cell,
                norm_excess_factor=norm_excess_factor,
                realizability_max_iterations=realizability_max_iterations,
            )
        )

    distinct: list[VoronoiCell] = []
    distinct_grams: list[list[list[int]]] = []
    for cand in raw:
        cg = _gram_centroid(cand)
        is_new = True
        for d_gram in distinct_grams:
            if isometry(cg, d_gram) is not None:
                is_new = False
                break
        if is_new:
            distinct.append(cand)
            distinct_grams.append(cg)
    return distinct
