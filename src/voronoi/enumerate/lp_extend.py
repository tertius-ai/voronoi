"""LP-based cell enumeration: extend cells by one min-vector dimension.

Implements [DSEKM19] §3 in concrete form. Given a cell σ at (N, n) with
min-vector set V, enumerate cells at (N, n+1) that are formed by adding
one more vector u to V's set. Each extension V ∪ {u} is tested for
realizability via :func:`noether.api.lattice.is_realizable_min_vector_set`.

This is the basic building block for enumerating cells beyond the
Watson `n = N` case — particularly the (N, n=12) cells we need at
N ∈ {9, 10, 11} for the K_12(Z) program.

Empirical status (diagnostic suite, 2026-05-23)
-----------------------------------------------

The "add one min-vector at a time" model is **sound** for the
(N=8, n=8) → (N=8, n=9) layer:

  - All 106 published (N=8, n=9) orbits are simplicial-cone cofaces
    (``|Min(τ)| = 9`` = cone dimension), so each one is reachable in
    principle by adding a single vector to some 8-pair subset that
    matches an (N=8, n=8) orbit. No polyhedral-incompleteness gap.

Subprocess-isolated ``extend_layer`` over the 13 (N=8, n=8) cells at
``norm_excess_factor=2`` produces 775 raw extensions across 8 cells
(0–7); cells 8–12 crash or time out in PARI's lattice code (see below).
qfisom dedup on centroid Grams (which phase 4 confirmed is a faithful
invariant on this layer) collapses the 775 to 28 distinct orbits — a
73.6 % gap against the 106 published.

Per-target trace decomposes the 78 missing:

  - 25 are reachable at ``norm_excess_factor=2`` (already in our 28);
  - 73 need a larger bound — the extending vector ``u`` has
    ``A_V[u] / denom`` distributed median 4.0, max 72.0
    (15 in [2,3), 21 in [3,4), 9 in [4,5), 20 in [5,8), 5 in [8,16),
    3 in [16,72]);
  - 0 are blocked by LP false-negatives (hypothesis "LP rejects
    realizable seed" never fires at the 300-iteration default);
  - 7 sit on cells 8–12 alone — unreachable without those cells running.

So the gap is dominated by the search-radius parameter, not by the
model or by LP convergence.

The PARI wall blocks bumping the bound
--------------------------------------

Raising ``norm_excess_factor`` doesn't work: at larger bounds,
``qfminim``'s ``lllgramint`` preprocessing trips on ill-conditioned-
but-PD integer Grams far more often, and the per-candidate LP loop
multiplies the exposures. Validated 2026-05-23:
``norm_excess_factor=8`` triggers PARI segfaults on every n=8 cell
(cell 0 after ~26 min, cells 1–7 within seconds), recovering 0 orbits.
``norm_excess_factor=2`` is the safe default until one of the noether-
side fixes lands:

  (a) Rust ``cb_pari_err_recover`` + setjmp landing pad in
      :mod:`noether_engine.session` — proper recovery;
  (b) subprocess isolation of the ``qfminim`` call — robust, slow;
  (c) LLL pre-reduction of ``A_int`` via FLINT before handing to
      ``qfminim``, so the ``lllgramint`` rejection path doesn't fire.

Once one of those lands, ``norm_excess_factor=8`` should catch 67 of
the 73 norm-bound-blocked cells (the [16,72] tail needs adaptive bound),
pushing recovery from 28/106 to ≈ 92/99 reachable.

Engineering hooks remaining
---------------------------

``RuntimeError: realize_min_vector_set: did not converge`` is wrapped
``try/except → False`` per-candidate (graceful degradation), but per
the trace this path never fires on the 99 reachable n=9 targets at the
default 300-iteration budget — it's purely defensive.

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
    realizability_max_iterations: int = 200,
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
            min(A). Default 2 is the **only** safe value at present —
            see the module docstring's "PARI wall" section. Larger
            values trigger ``qfminim``/``lllgramint`` segfaults in the
            per-candidate LP loop until one of the noether-engine
            mitigations lands. Once the wall is gone, 8 is the natural
            production bound and recovers ≈ 92/99 of (N=8, n=9).
        realizability_max_iterations: passed through to the LP loop.
            Trace data shows the default catches every realizable
            target on the (N=8, n=9) layer; no bump needed.

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

    # backend="python": route through noether's pure-Python
    # Fincke–Pohst enumerator. PARI's qfminim crashes uncatchably on
    # the ill-conditioned LP-emitted Grams this pipeline produces at
    # any norm_excess_factor > 2 (and even at 2 for some cells); the
    # python backend is crash-immune and parity-tested.
    sv = short_vectors(A, bound=norm_excess_factor * denom, backend="python")

    v_set: set[tuple[int, ...]] = set()
    for v in V:
        v_set.add(tuple(v))
        v_set.add(tuple(-x for x in v))

    extensions: list[VoronoiCell] = []
    for u in sv.vectors:
        if tuple(u) in v_set or tuple(-x for x in u) in v_set:
            continue
        V_extended = V + [u]
        try:
            realizable = is_realizable_min_vector_set(
                V_extended, max_iterations=realizability_max_iterations
            )
        except RuntimeError:
            # Convergence failure within the LP loop's iteration budget
            # is treated as "not realizable" (false-negative tolerated).
            # Bump ``realizability_max_iterations`` to reduce these.
            realizable = False
        if realizable:
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
    realizability_max_iterations: int = 200,
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
