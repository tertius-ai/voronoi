"""Homology of the Voronoi chain complex, delegating to noether.

H_k(Vor_{GL_N}; Z) from a chain complex of sparse integer boundary
matrices. Delegates to ``noether.api.snf`` / ``noether.api.smooth_snf``
for the actual SNF prime sweep — this module is glue, not algorithm.
"""

from __future__ import annotations


def homology_mod_torsion(boundary_n, boundary_np1):
    """Rank of H_k given ∂_k and ∂_{k+1} as sparse integer matrices.

    TODO: delegate to ``noether.api.smooth_snf``.
    """
    raise NotImplementedError("homology stub; Layer A task.")
