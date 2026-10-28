"""Parser for the ``DATA_pari/ListSHV_n{N}_rank{n}`` files published in
https://github.com/elbazvip/Voronoi-complexes-database.

File format (per file, one cell orbit per line, plus a final summary):

    U1= [[1,0,0,...],[0,1,0,...],...]
    U2= [[...],[...],...]
    ...
    ListSHV_n{N}_rank{n} = [U1,U2,...,Uk]

Each ``Ui`` is an integer matrix, written in GP nested-list syntax.
Each inner list has ``N`` coordinates. The outer list consists of primitive
minimum-vector representatives modulo sign. The filename's ``rank{n}``
declares the cone dimension, the rank of their forms ``v v^t``; the number
of rows can differ from that rank. The projective cell has dimension ``n-1``.
We return a list of ``VoronoiCell`` instances.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from voronoi.cells import VoronoiCell

_FILENAME_RE = re.compile(r"ListSHV_n(?P<N>\d+)_rank(?P<n>\d+)$")
_ASSIGN_RE = re.compile(r"^(?P<name>U\d+)\s*=\s*(?P<rhs>.+)$")


def _parse_filename(path: Path) -> tuple[int, int]:
    """Extract (ambient rank, cone dimension) from a ListSHV filename."""
    m = _FILENAME_RE.match(path.name)
    if m is None:
        raise ValueError(
            f"{path.name!r} does not match ListSHV_n{{N}}_rank{{n}} pattern"
        )
    return int(m["N"]), int(m["n"])


def _parse_matrix_literal(text: str) -> list[list[int]]:
    """Parse a GP nested-list literal ``[[1,2],[3,4]]`` into a Python
    list-of-lists of ints. GP's list syntax is a strict subset of
    Python list syntax, so ``ast.literal_eval`` works directly once we
    strip the trailing semicolon.
    """
    text = text.strip().rstrip(";").strip()
    parsed = ast.literal_eval(text)
    if not isinstance(parsed, list) or not parsed:
        raise ValueError(f"expected non-empty nested list, got {type(parsed).__name__}")
    rows: list[list[int]] = []
    for i, row in enumerate(parsed):
        if not isinstance(row, list):
            raise TypeError(f"row {i} is not a list (got {type(row).__name__})")
        rows.append([int(x) for x in row])
    return rows


def parse_list_shv_file(path: str | Path) -> list[VoronoiCell]:
    """Parse a ``ListSHV_n{N}_rank{n}`` file.

    Returns one :class:`VoronoiCell` per ``Ui`` line, in file order.
    The trailing ``ListSHV_...= [U1,U2,...]`` summary line is ignored
    (it would require full GP evaluation to dereference the Ui names).
    """
    path = Path(path)
    lattice_rank, cell_dim = _parse_filename(path)

    cells: list[VoronoiCell] = []
    with path.open() as fh:
        for lineno, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line or line.startswith(("\\\\", "/*")):
                continue
            if line.startswith("ListSHV"):
                # trailing summary line ("ListSHV_n8_rank8 = [U1,U2,...,U13]")
                break
            m = _ASSIGN_RE.match(line)
            if m is None:
                continue
            try:
                rows = _parse_matrix_literal(m["rhs"])
            except (SyntaxError, ValueError) as exc:
                raise ValueError(f"{path}:{lineno}: parse error: {exc}") from exc
            try:
                cell = VoronoiCell.from_rows(rows, expected_dimension=cell_dim)
            except ValueError as exc:
                raise ValueError(f"{path}:{lineno}: invalid cell: {exc}") from exc
            if cell.lattice_rank != lattice_rank:
                raise ValueError(
                    f"{path}:{lineno}: cell shape "
                    f"({cell.cone_dimension}×{cell.lattice_rank}) disagrees with filename "
                    f"({cell_dim}×{lattice_rank})"
                )
            cells.append(cell)
    return cells
