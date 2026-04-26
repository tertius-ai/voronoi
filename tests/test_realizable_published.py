"""Validate ``noether.api.lattice.is_realizable_min_vector_set`` on
the (N=8, n=8) cells from the published Voronoi orbit database.

Each of the 13 published cells must be flagged as realizable: by
construction the cells exist as faces of perfect-form cones, so a
positive-definite Gram form witnessing each one must exist. This is
the M3-validate milestone for the small-cell-enumeration program; the
full M3 (enumerate from scratch, match the count of 13, GL_8(Z)-orbit
dedupe) requires Watson index theory and ships separately.

Skips cleanly when the database isn't fetched or when the noether
engine ``.so`` isn't available.
"""

from __future__ import annotations

from pathlib import Path

import pytest

try:
    from noether.api.lattice import is_realizable_min_vector_set
except ImportError:
    pytest.skip("noether not available", allow_module_level=True)

from voronoi.parse import parse_list_shv_file

_DATA = (
    Path(__file__).parent.parent
    / "data"
    / "elbazvip-Voronoi-complexes-database"
    / "DATA_pari"
)


@pytest.mark.slow
def test_all_13_published_n8_n8_cells_are_realizable() -> None:
    path = _DATA / "ListSHV_n8_rank8"
    if not path.exists():
        pytest.skip(f"{path.name} not fetched; run scripts/fetch_database.sh")
    cells = parse_list_shv_file(path)
    assert len(cells) == 13, "paper says 13 orbits at (N=8, n=8)"
    for i, cell in enumerate(cells):
        V = [list(v) for v in cell.min_vectors]
        assert is_realizable_min_vector_set(V, max_iterations=100), (
            f"cell {i} is in the published database, hence realizable, but "
            f"is_realizable_min_vector_set returned False"
        )


def test_sigma_n8_GL8_equals_zero() -> None:
    """All 13 published (N=8, n=8) cells have an orientation-reversing
    element in Stab(σ), so Σ_n=8(GL_8) = 0 — matching [DSEKM19] Table 4.

    This verifies the K_8(Z) = 0 chain-complex input at the (n=8, N=8)
    corner: V_8(GL_8) = Z[Σ_n=8] = 0, hence H_8 = 0 mod 2-torsion.
    """
    from voronoi.orientation import has_orientation_reversing_exact

    path = _DATA / "ListSHV_n8_rank8"
    if not path.exists():
        pytest.skip(f"{path.name} not fetched")
    cells = parse_list_shv_file(path)
    n_survive = sum(
        1 for cell in cells if not has_orientation_reversing_exact(cell)
    )
    assert n_survive == 0, (
        f"Σ_n=8(GL_8) = {n_survive}, expected 0 per DSEKM Table 4"
    )


def test_sigma_n9_GL8_equals_zero() -> None:
    """All 106 published (N=8, n=9) cells have an orientation-reversing
    element in Stab(σ), so Σ_n=9(GL_8) = 0 — matching [DSEKM19] Table 4.

    Tests the n > N (rectangular M) code path of
    has_orientation_reversing_exact.
    """
    from voronoi.orientation import has_orientation_reversing_exact

    path = _DATA / "ListSHV_n8_rank9"
    if not path.exists():
        pytest.skip(f"{path.name} not fetched")
    cells = parse_list_shv_file(path)
    assert len(cells) == 106
    n_survive = sum(
        1 for cell in cells if not has_orientation_reversing_exact(cell)
    )
    assert n_survive == 0, (
        f"Σ_n=9(GL_8) = {n_survive}, expected 0 per DSEKM Table 4"
    )


@pytest.mark.slow
def test_sigma_n10_GL8_equals_zero() -> None:
    """All 783 (N=8, n=10) cells: Σ_n=10(GL_8) = 0 per DSEKM Table 4.
    Marked @slow because this takes ~30 seconds."""
    from voronoi.orientation import has_orientation_reversing_exact

    path = _DATA / "ListSHV_n8_rank10"
    if not path.exists():
        pytest.skip(f"{path.name} not fetched")
    cells = parse_list_shv_file(path)
    assert len(cells) == 783
    n_survive = sum(
        1 for cell in cells if not has_orientation_reversing_exact(cell)
    )
    assert n_survive == 0
