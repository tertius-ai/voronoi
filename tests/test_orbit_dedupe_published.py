"""Verify the 13 published ``(N=8, r=8)`` cells are distinct orbits.

Noether returns an exact unimodular transformation and induced line
permutation for every positive equivalence verdict.  The native search is the
correctness floor; this test no longer depends on a PARI centroid-isometry
proxy.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from voronoi.parse import parse_list_shv_file

pytestmark = pytest.mark.corpus

_DATA = (
    Path(__file__).parent.parent
    / "data"
    / "elbazvip-Voronoi-complexes-database"
    / "DATA_pari"
)


def test_13_published_cells_are_13_distinct_orbits() -> None:
    path = _DATA / "ListSHV_n8_rank8"
    if not path.exists():
        pytest.skip(f"{path.name} not fetched; run scripts/fetch_database.sh")

    cells = parse_list_shv_file(path)
    assert len(cells) == 13

    # Union-find over exact configuration-equivalence verdicts.
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
            equivalence = cells[i].configuration.equivalence_to(cells[j].configuration)
            if equivalence is not None:
                equivalence.verify()
                union(i, j)

    classes: set[int] = {find(i) for i in range(len(cells))}
    assert len(classes) == 13, (
        f"expected 13 distinct GL_8(Z) orbits per [DSEKM19] Table 2, got {len(classes)}"
    )
