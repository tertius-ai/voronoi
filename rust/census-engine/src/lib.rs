// SPDX-License-Identifier: MIT
//! Bounded hot loops for the Voronoi coface-gluing census.
//!
//! Noether owns exact line configurations, their integral automorphisms, and
//! the finite-group double-coset kernel. This crate owns the application-level
//! operation of joining two known cofaces around a lower Voronoi cell. Each
//! exact pair orbit is classified as it is visited, so a multi-million-entry
//! double-coset table never becomes a Python object graph.

use std::collections::BTreeMap;
use std::path::PathBuf;
use std::str::FromStr;

use anyhow::{bail, Context, Result};
use noether::groups::{visit_double_coset_triangle, DoubleCoset, Permutation, PermutationGroup};
use noether::linalg::{
    IntegralLineConfiguration, Matrix, MinimumCompletion, MinimumCompletionCertificate,
    MinimumRealization, MinimumVectorConfiguration,
};
use noether::{Integer, SemanticType, Z};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

mod candidate_artifact;
mod catalog_match;
mod ledger_replay;
mod negative_certificate;
mod orbit_artifact;

use candidate_artifact::CandidateSpill;
pub use candidate_artifact::{
    CandidateArtifactSummary, CANDIDATE_ARTIFACT_SCHEMA, CANDIDATE_FOOTER_SCHEMA,
    CANDIDATE_RECORD_SCHEMA, CANDIDATE_SUMMARY_SCHEMA,
};
pub use catalog_match::{
    match_catalog, CatalogEntry, CatalogMatchReport, CatalogMatchTask, CATALOG_MATCH_REPORT_SCHEMA,
    CATALOG_MATCH_TASK_SCHEMA,
};
pub use ledger_replay::{
    replay_ledger_stream, LedgerReplayTask, LEDGER_REPLAY_REPORT_SCHEMA, LEDGER_REPLAY_TASK_SCHEMA,
};
pub use negative_certificate::{
    check_negative_batch, check_negative_proof, CheckedNegativeProof, NegativeCheckReport,
    NegativeCheckTask, NegativeProofInput, NEGATIVE_CHECK_REPORT_SCHEMA,
    NEGATIVE_CHECK_TASK_SCHEMA,
};
pub use orbit_artifact::{
    audit_orbit_artifact, key_candidate_artifact, reduce_keyed_artifact, OrbitAuditReport,
    OrbitAuditTask, OrbitKeyReport, OrbitKeyTask, OrbitReductionReport, OrbitReductionTask,
    KEYED_ARTIFACT_SCHEMA, KEYED_FOOTER_SCHEMA, KEYED_RECORD_SCHEMA, ORBIT_ARTIFACT_SCHEMA,
    ORBIT_AUDIT_REPORT_SCHEMA, ORBIT_AUDIT_TASK_SCHEMA, ORBIT_FINGERPRINT_SCHEMA,
    ORBIT_FOOTER_SCHEMA, ORBIT_KEY_REPORT_SCHEMA, ORBIT_KEY_TASK_SCHEMA, ORBIT_RECORD_SCHEMA,
    ORBIT_REDUCTION_REPORT_SCHEMA, ORBIT_REDUCTION_TASK_SCHEMA,
};

/// Input schema consumed by the bounded coface-pair engine.
pub const TASK_SCHEMA: &str = "voronoi/coface-pair-task@2";
/// Output schema produced by the bounded coface-pair engine.
pub const REPORT_SCHEMA: &str = "voronoi/coface-pair-rank-report@2";
/// Input schema for an independently bounded fixed-rank completion batch.
pub const COMPLETION_TASK_SCHEMA: &str = "voronoi/completion-batch-task@2";
/// Output schema for an independently bounded fixed-rank completion batch.
pub const COMPLETION_REPORT_SCHEMA: &str = "voronoi/completion-batch-report@4";
/// Hard ceiling on report-retained or spill-buffered candidate configurations.
pub const MAX_CANDIDATE_CAP: usize = 100_000;
/// Hard ceiling on completions sharing one process.
pub const MAX_COMPLETION_BATCH_SIZE: usize = 10;

fn noether_contract() -> BTreeMap<String, String> {
    [
        ("DoubleCoset", DoubleCoset::TYPE_ID),
        (
            "IntegralLineConfiguration",
            IntegralLineConfiguration::TYPE_ID,
        ),
        ("MinimumCompletion", MinimumCompletion::TYPE_ID),
        (
            "MinimumCompletionCertificate",
            MinimumCompletionCertificate::TYPE_ID,
        ),
        ("Permutation", Permutation::TYPE_ID),
    ]
    .into_iter()
    .map(|(name, type_id)| (name.to_owned(), type_id.to_owned()))
    .collect()
}

fn completion_contract() -> BTreeMap<String, String> {
    let mut contract = noether_contract();
    contract.insert(
        "MinimumRealization".to_owned(),
        MinimumRealization::TYPE_ID.to_owned(),
    );
    contract
}

/// One coface type embedded in the coordinates of a fixed lower cell.
#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct CofaceInput {
    /// Stable incidence identifier from the Python census layer.
    pub incidence_id: String,
    /// The one primitive line attached to the lower configuration.
    pub attached_line: Vec<i64>,
    /// Integral matrices generating its exact stabilizer inside the lower
    /// configuration stabilizer.
    pub subgroup_generators: Vec<Vec<Vec<i64>>>,
    /// Exact expected order of that subgroup.
    pub subgroup_order: String,
}

/// One independently bounded lower-cell coface-pair task.
#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct CofacePairTask {
    /// Must equal [`TASK_SCHEMA`].
    pub r#type: String,
    /// Exact Noether semantic identities required by this task.
    pub noether_contract: BTreeMap<String, String>,
    /// Content identity of the complete relative incidence layer.
    pub incidence_layer_id: String,
    /// Cross-language canonical digest of the mathematical task inputs.
    pub input_sha256: String,
    /// Catalog index of the lower cell.
    pub lower_index: usize,
    /// Canonical primitive-line rows of the lower cell.
    pub lower_vectors: Vec<Vec<i64>>,
    /// Required perfection rank after the two cofaces are joined.
    pub target_dimension: usize,
    /// Exact embedded coface types.
    pub cofaces: Vec<CofaceInput>,
    /// Maximum distinct candidates retained in memory before overflow or spill.
    pub candidate_cap: usize,
    /// Optional absolute path for a complete externally merged candidate artifact.
    #[serde(default)]
    pub candidate_artifact_path: Option<PathBuf>,
    /// Maximum retained candidates subjected to exact fixed-rank completion.
    #[serde(default)]
    pub completion_candidate_limit: usize,
    /// Cutting-plane iteration ceiling per attempted completion.
    #[serde(default = "default_completion_iterations")]
    pub completion_max_iterations: usize,
}

fn default_completion_iterations() -> usize {
    50
}

/// Deterministic aggregate for one subgroup pair.
#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize)]
pub struct PairSummary {
    /// Left incidence identifier.
    pub left_incidence_id: String,
    /// Right incidence identifier.
    pub right_incidence_id: String,
    /// Exact number of double cosets in this pair partition.
    pub raw_double_cosets: u64,
    /// Equal-coface identity classes omitted from unordered pairs.
    pub diagonal: u64,
    /// Classes represented by their inverse partner.
    pub transpose_duplicates: u64,
    /// Unions that added fewer than two distinct lines.
    pub duplicate_line: u64,
    /// Distinct two-line unions with the wrong perfection rank.
    pub wrong_dimension: u64,
    /// Occurrences of retained target-rank embedded candidates.
    pub candidate_occurrences: u64,
}

impl PairSummary {
    fn terminal_count(&self) -> u64 {
        self.diagonal
            + self.transpose_duplicates
            + self.duplicate_line
            + self.wrong_dimension
            + self.candidate_occurrences
    }
}

/// A bounded representative of one exact embedded candidate configuration.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct CandidateSummary {
    /// Stable digest of the exact embedded line rows.
    pub candidate_id: String,
    /// Canonically signed and sorted primitive lines.
    pub vectors: Vec<Vec<i64>>,
    /// Number of pair orbits producing this exact embedded configuration.
    pub occurrence_count: u64,
    /// First left incidence in deterministic traversal order.
    pub witness_left_incidence_id: String,
    /// First right incidence in deterministic traversal order.
    pub witness_right_incidence_id: String,
    /// Canonical signed-action representative of the first occurrence.
    pub witness_representative: Vec<u32>,
    /// Three-way fixed-rank completion status when this retained candidate was
    /// selected for bounded calibration.
    pub completion_status: Option<String>,
    /// Digest of the canonical Noether completion evidence.
    pub completion_evidence_sha256: Option<String>,
    /// Completed minimum shell, when the completion was positive.
    pub completed_vectors: Option<Vec<Vec<i64>>>,
}

#[derive(Clone, Debug)]
struct CandidateAccumulator {
    occurrence_count: u64,
    witness_left_incidence_id: String,
    witness_right_incidence_id: String,
    witness_representative: Vec<u32>,
    completion_status: Option<String>,
    completion_evidence_sha256: Option<String>,
    completed_vectors: Option<Vec<Vec<i64>>>,
}

/// Bounded calibration totals for fixed-rank minimum completion.
#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize)]
pub struct CompletionSummary {
    /// Maximum distinct retained candidates selected for completion.
    pub candidate_limit: usize,
    /// Per-candidate cutting-plane iteration ceiling.
    pub max_iterations: usize,
    /// Number of distinct embedded candidates actually attempted.
    pub attempted: u64,
    /// Positive fixed-rank completions.
    pub completed: u64,
    /// Exact fixed-rank negatives.
    pub nonrealizable: u64,
    /// Honest work-limit checkpoints.
    pub inconclusive: u64,
}

/// One exact embedded configuration selected for isolated completion.
#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct CompletionCandidateInput {
    /// Stable application-level candidate identifier.
    pub candidate_id: String,
    /// Canonically signed primitive lines, revalidated by Noether.
    pub vectors: Vec<Vec<i64>>,
}

/// An independently resource-bounded completion batch.
#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct CompletionBatchTask {
    /// Must equal [`COMPLETION_TASK_SCHEMA`].
    pub r#type: String,
    /// Exact Noether semantic identities required by this task.
    pub noether_contract: BTreeMap<String, String>,
    /// `fixed_rank` admits forced same-rank lines; `exact_shell` does not.
    pub strategy: String,
    /// Cutting-plane iteration ceiling for each candidate.
    pub max_iterations: usize,
    /// At most [`MAX_COMPLETION_BATCH_SIZE`] exact candidates.
    pub candidates: Vec<CompletionCandidateInput>,
}

/// Replayable Gram witness for a positive completion.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct MinimumShellWitness {
    /// Exact positive-definite integral Gram matrix in the completed coordinates.
    pub gram_matrix: Vec<Vec<String>>,
    /// Exact squared minimum; replay also checks that no extra minimal lines occur.
    pub minimum: String,
}

impl From<&MinimumVectorConfiguration> for MinimumShellWitness {
    fn from(value: &MinimumVectorConfiguration) -> Self {
        Self {
            gram_matrix: value
                .gram_matrix()
                .rows()
                .map(|row| row.into_iter().map(|entry| entry.to_string()).collect())
                .collect(),
            minimum: value.minimum().to_string(),
        }
    }
}

/// One three-way completion result, including a replayable positive witness.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct CompletionCandidateResult {
    /// Input candidate identifier.
    pub candidate_id: String,
    /// `completed`, `nonrealizable`, or `inconclusive`.
    pub status: String,
    /// Certificate kind or inconclusive diagnostic reason; absent for a positive.
    pub detail: Option<String>,
    /// Digest of the canonical Noether evidence value.
    pub evidence_sha256: String,
    /// Canonical Noether value, already verified in memory. A positive value's
    /// identity omits its Gram, which is retained separately below.
    pub evidence_canonical_json: String,
    /// Complete minimum shell for a positive result.
    pub completed_vectors: Option<Vec<Vec<i64>>>,
    /// Positive witness omitted by Noether's configuration-identity serialization.
    pub realization_witness: Option<MinimumShellWitness>,
}

/// Complete terminal report for one small completion process.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct CompletionBatchReport {
    /// Always [`COMPLETION_REPORT_SCHEMA`].
    pub r#type: &'static str,
    /// Exact Noether semantic identities that produced the evidence.
    pub noether_contract: BTreeMap<String, String>,
    /// Mathematical playbook selected by the task.
    pub strategy: String,
    /// Per-candidate cutting-plane iteration ceiling.
    pub max_iterations: usize,
    /// Results in input order.
    pub results: Vec<CompletionCandidateResult>,
    /// Verified positive completions.
    pub completed: u64,
    /// Exact nonrealizability certificates.
    pub nonrealizable: u64,
    /// Honest work-limit checkpoints.
    pub inconclusive: u64,
}

impl CompletionBatchReport {
    /// Verify the terminal-status counts.
    pub fn verify_counts(&self) -> Result<()> {
        if self.results.len() as u64 != self.completed + self.nonrealizable + self.inconclusive {
            bail!("completion-batch terminal counts do not balance");
        }
        Ok(())
    }
}

/// Exact streaming coverage report for one lower cell.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct CofacePairReport {
    /// Always [`REPORT_SCHEMA`].
    pub r#type: &'static str,
    /// Exact Noether semantic identities that produced the evidence.
    pub noether_contract: BTreeMap<String, String>,
    /// SHA-256 of the mathematical task inputs, excluding resource/output knobs.
    pub input_sha256: String,
    /// Lower-cell catalog index.
    pub lower_index: usize,
    /// Ambient lattice rank.
    pub ambient_rank: usize,
    /// Required perfection rank.
    pub target_dimension: usize,
    /// Exact lower-cell automorphism-group order.
    pub automorphism_order: String,
    /// Number of coface types.
    pub coface_count: usize,
    /// Exact raw double-coset count across the lower triangle.
    pub raw_double_coset_count: u64,
    /// Exact terminal-status aggregates by subgroup pair.
    pub pairs: Vec<PairSummary>,
    /// Exact embedded candidates retained up to the configured cap.
    pub candidates: Vec<CandidateSummary>,
    /// Maximum number of candidates that could be retained.
    pub candidate_cap: usize,
    /// Candidate occurrences encountered after the distinct-candidate cap was
    /// first reached. These are still rank-classified but not deduplicated.
    pub overflow_candidate_occurrences: u64,
    /// True only when every target-rank occurrence participated in exact
    /// embedded-configuration deduplication.
    pub candidate_aggregation_complete: bool,
    /// Complete disk-backed aggregate when the task requested an artifact.
    pub candidate_artifact: Option<CandidateArtifactSummary>,
    /// Optional bounded fixed-rank completion calibration.
    pub completion: CompletionSummary,
    /// SHA-256 of every pair-orbit representative, size, and terminal status
    /// in deterministic visitation order.
    pub event_stream_sha256: String,
}

impl CofacePairReport {
    /// Check all count identities carried by this report.
    pub fn verify_counts(&self) -> Result<()> {
        let raw: u64 = self.pairs.iter().map(|pair| pair.raw_double_cosets).sum();
        if raw != self.raw_double_coset_count {
            bail!("pair summaries do not add to the raw double-coset count");
        }
        if self
            .pairs
            .iter()
            .any(|pair| pair.raw_double_cosets != pair.terminal_count())
        {
            bail!("one or more pair summaries do not have terminal coverage");
        }
        let retained_occurrences: u64 = self
            .candidates
            .iter()
            .map(|candidate| candidate.occurrence_count)
            .sum();
        let all_candidate_occurrences: u64 = self
            .pairs
            .iter()
            .map(|pair| pair.candidate_occurrences)
            .sum();
        let artifact_occurrences = self
            .candidate_artifact
            .as_ref()
            .map_or(0, |artifact| artifact.candidate_occurrence_count);
        if self.candidate_artifact.is_some()
            && (!self.candidates.is_empty() || self.overflow_candidate_occurrences != 0)
        {
            bail!("disk-backed candidate aggregation also retained or overflowed candidates");
        }
        if self.candidate_aggregation_complete {
            if self.overflow_candidate_occurrences != 0
                || retained_occurrences + artifact_occurrences != all_candidate_occurrences
            {
                bail!("complete candidate aggregation has inconsistent counts");
            }
        } else if self.candidate_artifact.is_some()
            || retained_occurrences + self.overflow_candidate_occurrences
                != all_candidate_occurrences
        {
            bail!("bounded candidate aggregation has inconsistent counts");
        }
        if self.completion.attempted
            != self.completion.completed
                + self.completion.nonrealizable
                + self.completion.inconclusive
            || self.completion.attempted > self.completion.candidate_limit as u64
        {
            bail!("fixed-rank completion calibration counts do not balance");
        }
        Ok(())
    }
}

#[derive(Serialize)]
struct DigestEvent<'a> {
    left: usize,
    right: usize,
    representative: &'a [u32],
    inverse_representative: Option<&'a [u32]>,
    right_coset_count: usize,
    size: String,
    status: &'static str,
}

fn pair_input_sha256(task: &CofacePairTask) -> Result<String> {
    let mut identity = BTreeMap::<String, serde_json::Value>::new();
    identity.insert(
        "type".to_owned(),
        serde_json::Value::String("voronoi/coface-pair-input@1".to_owned()),
    );
    identity.insert(
        "noether_contract".to_owned(),
        serde_json::to_value(&task.noether_contract)?,
    );
    identity.insert(
        "incidence_layer_id".to_owned(),
        serde_json::Value::String(task.incidence_layer_id.clone()),
    );
    identity.insert(
        "lower_index".to_owned(),
        serde_json::to_value(task.lower_index)?,
    );
    identity.insert(
        "lower_vectors".to_owned(),
        serde_json::to_value(&task.lower_vectors)?,
    );
    identity.insert(
        "target_dimension".to_owned(),
        serde_json::to_value(task.target_dimension)?,
    );
    identity.insert("cofaces".to_owned(), serde_json::to_value(&task.cofaces)?);
    Ok(format!(
        "{:x}",
        Sha256::digest(serde_json::to_vec(&identity)?)
    ))
}

fn integers(values: &[i64]) -> Vec<Integer> {
    values.iter().copied().map(Integer::from).collect()
}

fn configuration(rows: &[Vec<i64>], ambient_rank: usize) -> Result<IntegralLineConfiguration> {
    IntegralLineConfiguration::new(
        ambient_rank,
        rows.iter().map(|row| integers(row)).collect::<Vec<_>>(),
    )
    .context("invalid integral-line configuration")
}

fn matrix(rows: &[Vec<i64>], ambient_rank: usize) -> Result<Matrix<noether::IntegerRing>> {
    if rows.len() != ambient_rank || rows.iter().any(|row| row.len() != ambient_rank) {
        bail!("subgroup generator is not an {ambient_rank}x{ambient_rank} matrix");
    }
    Matrix::from_rows(Z, rows.iter().map(|row| integers(row)).collect::<Vec<_>>())
        .context("invalid subgroup-generator matrix")
}

fn i64_vectors(configuration: &IntegralLineConfiguration) -> Result<Vec<Vec<i64>>> {
    configuration
        .vectors()
        .iter()
        .map(|line| {
            line.iter()
                .map(|entry| {
                    i64::from_str(&entry.to_string())
                        .context("candidate coordinate does not fit the census i64 schema")
                })
                .collect()
        })
        .collect()
}

fn pair_slot(left: usize, right: usize) -> usize {
    right * (right + 1) / 2 + left
}

/// Enumerate and immediately rank-classify every unordered coface-pair orbit.
///
/// The finite-group partitions are exact and order-certified by Noether. This
/// function verifies all supplied subgroup matrices against the lower line
/// configuration, enforces the subgroup orders, and records a terminal status
/// for every visited double coset. Candidate retention is separately bounded;
/// reaching that cap produces an honest incomplete aggregation flag without
/// changing the exact rank-classification counts.
pub fn enumerate_coface_pairs(task: &CofacePairTask) -> Result<CofacePairReport> {
    if task.r#type != TASK_SCHEMA {
        bail!("unsupported coface-pair task schema: {}", task.r#type);
    }
    if task.noether_contract != noether_contract() {
        bail!("coface-pair task uses a different Noether semantic contract");
    }
    if !task.incidence_layer_id.starts_with("sha256:") {
        bail!("coface-pair task has an invalid incidence-layer identity");
    }
    if task.lower_vectors.is_empty() {
        bail!("a coface-pair task requires a nonempty lower configuration");
    }
    if task.cofaces.is_empty() {
        bail!("a coface-pair task requires at least one coface");
    }
    if task.candidate_cap == 0 {
        bail!("candidate_cap must be positive");
    }
    if task.candidate_cap > MAX_CANDIDATE_CAP {
        bail!(
            "candidate_cap {} exceeds the engine ceiling {}",
            task.candidate_cap,
            MAX_CANDIDATE_CAP
        );
    }
    if task.completion_candidate_limit > task.candidate_cap {
        bail!("completion_candidate_limit cannot exceed candidate_cap");
    }
    if task.completion_candidate_limit > MAX_COMPLETION_BATCH_SIZE {
        bail!(
            "inline completion calibration cannot exceed {}; use a separate completion-batch task",
            MAX_COMPLETION_BATCH_SIZE
        );
    }
    if task.candidate_artifact_path.is_some() && task.completion_candidate_limit != 0 {
        bail!("disk-backed candidate aggregation requires process-isolated completion batches");
    }
    let mut candidate_spill = task
        .candidate_artifact_path
        .as_ref()
        .map(|path| CandidateSpill::new(path, task.candidate_cap))
        .transpose()?;
    let input_sha256 = pair_input_sha256(task)?;
    if task.input_sha256 != input_sha256 {
        bail!("coface-pair task input digest does not match its mathematical inputs");
    }
    let ambient_rank = task.lower_vectors[0].len();
    let lower = configuration(&task.lower_vectors, ambient_rank)?;
    if !lower.is_spanning() {
        bail!("the lower configuration is not spanning");
    }
    if task.target_dimension != lower.perfection_rank() + 2 {
        bail!("target_dimension must be exactly two above the lower perfection rank");
    }
    let automorphisms = lower
        .automorphism_group()
        .context("could not compute the lower configuration stabilizer")?;
    automorphisms
        .verify()
        .context("lower configuration stabilizer did not verify")?;

    let mut subgroups = Vec::with_capacity(task.cofaces.len());
    for coface in &task.cofaces {
        if coface.attached_line.len() != ambient_rank {
            bail!(
                "coface {} has an attached line of the wrong rank",
                coface.incidence_id
            );
        }
        let generators = coface
            .subgroup_generators
            .iter()
            .map(|rows| matrix(rows, ambient_rank))
            .collect::<Result<Vec<_>>>()?;
        let actions = generators
            .iter()
            .map(|generator| lower.induced_signed_permutation(generator))
            .collect::<std::result::Result<Vec<_>, _>>()
            .context("a coface subgroup generator did not preserve the lower configuration")?;
        let subgroup = PermutationGroup::from_generators(2 * lower.line_count(), &actions)
            .context("invalid coface signed action")?;
        if subgroup.order().to_decimal() != coface.subgroup_order {
            bail!(
                "coface {} subgroup order mismatch: expected {}, got {}",
                coface.incidence_id,
                coface.subgroup_order,
                subgroup.order()
            );
        }
        if subgroup.generators().iter().any(|generator| {
            !automorphisms
                .signed_action()
                .contains(generator)
                .unwrap_or(false)
        }) {
            bail!(
                "coface {} is not a subgroup of the lower stabilizer",
                coface.incidence_id
            );
        }
        subgroups.push(subgroup);
    }

    let mut pairs = Vec::with_capacity(task.cofaces.len() * (task.cofaces.len() + 1) / 2);
    for (right, right_coface) in task.cofaces.iter().enumerate() {
        for left_coface in &task.cofaces[..=right] {
            pairs.push(PairSummary {
                left_incidence_id: left_coface.incidence_id.clone(),
                right_incidence_id: right_coface.incidence_id.clone(),
                ..PairSummary::default()
            });
        }
    }

    let mut candidates: BTreeMap<Vec<Vec<i64>>, CandidateAccumulator> = BTreeMap::new();
    let mut overflow_candidate_occurrences = 0u64;
    let mut raw_double_coset_count = 0u64;
    let mut stream = Sha256::new();
    let mut application_error = None;
    let mut completion = CompletionSummary {
        candidate_limit: task.completion_candidate_limit,
        max_iterations: task.completion_max_iterations,
        ..CompletionSummary::default()
    };

    visit_double_coset_triangle(
        automorphisms.signed_action(),
        &subgroups,
        |left, right, double_coset| {
            if application_error.is_some() {
                return;
            }
            let result = (|| -> Result<()> {
                let slot = pair_slot(left, right);
                let pair = &mut pairs[slot];
                pair.raw_double_cosets += 1;
                raw_double_coset_count += 1;
                if raw_double_coset_count.is_multiple_of(100_000) {
                    eprintln!(
                        "coface-pair progress: raw={} retained_candidates={} overflow_occurrences={}",
                        raw_double_coset_count,
                        candidates.len(),
                        overflow_candidate_occurrences
                    );
                }
                let representative = double_coset.representative();
                let inverse = double_coset.inverse_representative();

                let status = if left == right && subgroups[left].contains(representative)? {
                    pair.diagonal += 1;
                    "diagonal"
                } else if left == right
                    && inverse.is_some_and(|inverse| representative.images() > inverse.images())
                {
                    pair.transpose_duplicates += 1;
                    "transpose_duplicate"
                } else {
                    let right_line = automorphisms
                        .apply_signed_action_to_external_line(
                            representative,
                            integers(&task.cofaces[right].attached_line),
                        )
                        .context("could not act on an attached external line")?;
                    let mut lines = lower.vectors().to_vec();
                    lines.push(integers(&task.cofaces[left].attached_line));
                    lines.push(right_line);
                    let candidate = IntegralLineConfiguration::new(ambient_rank, lines)
                        .context("joined cofaces did not form an integral-line configuration")?;
                    if candidate.line_count() != lower.line_count() + 2 {
                        pair.duplicate_line += 1;
                        "duplicate_line"
                    } else if candidate.perfection_rank() != task.target_dimension {
                        pair.wrong_dimension += 1;
                        "wrong_dimension"
                    } else {
                        pair.candidate_occurrences += 1;
                        let key = i64_vectors(&candidate)?;
                        if let Some(spill) = &mut candidate_spill {
                            spill.record(
                                key,
                                raw_double_coset_count,
                                &task.cofaces[left].incidence_id,
                                &task.cofaces[right].incidence_id,
                                representative.images(),
                            )?;
                        } else if let Some(existing) = candidates.get_mut(&key) {
                            existing.occurrence_count += 1;
                        } else if candidates.len() < task.candidate_cap {
                            let (
                                completion_status,
                                completion_evidence_sha256,
                                completed_vectors,
                            ) = if candidates.len() < task.completion_candidate_limit {
                                let result = candidate
                                    .complete_minimum(task.completion_max_iterations)
                                    .context("fixed-rank candidate completion failed")?;
                                result
                                    .verify()
                                    .context("fixed-rank completion evidence did not verify")?;
                                completion.attempted += 1;
                                match result.status() {
                                    "completed" => completion.completed += 1,
                                    "nonrealizable" => completion.nonrealizable += 1,
                                    "inconclusive" => completion.inconclusive += 1,
                                    status => bail!("unknown completion status {status}"),
                                }
                                let digest = format!(
                                    "{:x}",
                                    Sha256::digest(result.canonical_bytes()?)
                                );
                                let completed = result
                                    .realization()
                                    .map(|value| i64_vectors(value.configuration()))
                                    .transpose()?;
                                (
                                    Some(result.status().to_owned()),
                                    Some(digest),
                                    completed,
                                )
                            } else {
                                (None, None, None)
                            };
                            candidates.insert(
                                key,
                                CandidateAccumulator {
                                    occurrence_count: 1,
                                    witness_left_incidence_id: task.cofaces[left]
                                        .incidence_id
                                        .clone(),
                                    witness_right_incidence_id: task.cofaces[right]
                                        .incidence_id
                                        .clone(),
                                    witness_representative: representative.images().to_vec(),
                                    completion_status,
                                    completion_evidence_sha256,
                                    completed_vectors,
                                },
                            );
                        } else {
                            overflow_candidate_occurrences += 1;
                        }
                        "candidate"
                    }
                };

                let event = DigestEvent {
                    left,
                    right,
                    representative: representative.images(),
                    inverse_representative: inverse.map(|value| value.images()),
                    right_coset_count: double_coset.right_coset_count(),
                    size: double_coset.size().to_decimal(),
                    status,
                };
                let bytes = serde_json::to_vec(&event)?;
                stream.update((bytes.len() as u64).to_be_bytes());
                stream.update(bytes);
                Ok(())
            })();
            if let Err(error) = result {
                application_error = Some(error);
            }
        },
    )
    .context("exact double-coset enumeration failed")?;
    if let Some(error) = application_error {
        return Err(error);
    }

    let event_stream_sha256 = format!("{:x}", stream.finalize());
    let candidate_artifact = candidate_spill
        .as_mut()
        .map(|spill| {
            spill.finish(
                &task.noether_contract,
                task.lower_index,
                ambient_rank,
                task.target_dimension,
                &input_sha256,
                &event_stream_sha256,
            )
        })
        .transpose()?;
    let candidates = candidates
        .into_iter()
        .map(|(vectors, aggregate)| -> Result<CandidateSummary> {
            let digest = Sha256::digest(serde_json::to_vec(&vectors)?);
            Ok(CandidateSummary {
                candidate_id: format!("sha256:{digest:x}"),
                vectors,
                occurrence_count: aggregate.occurrence_count,
                witness_left_incidence_id: aggregate.witness_left_incidence_id,
                witness_right_incidence_id: aggregate.witness_right_incidence_id,
                witness_representative: aggregate.witness_representative,
                completion_status: aggregate.completion_status,
                completion_evidence_sha256: aggregate.completion_evidence_sha256,
                completed_vectors: aggregate.completed_vectors,
            })
        })
        .collect::<Result<Vec<_>>>()?;
    let report = CofacePairReport {
        r#type: REPORT_SCHEMA,
        noether_contract: noether_contract(),
        input_sha256,
        lower_index: task.lower_index,
        ambient_rank,
        target_dimension: task.target_dimension,
        automorphism_order: automorphisms.order().to_string(),
        coface_count: task.cofaces.len(),
        raw_double_coset_count,
        pairs,
        candidates,
        candidate_cap: task.candidate_cap,
        overflow_candidate_occurrences,
        candidate_aggregation_complete: candidate_artifact.is_some()
            || overflow_candidate_occurrences == 0,
        candidate_artifact,
        completion,
        event_stream_sha256,
    };
    report.verify_counts()?;
    Ok(report)
}

/// Complete a small candidate batch without retaining a double-coset table.
///
/// This is deliberately a separate process-level task from pair enumeration:
/// exact LP allocators and hard candidates cannot accumulate inside the
/// long-lived process that owns a multi-gigabyte ambient group table.
pub fn complete_candidate_batch(task: &CompletionBatchTask) -> Result<CompletionBatchReport> {
    if task.r#type != COMPLETION_TASK_SCHEMA {
        bail!("unsupported completion-batch task schema: {}", task.r#type);
    }
    if task.noether_contract != completion_contract() {
        bail!("completion task uses a different Noether semantic contract");
    }
    if !matches!(task.strategy.as_str(), "fixed_rank" | "exact_shell") {
        bail!("unsupported completion strategy {}", task.strategy);
    }
    if task.candidates.is_empty() {
        bail!("a completion batch requires at least one candidate");
    }
    if task.candidates.len() > MAX_COMPLETION_BATCH_SIZE {
        bail!(
            "completion batch has {} candidates; the process ceiling is {}",
            task.candidates.len(),
            MAX_COMPLETION_BATCH_SIZE
        );
    }
    let mut results = Vec::with_capacity(task.candidates.len());
    let mut completed = 0u64;
    let mut nonrealizable = 0u64;
    let mut inconclusive = 0u64;
    for (index, input) in task.candidates.iter().enumerate() {
        if input.vectors.is_empty() {
            bail!("completion candidate {} has no lines", input.candidate_id);
        }
        eprintln!(
            "completion progress: candidate={}/{} id={}",
            index + 1,
            task.candidates.len(),
            input.candidate_id
        );
        let seed = configuration(&input.vectors, input.vectors[0].len())?;
        let (status, detail, completed_vectors, evidence_bytes, realization_witness) =
            if task.strategy == "fixed_rank" {
                let result = seed
                    .complete_minimum(task.max_iterations)
                    .context("fixed-rank candidate completion failed")?;
                result
                    .verify()
                    .context("fixed-rank completion evidence did not verify")?;
                let (detail, completed_vectors) = match result.status() {
                    "completed" => {
                        let realization = result
                            .realization()
                            .context("completed result omitted its realization")?;
                        (None, Some(i64_vectors(realization.configuration())?))
                    }
                    "nonrealizable" => {
                        let certificate = result
                            .certificate()
                            .context("negative result omitted its certificate")?;
                        (Some(certificate.kind().to_owned()), None)
                    }
                    "inconclusive" => {
                        let diagnostic = result
                            .diagnostic()
                            .context("inconclusive result omitted its diagnostic")?;
                        (Some(diagnostic.reason().to_owned()), None)
                    }
                    status => bail!("unknown completion status {status}"),
                };
                (
                    result.status().to_owned(),
                    detail,
                    completed_vectors,
                    result.canonical_bytes()?,
                    result.realization().map(MinimumShellWitness::from),
                )
            } else {
                let result = seed
                    .realize_minimum(task.max_iterations)
                    .context("exact-shell candidate realization failed")?;
                result
                    .verify()
                    .context("exact-shell realization evidence did not verify")?;
                let (status, detail, completed_vectors) = match result.status() {
                    "realized" => {
                        let realization = result
                            .realization()
                            .context("realized result omitted its realization")?;
                        (
                            "completed".to_owned(),
                            None,
                            Some(i64_vectors(realization.configuration())?),
                        )
                    }
                    "nonrealizable" => {
                        let certificate = result
                            .certificate()
                            .context("negative result omitted its certificate")?;
                        (
                            "nonrealizable".to_owned(),
                            Some(certificate.kind().to_owned()),
                            None,
                        )
                    }
                    "inconclusive" => {
                        let diagnostic = result
                            .diagnostic()
                            .context("inconclusive result omitted its diagnostic")?;
                        (
                            "inconclusive".to_owned(),
                            Some(diagnostic.reason().to_owned()),
                            None,
                        )
                    }
                    status => bail!("unknown realization status {status}"),
                };
                (
                    status,
                    detail,
                    completed_vectors,
                    result.canonical_bytes()?,
                    result.realization().map(MinimumShellWitness::from),
                )
            };
        match status.as_str() {
            "completed" => completed += 1,
            "nonrealizable" => nonrealizable += 1,
            "inconclusive" => inconclusive += 1,
            _ => bail!("unknown normalized completion status {status}"),
        }
        let evidence_canonical_json = String::from_utf8(evidence_bytes.clone())
            .context("canonical completion evidence was not UTF-8 JSON")?;
        serde_json::from_slice::<serde_json::Value>(&evidence_bytes)
            .context("canonical completion evidence was not JSON")?;
        results.push(CompletionCandidateResult {
            candidate_id: input.candidate_id.clone(),
            status,
            detail,
            evidence_sha256: format!("{:x}", Sha256::digest(&evidence_bytes)),
            evidence_canonical_json,
            completed_vectors,
            realization_witness,
        });
    }
    let report = CompletionBatchReport {
        r#type: COMPLETION_REPORT_SCHEMA,
        noether_contract: completion_contract(),
        strategy: task.strategy.clone(),
        max_iterations: task.max_iterations,
        results,
        completed,
        nonrealizable,
        inconclusive,
    };
    report.verify_counts()?;
    Ok(report)
}

#[cfg(test)]
mod tests {
    use std::fs;
    use std::time::{SystemTime, UNIX_EPOCH};

    use super::*;

    fn trivial_coface(id: &str, attached_line: Vec<i64>) -> CofaceInput {
        CofaceInput {
            incidence_id: id.to_owned(),
            attached_line,
            subgroup_generators: Vec::new(),
            subgroup_order: "1".to_owned(),
        }
    }

    fn signed_task(mut task: CofacePairTask) -> CofacePairTask {
        task.input_sha256 = pair_input_sha256(&task).unwrap();
        task
    }

    #[test]
    fn small_stream_has_exact_terminal_coverage() {
        let task = signed_task(CofacePairTask {
            r#type: TASK_SCHEMA.to_owned(),
            noether_contract: noether_contract(),
            incidence_layer_id: "sha256:test-incidence".to_owned(),
            input_sha256: String::new(),
            lower_index: 7,
            lower_vectors: vec![vec![1, 0, 0], vec![0, 1, 0], vec![0, 0, 1]],
            target_dimension: 5,
            cofaces: vec![
                trivial_coface("a", vec![1, 1, 0]),
                trivial_coface("b", vec![1, 0, 1]),
            ],
            candidate_cap: 1_000,
            candidate_artifact_path: None,
            completion_candidate_limit: 2,
            completion_max_iterations: 20,
        });
        let first = enumerate_coface_pairs(&task).unwrap();
        let second = enumerate_coface_pairs(&task).unwrap();
        first.verify_counts().unwrap();
        assert_eq!(first, second);
        assert!(first.raw_double_coset_count > 0);
        assert!(first.candidate_aggregation_complete);
        assert!(!first.candidates.is_empty());
        assert_eq!(first.completion.attempted, 2);
    }

    #[test]
    fn candidate_cap_is_honest() {
        let task = signed_task(CofacePairTask {
            r#type: TASK_SCHEMA.to_owned(),
            noether_contract: noether_contract(),
            incidence_layer_id: "sha256:test-incidence".to_owned(),
            input_sha256: String::new(),
            lower_index: 0,
            lower_vectors: vec![vec![1, 0, 0], vec![0, 1, 0], vec![0, 0, 1]],
            target_dimension: 5,
            cofaces: vec![
                trivial_coface("a", vec![1, 1, 0]),
                trivial_coface("b", vec![1, 0, 1]),
            ],
            candidate_cap: 1,
            candidate_artifact_path: None,
            completion_candidate_limit: 0,
            completion_max_iterations: 20,
        });
        let report = enumerate_coface_pairs(&task).unwrap();
        report.verify_counts().unwrap();
        assert!(!report.candidate_aggregation_complete);
        assert_eq!(report.candidates.len(), 1);
        assert!(report.overflow_candidate_occurrences > 0);
    }

    #[test]
    fn candidate_spill_is_complete_deterministic_and_non_overwriting() {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let first_path = std::env::temp_dir().join(format!(
            "voronoi-candidate-artifact-{}-{nonce}-first.jsonl",
            std::process::id()
        ));
        let second_path = std::env::temp_dir().join(format!(
            "voronoi-candidate-artifact-{}-{nonce}-second.jsonl",
            std::process::id()
        ));
        let base = signed_task(CofacePairTask {
            r#type: TASK_SCHEMA.to_owned(),
            noether_contract: noether_contract(),
            incidence_layer_id: "sha256:test-incidence".to_owned(),
            input_sha256: String::new(),
            lower_index: 0,
            lower_vectors: vec![vec![1, 0, 0], vec![0, 1, 0], vec![0, 0, 1]],
            target_dimension: 5,
            cofaces: vec![
                trivial_coface("a", vec![1, 1, 0]),
                trivial_coface("b", vec![1, 0, 1]),
            ],
            candidate_cap: 1,
            candidate_artifact_path: Some(first_path.clone()),
            completion_candidate_limit: 0,
            completion_max_iterations: 20,
        });
        let first = enumerate_coface_pairs(&base).unwrap();
        first.verify_counts().unwrap();
        let summary = first.candidate_artifact.as_ref().unwrap();
        assert!(first.candidates.is_empty());
        assert_eq!(first.overflow_candidate_occurrences, 0);
        assert!(first.candidate_aggregation_complete);
        assert!(summary.distinct_candidate_count > 1);
        assert_eq!(
            summary.candidate_occurrence_count,
            first
                .pairs
                .iter()
                .map(|pair| pair.candidate_occurrences)
                .sum::<u64>()
        );
        assert!(enumerate_coface_pairs(&base)
            .unwrap_err()
            .to_string()
            .contains("already exists"));

        let mut second_task = base;
        second_task.candidate_artifact_path = Some(second_path.clone());
        let second = enumerate_coface_pairs(&second_task).unwrap();
        assert_eq!(first, second);
        assert_eq!(
            fs::read(&first_path).unwrap(),
            fs::read(&second_path).unwrap()
        );

        let lines = fs::read_to_string(&first_path).unwrap();
        let decoded = lines
            .lines()
            .map(|line| serde_json::from_str::<serde_json::Value>(line).unwrap())
            .collect::<Vec<_>>();
        assert_eq!(decoded.first().unwrap()["type"], CANDIDATE_ARTIFACT_SCHEMA);
        assert_eq!(decoded.last().unwrap()["type"], CANDIDATE_FOOTER_SCHEMA);
        assert_eq!(
            decoded
                .iter()
                .filter(|line| line["type"] == CANDIDATE_RECORD_SCHEMA)
                .count() as u64,
            summary.distinct_candidate_count
        );

        fs::remove_file(first_path).unwrap();
        fs::remove_file(second_path).unwrap();
    }

    #[test]
    fn completion_batch_is_small_terminal_and_deterministic() {
        let task = CompletionBatchTask {
            r#type: COMPLETION_TASK_SCHEMA.to_owned(),
            noether_contract: completion_contract(),
            strategy: "fixed_rank".to_owned(),
            max_iterations: 20,
            candidates: vec![
                CompletionCandidateInput {
                    candidate_id: "axes".to_owned(),
                    vectors: vec![vec![1, 0], vec![0, 1]],
                },
                CompletionCandidateInput {
                    candidate_id: "inconsistent".to_owned(),
                    vectors: vec![vec![1, 0], vec![0, 1], vec![1, 1], vec![1, -1]],
                },
            ],
        };
        let first = complete_candidate_batch(&task).unwrap();
        let second = complete_candidate_batch(&task).unwrap();
        assert_eq!(first, second);
        assert_eq!(first.completed, 1);
        assert_eq!(first.nonrealizable, 1);
        assert_eq!(first.inconclusive, 0);
        assert!(first.results[0].realization_witness.is_some());
        assert!(first.results[1].realization_witness.is_none());
        first.verify_counts().unwrap();

        let exact = complete_candidate_batch(&CompletionBatchTask {
            strategy: "exact_shell".to_owned(),
            ..task
        })
        .unwrap();
        assert_eq!(exact.completed, 1);
        assert_eq!(exact.nonrealizable, 1);
        assert_eq!(exact.inconclusive, 0);
        exact.verify_counts().unwrap();
    }

    #[test]
    fn equality_reduced_completion_resolves_the_large_coefficient_tail() {
        let task = CompletionBatchTask {
            r#type: COMPLETION_TASK_SCHEMA.to_owned(),
            noether_contract: completion_contract(),
            strategy: "exact_shell".to_owned(),
            max_iterations: 200,
            candidates: vec![
                CompletionCandidateInput {
                    candidate_id:
                        "sha256:b82d97ad12dd84ae8d7035a92fadfdc4076a69aab9c125be4de7bcc33deb183f"
                            .to_owned(),
                    vectors: vec![
                        vec![0, 0, 0, 0, 0, 0, 0, 1],
                        vec![0, 0, 0, 0, 0, 0, 1, 0],
                        vec![0, 0, 0, 0, 0, 1, 0, 0],
                        vec![0, 0, 0, 0, 1, 0, 0, 0],
                        vec![0, 0, 0, 1, 0, 0, 0, 0],
                        vec![0, 0, 1, 0, 0, 0, 0, 0],
                        vec![0, 1, 0, 0, 0, 0, 0, 0],
                        vec![1, 0, 0, 0, 0, 0, 0, 0],
                        vec![1, 4, -1, -3, 2, -1, -1, 1],
                        vec![2, 2, -5, 1, 1, 1, -3, 4],
                    ],
                },
                CompletionCandidateInput {
                    candidate_id:
                        "sha256:0935e7c9391525882540c3b2b34258061333b40702f4d1fa0f01d8d0d51d09e8"
                            .to_owned(),
                    vectors: vec![
                        vec![0, 0, 0, 0, 0, 0, 0, 1],
                        vec![0, 0, 0, 0, 0, 0, 1, 0],
                        vec![0, 0, 0, 0, 0, 1, 0, 0],
                        vec![0, 0, 0, 0, 1, 0, 0, 0],
                        vec![0, 0, 0, 1, 0, 0, 0, 0],
                        vec![0, 0, 1, 0, 0, 0, 0, 0],
                        vec![0, 1, 0, 0, 0, 0, 0, 0],
                        vec![1, 0, 0, 0, 0, 0, 0, 0],
                        vec![2, -3, -4, -1, -1, -1, 1, -2],
                        vec![4, -3, -1, -1, -2, -1, 2, 0],
                    ],
                },
                CompletionCandidateInput {
                    candidate_id:
                        "sha256:1d95e427baf77e35df6c5cd6168dc600f4308e4da2bdb9106bb78c43e635cfae"
                            .to_owned(),
                    vectors: vec![
                        vec![0, 0, 0, 0, 0, 0, 0, 1],
                        vec![0, 0, 0, 0, 0, 0, 1, 0],
                        vec![0, 0, 0, 0, 0, 1, 0, 0],
                        vec![0, 0, 0, 0, 1, 0, 0, 0],
                        vec![0, 0, 0, 1, 0, 0, 0, 0],
                        vec![0, 0, 1, 0, 0, 0, 0, 0],
                        vec![0, 1, 0, 0, 0, 0, 0, 0],
                        vec![1, 0, 0, 0, 0, 0, 0, 0],
                        vec![2, -3, -1, 2, 2, 2, -3, 1],
                        vec![2, -3, 1, 2, 2, -1, -1, 0],
                    ],
                },
            ],
        };
        let report = complete_candidate_batch(&task).unwrap();
        assert_eq!(report, complete_candidate_batch(&task).unwrap());
        assert_eq!(report.completed, 0);
        assert_eq!(report.nonrealizable, 3);
        assert_eq!(report.inconclusive, 0);
        assert_eq!(
            report
                .results
                .iter()
                .map(|result| result.detail.as_deref())
                .collect::<Vec<_>>(),
            vec![Some("nonpositive_outsider_margin"); 3]
        );
        report.verify_counts().unwrap();
    }
}
