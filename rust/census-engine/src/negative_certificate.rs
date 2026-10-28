// SPDX-License-Identifier: MIT
//! Voronoi's historical minimum-shell proof adapter and exact checker.
//!
//! The stored schema and quadratic constraint conventions belong here.
//! Rational arithmetic, matrix products, and row reduction use public Noether.

use std::collections::BTreeMap;

use anyhow::{ensure, Context, Result};
use noether::linalg::{IntegralLineConfiguration, Matrix};
use noether::{Integer, Rational, SemanticType, Q};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use crate::noether_contract;

pub const NEGATIVE_CHECK_TASK_SCHEMA: &str = "voronoi/negative-check-task@1";
pub const NEGATIVE_CHECK_REPORT_SCHEMA: &str = "voronoi/negative-check-report@1";
const MAX_BATCH: usize = 100;

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NegativeProofInput {
    pub candidate_id: String,
    pub evidence_sha256: String,
    pub evidence_canonical_json: String,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NegativeCheckTask {
    pub r#type: String,
    pub noether_contract: BTreeMap<String, String>,
    pub proofs: Vec<NegativeProofInput>,
}

#[derive(Debug, Serialize)]
pub struct NegativeCheckReport {
    pub r#type: &'static str,
    pub noether_contract: BTreeMap<String, String>,
    pub input_sha256: String,
    pub checked: usize,
    pub proofs: Vec<CheckedNegativeProof>,
}

#[derive(Debug, Serialize)]
pub struct CheckedNegativeProof {
    pub candidate_id: String,
    pub evidence_sha256: String,
    pub kind: String,
    pub normalization: String,
    pub ambient_rank: usize,
    pub cone_dimension: usize,
    pub vectors: Vec<Vec<String>>,
}

type WireRealization = (String, String, Vec<u8>);
type WireCertificate = (String, Vec<u8>, String, Vec<Vec<String>>, Vec<String>);
type WireConfiguration = (String, usize, Vec<Vec<String>>);

fn quadratic_row(vector: &[Integer]) -> Vec<Rational> {
    (0..vector.len())
        .flat_map(|i| {
            (i..vector.len()).map(move |j| {
                let product = &vector[i] * &vector[j];
                Rational::from(if i == j {
                    product
                } else {
                    product * Integer::from(2)
                })
            })
        })
        .collect()
}

fn column(values: &[Rational]) -> Result<Matrix<noether::RationalField>> {
    Ok(Matrix::from_rows(
        Q,
        values.iter().map(|value| [value.clone()]),
    )?)
}

fn product(rows: &[Vec<Rational>], weights: &[Rational]) -> Result<Vec<Rational>> {
    ensure!(
        !rows.is_empty() && rows.len() == weights.len(),
        "proof multiplier count disagrees"
    );
    let result = Matrix::from_rows(Q, rows.to_vec())?
        .transpose()
        .matmul(&column(weights)?)?;
    Ok(result.rows().map(|row| row[0].clone()).collect())
}

fn dual_matches(
    rows: &[Vec<Rational>],
    rhs: &[Rational],
    objective: &[Rational],
    weights: &[Rational],
    kind: &str,
) -> Result<bool> {
    ensure!(
        rows.len() == rhs.len() && rhs.len() == weights.len(),
        "proof multiplier count disagrees"
    );
    ensure!(
        weights.iter().all(|value| !value.is_negative()),
        "negative dual multiplier"
    );
    let image = product(rows, weights)?;
    let bound = product(
        &rhs.iter()
            .map(|value| vec![value.clone()])
            .collect::<Vec<_>>(),
        weights,
    )?[0]
        .clone();
    Ok(match kind {
        "farkas_infeasible" => image.iter().all(Rational::is_zero) && bound.is_negative(),
        "nonpositive_outsider_margin" => image == objective && !bound.is_positive(),
        "homogeneous_minimum_at_least_one" => image == objective && bound <= Rational::from(-1),
        _ => false,
    })
}

fn homogeneous_rows(
    equalities: &[Vec<Rational>],
    outsiders: &[Vec<Rational>],
) -> (Vec<Vec<Rational>>, Vec<Rational>, Vec<Rational>) {
    let width = equalities[0].len() + 1;
    let mut rows = Vec::new();
    let mut rhs = Vec::new();
    for equality in equalities {
        let mut row = equality.clone();
        row.push(Rational::from(-1));
        rows.push(row.clone());
        rows.push(row.iter().map(|value| -value).collect());
        rhs.extend([Rational::zero(), Rational::zero()]);
    }
    for outsider in outsiders {
        let mut row = outsider.iter().map(|value| -value).collect::<Vec<_>>();
        row.push(Rational::zero());
        rows.push(row);
        rhs.push(Rational::from(-1));
    }
    let mut objective = vec![Rational::zero(); width];
    objective[width - 1] = Rational::from(-1);
    rows.push(objective.clone());
    rhs.push(Rational::zero());
    (rows, rhs, objective)
}

fn margin_rows(
    equalities: &[Vec<Rational>],
    outsiders: &[Vec<Rational>],
) -> Result<(Vec<Vec<Rational>>, Vec<Rational>, Vec<Rational>)> {
    ensure!(!outsiders.is_empty(), "outsider proof has no obstacles");
    let dimension = equalities[0].len();
    let augmented = equalities
        .iter()
        .map(|row| {
            let mut row = row.clone();
            row.push(Rational::one());
            row
        })
        .collect::<Vec<_>>();
    let reduced = Matrix::from_rows(Q, augmented)?
        .rref()?
        .rows()
        .collect::<Vec<_>>();
    let mut pivots = Vec::new();
    for row in &reduced {
        if let Some(pivot) = row.iter().position(|value| !value.is_zero()) {
            ensure!(
                pivot < dimension,
                "inconsistent norms require an equality-inconsistency proof"
            );
            pivots.push(pivot);
        }
    }
    let free = (0..dimension)
        .filter(|column| !pivots.contains(column))
        .collect::<Vec<_>>();
    // Historical wire coordinates: free Gram entries in increasing column
    // order, zero free coordinates for the particular solution. RREF is unique.
    let mut affine = vec![vec![Rational::zero(); free.len() + 1]; dimension];
    for (row_index, pivot) in pivots.iter().enumerate() {
        affine[*pivot][0] = reduced[row_index][dimension].clone();
        for (index, column) in free.iter().enumerate() {
            affine[*pivot][index + 1] = -&reduced[row_index][*column];
        }
    }
    for (index, column) in free.iter().enumerate() {
        affine[*column][index + 1] = Rational::one();
    }
    let evaluations =
        Matrix::from_rows(Q, outsiders.to_vec())?.matmul(&Matrix::from_rows(Q, affine)?)?;
    let mut rows = Vec::new();
    let mut rhs = Vec::new();
    for evaluation in evaluations.rows() {
        let mut row = evaluation[1..]
            .iter()
            .map(|value| -value)
            .collect::<Vec<_>>();
        row.push(Rational::one());
        rows.push(row);
        rhs.push(&evaluation[0] - &Rational::one());
    }
    let mut objective = vec![Rational::zero(); free.len() + 1];
    objective[free.len()] = Rational::one();
    Ok((rows, rhs, objective))
}

/// Verify a saved proof independently of its producer and of Noether's opaque
/// certificate objects. An optional expected configuration binds ledger replay
/// to the already audited orbit representative, not merely a stored label.
pub fn check_negative_proof(
    input: &NegativeProofInput,
    expected: Option<&IntegralLineConfiguration>,
) -> Result<CheckedNegativeProof> {
    let digest = format!(
        "{:x}",
        Sha256::digest(input.evidence_canonical_json.as_bytes())
    );
    ensure!(
        digest == input.evidence_sha256,
        "negative evidence digest disagrees"
    );
    let (type_id, status, encoded): WireRealization =
        serde_json::from_str(&input.evidence_canonical_json)?;
    ensure!(
        type_id == "noether/linalg/MinimumRealization@1" && status == "nonrealizable",
        "unsupported negative realization wire value"
    );
    let (type_id, encoded, kind, obstacle_rows, multiplier_strings): WireCertificate =
        serde_json::from_slice(&encoded)?;
    ensure!(
        type_id == "noether/linalg/MinimumNonrealizabilityCertificate@1",
        "unsupported negative certificate type"
    );
    ensure!(
        matches!(
            kind.as_str(),
            "inconsistent_equal_norms"
                | "farkas_infeasible"
                | "nonpositive_outsider_margin"
                | "homogeneous_minimum_at_least_one"
        ),
        "unsupported negative proof kind"
    );
    let (type_id, rank, vector_rows): WireConfiguration = serde_json::from_slice(&encoded)?;
    ensure!(
        type_id == IntegralLineConfiguration::TYPE_ID
            && (1..=32).contains(&rank)
            && !vector_rows.is_empty()
            && vector_rows.len() <= 10_000
            && obstacle_rows.len() <= 100_000,
        "unsupported negative configuration shape or size"
    );
    let parse_rows = |rows: &[Vec<String>]| -> Result<Vec<Vec<Integer>>> {
        rows.iter()
            .map(|row| {
                ensure!(
                    row.len() == rank,
                    "negative proof vector has wrong ambient rank"
                );
                row.iter()
                    .map(|value| value.parse::<Integer>().map_err(Into::into))
                    .collect()
            })
            .collect()
    };
    let vectors = parse_rows(&vector_rows)?;
    let configuration = IntegralLineConfiguration::new(rank, vectors.clone())?;
    ensure!(
        configuration.vectors() == vectors && configuration.is_spanning(),
        "negative source vectors are not canonical and spanning"
    );
    if let Some(expected) = expected {
        ensure!(
            &configuration == expected,
            "negative proof is for another orbit representative"
        );
    }
    // Hash the original integral coordinates, never their decimal strings.
    let numeric_rows = vectors
        .iter()
        .map(|row| {
            row.iter()
                .map(|entry| entry.to_string().parse::<i64>())
                .collect::<std::result::Result<Vec<_>, _>>()
        })
        .collect::<std::result::Result<Vec<_>, _>>()?;
    let candidate_id = format!(
        "sha256:{:x}",
        Sha256::digest(serde_json::to_vec(&numeric_rows)?)
    );
    ensure!(
        candidate_id == input.candidate_id,
        "negative source content identity disagrees"
    );
    let obstacles = parse_rows(&obstacle_rows)?;
    for obstacle in &obstacles {
        ensure!(
            obstacle.iter().any(|value| !value.is_zero()),
            "zero vector cannot be an outsider"
        );
        let negated = obstacle.iter().map(|value| -value).collect::<Vec<_>>();
        ensure!(
            !vectors.contains(obstacle) && !vectors.contains(&negated),
            "claimed outsider is a source minimum vector"
        );
    }
    let weights = multiplier_strings
        .iter()
        .map(|value| value.parse::<Rational>())
        .collect::<std::result::Result<Vec<_>, _>>()?;
    let equalities = vectors
        .iter()
        .map(|vector| quadratic_row(vector))
        .collect::<Vec<_>>();
    let outsiders = obstacles
        .iter()
        .map(|vector| quadratic_row(vector))
        .collect::<Vec<_>>();
    let normalization = if kind == "inconsistent_equal_norms" {
        ensure!(
            weights.len() == vectors.len(),
            "equality multiplier count disagrees"
        );
        let mut augmented = equalities.clone();
        for row in &mut augmented {
            row.push(Rational::one());
        }
        let identity = product(&augmented, &weights)?;
        ensure!(
            identity[..identity.len() - 1].iter().all(Rational::is_zero)
                && !identity[identity.len() - 1].is_zero(),
            "invalid equal-norm inconsistency identity"
        );
        "equality"
    } else if kind == "homogeneous_minimum_at_least_one" {
        let (rows, rhs, objective) = homogeneous_rows(&equalities, &outsiders);
        ensure!(
            dual_matches(&rows, &rhs, &objective, &weights, &kind)?,
            "invalid homogeneous dual bound"
        );
        "homogeneous"
    } else {
        let (mut rows, mut rhs, objective) = margin_rows(&equalities, &outsiders)?;
        if dual_matches(&rows, &rhs, &objective, &weights, &kind)? {
            "unscaled"
        } else {
            // Both conventions encode the same necessary inequalities. A mode
            // is accepted only when its complete exact dual identity checks.
            let mut changed = false;
            for (row, bound) in rows.iter_mut().zip(&mut rhs) {
                let scale = row
                    .iter()
                    .chain(std::iter::once(&*bound))
                    .map(|value| {
                        if value.is_negative() {
                            -value
                        } else {
                            value.clone()
                        }
                    })
                    .max()
                    .context("empty outsider inequality")?;
                if scale > Rational::from(1_000_000) {
                    changed = true;
                    for value in row {
                        *value = &*value / &scale;
                    }
                    *bound = &*bound / &scale;
                }
            }
            ensure!(
                changed && dual_matches(&rows, &rhs, &objective, &weights, &kind)?,
                "invalid outsider dual identity or bound"
            );
            "scaled-1000000"
        }
    };
    Ok(CheckedNegativeProof {
        candidate_id,
        evidence_sha256: digest,
        kind,
        normalization: normalization.to_owned(),
        ambient_rank: rank,
        cone_dimension: configuration.perfection_rank(),
        vectors: vector_rows,
    })
}

pub fn check_negative_batch(task: &NegativeCheckTask) -> Result<NegativeCheckReport> {
    ensure!(
        task.r#type == NEGATIVE_CHECK_TASK_SCHEMA && task.noether_contract == noether_contract(),
        "unsupported negative check task or Noether contract"
    );
    ensure!(
        !task.proofs.is_empty() && task.proofs.len() <= MAX_BATCH,
        "negative check batch size is outside 1..100"
    );
    let proofs = task
        .proofs
        .iter()
        .map(|proof| {
            check_negative_proof(proof, None)
                .with_context(|| format!("negative proof {}", proof.candidate_id))
        })
        .collect::<Result<Vec<_>>>()?;
    Ok(NegativeCheckReport {
        r#type: NEGATIVE_CHECK_REPORT_SCHEMA,
        noether_contract: noether_contract(),
        input_sha256: format!(
            "{:x}",
            Sha256::digest(serde_json::to_vec(&serde_json::to_value(task)?)?)
        ),
        checked: proofs.len(),
        proofs,
    })
}
