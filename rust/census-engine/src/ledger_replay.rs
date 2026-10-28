// SPDX-License-Identifier: MIT
//! Streaming replay of immutable completion ledgers, bound to the orbit input.

use std::collections::BTreeMap;
use std::fs::{self, File, OpenOptions};
use std::io::{BufRead, BufReader, BufWriter, Write};
use std::path::PathBuf;

use anyhow::{ensure, Context, Result};
use noether::linalg::{Lattice, Matrix};
use noether::{Integer, Z};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use crate::{
    check_negative_proof, configuration, i64_vectors, noether_contract, NegativeProofInput,
};

pub const LEDGER_REPLAY_TASK_SCHEMA: &str = "voronoi/ledger-replay-task@1";
pub const LEDGER_REPLAY_REPORT_SCHEMA: &str = "voronoi/ledger-replay-report@1";

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct LedgerReplayTask {
    pub r#type: String,
    pub noether_contract: BTreeMap<String, String>,
    pub orbit_path: PathBuf,
    pub orbit_content_sha256: String,
    pub positive_witnesses_path: PathBuf,
    pub positive_witnesses_sha256: String,
    pub source_metadata_sha256: String,
    pub receipt_path: PathBuf,
    pub ambient_rank: usize,
    pub cone_dimension: usize,
    pub lower_index: usize,
    pub pair_input_sha256: String,
    pub event_stream_sha256: String,
    pub orbit_count: usize,
    pub partition_index: usize,
    pub partition_count: usize,
    pub expected_positive: usize,
    pub expected_negative: usize,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct PositiveWitness {
    candidate_id: String,
    vectors: Vec<Vec<i64>>,
    gram_matrix: Vec<Vec<String>>,
    minimum: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct LedgerPayload {
    candidate_id: String,
    status: String,
    evidence_sha256: String,
    evidence_canonical_json: String,
    completed_vectors: Option<Vec<Vec<i64>>>,
    detail: Option<String>,
    #[serde(default)]
    realization_witness: Option<serde_json::Value>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct LedgerRow {
    candidate_index: usize,
    batch_index: usize,
    max_iterations: usize,
    candidate_id: String,
    status: String,
    payload: LedgerPayload,
}

#[derive(Debug, Deserialize)]
struct OrbitRow {
    r#type: String,
    representative: OrbitRepresentative,
}

#[derive(Debug, Deserialize)]
struct OrbitRepresentative {
    candidate_id: String,
    vectors: Vec<Vec<i64>>,
}

#[derive(Debug, Serialize)]
pub struct LedgerReplayReport {
    pub r#type: &'static str,
    pub noether_contract: BTreeMap<String, String>,
    pub task_sha256: String,
    pub input_content_sha256: String,
    pub orbit_content_sha256: String,
    pub positive_witnesses_sha256: String,
    pub source_metadata_sha256: String,
    pub partition_index: usize,
    pub partition_count: usize,
    pub positive: usize,
    pub negative: usize,
    pub record_count: usize,
    pub negative_kinds: BTreeMap<String, usize>,
    pub normalizations: BTreeMap<String, usize>,
    pub receipt_content_sha256: String,
}

fn line(reader: &mut impl BufRead) -> Result<Vec<u8>> {
    let mut bytes = Vec::new();
    reader.read_until(b'\n', &mut bytes)?;
    ensure!(
        bytes.ends_with(b"\n"),
        "replay input is truncated or not newline terminated"
    );
    Ok(bytes)
}

fn write_line(
    writer: &mut impl Write,
    digest: &mut Sha256,
    value: &serde_json::Value,
) -> Result<()> {
    let mut bytes = serde_json::to_vec(value)?;
    bytes.push(b'\n');
    writer.write_all(&bytes)?;
    digest.update(bytes);
    Ok(())
}

pub fn replay_ledger_stream(
    task: &LedgerReplayTask,
    header_line: &[u8],
    input: &mut impl BufRead,
) -> Result<LedgerReplayReport> {
    ensure!(
        task.r#type == LEDGER_REPLAY_TASK_SCHEMA && task.noether_contract == noether_contract(),
        "unsupported ledger replay task or contract"
    );
    ensure!(
        (1..=64).contains(&task.partition_count)
            && task.partition_index < task.partition_count
            && (1..=32).contains(&task.ambient_rank)
            && task.orbit_count > 0,
        "invalid replay partition or ambient rank"
    );
    for path in [&task.orbit_path, &task.positive_witnesses_path] {
        ensure!(
            path.is_absolute() && path.is_file(),
            "replay source must be an absolute file path"
        );
    }
    ensure!(
        task.receipt_path.is_absolute() && !task.receipt_path.exists(),
        "replay receipt destination exists or is relative"
    );
    let positive_bytes = fs::read(&task.positive_witnesses_path)?;
    ensure!(
        format!("{:x}", Sha256::digest(&positive_bytes)) == task.positive_witnesses_sha256,
        "positive witness file digest disagrees"
    );
    let mut positives = BTreeMap::new();
    for witness in serde_json::from_slice::<Vec<PositiveWitness>>(&positive_bytes)? {
        ensure!(
            positives
                .insert(witness.candidate_id.clone(), witness)
                .is_none(),
            "duplicate positive witness"
        );
    }
    let task_sha256 = format!(
        "{:x}",
        Sha256::digest(serde_json::to_vec(&serde_json::to_value(task)?)?)
    );
    let partial = task
        .receipt_path
        .with_extension(format!("partial-{}", std::process::id()));
    let file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&partial)?;
    let mut writer = BufWriter::new(file);
    let mut receipt_digest = Sha256::new();
    write_line(
        &mut writer,
        &mut receipt_digest,
        &serde_json::json!({
            "type":"voronoi/ledger-replay-receipts@1", "task_sha256":task_sha256,
            "orbit_content_sha256":task.orbit_content_sha256,
            "positive_witnesses_sha256":task.positive_witnesses_sha256,
            "partition_index":task.partition_index,"partition_count":task.partition_count,
        }),
    )?;
    let mut orbit = BufReader::new(File::open(&task.orbit_path)?);
    let orbit_header_line = line(&mut orbit)?;
    let header: serde_json::Value = serde_json::from_slice(&orbit_header_line)?;
    ensure!(
        header["type"] == "voronoi/orbit-artifact@1"
            && header["ambient_rank"] == task.ambient_rank
            && header["target_dimension"] == task.cone_dimension
            && header["lower_index"] == task.lower_index
            && header["input_sha256"] == task.pair_input_sha256
            && header["event_stream_sha256"] == task.event_stream_sha256
            && header["noether_contract"] == serde_json::to_value(noether_contract())?,
        "orbit replay source scope disagrees"
    );
    let mut orbit_digest = Sha256::new();
    orbit_digest.update(&orbit_header_line);
    let mut input_digest = Sha256::new();
    input_digest.update(header_line);
    let mut positive = 0;
    let mut negative = 0;
    let mut kinds = BTreeMap::new();
    let mut normalizations = BTreeMap::new();
    for index in 0..task.orbit_count {
        let orbit_line = line(&mut orbit)?;
        orbit_digest.update(&orbit_line);
        if index % task.partition_count != task.partition_index {
            continue;
        }
        let expected: OrbitRow = serde_json::from_slice(&orbit_line)?;
        ensure!(
            expected.r#type == "voronoi/orbit-record@1",
            "unexpected orbit record type"
        );
        let bytes = line(input)?;
        input_digest.update(&bytes);
        let row: LedgerRow = serde_json::from_slice(&bytes)?;
        let result = (|| -> Result<serde_json::Value> {
            ensure!(
                row.candidate_index == index && row.batch_index == index,
                "ledger index coverage disagrees with orbit stream"
            );
            ensure!(
                row.candidate_id == expected.representative.candidate_id
                    && row.candidate_id == row.payload.candidate_id
                    && row.status == row.payload.status,
                "ledger candidate identity or status disagrees with orbit stream"
            );
            let _ = (row.max_iterations, &row.payload.detail);
            let expected_configuration =
                configuration(&expected.representative.vectors, task.ambient_rank)?;
            ensure!(
                i64_vectors(&expected_configuration)? == expected.representative.vectors,
                "orbit source vectors are not canonical"
            );
            let evidence_sha256 = format!(
                "{:x}",
                Sha256::digest(row.payload.evidence_canonical_json.as_bytes())
            );
            ensure!(
                evidence_sha256 == row.payload.evidence_sha256,
                "stored evidence digest disagrees"
            );
            let (kind, normalization) = match row.status.as_str() {
                "nonrealizable" => {
                    ensure!(
                        row.payload.completed_vectors.is_none()
                            && row.payload.realization_witness.is_none(),
                        "negative ledger result carries a positive shell"
                    );
                    let checked = check_negative_proof(
                        &NegativeProofInput {
                            candidate_id: row.candidate_id.clone(),
                            evidence_sha256: evidence_sha256.clone(),
                            evidence_canonical_json: row.payload.evidence_canonical_json,
                        },
                        Some(&expected_configuration),
                    )?;
                    ensure!(
                        checked.cone_dimension == task.cone_dimension,
                        "negative proof has wrong cone dimension"
                    );
                    negative += 1;
                    *kinds.entry(checked.kind.clone()).or_insert(0usize) += 1;
                    *normalizations
                        .entry(checked.normalization.clone())
                        .or_insert(0usize) += 1;
                    (checked.kind, checked.normalization)
                }
                "completed" => {
                    ensure!(
                        row.payload.completed_vectors.as_ref()
                            == Some(&expected.representative.vectors),
                        "historical exact-shell positive changed its source vectors"
                    );
                    let witness = positives
                        .remove(&row.candidate_id)
                        .context("positive ledger result has no Gram witness")?;
                    ensure!(
                        witness.vectors == expected.representative.vectors,
                        "positive witness is for another configuration"
                    );
                    let gram_rows = witness
                        .gram_matrix
                        .iter()
                        .map(|row| {
                            row.iter()
                                .map(|value| value.parse::<Integer>())
                                .collect::<std::result::Result<Vec<_>, _>>()
                        })
                        .collect::<std::result::Result<Vec<_>, _>>()?;
                    let shell = Lattice::from_gram(Matrix::from_rows(Z, gram_rows)?)?
                        .minimum_vector_configuration()?;
                    shell.verify()?;
                    ensure!(
                        shell.configuration() == &expected_configuration
                            && shell.minimum().to_string() == witness.minimum
                            && expected_configuration.perfection_rank() == task.cone_dimension,
                        "positive Gram did not reproduce its complete minimum shell"
                    );
                    positive += 1;
                    (
                        "positive_gram".to_owned(),
                        "original_coordinates".to_owned(),
                    )
                }
                _ => anyhow::bail!("ledger result is not terminal"),
            };
            Ok(serde_json::json!({"type":"voronoi/ledger-proof-receipt@1",
                "candidate_index":index,"candidate_id":row.candidate_id,"status":row.status,
                "evidence_sha256":evidence_sha256,"kind":kind,"normalization":normalization}))
        })()
        .with_context(|| format!("ledger replay index={index} id={}", row.candidate_id))?;
        write_line(&mut writer, &mut receipt_digest, &result)?;
        if (positive + negative) % 10_000 == 0 {
            eprintln!(
                "ledger replay partition={}: positive={positive} negative={negative}",
                task.partition_index
            );
        }
    }
    let orbit_footer: serde_json::Value = serde_json::from_slice(&line(&mut orbit)?)?;
    let orbit_sha256 = format!("{:x}", orbit_digest.finalize());
    ensure!(
        orbit_footer["type"] == "voronoi/orbit-footer@1"
            && orbit_footer["orbit_count"] == task.orbit_count
            && orbit_footer["content_sha256"] == orbit_sha256
            && orbit_sha256 == task.orbit_content_sha256
            && orbit.fill_buf()?.is_empty(),
        "orbit replay source digest or extent disagrees"
    );
    let input_footer: serde_json::Value = serde_json::from_slice(&line(input)?)?;
    let input_sha256 = format!("{:x}", input_digest.finalize());
    ensure!(
        input_footer
            == serde_json::json!({"type":"voronoi/ledger-stream-footer@1",
        "record_count":positive+negative,"content_sha256":input_sha256})
            && input.fill_buf()?.is_empty(),
        "ledger input stream digest or extent disagrees"
    );
    ensure!(
        positive == task.expected_positive && negative == task.expected_negative,
        "ledger replay positive/negative coverage disagrees"
    );
    let receipt_sha256 = format!("{:x}", receipt_digest.finalize());
    serde_json::to_writer(
        &mut writer,
        &serde_json::json!({
            "type":"voronoi/ledger-replay-footer@1","record_count":positive+negative,
            "positive":positive,"negative":negative,"content_sha256":receipt_sha256,
        }),
    )?;
    writer.write_all(b"\n")?;
    writer.flush()?;
    writer
        .into_inner()
        .map_err(|error| error.into_error())?
        .sync_all()?;
    fs::hard_link(&partial, &task.receipt_path)?;
    fs::remove_file(&partial)?;
    Ok(LedgerReplayReport {
        r#type: LEDGER_REPLAY_REPORT_SCHEMA,
        noether_contract: noether_contract(),
        task_sha256,
        input_content_sha256: input_sha256,
        orbit_content_sha256: orbit_sha256,
        positive_witnesses_sha256: task.positive_witnesses_sha256.clone(),
        source_metadata_sha256: task.source_metadata_sha256.clone(),
        partition_index: task.partition_index,
        partition_count: task.partition_count,
        positive,
        negative,
        record_count: positive + negative,
        negative_kinds: kinds,
        normalizations,
        receipt_content_sha256: receipt_sha256,
    })
}
