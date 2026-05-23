"""Parser sanity tests. Skip cleanly when the database isn't fetched."""

from __future__ import annotations

from pathlib import Path

import pytest

from voronoi.parse import parse_list_shv_file

_DATA_ROOT = Path(__file__).parent.parent / "data" / "elbazvip-Voronoi-complexes-database" / "DATA_pari"

# Cell-orbit counts per (lattice_rank N, cell_dim n) from the paper's
# Table NrOrbitCones_Perfect. Used as a reproducibility checkpoint:
# our parser must yield exactly these counts on the shipped files.
EXPECTED_COUNTS: dict[tuple[int, int], int] = {
    (8, 8): 13,
    (8, 9): 106,
    (8, 10): 783,
    (8, 11): 6167,
    (8, 12): 50645,
    (9, 9): 44,
    (9, 10): 759,
    (9, 11): 13437,
    (10, 10): 283,
    (10, 11): 16062,
    (11, 11): 6674,
}


def _file_for(N: int, n: int) -> Path:
    return _DATA_ROOT / f"ListSHV_n{N}_rank{n}"


@pytest.fixture(scope="module")
def data_available() -> bool:
    return _DATA_ROOT.exists()


@pytest.mark.parametrize(
    "N,n,expected",
    [(N, n, exp) for (N, n), exp in EXPECTED_COUNTS.items()],
)
def test_orbit_count_matches_paper(N, n, expected, data_available):
    if not data_available:
        pytest.skip("database not fetched — run scripts/fetch_database.sh")
    path = _file_for(N, n)
    if not path.exists():
        pytest.skip(f"{path.name} not in database (partial clone)")
    cells = parse_list_shv_file(path)
    assert len(cells) == expected, (
        f"{path.name}: parsed {len(cells)} cells, paper says {expected}"
    )


def test_cell_shape_smallest(data_available):
    """The smallest corpus (N=8, n=8, 13 cells) must parse and all
    cells must have the advertised shape (dim × lattice_rank)."""
    if not data_available:
        pytest.skip("database not fetched")
    path = _file_for(8, 8)
    if not path.exists():
        pytest.skip("n8_rank8 not in database")
    cells = parse_list_shv_file(path)
    assert len(cells) == 13
    for c in cells:
        assert c.lattice_rank == 8
        assert c.dim == 8
        assert len(c.min_vectors) == 8
        for row in c.min_vectors:
            assert len(row) == 8


def test_cell_shape_larger_dim(data_available):
    """For (N=8, n=12) — dim/col asymmetry check."""
    if not data_available:
        pytest.skip("database not fetched")
    path = _file_for(8, 12)
    if not path.exists():
        pytest.skip("n8_rank12 not in database")
    cells = parse_list_shv_file(path)
    assert len(cells) == 50645
    sample = cells[0]
    assert sample.lattice_rank == 8
    assert sample.dim == 12
    assert len(sample.min_vectors) == 12
    assert all(len(row) == 8 for row in sample.min_vectors)
