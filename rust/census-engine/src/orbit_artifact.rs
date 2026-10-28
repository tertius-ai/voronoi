// SPDX-License-Identifier: MIT
//! Disk-backed invariant partitioning and exact integral-line orbit reduction.

use std::cmp::Ordering;
use std::collections::{BTreeMap, BinaryHeap};
use std::fs::{self, File, OpenOptions};
use std::io::{BufRead, BufReader, BufWriter, Write};
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use anyhow::{bail, Context, Result};
use noether::linalg::{IntegralLineAutomorphismGroup, IntegralLineConfiguration, Matrix};
use noether::Z;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use crate::{configuration, i64_vectors, noether_contract, MAX_CANDIDATE_CAP};

pub const ORBIT_KEY_TASK_SCHEMA: &str = "voronoi/orbit-key-task@1";
pub const ORBIT_KEY_REPORT_SCHEMA: &str = "voronoi/orbit-key-report@1";
pub const ORBIT_FINGERPRINT_SCHEMA: &str = "voronoi/maximal-minor-incidence@1";
pub const KEYED_ARTIFACT_SCHEMA: &str = "voronoi/keyed-candidate-artifact@1";
pub const KEYED_RECORD_SCHEMA: &str = "voronoi/keyed-candidate-record@1";
pub const KEYED_FOOTER_SCHEMA: &str = "voronoi/keyed-candidate-footer@1";
pub const ORBIT_REDUCTION_TASK_SCHEMA: &str = "voronoi/orbit-reduction-task@1";
pub const ORBIT_REDUCTION_REPORT_SCHEMA: &str = "voronoi/orbit-reduction-report@1";
pub const ORBIT_ARTIFACT_SCHEMA: &str = "voronoi/orbit-artifact@1";
pub const ORBIT_RECORD_SCHEMA: &str = "voronoi/orbit-record@1";
pub const ORBIT_FOOTER_SCHEMA: &str = "voronoi/orbit-footer@1";

const CANDIDATE_ARTIFACT_SCHEMA: &str = "voronoi/embedded-candidate-artifact@1";
const CANDIDATE_RECORD_SCHEMA: &str = "voronoi/embedded-candidate-record@1";
const CANDIDATE_FOOTER_SCHEMA: &str = "voronoi/embedded-candidate-footer@1";
const MAX_BASIS_MINOR_COUNT: usize = 10_000;

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct OrbitKeyTask {
    pub r#type: String,
    pub noether_contract: BTreeMap<String, String>,
    pub candidate_artifact_path: PathBuf,
    pub keyed_artifact_path: PathBuf,
    pub candidate_content_sha256: String,
    pub candidate_count: u64,
    pub candidate_occurrence_count: u64,
    pub buffer_cap: usize,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct OrbitKeyReport {
    pub r#type: &'static str,
    pub noether_contract: BTreeMap<String, String>,
    pub fingerprint_schema: &'static str,
    pub candidate_content_sha256: String,
    pub keyed_content_sha256: String,
    pub candidate_count: u64,
    pub candidate_occurrence_count: u64,
    pub fingerprint_group_count: u64,
    pub keyed_artifact_path: PathBuf,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct OrbitReductionTask {
    pub r#type: String,
    pub noether_contract: BTreeMap<String, String>,
    pub keyed_artifact_path: PathBuf,
    pub orbit_artifact_path: PathBuf,
    pub candidate_content_sha256: String,
    pub keyed_content_sha256: String,
    pub candidate_count: u64,
    pub candidate_occurrence_count: u64,
    pub fingerprint_group_count: u64,
    pub max_fingerprint_group_size: usize,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct OrbitReductionReport {
    pub r#type: &'static str,
    pub noether_contract: BTreeMap<String, String>,
    pub fingerprint_schema: &'static str,
    pub candidate_content_sha256: String,
    pub keyed_content_sha256: String,
    pub orbit_content_sha256: String,
    pub candidate_count: u64,
    pub candidate_occurrence_count: u64,
    pub fingerprint_group_count: u64,
    pub orbit_count: u64,
    pub duplicate_candidate_count: u64,
    pub exact_equivalence_count: u64,
    pub orbit_artifact_path: PathBuf,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct CandidateHeader {
    r#type: String,
    noether_contract: BTreeMap<String, String>,
    lower_index: usize,
    ambient_rank: usize,
    target_dimension: usize,
    input_sha256: String,
    event_stream_sha256: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct CandidateRecord {
    r#type: String,
    candidate_id: String,
    vectors: Vec<Vec<i64>>,
    occurrence_count: u64,
    first_event_index: u64,
    witness_left_incidence_id: String,
    witness_right_incidence_id: String,
    witness_representative: Vec<u32>,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct CandidateFooter {
    r#type: String,
    content_sha256: String,
    distinct_candidate_count: u64,
    candidate_occurrence_count: u64,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct KeyedRecord {
    r#type: String,
    fingerprint_sha256: String,
    candidate_id: String,
    vectors: Vec<Vec<i64>>,
    occurrence_count: u64,
    first_event_index: u64,
    witness_left_incidence_id: String,
    witness_right_incidence_id: String,
    witness_representative: Vec<u32>,
}

#[derive(Serialize)]
struct KeyedHeader<'a> {
    r#type: &'static str,
    noether_contract: &'a BTreeMap<String, String>,
    fingerprint_schema: &'static str,
    candidate_content_sha256: &'a str,
    lower_index: usize,
    ambient_rank: usize,
    target_dimension: usize,
    input_sha256: &'a str,
    event_stream_sha256: &'a str,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct OwnedKeyedHeader {
    r#type: String,
    noether_contract: BTreeMap<String, String>,
    fingerprint_schema: String,
    candidate_content_sha256: String,
    lower_index: usize,
    ambient_rank: usize,
    target_dimension: usize,
    input_sha256: String,
    event_stream_sha256: String,
}

#[derive(Serialize)]
struct KeyedFooter<'a> {
    r#type: &'static str,
    content_sha256: &'a str,
    candidate_count: u64,
    candidate_occurrence_count: u64,
    fingerprint_group_count: u64,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct OwnedKeyedFooter {
    r#type: String,
    content_sha256: String,
    candidate_count: u64,
    candidate_occurrence_count: u64,
    fingerprint_group_count: u64,
}

#[derive(Clone, Serialize)]
struct OrbitCandidate {
    candidate_id: String,
    vectors: Vec<Vec<i64>>,
    occurrence_count: u64,
    first_event_index: u64,
    witness_left_incidence_id: String,
    witness_right_incidence_id: String,
    witness_representative: Vec<u32>,
}

#[derive(Serialize)]
struct EquivalentMember {
    candidate: OrbitCandidate,
    transformation_to_representative: Vec<Vec<String>>,
    line_permutation: Vec<u32>,
}

#[derive(Serialize)]
struct OrbitRecord {
    r#type: &'static str,
    fingerprint_sha256: String,
    representative: OrbitCandidate,
    equivalent_members: Vec<EquivalentMember>,
    member_count: u64,
    candidate_occurrence_count: u64,
}

#[derive(Serialize)]
struct OrbitHeader<'a> {
    r#type: &'static str,
    noether_contract: &'a BTreeMap<String, String>,
    fingerprint_schema: &'static str,
    candidate_content_sha256: &'a str,
    keyed_content_sha256: &'a str,
    lower_index: usize,
    ambient_rank: usize,
    target_dimension: usize,
    input_sha256: &'a str,
    event_stream_sha256: &'a str,
}

#[derive(Serialize)]
struct OrbitFooter<'a> {
    r#type: &'static str,
    content_sha256: &'a str,
    candidate_count: u64,
    candidate_occurrence_count: u64,
    fingerprint_group_count: u64,
    orbit_count: u64,
    duplicate_candidate_count: u64,
    exact_equivalence_count: u64,
}

fn candidate_key(record: &KeyedRecord) -> (&str, &Vec<Vec<i64>>) {
    (&record.fingerprint_sha256, &record.vectors)
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct HeapEntry {
    fingerprint_sha256: String,
    vectors: Vec<Vec<i64>>,
    run_index: usize,
}

impl Ord for HeapEntry {
    fn cmp(&self, other: &Self) -> Ordering {
        other
            .fingerprint_sha256
            .cmp(&self.fingerprint_sha256)
            .then_with(|| other.vectors.cmp(&self.vectors))
            .then_with(|| other.run_index.cmp(&self.run_index))
    }
}

impl PartialOrd for HeapEntry {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

struct RunCursor {
    reader: BufReader<File>,
    current: Option<KeyedRecord>,
    previous: Option<(String, Vec<Vec<i64>>)>,
}

impl RunCursor {
    fn open(path: &Path) -> Result<Self> {
        let mut value = Self {
            reader: BufReader::new(
                File::open(path)
                    .with_context(|| format!("could not open orbit-key run {}", path.display()))?,
            ),
            current: None,
            previous: None,
        };
        value.advance()?;
        if value.current.is_none() {
            bail!("orbit-key run {} was empty", path.display());
        }
        Ok(value)
    }

    fn advance(&mut self) -> Result<()> {
        let mut line = String::new();
        if self.reader.read_line(&mut line)? == 0 {
            self.current = None;
            return Ok(());
        }
        let record: KeyedRecord =
            serde_json::from_str(&line).context("orbit-key run contained invalid JSON")?;
        let key = (record.fingerprint_sha256.clone(), record.vectors.clone());
        if self
            .previous
            .as_ref()
            .is_some_and(|previous| previous >= &key)
        {
            bail!("orbit-key run was not strictly sorted");
        }
        self.previous = Some(key);
        self.current = Some(record);
        Ok(())
    }
}

struct KeySpill {
    destination: PathBuf,
    buffer_cap: usize,
    buffer: Vec<KeyedRecord>,
    run_paths: Vec<PathBuf>,
    nonce: u128,
    next_index: u64,
}

impl KeySpill {
    fn new(destination: &Path, buffer_cap: usize) -> Result<Self> {
        validate_destination(destination)?;
        if !(1..=MAX_CANDIDATE_CAP).contains(&buffer_cap) {
            bail!("orbit-key buffer cap must lie in 1..={MAX_CANDIDATE_CAP}");
        }
        Ok(Self {
            destination: destination.to_path_buf(),
            buffer_cap,
            buffer: Vec::with_capacity(buffer_cap),
            run_paths: Vec::new(),
            nonce: SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .context("system clock is before the Unix epoch")?
                .as_nanos(),
            next_index: 0,
        })
    }

    fn temporary_file(&mut self, kind: &str) -> Result<(PathBuf, File)> {
        let parent = self
            .destination
            .parent()
            .context("orbit-key destination has no parent")?;
        for _ in 0..1_000 {
            let index = self.next_index;
            self.next_index += 1;
            let path = parent.join(format!(
                ".voronoi-orbit-key-{kind}-{}-{}-{index}",
                std::process::id(),
                self.nonce
            ));
            match OpenOptions::new().write(true).create_new(true).open(&path) {
                Ok(file) => return Ok((path, file)),
                Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
                Err(error) => return Err(error.into()),
            }
        }
        bail!("could not allocate a unique orbit-key temporary file")
    }

    fn record(&mut self, record: KeyedRecord) -> Result<()> {
        if self.buffer.len() == self.buffer_cap {
            self.flush_run()?;
        }
        self.buffer.push(record);
        Ok(())
    }

    fn flush_run(&mut self) -> Result<()> {
        if self.buffer.is_empty() {
            return Ok(());
        }
        self.buffer.sort_by(|left, right| {
            candidate_key(left)
                .0
                .cmp(candidate_key(right).0)
                .then_with(|| candidate_key(left).1.cmp(candidate_key(right).1))
        });
        if self
            .buffer
            .windows(2)
            .any(|pair| candidate_key(&pair[0]) >= candidate_key(&pair[1]))
        {
            bail!("orbit-key buffer contained a duplicate candidate")
        }
        let (path, file) = self.temporary_file("run")?;
        let result = (|| -> Result<()> {
            let mut writer = BufWriter::new(file);
            for record in &self.buffer {
                serde_json::to_writer(&mut writer, record)?;
                writer.write_all(b"\n")?;
            }
            writer.flush()?;
            writer
                .into_inner()
                .map_err(|error| error.into_error())?
                .sync_all()?;
            Ok(())
        })();
        if let Err(error) = result {
            let _ = fs::remove_file(&path);
            return Err(error);
        }
        self.buffer.clear();
        self.run_paths.push(path);
        Ok(())
    }

    fn finish(&mut self, header: &CandidateHeader, task: &OrbitKeyTask) -> Result<OrbitKeyReport> {
        self.flush_run()?;
        let mut cursors = self
            .run_paths
            .iter()
            .map(|path| RunCursor::open(path))
            .collect::<Result<Vec<_>>>()?;
        let mut heap = BinaryHeap::new();
        for (run_index, cursor) in cursors.iter().enumerate() {
            let record = cursor.current.as_ref().context("orbit-key run was empty")?;
            heap.push(HeapEntry {
                fingerprint_sha256: record.fingerprint_sha256.clone(),
                vectors: record.vectors.clone(),
                run_index,
            });
        }
        let (temporary_path, file) = self.temporary_file("artifact")?;
        let result = (|| -> Result<OrbitKeyReport> {
            let mut writer = BufWriter::new(file);
            let mut digest = Sha256::new();
            let output_header = KeyedHeader {
                r#type: KEYED_ARTIFACT_SCHEMA,
                noether_contract: &task.noether_contract,
                fingerprint_schema: ORBIT_FINGERPRINT_SCHEMA,
                candidate_content_sha256: &task.candidate_content_sha256,
                lower_index: header.lower_index,
                ambient_rank: header.ambient_rank,
                target_dimension: header.target_dimension,
                input_sha256: &header.input_sha256,
                event_stream_sha256: &header.event_stream_sha256,
            };
            write_hashed_json_line(&mut writer, &mut digest, &output_header)?;
            let mut count = 0u64;
            let mut occurrences = 0u64;
            let mut fingerprint_groups = 0u64;
            let mut previous: Option<(String, Vec<Vec<i64>>)> = None;
            let mut previous_fingerprint: Option<String> = None;
            while let Some(entry) = heap.pop() {
                let cursor = &mut cursors[entry.run_index];
                let record = cursor
                    .current
                    .take()
                    .context("orbit-key run exhausted early")?;
                let key = (record.fingerprint_sha256.clone(), record.vectors.clone());
                if previous.as_ref().is_some_and(|value| value >= &key) {
                    bail!("external orbit-key merge did not advance")
                }
                if previous_fingerprint.as_ref() != Some(&record.fingerprint_sha256) {
                    fingerprint_groups = fingerprint_groups
                        .checked_add(1)
                        .context("fingerprint-group count overflow")?;
                    previous_fingerprint = Some(record.fingerprint_sha256.clone());
                }
                count = count.checked_add(1).context("candidate count overflow")?;
                occurrences = occurrences
                    .checked_add(record.occurrence_count)
                    .context("candidate occurrence count overflow")?;
                write_hashed_json_line(&mut writer, &mut digest, &record)?;
                previous = Some(key);
                cursor.advance()?;
                if let Some(next) = &cursor.current {
                    heap.push(HeapEntry {
                        fingerprint_sha256: next.fingerprint_sha256.clone(),
                        vectors: next.vectors.clone(),
                        run_index: entry.run_index,
                    });
                }
            }
            if count != task.candidate_count || occurrences != task.candidate_occurrence_count {
                bail!("keyed artifact coverage disagrees with its task")
            }
            let content_sha256 = format!("{:x}", digest.finalize());
            let footer = KeyedFooter {
                r#type: KEYED_FOOTER_SCHEMA,
                content_sha256: &content_sha256,
                candidate_count: count,
                candidate_occurrence_count: occurrences,
                fingerprint_group_count: fingerprint_groups,
            };
            serde_json::to_writer(&mut writer, &footer)?;
            writer.write_all(b"\n")?;
            writer.flush()?;
            writer
                .into_inner()
                .map_err(|error| error.into_error())?
                .sync_all()?;
            Ok(OrbitKeyReport {
                r#type: ORBIT_KEY_REPORT_SCHEMA,
                noether_contract: noether_contract(),
                fingerprint_schema: ORBIT_FINGERPRINT_SCHEMA,
                candidate_content_sha256: task.candidate_content_sha256.clone(),
                keyed_content_sha256: content_sha256,
                candidate_count: count,
                candidate_occurrence_count: occurrences,
                fingerprint_group_count: fingerprint_groups,
                keyed_artifact_path: task.keyed_artifact_path.clone(),
            })
        })();
        let report = match result {
            Ok(value) => value,
            Err(error) => {
                let _ = fs::remove_file(&temporary_path);
                return Err(error);
            }
        };
        fs::hard_link(&temporary_path, &self.destination)?;
        fs::remove_file(&temporary_path)?;
        self.cleanup_runs()?;
        Ok(report)
    }

    fn cleanup_runs(&mut self) -> Result<()> {
        for path in self.run_paths.drain(..) {
            fs::remove_file(&path)?;
        }
        Ok(())
    }
}

impl Drop for KeySpill {
    fn drop(&mut self) {
        for path in self.run_paths.drain(..) {
            let _ = fs::remove_file(path);
        }
    }
}

pub fn key_candidate_artifact(task: &OrbitKeyTask) -> Result<OrbitKeyReport> {
    if task.r#type != ORBIT_KEY_TASK_SCHEMA {
        bail!("unsupported orbit-key task schema: {}", task.r#type)
    }
    if task.noether_contract != noether_contract() {
        bail!("orbit-key task uses a different Noether semantic contract")
    }
    validate_source(&task.candidate_artifact_path)?;
    let mut spill = KeySpill::new(&task.keyed_artifact_path, task.buffer_cap)?;
    let file = File::open(&task.candidate_artifact_path)?;
    let mut reader = BufReader::new(file);
    let header_line = read_required_line(&mut reader, "candidate header")?;
    let header: CandidateHeader = serde_json::from_slice(&header_line)?;
    if header.r#type != CANDIDATE_ARTIFACT_SCHEMA || header.noether_contract != noether_contract() {
        bail!("candidate artifact has an unsupported header")
    }
    let mut digest = Sha256::new();
    digest.update(&header_line);
    let mut previous_vectors: Option<Vec<Vec<i64>>> = None;
    let mut count = 0u64;
    let mut occurrences = 0u64;
    let footer = loop {
        let line = read_required_line(&mut reader, "candidate record or footer")?;
        let payload: serde_json::Value = serde_json::from_slice(&line)?;
        let kind = payload.get("type").and_then(serde_json::Value::as_str);
        if kind == Some(CANDIDATE_FOOTER_SCHEMA) {
            break serde_json::from_value::<CandidateFooter>(payload)?;
        }
        let record = serde_json::from_value::<CandidateRecord>(payload)?;
        validate_candidate_record(&record, header.ambient_rank, previous_vectors.as_ref())?;
        digest.update(&line);
        previous_vectors = Some(record.vectors.clone());
        count = count.checked_add(1).context("candidate count overflow")?;
        occurrences = occurrences
            .checked_add(record.occurrence_count)
            .context("candidate occurrence count overflow")?;
        let fingerprint_sha256 = equivalence_fingerprint(&record.vectors, header.ambient_rank)?;
        spill.record(KeyedRecord {
            r#type: KEYED_RECORD_SCHEMA.to_owned(),
            fingerprint_sha256,
            candidate_id: record.candidate_id,
            vectors: record.vectors,
            occurrence_count: record.occurrence_count,
            first_event_index: record.first_event_index,
            witness_left_incidence_id: record.witness_left_incidence_id,
            witness_right_incidence_id: record.witness_right_incidence_id,
            witness_representative: record.witness_representative,
        })?;
    };
    if !reader.fill_buf()?.is_empty() {
        bail!("candidate artifact has data after its footer")
    }
    let content_sha256 = format!("{:x}", digest.finalize());
    if footer.r#type != CANDIDATE_FOOTER_SCHEMA
        || footer.content_sha256 != content_sha256
        || footer.content_sha256 != task.candidate_content_sha256
        || footer.distinct_candidate_count != count
        || footer.candidate_occurrence_count != occurrences
        || count != task.candidate_count
        || occurrences != task.candidate_occurrence_count
    {
        bail!("candidate artifact coverage or digest does not verify")
    }
    spill.finish(&header, task)
}

struct OrbitClass {
    representative: KeyedRecord,
    configuration: IntegralLineConfiguration,
    automorphisms: Option<IntegralLineAutomorphismGroup>,
    equivalent_members: Vec<EquivalentMember>,
    occurrence_count: u64,
}

fn classify_group(
    fingerprint: &str,
    group: Vec<KeyedRecord>,
    ambient_rank: usize,
) -> Result<(Vec<OrbitRecord>, u64)> {
    let mut classes: Vec<OrbitClass> = Vec::new();
    let mut equivalences = 0u64;
    for candidate in group {
        let source = configuration(&candidate.vectors, ambient_rank)?;
        let mut found = None;
        for (index, class) in classes.iter_mut().enumerate() {
            if class.automorphisms.is_none() {
                class.automorphisms = Some(class.configuration.automorphism_group()?);
            }
            let equivalence = source.equivalence_to_with_target_automorphisms(
                &class.configuration,
                class
                    .automorphisms
                    .as_ref()
                    .context("orbit representative omitted its automorphisms")?,
            )?;
            if let Some(equivalence) = equivalence {
                equivalence.verify()?;
                found = Some((index, equivalence));
                break;
            }
        }
        if let Some((index, equivalence)) = found {
            let transformation_to_representative = equivalence
                .transformation()
                .rows()
                .map(|row| row.into_iter().map(|entry| entry.to_string()).collect())
                .collect();
            let line_permutation = equivalence.line_permutation().images().to_vec();
            let class = &mut classes[index];
            class.occurrence_count = class
                .occurrence_count
                .checked_add(candidate.occurrence_count)
                .context("orbit occurrence count overflow")?;
            class.equivalent_members.push(EquivalentMember {
                candidate: candidate.into(),
                transformation_to_representative,
                line_permutation,
            });
            equivalences = equivalences
                .checked_add(1)
                .context("equivalence count overflow")?;
        } else {
            let occurrence_count = candidate.occurrence_count;
            classes.push(OrbitClass {
                representative: candidate,
                configuration: source,
                automorphisms: None,
                equivalent_members: Vec::new(),
                occurrence_count,
            });
        }
    }
    let records = classes
        .into_iter()
        .map(|class| OrbitRecord {
            r#type: ORBIT_RECORD_SCHEMA,
            fingerprint_sha256: fingerprint.to_owned(),
            member_count: 1 + class.equivalent_members.len() as u64,
            candidate_occurrence_count: class.occurrence_count,
            representative: class.representative.into(),
            equivalent_members: class.equivalent_members,
        })
        .collect();
    Ok((records, equivalences))
}

impl From<KeyedRecord> for OrbitCandidate {
    fn from(value: KeyedRecord) -> Self {
        Self {
            candidate_id: value.candidate_id,
            vectors: value.vectors,
            occurrence_count: value.occurrence_count,
            first_event_index: value.first_event_index,
            witness_left_incidence_id: value.witness_left_incidence_id,
            witness_right_incidence_id: value.witness_right_incidence_id,
            witness_representative: value.witness_representative,
        }
    }
}

pub fn reduce_keyed_artifact(task: &OrbitReductionTask) -> Result<OrbitReductionReport> {
    if task.r#type != ORBIT_REDUCTION_TASK_SCHEMA {
        bail!("unsupported orbit-reduction task schema: {}", task.r#type)
    }
    if task.noether_contract != noether_contract() {
        bail!("orbit-reduction task uses a different Noether semantic contract")
    }
    if task.max_fingerprint_group_size == 0 {
        bail!("maximum fingerprint group size must be positive")
    }
    validate_source(&task.keyed_artifact_path)?;
    validate_destination(&task.orbit_artifact_path)?;
    let mut reader = BufReader::new(File::open(&task.keyed_artifact_path)?);
    let header_line = read_required_line(&mut reader, "keyed header")?;
    let header: OwnedKeyedHeader = serde_json::from_slice(&header_line)?;
    if header.r#type != KEYED_ARTIFACT_SCHEMA
        || header.noether_contract != noether_contract()
        || header.fingerprint_schema != ORBIT_FINGERPRINT_SCHEMA
        || header.candidate_content_sha256 != task.candidate_content_sha256
    {
        bail!("keyed candidate artifact has an unsupported header")
    }
    let (temporary_path, file) = temporary_output(&task.orbit_artifact_path, "orbit")?;
    let result = (|| -> Result<OrbitReductionReport> {
        let mut writer = BufWriter::new(file);
        let output_header = OrbitHeader {
            r#type: ORBIT_ARTIFACT_SCHEMA,
            noether_contract: &task.noether_contract,
            fingerprint_schema: ORBIT_FINGERPRINT_SCHEMA,
            candidate_content_sha256: &task.candidate_content_sha256,
            keyed_content_sha256: &task.keyed_content_sha256,
            lower_index: header.lower_index,
            ambient_rank: header.ambient_rank,
            target_dimension: header.target_dimension,
            input_sha256: &header.input_sha256,
            event_stream_sha256: &header.event_stream_sha256,
        };
        let mut output_digest = Sha256::new();
        write_hashed_json_line(&mut writer, &mut output_digest, &output_header)?;
        let mut input_digest = Sha256::new();
        input_digest.update(&header_line);
        let mut previous: Option<(String, Vec<Vec<i64>>)> = None;
        let mut current_fingerprint: Option<String> = None;
        let mut group = Vec::new();
        let mut candidate_count = 0u64;
        let mut occurrences = 0u64;
        let mut fingerprint_groups = 0u64;
        let mut orbit_count = 0u64;
        let mut equivalence_count = 0u64;
        let footer = loop {
            let line = read_required_line(&mut reader, "keyed record or footer")?;
            let payload: serde_json::Value = serde_json::from_slice(&line)?;
            let kind = payload.get("type").and_then(serde_json::Value::as_str);
            if kind == Some(KEYED_FOOTER_SCHEMA) {
                break serde_json::from_value::<OwnedKeyedFooter>(payload)?;
            }
            let record = serde_json::from_value::<KeyedRecord>(payload)?;
            validate_keyed_record(&record, header.ambient_rank, previous.as_ref())?;
            let recomputed = equivalence_fingerprint(&record.vectors, header.ambient_rank)?;
            if recomputed != record.fingerprint_sha256 {
                bail!("keyed candidate has the wrong equivalence fingerprint")
            }
            input_digest.update(&line);
            let key = (record.fingerprint_sha256.clone(), record.vectors.clone());
            previous = Some(key);
            candidate_count = candidate_count
                .checked_add(1)
                .context("candidate count overflow")?;
            occurrences = occurrences
                .checked_add(record.occurrence_count)
                .context("candidate occurrence count overflow")?;
            if current_fingerprint.as_ref() != Some(&record.fingerprint_sha256) {
                if let Some(fingerprint) = current_fingerprint.take() {
                    let (records, exact) = classify_group(
                        &fingerprint,
                        std::mem::take(&mut group),
                        header.ambient_rank,
                    )?;
                    for record in records {
                        orbit_count = orbit_count.checked_add(1).context("orbit count overflow")?;
                        write_hashed_json_line(&mut writer, &mut output_digest, &record)?;
                    }
                    equivalence_count = equivalence_count
                        .checked_add(exact)
                        .context("equivalence count overflow")?;
                }
                fingerprint_groups = fingerprint_groups
                    .checked_add(1)
                    .context("fingerprint-group count overflow")?;
                current_fingerprint = Some(record.fingerprint_sha256.clone());
            }
            group.push(record);
            if group.len() > task.max_fingerprint_group_size {
                bail!(
                    "fingerprint group exceeded the {}-candidate task cap",
                    task.max_fingerprint_group_size
                )
            }
        };
        if let Some(fingerprint) = current_fingerprint.take() {
            let (records, exact) = classify_group(&fingerprint, group, header.ambient_rank)?;
            for record in records {
                orbit_count = orbit_count.checked_add(1).context("orbit count overflow")?;
                write_hashed_json_line(&mut writer, &mut output_digest, &record)?;
            }
            equivalence_count = equivalence_count
                .checked_add(exact)
                .context("equivalence count overflow")?;
        }
        if !reader.fill_buf()?.is_empty() {
            bail!("keyed candidate artifact has data after its footer")
        }
        let keyed_content_sha256 = format!("{:x}", input_digest.finalize());
        if footer.r#type != KEYED_FOOTER_SCHEMA
            || footer.content_sha256 != keyed_content_sha256
            || footer.content_sha256 != task.keyed_content_sha256
            || footer.candidate_count != candidate_count
            || footer.candidate_occurrence_count != occurrences
            || footer.fingerprint_group_count != fingerprint_groups
            || candidate_count != task.candidate_count
            || occurrences != task.candidate_occurrence_count
            || fingerprint_groups != task.fingerprint_group_count
        {
            bail!("keyed candidate artifact coverage or digest does not verify")
        }
        let duplicate_candidate_count = candidate_count
            .checked_sub(orbit_count)
            .context("orbit count exceeds candidate count")?;
        if duplicate_candidate_count != equivalence_count {
            bail!("every exact orbit merge must carry one equivalence witness")
        }
        let orbit_content_sha256 = format!("{:x}", output_digest.finalize());
        let output_footer = OrbitFooter {
            r#type: ORBIT_FOOTER_SCHEMA,
            content_sha256: &orbit_content_sha256,
            candidate_count,
            candidate_occurrence_count: occurrences,
            fingerprint_group_count: fingerprint_groups,
            orbit_count,
            duplicate_candidate_count,
            exact_equivalence_count: equivalence_count,
        };
        serde_json::to_writer(&mut writer, &output_footer)?;
        writer.write_all(b"\n")?;
        writer.flush()?;
        writer
            .into_inner()
            .map_err(|error| error.into_error())?
            .sync_all()?;
        Ok(OrbitReductionReport {
            r#type: ORBIT_REDUCTION_REPORT_SCHEMA,
            noether_contract: noether_contract(),
            fingerprint_schema: ORBIT_FINGERPRINT_SCHEMA,
            candidate_content_sha256: task.candidate_content_sha256.clone(),
            keyed_content_sha256,
            orbit_content_sha256,
            candidate_count,
            candidate_occurrence_count: occurrences,
            fingerprint_group_count: fingerprint_groups,
            orbit_count,
            duplicate_candidate_count,
            exact_equivalence_count: equivalence_count,
            orbit_artifact_path: task.orbit_artifact_path.clone(),
        })
    })();
    let report = match result {
        Ok(value) => value,
        Err(error) => {
            let _ = fs::remove_file(&temporary_path);
            return Err(error);
        }
    };
    fs::hard_link(&temporary_path, &task.orbit_artifact_path)?;
    fs::remove_file(&temporary_path)?;
    Ok(report)
}

fn validate_candidate_record(
    record: &CandidateRecord,
    ambient_rank: usize,
    previous_vectors: Option<&Vec<Vec<i64>>>,
) -> Result<()> {
    if record.r#type != CANDIDATE_RECORD_SCHEMA || record.occurrence_count == 0 {
        bail!("candidate artifact contains an invalid record")
    }
    if previous_vectors.is_some_and(|previous| previous >= &record.vectors) {
        bail!("candidate artifact is not strictly ordered")
    }
    let checked = configuration(&record.vectors, ambient_rank)?;
    if i64_vectors(&checked)? != record.vectors {
        bail!("candidate artifact contains noncanonical vectors")
    }
    if record.candidate_id != candidate_id(&record.vectors)? {
        bail!("candidate artifact contains the wrong candidate identifier")
    }
    Ok(())
}

fn validate_keyed_record(
    record: &KeyedRecord,
    ambient_rank: usize,
    previous: Option<&(String, Vec<Vec<i64>>)>,
) -> Result<()> {
    if record.r#type != KEYED_RECORD_SCHEMA || record.occurrence_count == 0 {
        bail!("keyed artifact contains an invalid record")
    }
    let key = (record.fingerprint_sha256.clone(), record.vectors.clone());
    if previous.is_some_and(|value| value >= &key) {
        bail!("keyed artifact is not strictly ordered")
    }
    let candidate = CandidateRecord {
        r#type: CANDIDATE_RECORD_SCHEMA.to_owned(),
        candidate_id: record.candidate_id.clone(),
        vectors: record.vectors.clone(),
        occurrence_count: record.occurrence_count,
        first_event_index: record.first_event_index,
        witness_left_incidence_id: record.witness_left_incidence_id.clone(),
        witness_right_incidence_id: record.witness_right_incidence_id.clone(),
        witness_representative: record.witness_representative.clone(),
    };
    validate_candidate_record(&candidate, ambient_rank, None)
}

fn equivalence_fingerprint(vectors: &[Vec<i64>], ambient_rank: usize) -> Result<String> {
    let checked = configuration(vectors, ambient_rank)?;
    if checked.vectors().len() < ambient_rank {
        bail!("orbit fingerprint requires at least ambient-rank many lines")
    }
    let subsets = combinations(checked.vectors().len(), ambient_rank, MAX_BASIS_MINOR_COUNT)?;
    let mut minors = Vec::with_capacity(subsets.len());
    for subset in &subsets {
        let matrix = Matrix::from_rows(
            Z,
            subset
                .iter()
                .map(|index| checked.vectors()[*index].clone())
                .collect::<Vec<_>>(),
        )?;
        minors.push(matrix.det()?.abs());
    }
    let mut values = minors.clone();
    values.sort();
    values.dedup();
    let colors = minors
        .iter()
        .map(|minor| {
            values
                .binary_search(minor)
                .expect("minor value remains in its sorted unique palette")
        })
        .collect::<Vec<_>>();
    let mut line_signatures = vec![Vec::new(); checked.vectors().len()];
    for (subset, color) in subsets.iter().zip(&colors) {
        for line in subset {
            line_signatures[*line].push(*color);
        }
    }
    for signature in &mut line_signatures {
        signature.sort_unstable();
    }
    line_signatures.sort();
    let value_strings = values.iter().map(ToString::to_string).collect::<Vec<_>>();
    let bytes = serde_json::to_vec(&(
        ORBIT_FINGERPRINT_SCHEMA,
        ambient_rank,
        checked.vectors().len(),
        value_strings,
        line_signatures,
    ))?;
    Ok(format!("{:x}", Sha256::digest(bytes)))
}

fn combinations(count: usize, choose: usize, cap: usize) -> Result<Vec<Vec<usize>>> {
    fn visit(
        count: usize,
        choose: usize,
        start: usize,
        current: &mut Vec<usize>,
        output: &mut Vec<Vec<usize>>,
        cap: usize,
    ) -> Result<()> {
        if current.len() == choose {
            if output.len() == cap {
                bail!("basis-minor fingerprint exceeds its {cap}-subset cap")
            }
            output.push(current.clone());
            return Ok(());
        }
        let remaining = choose - current.len();
        for value in start..=count - remaining {
            current.push(value);
            visit(count, choose, value + 1, current, output, cap)?;
            current.pop();
        }
        Ok(())
    }
    if choose > count {
        return Ok(Vec::new());
    }
    let mut output = Vec::new();
    visit(count, choose, 0, &mut Vec::new(), &mut output, cap)?;
    Ok(output)
}

fn candidate_id(vectors: &[Vec<i64>]) -> Result<String> {
    Ok(format!(
        "sha256:{:x}",
        Sha256::digest(serde_json::to_vec(vectors)?)
    ))
}

fn validate_source(path: &Path) -> Result<()> {
    if !path.is_absolute() || !path.is_file() {
        bail!(
            "artifact source must be an existing absolute file: {}",
            path.display()
        )
    }
    Ok(())
}

fn validate_destination(path: &Path) -> Result<()> {
    if !path.is_absolute() || path.exists() {
        bail!(
            "artifact destination must be a new absolute path: {}",
            path.display()
        )
    }
    if !path.parent().is_some_and(Path::is_dir) {
        bail!(
            "artifact destination parent does not exist: {}",
            path.display()
        )
    }
    Ok(())
}

fn temporary_output(destination: &Path, kind: &str) -> Result<(PathBuf, File)> {
    let parent = destination
        .parent()
        .context("artifact destination has no parent")?;
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .context("system clock is before the Unix epoch")?
        .as_nanos();
    for index in 0..1_000 {
        let path = parent.join(format!(
            ".voronoi-{kind}-{}-{nonce}-{index}",
            std::process::id()
        ));
        match OpenOptions::new().write(true).create_new(true).open(&path) {
            Ok(file) => return Ok((path, file)),
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(error) => return Err(error.into()),
        }
    }
    bail!("could not allocate a unique artifact temporary file")
}

fn read_required_line(reader: &mut BufReader<File>, description: &str) -> Result<Vec<u8>> {
    let mut line = Vec::new();
    if reader.read_until(b'\n', &mut line)? == 0 {
        bail!("artifact omitted its {description}")
    }
    if !line.ends_with(b"\n") {
        bail!("artifact {description} is not newline terminated")
    }
    Ok(line)
}

fn write_hashed_json_line<T: Serialize>(
    writer: &mut BufWriter<File>,
    digest: &mut Sha256,
    value: &T,
) -> Result<()> {
    let bytes = serde_json::to_vec(value)?;
    writer.write_all(&bytes)?;
    writer.write_all(b"\n")?;
    digest.update(&bytes);
    digest.update(b"\n");
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn maximal_minor_fingerprint_is_invariant_under_unimodular_equivalence() {
        let source = vec![
            vec![1, 0, 0],
            vec![0, 1, 0],
            vec![0, 0, 1],
            vec![1, 1, 0],
            vec![1, 0, 1],
        ];
        let transformation = Matrix::from_rows(
            Z,
            vec![
                vec![1.into(), 1.into(), 0.into()],
                vec![0.into(), 1.into(), 1.into()],
                vec![0.into(), 0.into(), 1.into()],
            ],
        )
        .unwrap();
        let transformed = configuration(&source, 3)
            .unwrap()
            .transform(&transformation)
            .unwrap();
        assert_eq!(
            equivalence_fingerprint(&source, 3).unwrap(),
            equivalence_fingerprint(&i64_vectors(&transformed).unwrap(), 3).unwrap()
        );
    }
}
