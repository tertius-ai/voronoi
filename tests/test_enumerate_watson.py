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
from voronoi.enumerate import (
    enumerate_index_1_cells,
    enumerate_index_2_cells,
    enumerate_index_3_cells,
    enumerate_index_4_cyclic_cells,
    enumerate_index_5_cells,
)
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


def test_index_3_n8_count() -> None:
    """2 cells: weights 7 and 8 (Watson constraint ∑|a_i| > 2d = 6)."""
    enumerated = enumerate_index_3_cells(8)
    assert len(enumerated) == 2


def test_index_3_n_too_small_returns_empty() -> None:
    """No d=3 cells with s=n in dim < 7."""
    for n in range(1, 7):
        assert enumerate_index_3_cells(n) == []


def test_index_3_n8_each_matches_one_database_cell() -> None:
    """Each of the 2 enumerated d=3 cells must match exactly one
    database cell."""
    enumerated = enumerate_index_3_cells(8)
    assert len(enumerated) == 2

    path = _DATA / "ListSHV_n8_rank8"
    if not path.exists():
        pytest.skip(f"{path.name} not fetched")
    db_cells = parse_list_shv_file(path)

    matched_db: set[int] = set()
    for w_idx, enum_cell in enumerate(enumerated):
        matches = [i for i, c in enumerate(db_cells) if _cells_match(enum_cell, c)]
        weight = w_idx + 7
        assert len(matches) == 1, (
            f"d=3 w={weight}: expected exactly one db match, got {matches}"
        )
        matched_db.add(matches[0])
    assert len(matched_db) == 2


def test_index_1_2_3_together_cover_7_distinct_db_cells() -> None:
    """Combined d=1, d=2, d=3 enumerations should distinguish 7 cells
    (1 + 4 + 2) and cover 7 distinct database cells."""
    all_enumerated = (
        enumerate_index_1_cells(8)
        + enumerate_index_2_cells(8)
        + enumerate_index_3_cells(8)
    )
    assert len(all_enumerated) == 7

    path = _DATA / "ListSHV_n8_rank8"
    if not path.exists():
        pytest.skip(f"{path.name} not fetched")
    db_cells = parse_list_shv_file(path)

    matched_db: set[int] = set()
    for enum_cell in all_enumerated:
        matches = [i for i, c in enumerate(db_cells) if _cells_match(enum_cell, c)]
        assert len(matches) == 1
        matched_db.add(matches[0])
    assert len(matched_db) == 7


@pytest.mark.slow
def test_index_4_cyclic_n8_count() -> None:
    """4 cells: enumerated from 16 Z/4Z compositions then filtered via
    is_realizable_min_vector_set + qfisom dedupe."""
    cells = enumerate_index_4_cyclic_cells(8)
    assert len(cells) == 4


@pytest.mark.slow
def test_index_4_cyclic_n8_each_matches_one_database_cell() -> None:
    """The 4 enumerated d=4 cyclic cells should each match exactly one
    database cell."""
    enumerated = enumerate_index_4_cyclic_cells(8)
    assert len(enumerated) == 4

    path = _DATA / "ListSHV_n8_rank8"
    if not path.exists():
        pytest.skip(f"{path.name} not fetched")
    db_cells = parse_list_shv_file(path)

    matched_db: set[int] = set()
    for enum_cell in enumerated:
        matches = [i for i, c in enumerate(db_cells) if _cells_match(enum_cell, c)]
        assert len(matches) == 1
        matched_db.add(matches[0])
    assert len(matched_db) == 4


@pytest.mark.slow
def test_d1_through_d4_cyclic_cover_11_distinct_db_cells() -> None:
    """Combined d=1, d=2, d=3, d=4-cyclic enumerations: 1 + 4 + 2 + 4 = 11
    distinct database cells. (Remaining 2: d=2² Klein, d=5.)"""
    all_enumerated = (
        enumerate_index_1_cells(8)
        + enumerate_index_2_cells(8)
        + enumerate_index_3_cells(8)
        + enumerate_index_4_cyclic_cells(8)
    )
    assert len(all_enumerated) == 11

    path = _DATA / "ListSHV_n8_rank8"
    if not path.exists():
        pytest.skip(f"{path.name} not fetched")
    db_cells = parse_list_shv_file(path)

    matched_db: set[int] = set()
    for enum_cell in all_enumerated:
        matches = [i for i, c in enumerate(db_cells) if _cells_match(enum_cell, c)]
        assert len(matches) == 1, f"expected one match, got {matches}"
        matched_db.add(matches[0])
    assert len(matched_db) == 11


@pytest.mark.slow
def test_index_5_n8_count() -> None:
    """1 cell per [DSEKM19] Table 2."""
    cells = enumerate_index_5_cells(8)
    assert len(cells) == 1


@pytest.mark.slow
def test_index_5_n8_matches_database() -> None:
    """The unique d=5 cell should match exactly one database cell."""
    cells = enumerate_index_5_cells(8)
    assert len(cells) == 1
    path = _DATA / "ListSHV_n8_rank8"
    if not path.exists():
        pytest.skip(f"{path.name} not fetched")
    db_cells = parse_list_shv_file(path)
    matches = [i for i, c in enumerate(db_cells) if _cells_match(cells[0], c)]
    assert len(matches) == 1


@pytest.mark.slow
def test_d1_through_d5_cover_12_distinct_db_cells() -> None:
    """Combined d=1, d=2, d=3, d=4-cyclic, d=5 enumerations:
    1 + 4 + 2 + 4 + 1 = 12 distinct database cells. (Remaining 1: d=2².)"""
    all_enumerated = (
        enumerate_index_1_cells(8)
        + enumerate_index_2_cells(8)
        + enumerate_index_3_cells(8)
        + enumerate_index_4_cyclic_cells(8)
        + enumerate_index_5_cells(8)
    )
    assert len(all_enumerated) == 12

    path = _DATA / "ListSHV_n8_rank8"
    if not path.exists():
        pytest.skip(f"{path.name} not fetched")
    db_cells = parse_list_shv_file(path)

    matched_db: set[int] = set()
    for enum_cell in all_enumerated:
        matches = [i for i, c in enumerate(db_cells) if _cells_match(enum_cell, c)]
        assert len(matches) == 1
        matched_db.add(matches[0])
    assert len(matched_db) == 12
