"""Verify the 13 published (N=8, n=8) cells are 13 distinct orbits.

Independent confirmation that the orbit count from arXiv:1910.11598
holds when reproduced via PARI's qfisom on centroid Gram forms.

For each cell σ with min-vector matrix M (rows = v_i), the centroid
Gram form is

    A_σ = M^T M = Σ_i v_i v_i^T

which lies in σ's relative interior. Two cells σ_1, σ_2 are
GL_N(Z)-equivalent iff their centroid Gram forms are GL-isometric (the
GL action on σ-space is by congruence g · σ · g^T, and the centroid is
GL-equivariant). So pairwise qfisom on the centroids gives the orbit
partition.

Result: 13/13 distinct equivalence classes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

try:
    from noether.api.lattice import isometry
except ImportError:
    pytest.skip("noether not available", allow_module_level=True)

from voronoi.cells import VoronoiCell
from voronoi.parse import parse_list_shv_file

_DATA = (
    Path(__file__).parent.parent
    / "data"
    / "elbazvip-Voronoi-complexes-database"
    / "DATA_pari"
)


def _gram_centroid(cell: VoronoiCell) -> list[list[int]]:
    """A_σ = Σ_v v v^T."""
    n = cell.lattice_rank
    g = [[0] * n for _ in range(n)]
    for v in cell.min_vectors:
        for i in range(n):
            for j in range(n):
                g[i][j] += v[i] * v[j]
    return g


def test_13_published_cells_are_13_distinct_orbits() -> None:
    path = _DATA / "ListSHV_n8_rank8"
    if not path.exists():
        pytest.skip(f"{path.name} not fetched; run scripts/fetch_database.sh")

    cells = parse_list_shv_file(path)
    assert len(cells) == 13

    grams = [_gram_centroid(c) for c in cells]

    # Union-find over pairwise qfisom verdicts.
    parent = list(range(len(cells)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        parent[find(x)] = find(y)

    for i in range(len(cells)):
        for j in range(i + 1, len(cells)):
            if find(i) == find(j):
                continue
            if isometry(grams[i], grams[j]) is not None:
                union(i, j)

    classes: set[int] = {find(i) for i in range(len(cells))}
    assert len(classes) == 13, (
        f"expected 13 distinct GL_8(Z) orbits per [DSEKM19] Table 2, "
        f"got {len(classes)}"
    )
