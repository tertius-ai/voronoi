"""Stabilizer Stab(σ) of a Voronoi cell σ in GL_N(Z).

Implementation depends on the libpari FFI binding in noether that
wraps PARI's ``qfauto``. That binding does not yet exist — see
PLAN.md's "What graduates to noether" table.

Until then, this module raises ``NotImplementedError`` with a
pointer to the noether feature to add.
"""

from __future__ import annotations

from voronoi.cells import VoronoiCell


def stabilizer_generators(cell: VoronoiCell) -> list[list[list[int]]]:
    """Generators of Stab(σ) ⊂ GL_N(Z), as integer matrices.

    TODO: implement once ``noether.api.lattice.automorphism`` lands.
    The algorithm:

    1. Build the min-vector matrix M ∈ Z^{dim × N}.
    2. Build the Gram matrix G = M · Q · M^T for a canonical Q ∈ σ.
       (For top-dim cells Q is unique; for lower-dim cells any
       interior-of-σ Q suffices — the stabilizer is independent of
       the choice.)
    3. Call ``noether.api.lattice.automorphism(G)`` which wraps
       PARI's qfauto and returns generators in GL_N(Z).
    4. Return them as nested Python lists.
    """
    raise NotImplementedError(
        "Stab(σ) requires noether.api.lattice.automorphism "
        "(libpari qfauto binding). See PLAN.md."
    )
