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
from voronoi.enumerate import enumerate_index_1_cells, enumerate_index_2_cells
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


def test_index_2_n8_count() -> None:
    """4 cells: weights 5, 6, 7, 8."""
    enumerated = enumerate_index_2_cells(8)
    assert len(enumerated) == 4


def test_index_2_n_too_small_returns_empty() -> None:
    """No d=2 cells with s=n in dim < 5."""
    for n in range(1, 5):
        assert enumerate_index_2_cells(n) == []


def test_index_2_n8_each_matches_one_database_cell() -> None:
    """Each of the 4 enumerated d=2 cells must match exactly one
    database cell, and the 4 must collectively map to 4 distinct
    database cells."""
    enumerated = enumerate_index_2_cells(8)
    assert len(enumerated) == 4

    path = _DATA / "ListSHV_n8_rank8"
    if not path.exists():
        pytest.skip(f"{path.name} not fetched")
    db_cells = parse_list_shv_file(path)

    matched_db: set[int] = set()
    for w_idx, enum_cell in enumerate(enumerated):
        matches = [i for i, c in enumerate(db_cells) if _cells_match(enum_cell, c)]
        weight = w_idx + 5
        assert len(matches) == 1, (
            f"w={weight}: expected exactly one db match, got {matches}"
        )
        matched_db.add(matches[0])
    assert len(matched_db) == 4, (
        f"4 enumerated cells should map to 4 distinct db cells, got {matched_db}"
    )


def test_index_1_and_2_together_cover_5_distinct_db_cells() -> None:
    """Combined d=1 and d=2 enumerations should distinguish 5 database
    cells (1 + 4) — and we should be able to confirm none of them
    overlap."""
    all_enumerated = enumerate_index_1_cells(8) + enumerate_index_2_cells(8)
    assert len(all_enumerated) == 5

    path = _DATA / "ListSHV_n8_rank8"
    if not path.exists():
        pytest.skip(f"{path.name} not fetched")
    db_cells = parse_list_shv_file(path)

    matched_db: set[int] = set()
    for enum_cell in all_enumerated:
        matches = [i for i, c in enumerate(db_cells) if _cells_match(enum_cell, c)]
        assert len(matches) == 1
        matched_db.add(matches[0])
    assert len(matched_db) == 5
