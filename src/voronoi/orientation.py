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
    """
    from voronoi.stab import stabilizer

    stab = stabilizer(cell)
    signs = orientation_signs(cell, stab.generators)
    return any(s == -1 for s in signs)
