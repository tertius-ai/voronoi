"""Orientation character χ_σ : Stab(σ) → {±1}.

For a cell σ of dimension ``dim`` with min-vector matrix
M ∈ Z^{dim × N}, an element g ∈ Stab(σ) permutes the signed set
{±row_i(M)}. The induced action on the top exterior power of the
span of the min vectors is ±1; this sign is χ_σ(g).

Concretely: g · M = P_g · M (as row-transformation on the signed
min-vector set), where P_g is a signed permutation matrix on the
``dim`` rows. Then χ_σ(g) = det(P_g) ∈ {±1}.

The paper proves Σ_n(GL_8) = 0 for n ∈ {8..12} by showing χ_σ is
*not identically +1* for every cell — equivalently, for every σ
there exists g ∈ Stab(σ) with χ_σ(g) = -1.

This module is a stub until ``stab.stabilizer_generators`` is wired.
"""

from __future__ import annotations

from voronoi.cells import VoronoiCell


def orientation_is_preserving(cell: VoronoiCell) -> bool:
    """True iff χ_σ is identically +1 on Stab(σ).

    A cell with ``orientation_is_preserving(σ) == False`` contributes
    0 to the Voronoi chain group C_n(Vor_{GL_N}) mod 2-torsion.

    TODO: depends on ``voronoi.stab.stabilizer_generators`` which
    depends on ``noether.api.lattice.automorphism``.
    """
    raise NotImplementedError(
        "orientation character requires stabilizer generators "
        "(see voronoi.stab and PLAN.md)."
    )
