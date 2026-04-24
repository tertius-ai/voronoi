"""Voronoi chain complex assembly.

Given per-dimension cell orbits, build the boundary maps
∂_n : C_n(Vor_{GL_N}) → C_{n-1}(Vor_{GL_N}) as sparse integer
matrices. Entries are incidence coefficients ±1 · (orientation of
Stab).

Stub — fills in during Layer A once parsing + stabilizers are live.
"""

from __future__ import annotations


def boundary_matrix(dim_n_cells, dim_nm1_cells):
    raise NotImplementedError("boundary_matrix stub; Layer A task.")
