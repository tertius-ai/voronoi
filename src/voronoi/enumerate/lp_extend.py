"""Diagnostic radius-based extension of minimum-vector configurations.

This module preserves the recovered DSEKM-style experiment for calibration.
It is not the production census algorithm: an arbitrary norm radius does not
carry a completeness proof for a whole coface layer. Production enumeration
uses the finite incidence-orbit and completion strategy in ``PLAN.md``.

Every mathematical decision here delegates to Noether's exact typed surface.
An inconclusive realization checkpoint is propagated as an error and is never
treated as a negative.
"""

from __future__ import annotations

from collections.abc import Iterable

from noether.linalg import Lattice, MinimumVectorConfiguration

from voronoi.cells import VoronoiCell


def _realization_or_raise(
    cell: VoronoiCell, *, max_iterations: int
) -> MinimumVectorConfiguration:
    """Return a verified positive witness or report the exact terminal state."""

    result = cell.configuration.realize_minimum(max_iterations=max_iterations)
    result.verify()
    if result.status == "nonrealizable":
        raise ValueError("input cell has a certified nonrealizable line configuration")
    if result.status == "inconclusive":
        checkpoint = result.checkpoint
        reason = "missing checkpoint" if checkpoint is None else checkpoint.reason
        raise RuntimeError(f"input cell realization is inconclusive: {reason}")
    realization = result.realization
    if realization is None:
        raise RuntimeError("realized result omitted its minimum-vector witness")
    realization.verify()
    return realization


def extend_cell_by_one(
    cell: VoronoiCell,
    *,
    norm_excess_factor: int = 2,
    realizability_max_iterations: int = 200,
) -> list[VoronoiCell]:
    """Return certified one-line extensions found inside a diagnostic radius.

    The witness Gram for ``cell`` is enumerated completely through
    ``norm_excess_factor * minimum``. Each new line is added to the input and
    retained only when Noether returns a verified complete minimum-shell
    realization. The result is sound but not a complete coface enumeration.
    """

    if norm_excess_factor < 1:
        raise ValueError("norm_excess_factor must be positive")
    realization = _realization_or_raise(
        cell, max_iterations=realizability_max_iterations
    )
    lattice = Lattice(realization.gram_matrix)
    short = lattice.shortest_vectors(bound=norm_excess_factor * realization.minimum)
    short.verify(lattice)
    if not short.complete:
        raise RuntimeError("diagnostic short-vector search was incomplete")

    known = set(cell.configuration.vectors)
    extensions: list[VoronoiCell] = []
    for vector in short.vectors:
        if tuple(vector) in known:
            continue
        try:
            candidate = VoronoiCell.from_rows((*cell.min_vectors, vector))
        except ValueError:
            continue
        result = candidate.configuration.realize_minimum(
            max_iterations=realizability_max_iterations
        )
        result.verify()
        if result.status == "realized":
            extensions.append(candidate)
        elif result.status == "inconclusive":
            checkpoint = result.checkpoint
            reason = "missing checkpoint" if checkpoint is None else checkpoint.reason
            raise RuntimeError(
                f"extension realization is inconclusive for {vector}: {reason}"
            )
    return extensions


def extend_layer(
    seeds: Iterable[VoronoiCell],
    *,
    norm_excess_factor: int = 2,
    realizability_max_iterations: int = 200,
) -> list[VoronoiCell]:
    """Run :func:`extend_cell_by_one` and exactly deduplicate its output."""

    raw: list[VoronoiCell] = []
    for cell in seeds:
        raw.extend(
            extend_cell_by_one(
                cell,
                norm_excess_factor=norm_excess_factor,
                realizability_max_iterations=realizability_max_iterations,
            )
        )

    distinct: list[VoronoiCell] = []
    for candidate in raw:
        for representative in distinct:
            equivalence = candidate.configuration.equivalence_to(
                representative.configuration
            )
            if equivalence is not None:
                equivalence.verify()
                break
        else:
            distinct.append(candidate)
    return distinct
