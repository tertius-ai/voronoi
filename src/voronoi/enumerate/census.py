"""Coverage-certified incidence artifacts for the Voronoi census.

This module owns application-level enumeration state.  Exact line
configurations, transformations, equivalence, stabilizers, and minimum-shell
verification remain Noether operations; this module records how those values
are used in a Voronoi census.

The first implemented M4 operation is codimension-one incidence enumeration
for a supplied pair of orbit catalogs.  For each upper representative, ray
deletions are reduced by its exact stabilizer.  Every resulting face orbit is
then either matched to a unique lower representative with an exact coordinate
transport, or recorded as non-well-rounded.  An unmatched spanning face is an
error, never a silently omitted incidence.

"Complete" in these artifacts is deliberately relative to the supplied orbit
catalogs.  A global census claim additionally needs a certificate that those
input catalogs were themselves exhaustively enumerated.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from noether import Z
from noether.linalg import (
    IntegralLineAutomorphismGroup,
    IntegralLineConfiguration,
    IntegralLineEquivalence,
    IntegralLineSubgroup,
    Lattice,
    Matrix,
    MinimumVectorConfiguration,
)

from voronoi.cells import VoronoiCell
from voronoi.enumerate.census_engine import ENGINE_NOETHER_CONTRACT

SCHEMA_VERSION = "voronoi/census-incidence@1"
PAIR_SCHEMA_VERSION = "voronoi/coface-pair-layer@1"
PAIR_TASK_SCHEMA_VERSION = "voronoi/coface-pair-task@2"

# The legacy Python materializer is retained for hand-checkable cases only.
# Production layers use the Rust streaming boundary in ``census_engine``.
PYTHON_PAIR_ENTRY_UPPER_BOUND_CAP = 1_000_000
PAIR_TASK_CANDIDATE_CAP = 100_000
PAIR_INLINE_COMPLETION_CAP = 10

# These semantic identities are the frozen Noether contract consumed by M4.
# A version change requires an explicit artifact migration, not a best-effort
# interpretation of old evidence.
NOETHER_CONTRACT: Mapping[str, str] = {
    "IntegralLineConfiguration": "noether/linalg/IntegralLineConfiguration@1",
    "IntegralLineEquivalence": "noether/linalg/IntegralLineEquivalence@1",
    "IntegralLineAutomorphismGroup": ("noether/linalg/IntegralLineAutomorphismGroup@1"),
    "MinimumVectorConfiguration": "noether/linalg/MinimumVectorConfiguration@1",
    "Lattice": "noether/linalg/Lattice@1",
    "Matrix": "noether/linalg/Matrix@1",
}

PAIR_NOETHER_CONTRACT: Mapping[str, str] = {
    **NOETHER_CONTRACT,
    **ENGINE_NOETHER_CONTRACT,
    "IntegralLineSubgroup": "noether/linalg/IntegralLineSubgroup@1",
}

FaceOrbitStatus = Literal["matched", "non_well_rounded"]


def verify_noether_contract() -> None:
    """Reject an engine whose semantic identities differ from the M4 contract."""

    actual = {
        "IntegralLineConfiguration": IntegralLineConfiguration.type_id,
        "IntegralLineEquivalence": IntegralLineEquivalence.type_id,
        "IntegralLineAutomorphismGroup": IntegralLineAutomorphismGroup.type_id,
        "MinimumVectorConfiguration": MinimumVectorConfiguration.type_id,
        "Lattice": Lattice.type_id,
        "Matrix": Matrix.type_id,
    }
    if actual != NOETHER_CONTRACT:
        raise RuntimeError(
            "the installed Noether semantic surface does not match the M4 "
            f"artifact contract: expected {dict(NOETHER_CONTRACT)!r}, got {actual!r}"
        )


def verify_pair_noether_contract() -> None:
    """Reject an engine without the exact subgroup/double-coset surface."""

    verify_noether_contract()
    actual = {
        **NOETHER_CONTRACT,
        **ENGINE_NOETHER_CONTRACT,
        "IntegralLineSubgroup": IntegralLineSubgroup.type_id,
    }
    if actual != PAIR_NOETHER_CONTRACT:
        raise RuntimeError(
            "the installed Noether semantic surface does not match the coface-pair "
            f"contract: expected {dict(PAIR_NOETHER_CONTRACT)!r}, got {actual!r}"
        )


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload).encode()).hexdigest()


def _matrix_rows(matrix: Matrix) -> tuple[tuple[int, ...], ...]:
    return tuple(tuple(int(entry) for entry in row) for row in matrix.to_rows())


def cell_id(cell: VoronoiCell) -> str:
    """Content identity of one embedded cell, independent of its witness."""

    payload = {
        "type": "voronoi/embedded-cell@1",
        "ambient_rank": cell.lattice_rank,
        "vectors": cell.min_vectors,
    }
    return f"sha256:{_digest(payload)}"


@dataclass(frozen=True)
class CertifiedCellRecord:
    """Persistable exact evidence that a line configuration is a minimum shell."""

    vectors: tuple[tuple[int, ...], ...]
    cone_dimension: int
    gram_matrix: tuple[tuple[int, ...], ...]
    minimum: int

    @classmethod
    def certify(
        cls, cell: VoronoiCell, *, max_iterations: int = 200
    ) -> CertifiedCellRecord:
        """Run Noether's three-way realization playbook and require a positive."""

        result = cell.configuration.realize_minimum(max_iterations=max_iterations)
        result.verify()
        if result.status == "nonrealizable":
            raise ValueError("cell has a certified nonrealizable line configuration")
        if result.status == "inconclusive":
            diagnostic = result.diagnostic
            reason = "missing diagnostic" if diagnostic is None else diagnostic.reason
            raise RuntimeError(f"cell realization is inconclusive: {reason}")
        realization = result.realization
        if realization is None:
            raise RuntimeError("realized result omitted its minimum-vector witness")
        realization.verify()
        record = cls(
            vectors=cell.min_vectors,
            cone_dimension=cell.cone_dimension,
            gram_matrix=_matrix_rows(realization.gram_matrix),
            minimum=int(realization.minimum),
        )
        record.verify()
        return record

    @property
    def identifier(self) -> str:
        return cell_id(VoronoiCell.from_rows(self.vectors))

    def verify(self) -> VoronoiCell:
        """Rebuild and independently verify the complete minimum shell."""

        cell = VoronoiCell.from_rows(
            self.vectors, expected_dimension=self.cone_dimension
        )
        gram = Matrix.from_rows(Z, self.gram_matrix)
        realization = Lattice(gram).minimum_vector_configuration()
        realization.verify()
        if realization.configuration != cell.configuration:
            raise ValueError("Gram witness has a different complete minimum shell")
        if int(realization.minimum) != self.minimum:
            raise ValueError("recorded minimum disagrees with the Gram witness")
        return cell

    def to_payload(self) -> dict[str, object]:
        return {
            "type": "voronoi/certified-cell@1",
            "cell_id": self.identifier,
            "vectors": self.vectors,
            "cone_dimension": self.cone_dimension,
            "gram_matrix": self.gram_matrix,
            "minimum": self.minimum,
            "evidence_type": MinimumVectorConfiguration.type_id,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> CertifiedCellRecord:
        if payload.get("type") != "voronoi/certified-cell@1":
            raise ValueError("unsupported certified-cell artifact type")
        if (
            payload.get("evidence_type")
            != NOETHER_CONTRACT["MinimumVectorConfiguration"]
        ):
            raise ValueError("unsupported minimum-vector evidence type")
        record = cls(
            vectors=tuple(tuple(int(x) for x in row) for row in payload["vectors"]),
            cone_dimension=int(payload["cone_dimension"]),
            gram_matrix=tuple(
                tuple(int(x) for x in row) for row in payload["gram_matrix"]
            ),
            minimum=int(payload["minimum"]),
        )
        if payload.get("cell_id") != record.identifier:
            raise ValueError("certified-cell content hash does not match its payload")
        record.verify()
        return record


@dataclass(frozen=True)
class IncidenceCensusSpec:
    """Immutable input identity and deterministic sharding convention."""

    ambient_rank: int
    lower_dimension: int
    upper_dimension: int
    lower_cell_ids: tuple[str, ...]
    upper_cell_ids: tuple[str, ...]
    lower_catalog_claim: str
    upper_catalog_claim: str

    @classmethod
    def from_cells(
        cls,
        lower_cells: Sequence[VoronoiCell],
        upper_cells: Sequence[VoronoiCell],
        *,
        lower_catalog_claim: str,
        upper_catalog_claim: str,
    ) -> IncidenceCensusSpec:
        if not lower_cells or not upper_cells:
            raise ValueError("incidence catalogs must both be nonempty")
        ambient_rank = lower_cells[0].lattice_rank
        lower_dimension = lower_cells[0].cone_dimension
        upper_dimension = upper_cells[0].cone_dimension
        if upper_dimension != lower_dimension + 1:
            raise ValueError("incidence catalogs must have consecutive dimensions")
        if any(
            cell.lattice_rank != ambient_rank or cell.cone_dimension != lower_dimension
            for cell in lower_cells
        ):
            raise ValueError("lower catalog mixes ambient ranks or cone dimensions")
        if any(
            cell.lattice_rank != ambient_rank or cell.cone_dimension != upper_dimension
            for cell in upper_cells
        ):
            raise ValueError("upper catalog mixes ambient ranks or cone dimensions")
        if any(not cell.is_simplicial for cell in upper_cells):
            raise ValueError(
                "ray-deletion incidence enumeration currently requires simplicial "
                "upper cells"
            )
        lower_ids = tuple(cell_id(cell) for cell in lower_cells)
        upper_ids = tuple(cell_id(cell) for cell in upper_cells)
        if len(set(lower_ids)) != len(lower_ids):
            raise ValueError("lower catalog repeats an embedded cell")
        if len(set(upper_ids)) != len(upper_ids):
            raise ValueError("upper catalog repeats an embedded cell")
        return cls(
            ambient_rank=ambient_rank,
            lower_dimension=lower_dimension,
            upper_dimension=upper_dimension,
            lower_cell_ids=lower_ids,
            upper_cell_ids=upper_ids,
            lower_catalog_claim=lower_catalog_claim,
            upper_catalog_claim=upper_catalog_claim,
        )

    @property
    def identifier(self) -> str:
        return f"sha256:{_digest(self.to_payload())}"

    def to_payload(self) -> dict[str, object]:
        return {
            "type": "voronoi/incidence-spec@1",
            "ambient_rank": self.ambient_rank,
            "lower_dimension": self.lower_dimension,
            "upper_dimension": self.upper_dimension,
            "lower_cell_ids": self.lower_cell_ids,
            "upper_cell_ids": self.upper_cell_ids,
            "lower_catalog_claim": self.lower_catalog_claim,
            "upper_catalog_claim": self.upper_catalog_claim,
            "sharding": "upper_index_mod_shard_count",
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> IncidenceCensusSpec:
        if payload.get("type") != "voronoi/incidence-spec@1":
            raise ValueError("unsupported incidence-spec artifact type")
        if payload.get("sharding") != "upper_index_mod_shard_count":
            raise ValueError("unsupported incidence sharding convention")
        return cls(
            ambient_rank=int(payload["ambient_rank"]),
            lower_dimension=int(payload["lower_dimension"]),
            upper_dimension=int(payload["upper_dimension"]),
            lower_cell_ids=tuple(str(x) for x in payload["lower_cell_ids"]),
            upper_cell_ids=tuple(str(x) for x in payload["upper_cell_ids"]),
            lower_catalog_claim=str(payload["lower_catalog_claim"]),
            upper_catalog_claim=str(payload["upper_catalog_claim"]),
        )


@dataclass(frozen=True)
class IncidenceOrbitRecord:
    """One orbit of embedded inclusions ``lower < upper``."""

    lower_index: int
    upper_index: int
    upper_ray_orbit: tuple[int, ...]
    omitted_ray: int
    face_to_lower: tuple[tuple[int, ...], ...]
    attached_line: tuple[int, ...]

    @property
    def identifier(self) -> str:
        return f"sha256:{_digest(self.to_payload())}"

    def to_payload(self) -> dict[str, object]:
        return {
            "type": "voronoi/incidence-orbit@1",
            "lower_index": self.lower_index,
            "upper_index": self.upper_index,
            "upper_ray_orbit": self.upper_ray_orbit,
            "omitted_ray": self.omitted_ray,
            "face_to_lower": self.face_to_lower,
            "attached_line": self.attached_line,
            "equivalence_type": IntegralLineEquivalence.type_id,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> IncidenceOrbitRecord:
        if payload.get("type") != "voronoi/incidence-orbit@1":
            raise ValueError("unsupported incidence-orbit artifact type")
        if (
            payload.get("equivalence_type")
            != NOETHER_CONTRACT["IntegralLineEquivalence"]
        ):
            raise ValueError("unsupported incidence equivalence type")
        return cls(
            lower_index=int(payload["lower_index"]),
            upper_index=int(payload["upper_index"]),
            upper_ray_orbit=tuple(int(x) for x in payload["upper_ray_orbit"]),
            omitted_ray=int(payload["omitted_ray"]),
            face_to_lower=tuple(
                tuple(int(x) for x in row) for row in payload["face_to_lower"]
            ),
            attached_line=tuple(int(x) for x in payload["attached_line"]),
        )

    def verify(
        self,
        lower_cells: Sequence[VoronoiCell],
        upper_cells: Sequence[VoronoiCell],
        *,
        upper_automorphism_group: IntegralLineAutomorphismGroup | None = None,
    ) -> None:
        lower = lower_cells[self.lower_index]
        upper = upper_cells[self.upper_index]
        if tuple(sorted(set(self.upper_ray_orbit))) != self.upper_ray_orbit:
            raise ValueError("upper ray orbit is not sorted and duplicate-free")
        if self.omitted_ray != min(self.upper_ray_orbit):
            raise ValueError(
                "omitted ray is not the deterministic orbit representative"
            )
        if not 0 <= self.omitted_ray < upper.ray_count:
            raise ValueError("omitted ray is outside the upper configuration")

        rows = (
            upper.min_vectors[: self.omitted_ray]
            + upper.min_vectors[self.omitted_ray + 1 :]
        )
        face = VoronoiCell.from_rows(rows, expected_dimension=lower.cone_dimension)
        transformation = Matrix.from_rows(Z, self.face_to_lower)
        if face.configuration.transform(transformation) != lower.configuration:
            raise ValueError("face-to-lower coordinate transport does not verify")

        aligned_upper = upper.configuration.transform(transformation)
        attached = set(aligned_upper.vectors) - set(lower.min_vectors)
        if attached != {self.attached_line}:
            raise ValueError("aligned upper cell does not add the recorded line")

        automorphisms = upper_automorphism_group
        if automorphisms is None:
            automorphisms = upper.configuration.automorphism_group()
        automorphisms.verify()
        actual_orbit = tuple(sorted(automorphisms.line_action.orbit(self.omitted_ray)))
        if actual_orbit != self.upper_ray_orbit:
            raise ValueError("recorded ray orbit disagrees with the upper stabilizer")


@dataclass(frozen=True)
class FaceOrbitOutcome:
    """Terminal state of one upper-cell ray-deletion orbit."""

    upper_index: int
    upper_ray_orbit: tuple[int, ...]
    status: FaceOrbitStatus
    face_span_rank: int
    incidence_id: str | None

    def to_payload(self) -> dict[str, object]:
        return {
            "type": "voronoi/face-orbit-outcome@1",
            "upper_index": self.upper_index,
            "upper_ray_orbit": self.upper_ray_orbit,
            "status": self.status,
            "face_span_rank": self.face_span_rank,
            "incidence_id": self.incidence_id,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> FaceOrbitOutcome:
        status = str(payload["status"])
        if status not in {"matched", "non_well_rounded"}:
            raise ValueError(f"unsupported face-orbit status {status!r}")
        incidence_id = payload.get("incidence_id")
        return cls(
            upper_index=int(payload["upper_index"]),
            upper_ray_orbit=tuple(int(x) for x in payload["upper_ray_orbit"]),
            status=status,
            face_span_rank=int(payload["face_span_rank"]),
            incidence_id=None if incidence_id is None else str(incidence_id),
        )


@dataclass(frozen=True)
class IncidenceShard:
    """Deterministic, independently verifiable subset of incidence tasks."""

    specification: IncidenceCensusSpec
    shard_index: int
    shard_count: int
    upper_indices: tuple[int, ...]
    incidences: tuple[IncidenceOrbitRecord, ...]
    outcomes: tuple[FaceOrbitOutcome, ...]

    @property
    def identifier(self) -> str:
        return f"sha256:{_digest(self.to_payload())}"

    @property
    def relative_complete(self) -> bool:
        return all(
            outcome.status in {"matched", "non_well_rounded"}
            for outcome in self.outcomes
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "type": SCHEMA_VERSION,
            "noether_contract": dict(NOETHER_CONTRACT),
            "specification": self.specification.to_payload(),
            "specification_id": self.specification.identifier,
            "shard_index": self.shard_index,
            "shard_count": self.shard_count,
            "upper_indices": self.upper_indices,
            "incidences": [record.to_payload() for record in self.incidences],
            "outcomes": [outcome.to_payload() for outcome in self.outcomes],
            "coverage": "complete_relative_to_supplied_catalogs",
        }

    def to_json(self) -> str:
        return _canonical_json(self.to_payload()) + "\n"

    def write(self, path: str | Path) -> None:
        Path(path).write_text(self.to_json())

    @classmethod
    def from_json(cls, value: str) -> IncidenceShard:
        payload = json.loads(value)
        if payload.get("type") != SCHEMA_VERSION:
            raise ValueError("unsupported incidence-shard artifact type")
        if payload.get("noether_contract") != dict(NOETHER_CONTRACT):
            raise ValueError("incidence shard uses a different Noether contract")
        if payload.get("coverage") != "complete_relative_to_supplied_catalogs":
            raise ValueError(
                "incidence shard does not carry complete relative coverage"
            )
        specification = IncidenceCensusSpec.from_payload(payload["specification"])
        if payload.get("specification_id") != specification.identifier:
            raise ValueError("incidence specification hash does not match its payload")
        return cls(
            specification=specification,
            shard_index=int(payload["shard_index"]),
            shard_count=int(payload["shard_count"]),
            upper_indices=tuple(int(x) for x in payload["upper_indices"]),
            incidences=tuple(
                IncidenceOrbitRecord.from_payload(item)
                for item in payload["incidences"]
            ),
            outcomes=tuple(
                FaceOrbitOutcome.from_payload(item) for item in payload["outcomes"]
            ),
        )

    @classmethod
    def read(cls, path: str | Path) -> IncidenceShard:
        return cls.from_json(Path(path).read_text())

    def verify(
        self,
        lower_cells: Sequence[VoronoiCell],
        upper_cells: Sequence[VoronoiCell],
    ) -> None:
        verify_noether_contract()
        expected_spec = IncidenceCensusSpec.from_cells(
            lower_cells,
            upper_cells,
            lower_catalog_claim=self.specification.lower_catalog_claim,
            upper_catalog_claim=self.specification.upper_catalog_claim,
        )
        if expected_spec != self.specification:
            raise ValueError("incidence shard inputs do not match its specification")
        if self.shard_count < 1 or not 0 <= self.shard_index < self.shard_count:
            raise ValueError("invalid shard index or count")
        expected_upper_indices = tuple(
            index
            for index in range(len(upper_cells))
            if index % self.shard_count == self.shard_index
        )
        if self.upper_indices != expected_upper_indices:
            raise ValueError("shard contains the wrong deterministic upper-cell tasks")

        incidences = {record.identifier: record for record in self.incidences}
        if len(incidences) != len(self.incidences):
            raise ValueError("shard repeats an incidence record")
        outcomes_by_upper: dict[int, list[FaceOrbitOutcome]] = defaultdict(list)
        for outcome in self.outcomes:
            if outcome.upper_index not in expected_upper_indices:
                raise ValueError("face outcome belongs to another shard")
            if outcome.status == "matched":
                if outcome.incidence_id not in incidences:
                    raise ValueError("matched outcome omits its incidence record")
            elif outcome.incidence_id is not None:
                raise ValueError("non-well-rounded outcome refers to an incidence")
            outcomes_by_upper[outcome.upper_index].append(outcome)

        records_by_upper: dict[int, list[IncidenceOrbitRecord]] = defaultdict(list)
        for record in self.incidences:
            if record.upper_index not in expected_upper_indices:
                raise ValueError("incidence belongs to another shard")
            records_by_upper[record.upper_index].append(record)

        for upper_index in expected_upper_indices:
            automorphisms = upper_cells[upper_index].configuration.automorphism_group()
            automorphisms.verify()
            covered_rays: set[int] = set()
            for outcome in outcomes_by_upper[upper_index]:
                orbit = set(outcome.upper_ray_orbit)
                if covered_rays & orbit:
                    raise ValueError("face-orbit outcomes overlap")
                covered_rays |= orbit
            if covered_rays != set(range(upper_cells[upper_index].ray_count)):
                raise ValueError("face-orbit outcomes do not cover every upper ray")
            for record in records_by_upper[upper_index]:
                record.verify(
                    lower_cells,
                    upper_cells,
                    upper_automorphism_group=automorphisms,
                )


@dataclass(frozen=True)
class IncidenceLayer:
    """Merged shard-order-independent incidence artifact."""

    specification: IncidenceCensusSpec
    shard_ids: tuple[str, ...]
    incidences: tuple[IncidenceOrbitRecord, ...]
    outcomes: tuple[FaceOrbitOutcome, ...]

    @property
    def relative_complete(self) -> bool:
        return True

    @property
    def identifier(self) -> str:
        return f"sha256:{_digest(self.to_payload())}"

    def to_payload(self) -> dict[str, object]:
        return {
            "type": "voronoi/incidence-layer@1",
            "noether_contract": dict(NOETHER_CONTRACT),
            "specification": self.specification.to_payload(),
            "specification_id": self.specification.identifier,
            "shard_ids": self.shard_ids,
            "incidences": [record.to_payload() for record in self.incidences],
            "outcomes": [outcome.to_payload() for outcome in self.outcomes],
            "coverage": "complete_relative_to_supplied_catalogs",
        }

    def to_json(self) -> str:
        return _canonical_json(self.to_payload()) + "\n"


PairOrbitStatus = Literal["candidate", "degenerate"]


@dataclass(frozen=True)
class CofacePairOrbitRecord:
    """One unordered coface-pair orbit around a fixed lower cell.

    The double-coset representative lives in the lower cell's faithful signed
    line action.  ``candidate_vectors`` is the exact two-ray extension in the
    lower cell's coordinates; it is retained even when it is degenerate so the
    terminal outcome is independently inspectable.
    """

    lower_index: int
    left_incidence_id: str
    right_incidence_id: str
    representative: tuple[int, ...]
    inverse_representative: tuple[int, ...] | None
    right_coset_count: int
    double_coset_size: int
    candidate_vectors: tuple[tuple[int, ...], ...]
    candidate_dimension: int
    status: PairOrbitStatus

    @property
    def identifier(self) -> str:
        return f"sha256:{_digest(self.to_payload())}"

    @property
    def candidate_id(self) -> str:
        return cell_id(VoronoiCell.from_rows(self.candidate_vectors))

    def to_payload(self) -> dict[str, object]:
        return {
            "type": "voronoi/coface-pair-orbit@1",
            "lower_index": self.lower_index,
            "left_incidence_id": self.left_incidence_id,
            "right_incidence_id": self.right_incidence_id,
            "representative": self.representative,
            "inverse_representative": self.inverse_representative,
            "right_coset_count": self.right_coset_count,
            "double_coset_size": self.double_coset_size,
            "candidate_vectors": self.candidate_vectors,
            "candidate_dimension": self.candidate_dimension,
            "candidate_id": self.candidate_id,
            "status": self.status,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> CofacePairOrbitRecord:
        if payload.get("type") != "voronoi/coface-pair-orbit@1":
            raise ValueError("unsupported coface-pair orbit artifact type")
        inverse = payload.get("inverse_representative")
        record = cls(
            lower_index=int(payload["lower_index"]),
            left_incidence_id=str(payload["left_incidence_id"]),
            right_incidence_id=str(payload["right_incidence_id"]),
            representative=tuple(int(x) for x in payload["representative"]),
            inverse_representative=(
                None if inverse is None else tuple(int(x) for x in inverse)
            ),
            right_coset_count=int(payload["right_coset_count"]),
            double_coset_size=int(payload["double_coset_size"]),
            candidate_vectors=tuple(
                tuple(int(x) for x in row) for row in payload["candidate_vectors"]
            ),
            candidate_dimension=int(payload["candidate_dimension"]),
            status=str(payload["status"]),  # type: ignore[arg-type]
        )
        if record.status not in {"candidate", "degenerate"}:
            raise ValueError("invalid coface-pair terminal status")
        if payload.get("candidate_id") != record.candidate_id:
            raise ValueError("coface-pair candidate hash does not match its vectors")
        return record


@dataclass(frozen=True)
class CofacePairLayer:
    """Complete unordered coface-pair coverage for one incidence layer."""

    incidence_layer_id: str
    lower_cell_ids: tuple[str, ...]
    middle_cell_ids: tuple[str, ...]
    target_dimension: int
    records: tuple[CofacePairOrbitRecord, ...]
    raw_double_coset_count: int
    diagonal_count: int
    transpose_duplicate_count: int

    @property
    def relative_complete(self) -> bool:
        return self.raw_double_coset_count == (
            len(self.records) + self.diagonal_count + self.transpose_duplicate_count
        )

    @property
    def identifier(self) -> str:
        return f"sha256:{_digest(self.to_payload())}"

    def to_payload(self) -> dict[str, object]:
        return {
            "type": PAIR_SCHEMA_VERSION,
            "noether_contract": dict(PAIR_NOETHER_CONTRACT),
            "incidence_layer_id": self.incidence_layer_id,
            "lower_cell_ids": self.lower_cell_ids,
            "middle_cell_ids": self.middle_cell_ids,
            "target_dimension": self.target_dimension,
            "records": [record.to_payload() for record in self.records],
            "coverage": {
                "raw_double_cosets": self.raw_double_coset_count,
                "diagonal": self.diagonal_count,
                "transpose_duplicates": self.transpose_duplicate_count,
                "retained_unordered_orbits": len(self.records),
                "status": "complete_relative_to_incidence_layer",
            },
        }

    def to_json(self) -> str:
        return _canonical_json(self.to_payload()) + "\n"

    @classmethod
    def from_json(cls, value: str) -> CofacePairLayer:
        payload = json.loads(value)
        if payload.get("type") != PAIR_SCHEMA_VERSION:
            raise ValueError("unsupported coface-pair layer artifact type")
        if payload.get("noether_contract") != dict(PAIR_NOETHER_CONTRACT):
            raise ValueError("coface-pair layer uses a different Noether contract")
        coverage = payload.get("coverage", {})
        if coverage.get("status") != "complete_relative_to_incidence_layer":
            raise ValueError("coface-pair layer omits complete relative coverage")
        layer = cls(
            incidence_layer_id=str(payload["incidence_layer_id"]),
            lower_cell_ids=tuple(str(x) for x in payload["lower_cell_ids"]),
            middle_cell_ids=tuple(str(x) for x in payload["middle_cell_ids"]),
            target_dimension=int(payload["target_dimension"]),
            records=tuple(
                CofacePairOrbitRecord.from_payload(item) for item in payload["records"]
            ),
            raw_double_coset_count=int(coverage["raw_double_cosets"]),
            diagonal_count=int(coverage["diagonal"]),
            transpose_duplicate_count=int(coverage["transpose_duplicates"]),
        )
        if not layer.relative_complete:
            raise ValueError("coface-pair coverage counts do not balance")
        return layer


@dataclass(frozen=True)
class CofacePairCatalogMatch:
    """Comparison of one pair candidate with a supplied target catalog."""

    pair_id: str
    target_index: int | None
    candidate_to_target: tuple[tuple[int, ...], ...] | None

    @property
    def status(self) -> Literal["matched", "unmatched"]:
        return "matched" if self.target_index is not None else "unmatched"

    def to_payload(self) -> dict[str, object]:
        return {
            "pair_id": self.pair_id,
            "status": self.status,
            "target_index": self.target_index,
            "candidate_to_target": self.candidate_to_target,
        }


@dataclass(frozen=True)
class CofacePairCatalogReport:
    """Exhaustive comparison against one supplied target orbit catalog."""

    pair_layer_id: str
    target_cell_ids: tuple[str, ...]
    matches: tuple[CofacePairCatalogMatch, ...]
    degenerate_pair_ids: tuple[str, ...]

    @property
    def covered_target_indices(self) -> tuple[int, ...]:
        return tuple(
            sorted(
                {
                    match.target_index
                    for match in self.matches
                    if match.target_index is not None
                }
            )
        )

    @property
    def target_complete(self) -> bool:
        return self.covered_target_indices == tuple(range(len(self.target_cell_ids)))

    @property
    def unmatched_count(self) -> int:
        return sum(match.target_index is None for match in self.matches)

    @property
    def identifier(self) -> str:
        return f"sha256:{_digest(self.to_payload())}"

    def to_payload(self) -> dict[str, object]:
        return {
            "type": "voronoi/coface-pair-catalog-report@1",
            "pair_layer_id": self.pair_layer_id,
            "target_cell_ids": self.target_cell_ids,
            "matches": [match.to_payload() for match in self.matches],
            "degenerate_pair_ids": self.degenerate_pair_ids,
            "covered_target_indices": self.covered_target_indices,
            "target_complete": self.target_complete,
        }


def _lower_buckets(
    lower_cells: Sequence[VoronoiCell],
) -> dict[tuple[int, int, int], list[int]]:
    buckets: dict[tuple[int, int, int], list[int]] = defaultdict(list)
    for index, cell in enumerate(lower_cells):
        key = (
            cell.ray_count,
            cell.cone_dimension,
            int(cell.configuration.barycenter_form.det()),
        )
        buckets[key].append(index)
    return buckets


def _ray_orbits(cell: VoronoiCell) -> tuple[tuple[int, ...], ...]:
    automorphisms = cell.configuration.automorphism_group()
    automorphisms.verify()
    unseen = set(range(cell.ray_count))
    orbits: list[tuple[int, ...]] = []
    while unseen:
        representative = min(unseen)
        orbit = tuple(sorted(automorphisms.line_action.orbit(representative)))
        if representative not in orbit or not set(orbit) <= unseen:
            raise RuntimeError("Noether returned inconsistent ray orbits")
        unseen.difference_update(orbit)
        orbits.append(orbit)
    return tuple(orbits)


def build_incidence_shard(
    lower_cells: Sequence[VoronoiCell],
    upper_cells: Sequence[VoronoiCell],
    *,
    lower_catalog_claim: str,
    upper_catalog_claim: str,
    shard_index: int = 0,
    shard_count: int = 1,
) -> IncidenceShard:
    """Enumerate every codimension-one face orbit assigned to one shard."""

    verify_noether_contract()
    specification = IncidenceCensusSpec.from_cells(
        lower_cells,
        upper_cells,
        lower_catalog_claim=lower_catalog_claim,
        upper_catalog_claim=upper_catalog_claim,
    )
    if shard_count < 1 or not 0 <= shard_index < shard_count:
        raise ValueError("shard_index must lie in range(shard_count)")
    upper_indices = tuple(
        index for index in range(len(upper_cells)) if index % shard_count == shard_index
    )
    buckets = _lower_buckets(lower_cells)
    lower_automorphisms = [
        cell.configuration.automorphism_group() for cell in lower_cells
    ]
    for automorphisms in lower_automorphisms:
        automorphisms.verify()
    incidences: list[IncidenceOrbitRecord] = []
    outcomes: list[FaceOrbitOutcome] = []

    for upper_index in upper_indices:
        upper = upper_cells[upper_index]
        for ray_orbit in _ray_orbits(upper):
            omitted_ray = min(ray_orbit)
            rows = (
                upper.min_vectors[:omitted_ray] + upper.min_vectors[omitted_ray + 1 :]
            )
            face = VoronoiCell.from_rows(
                rows, expected_dimension=specification.lower_dimension
            )
            if not face.configuration.is_spanning:
                outcomes.append(
                    FaceOrbitOutcome(
                        upper_index=upper_index,
                        upper_ray_orbit=ray_orbit,
                        status="non_well_rounded",
                        face_span_rank=face.configuration.span_rank,
                        incidence_id=None,
                    )
                )
                continue

            key = (
                face.ray_count,
                face.cone_dimension,
                int(face.configuration.barycenter_form.det()),
            )
            matches: list[tuple[int, IntegralLineEquivalence]] = []
            for lower_index in buckets.get(key, []):
                equivalence = face.configuration.equivalence_to(
                    lower_cells[lower_index].configuration,
                    target_automorphisms=lower_automorphisms[lower_index],
                )
                if equivalence is not None:
                    equivalence.verify()
                    matches.append((lower_index, equivalence))
            if len(matches) != 1:
                raise RuntimeError(
                    "spanning face orbit did not match a unique lower orbit: "
                    f"upper={upper_index}, ray_orbit={ray_orbit}, matches="
                    f"{[index for index, _ in matches]}"
                )

            lower_index, equivalence = matches[0]
            aligned_upper = upper.configuration.transform(equivalence.transformation)
            attached = set(aligned_upper.vectors) - set(
                lower_cells[lower_index].min_vectors
            )
            if len(attached) != 1:
                raise RuntimeError("aligned codimension-one cell does not add one line")
            record = IncidenceOrbitRecord(
                lower_index=lower_index,
                upper_index=upper_index,
                upper_ray_orbit=ray_orbit,
                omitted_ray=omitted_ray,
                face_to_lower=_matrix_rows(equivalence.transformation),
                attached_line=attached.pop(),
            )
            incidences.append(record)
            outcomes.append(
                FaceOrbitOutcome(
                    upper_index=upper_index,
                    upper_ray_orbit=ray_orbit,
                    status="matched",
                    face_span_rank=face.configuration.span_rank,
                    incidence_id=record.identifier,
                )
            )

    shard = IncidenceShard(
        specification=specification,
        shard_index=shard_index,
        shard_count=shard_count,
        upper_indices=upper_indices,
        incidences=tuple(
            sorted(
                incidences,
                key=lambda record: (
                    record.upper_index,
                    record.omitted_ray,
                    record.lower_index,
                ),
            )
        ),
        outcomes=tuple(
            sorted(
                outcomes,
                key=lambda outcome: (outcome.upper_index, outcome.upper_ray_orbit),
            )
        ),
    )
    if not shard.relative_complete:
        raise RuntimeError("incidence shard contains a nonterminal face orbit")
    return shard


def merge_incidence_shards(shards: Iterable[IncidenceShard]) -> IncidenceLayer:
    """Merge a complete shard set with an order-independent artifact hash."""

    materialized = tuple(shards)
    if not materialized:
        raise ValueError("cannot merge zero incidence shards")
    specification = materialized[0].specification
    shard_count = materialized[0].shard_count
    if any(shard.specification != specification for shard in materialized):
        raise ValueError("cannot merge shards from different incidence specifications")
    if any(shard.shard_count != shard_count for shard in materialized):
        raise ValueError("cannot merge shards with different shard counts")
    by_index = {shard.shard_index: shard for shard in materialized}
    if len(by_index) != len(materialized):
        raise ValueError("incidence merge repeats a shard index")
    if set(by_index) != set(range(shard_count)):
        raise ValueError("incidence merge is missing one or more shards")
    expected_indices = set(range(len(specification.upper_cell_ids)))
    actual_indices = {
        upper_index for shard in materialized for upper_index in shard.upper_indices
    }
    if actual_indices != expected_indices:
        raise ValueError("merged shards do not cover every upper-cell task")

    incidences = tuple(
        sorted(
            (record for shard in materialized for record in shard.incidences),
            key=lambda record: (
                record.upper_index,
                record.omitted_ray,
                record.lower_index,
            ),
        )
    )
    outcomes = tuple(
        sorted(
            (outcome for shard in materialized for outcome in shard.outcomes),
            key=lambda outcome: (outcome.upper_index, outcome.upper_ray_orbit),
        )
    )
    incidence_ids = [record.identifier for record in incidences]
    if len(set(incidence_ids)) != len(incidence_ids):
        raise ValueError("merged shards contain duplicate incidence records")
    return IncidenceLayer(
        specification=specification,
        shard_ids=tuple(sorted(shard.identifier for shard in materialized)),
        incidences=incidences,
        outcomes=outcomes,
    )


def _transported_coface_subgroup(
    record: IncidenceOrbitRecord,
    lower: VoronoiCell,
    upper: VoronoiCell,
    upper_automorphisms: IntegralLineAutomorphismGroup,
) -> IntegralLineSubgroup:
    """Recover one coface stabilizer inside the chosen lower coordinates."""

    face_rows = (
        upper.min_vectors[: record.omitted_ray]
        + upper.min_vectors[record.omitted_ray + 1 :]
    )
    face = VoronoiCell.from_rows(face_rows, expected_dimension=lower.cone_dimension)
    transformation = Matrix.from_rows(Z, record.face_to_lower)
    subgroup = (
        upper_automorphisms.line_stabilizer(record.omitted_ray)
        .restrict(face.configuration)
        .conjugate(transformation)
    )
    subgroup.verify()
    if subgroup.configuration != lower.configuration:
        raise RuntimeError("transported coface subgroup has the wrong configuration")
    return subgroup


def build_coface_pair_task(
    lower_cells: Sequence[VoronoiCell],
    middle_cells: Sequence[VoronoiCell],
    incidence_layer: IncidenceLayer | IncidenceShard,
    *,
    lower_index: int,
    candidate_cap: int = 100_000,
    candidate_artifact_path: Path | None = None,
    completion_candidate_limit: int = 0,
    completion_max_iterations: int = 50,
) -> dict[str, object]:
    """Build one independently bounded lower-cell task for the Rust engine."""

    verify_pair_noether_contract()
    expected_specification = IncidenceCensusSpec.from_cells(
        lower_cells,
        middle_cells,
        lower_catalog_claim=incidence_layer.specification.lower_catalog_claim,
        upper_catalog_claim=incidence_layer.specification.upper_catalog_claim,
    )
    if expected_specification != incidence_layer.specification:
        raise ValueError("coface-pair inputs do not match the incidence layer")
    if not incidence_layer.relative_complete:
        raise ValueError("coface-pair enumeration requires complete relative incidence")
    if not 0 <= lower_index < len(lower_cells):
        raise ValueError("lower_index is outside the lower catalog")
    if not 1 <= candidate_cap <= PAIR_TASK_CANDIDATE_CAP:
        raise ValueError(f"candidate_cap must lie in 1..{PAIR_TASK_CANDIDATE_CAP}")
    if (
        not 0
        <= completion_candidate_limit
        <= min(candidate_cap, PAIR_INLINE_COMPLETION_CAP)
    ):
        raise ValueError(
            "completion_candidate_limit exceeds the inline calibration ceiling; "
            "use process-isolated completion batches"
        )
    if completion_max_iterations < 0:
        raise ValueError("completion_max_iterations cannot be negative")
    resolved_artifact_path: Path | None = None
    if candidate_artifact_path is not None:
        resolved_artifact_path = candidate_artifact_path.expanduser().resolve()
        if resolved_artifact_path.exists():
            raise FileExistsError(
                f"candidate artifact destination already exists: {resolved_artifact_path}"
            )
        if not resolved_artifact_path.parent.is_dir():
            raise ValueError("candidate artifact parent must be an existing directory")
        if completion_candidate_limit != 0:
            raise ValueError(
                "disk-backed candidate aggregation requires process-isolated "
                "completion batches"
            )

    incidences = sorted(
        (
            record
            for record in incidence_layer.incidences
            if record.lower_index == lower_index
        ),
        key=lambda record: record.identifier,
    )
    if not incidences:
        raise ValueError("the selected lower cell has no coface incidences")
    lower = lower_cells[lower_index]
    upper_automorphisms: dict[int, IntegralLineAutomorphismGroup] = {}
    cofaces: list[dict[str, object]] = []
    for incidence in incidences:
        if incidence.upper_index not in upper_automorphisms:
            automorphisms = middle_cells[
                incidence.upper_index
            ].configuration.automorphism_group()
            automorphisms.verify()
            upper_automorphisms[incidence.upper_index] = automorphisms
        subgroup = _transported_coface_subgroup(
            incidence,
            lower,
            middle_cells[incidence.upper_index],
            upper_automorphisms[incidence.upper_index],
        )
        cofaces.append(
            {
                "incidence_id": incidence.identifier,
                "attached_line": incidence.attached_line,
                "subgroup_generators": [
                    _matrix_rows(generator) for generator in subgroup.matrix_generators
                ],
                "subgroup_order": str(subgroup.order),
            }
        )
    input_payload: dict[str, object] = {
        "type": "voronoi/coface-pair-input@1",
        "noether_contract": dict(ENGINE_NOETHER_CONTRACT),
        "incidence_layer_id": incidence_layer.identifier,
        "lower_index": lower_index,
        "lower_vectors": lower.min_vectors,
        "target_dimension": incidence_layer.specification.lower_dimension + 2,
        "cofaces": cofaces,
    }
    task: dict[str, object] = {
        **input_payload,
        "type": PAIR_TASK_SCHEMA_VERSION,
        "input_sha256": _digest(input_payload),
        "candidate_cap": candidate_cap,
        "completion_candidate_limit": completion_candidate_limit,
        "completion_max_iterations": completion_max_iterations,
    }
    if resolved_artifact_path is not None:
        task["candidate_artifact_path"] = str(resolved_artifact_path)
    return task


def build_coface_pair_layer(
    lower_cells: Sequence[VoronoiCell],
    middle_cells: Sequence[VoronoiCell],
    incidence_layer: IncidenceLayer | IncidenceShard,
) -> CofacePairLayer:
    """Enumerate every unordered coface-pair orbit by exact double cosets.

    This compatibility path is limited to hand-checkable inputs. Production
    layers must use :func:`build_coface_pair_task` with the bounded Rust engine,
    because even a small faithful action can have millions of double cosets.
    """

    verify_pair_noether_contract()
    expected_specification = IncidenceCensusSpec.from_cells(
        lower_cells,
        middle_cells,
        lower_catalog_claim=incidence_layer.specification.lower_catalog_claim,
        upper_catalog_claim=incidence_layer.specification.upper_catalog_claim,
    )
    if expected_specification != incidence_layer.specification:
        raise ValueError("coface-pair inputs do not match the incidence layer")
    if not incidence_layer.relative_complete:
        raise ValueError("coface-pair enumeration requires complete relative incidence")
    records_by_lower: dict[int, list[IncidenceOrbitRecord]] = defaultdict(list)
    for record in incidence_layer.incidences:
        records_by_lower[record.lower_index].append(record)

    upper_automorphisms: dict[int, IntegralLineAutomorphismGroup] = {}
    records: list[CofacePairOrbitRecord] = []
    raw_double_coset_count = 0
    diagonal_count = 0
    transpose_duplicate_count = 0
    target_dimension = incidence_layer.specification.lower_dimension + 2

    for lower_index, lower in enumerate(lower_cells):
        incidences = sorted(
            records_by_lower.get(lower_index, []), key=lambda record: record.identifier
        )
        if not incidences:
            continue
        automorphisms = lower.configuration.automorphism_group()
        automorphisms.verify()
        entry_upper_bound = (
            len(incidences) * (len(incidences) + 1) // 2 * int(automorphisms.order)
        )
        if entry_upper_bound > PYTHON_PAIR_ENTRY_UPPER_BOUND_CAP:
            raise RuntimeError(
                "refusing to materialize a potentially large double-coset table "
                "in Python; build one lower-cell coface task and run it through "
                "voronoi.enumerate.census_engine.run_coface_pair_task"
            )
        subgroups: list[IntegralLineSubgroup] = []
        for incidence in incidences:
            upper_index = incidence.upper_index
            if upper_index not in upper_automorphisms:
                upper_automorphisms[upper_index] = middle_cells[
                    upper_index
                ].configuration.automorphism_group()
                upper_automorphisms[upper_index].verify()
            subgroup = _transported_coface_subgroup(
                incidence,
                lower,
                middle_cells[upper_index],
                upper_automorphisms[upper_index],
            )
            if any(
                not automorphisms.signed_action.contains(generator)
                for generator in subgroup.signed_action.generators
            ):
                raise RuntimeError(
                    "coface stabilizer is not contained in lower stabilizer"
                )
            subgroups.append(subgroup)

        triangle = automorphisms.signed_action.double_coset_triangle(
            [subgroup.signed_action for subgroup in subgroups]
        )
        if len(triangle) != len(incidences):
            raise RuntimeError("Noether returned an incomplete double-coset table")
        for right_index, row in enumerate(triangle):
            if len(row) != right_index + 1:
                raise RuntimeError(
                    "Noether returned a nontriangular double-coset table"
                )
            right_incidence = incidences[right_index]
            for left_index, double_cosets in enumerate(row):
                left_incidence = incidences[left_index]
                raw_double_coset_count += len(double_cosets)
                for double_coset in double_cosets:
                    representative = double_coset.representative
                    inverse_representative = double_coset.inverse_representative
                    if left_index == right_index:
                        if subgroups[left_index].signed_action.contains(representative):
                            diagonal_count += 1
                            continue
                        if inverse_representative is None:
                            raise RuntimeError(
                                "equal-subgroup double coset omitted its inverse class"
                            )
                        if tuple(representative.images) > tuple(
                            inverse_representative.images
                        ):
                            transpose_duplicate_count += 1
                            continue

                    transformation = automorphisms.lift_signed_action(representative)
                    transformed_right = (
                        IntegralLineConfiguration(
                            lower.lattice_rank, [right_incidence.attached_line]
                        )
                        .transform(transformation)
                        .vectors[0]
                    )
                    candidate = IntegralLineConfiguration(
                        lower.lattice_rank,
                        [
                            *lower.min_vectors,
                            left_incidence.attached_line,
                            transformed_right,
                        ],
                    )
                    status: PairOrbitStatus = (
                        "candidate"
                        if candidate.line_count == lower.ray_count + 2
                        and candidate.perfection_rank == target_dimension
                        else "degenerate"
                    )
                    inverse_images = (
                        None
                        if inverse_representative is None
                        else tuple(int(x) for x in inverse_representative.images)
                    )
                    records.append(
                        CofacePairOrbitRecord(
                            lower_index=lower_index,
                            left_incidence_id=left_incidence.identifier,
                            right_incidence_id=right_incidence.identifier,
                            representative=tuple(int(x) for x in representative.images),
                            inverse_representative=inverse_images,
                            right_coset_count=double_coset.right_coset_count,
                            double_coset_size=int(double_coset.size),
                            candidate_vectors=tuple(
                                tuple(int(x) for x in line)
                                for line in candidate.vectors
                            ),
                            candidate_dimension=candidate.perfection_rank,
                            status=status,
                        )
                    )

    layer = CofacePairLayer(
        incidence_layer_id=incidence_layer.identifier,
        lower_cell_ids=tuple(cell_id(cell) for cell in lower_cells),
        middle_cell_ids=tuple(cell_id(cell) for cell in middle_cells),
        target_dimension=target_dimension,
        records=tuple(
            sorted(
                records,
                key=lambda record: (
                    record.lower_index,
                    record.left_incidence_id,
                    record.right_incidence_id,
                    record.representative,
                ),
            )
        ),
        raw_double_coset_count=raw_double_coset_count,
        diagonal_count=diagonal_count,
        transpose_duplicate_count=transpose_duplicate_count,
    )
    if not layer.relative_complete:
        raise RuntimeError("coface-pair coverage counts do not balance")
    return layer


def compare_coface_pairs_to_catalog(
    pair_layer: CofacePairLayer,
    target_cells: Sequence[VoronoiCell],
) -> CofacePairCatalogReport:
    """Compare every nondegenerate candidate to a supplied orbit catalog.

    This is a validation oracle for a known staircase layer, not a substitute
    for realization or a global census proof.  Every candidate is terminally
    marked matched/unmatched and every target orbit's coverage is reported.
    """

    verify_pair_noether_contract()
    if any(cell.cone_dimension != pair_layer.target_dimension for cell in target_cells):
        raise ValueError("target catalog has the wrong cone dimension")
    buckets: dict[tuple[int, int, int], list[int]] = defaultdict(list)
    for index, cell in enumerate(target_cells):
        key = (
            cell.ray_count,
            cell.cone_dimension,
            int(cell.configuration.barycenter_form.det()),
        )
        buckets[key].append(index)
    target_automorphisms: dict[int, IntegralLineAutomorphismGroup] = {}
    candidate_cache: dict[
        str, tuple[int | None, tuple[tuple[int, ...], ...] | None]
    ] = {}
    matches: list[CofacePairCatalogMatch] = []
    degenerate_pair_ids: list[str] = []

    for record in pair_layer.records:
        if record.status == "degenerate":
            degenerate_pair_ids.append(record.identifier)
            continue
        if record.candidate_id not in candidate_cache:
            candidate = VoronoiCell.from_rows(
                record.candidate_vectors,
                expected_dimension=pair_layer.target_dimension,
            )
            key = (
                candidate.ray_count,
                candidate.cone_dimension,
                int(candidate.configuration.barycenter_form.det()),
            )
            found: list[tuple[int, IntegralLineEquivalence]] = []
            for target_index in buckets.get(key, []):
                if target_index not in target_automorphisms:
                    target_automorphisms[target_index] = target_cells[
                        target_index
                    ].configuration.automorphism_group()
                    target_automorphisms[target_index].verify()
                equivalence = candidate.configuration.equivalence_to(
                    target_cells[target_index].configuration,
                    target_automorphisms=target_automorphisms[target_index],
                )
                if equivalence is not None:
                    equivalence.verify()
                    found.append((target_index, equivalence))
            if len(found) > 1:
                raise RuntimeError(
                    "pair candidate matched multiple supplied target orbits: "
                    f"candidate={record.candidate_id}, targets="
                    f"{[index for index, _ in found]}"
                )
            candidate_cache[record.candidate_id] = (
                (None, None)
                if not found
                else (found[0][0], _matrix_rows(found[0][1].transformation))
            )
        target_index, transformation = candidate_cache[record.candidate_id]
        matches.append(
            CofacePairCatalogMatch(
                pair_id=record.identifier,
                target_index=target_index,
                candidate_to_target=transformation,
            )
        )

    return CofacePairCatalogReport(
        pair_layer_id=pair_layer.identifier,
        target_cell_ids=tuple(cell_id(cell) for cell in target_cells),
        matches=tuple(sorted(matches, key=lambda match: match.pair_id)),
        degenerate_pair_ids=tuple(sorted(degenerate_pair_ids)),
    )


__all__ = [
    "NOETHER_CONTRACT",
    "SCHEMA_VERSION",
    "CertifiedCellRecord",
    "CofacePairCatalogMatch",
    "CofacePairCatalogReport",
    "CofacePairLayer",
    "CofacePairOrbitRecord",
    "FaceOrbitOutcome",
    "IncidenceCensusSpec",
    "IncidenceLayer",
    "IncidenceOrbitRecord",
    "IncidenceShard",
    "build_coface_pair_layer",
    "build_coface_pair_task",
    "build_incidence_shard",
    "cell_id",
    "compare_coface_pairs_to_catalog",
    "merge_incidence_shards",
    "verify_noether_contract",
    "verify_pair_noether_contract",
]
