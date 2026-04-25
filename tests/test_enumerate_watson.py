"""Watson enumeration vs the published orbit database.

Each test enumerates cells of a given index from scratch (not from the
database), then matches each enumerated cell against the database via
qfisom on centroid Gram forms — the same orbit invariant used in
``test_orbit_dedupe_published.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

try:
    from noether.api.lattice import isometry
except ImportError:
    pytest.skip("noether not available", allow_module_level=True)

from voronoi.cells import VoronoiCell
from voronoi.enumerate import enumerate_index_1_cells
from voronoi.parse import parse_list_shv_file

_DATA = (
    Path(__file__).parent.parent
    / "data"
    / "elbazvip-Voronoi-complexes-database"
    / "DATA_pari"
)


def _gram_centroid(cell: VoronoiCell) -> list[list[int]]:
    n = cell.lattice_rank
    g = [[0] * n for _ in range(n)]
    for v in cell.min_vectors:
        for i in range(n):
            for j in range(n):
                g[i][j] += v[i] * v[j]
    return g


def _cells_match(a: VoronoiCell, b: VoronoiCell) -> bool:
    """Two cells are GL_n(Z)-equivalent iff their centroid Gram forms
    are GL-isometric."""
    return isometry(_gram_centroid(a), _gram_centroid(b)) is not None


def test_index_1_n8_matches_database_cell_0() -> None:
    """The unique index-1 cell at (N=8, n=8) is the standard basis,
    which is cell 0 in the published `ListSHV_n8_rank8` file."""
    enumerated = enumerate_index_1_cells(8)
    assert len(enumerated) == 1, "Watson Table 2: 1 orbit at index 1"
    enum_cell = enumerated[0]

    path = _DATA / "ListSHV_n8_rank8"
    if not path.exists():
        pytest.skip(f"{path.name} not fetched")
    db_cells = parse_list_shv_file(path)

    matches = [i for i, c in enumerate(db_cells) if _cells_match(enum_cell, c)]
    assert len(matches) == 1, (
        f"index-1 enumerated cell should match exactly one database cell; "
        f"got matches at {matches}"
    )


def test_index_1_validation_n_too_small() -> None:
    with pytest.raises(ValueError, match="n must be"):
        enumerate_index_1_cells(0)
