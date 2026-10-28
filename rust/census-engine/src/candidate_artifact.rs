// SPDX-License-Identifier: MIT
//! Bounded sorted-run aggregation for exact embedded census candidates.

use std::cmp::Ordering;
use std::collections::{BTreeMap, BinaryHeap};
use std::fs::{self, File, OpenOptions};
use std::io::{BufRead, BufReader, BufWriter, Write};
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use anyhow::{bail, Context, Result};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

/// Header line of a candidate JSON-lines artifact.
pub const CANDIDATE_ARTIFACT_SCHEMA: &str = "voronoi/embedded-candidate-artifact@1";
/// Schema of each exact candidate record.
pub const CANDIDATE_RECORD_SCHEMA: &str = "voronoi/embedded-candidate-record@1";
/// Terminal line carrying the artifact coverage identity.
pub const CANDIDATE_FOOTER_SCHEMA: &str = "voronoi/embedded-candidate-footer@1";
/// Schema embedded in the parent coface-pair report.
pub const CANDIDATE_SUMMARY_SCHEMA: &str = "voronoi/embedded-candidate-summary@1";

/// Exact identity and coverage totals for one externally merged artifact.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct CandidateArtifactSummary {
    /// Always [`CANDIDATE_SUMMARY_SCHEMA`].
    pub r#type: &'static str,
    /// SHA-256 of the header and candidate record lines, including newlines.
    pub content_sha256: String,
    /// Number of distinct embedded configurations after exact row equality.
    pub distinct_candidate_count: u64,
    /// Number of pair-orbit occurrences represented by those configurations.
    pub candidate_occurrence_count: u64,
}

#[derive(Serialize)]
struct CandidateArtifactHeader<'a> {
    r#type: &'static str,
    noether_contract: &'a BTreeMap<String, String>,
    lower_index: usize,
    ambient_rank: usize,
    target_dimension: usize,
    input_sha256: &'a str,
    event_stream_sha256: &'a str,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
struct CandidateRunRecord {
    vectors: Vec<Vec<i64>>,
    occurrence_count: u64,
    first_event_index: u64,
    witness_left_incidence_id: String,
    witness_right_incidence_id: String,
    witness_representative: Vec<u32>,
}

#[derive(Serialize)]
struct CandidateArtifactRecord<'a> {
    r#type: &'static str,
    candidate_id: String,
    vectors: &'a [Vec<i64>],
    occurrence_count: u64,
    first_event_index: u64,
    witness_left_incidence_id: &'a str,
    witness_right_incidence_id: &'a str,
    witness_representative: &'a [u32],
}

#[derive(Serialize)]
struct CandidateArtifactFooter<'a> {
    r#type: &'static str,
    content_sha256: &'a str,
    distinct_candidate_count: u64,
    candidate_occurrence_count: u64,
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct HeapEntry {
    vectors: Vec<Vec<i64>>,
    run_index: usize,
}

impl Ord for HeapEntry {
    fn cmp(&self, other: &Self) -> Ordering {
        // Reverse the lexical ordering so BinaryHeap acts as a min-heap.
        other
            .vectors
            .cmp(&self.vectors)
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
    current: Option<CandidateRunRecord>,
    previous_vectors: Option<Vec<Vec<i64>>>,
}

impl RunCursor {
    fn open(path: &Path) -> Result<Self> {
        let file = File::open(path)
            .with_context(|| format!("could not open candidate run {}", path.display()))?;
        let mut cursor = Self {
            reader: BufReader::new(file),
            current: None,
            previous_vectors: None,
        };
        cursor.advance()?;
        if cursor.current.is_none() {
            bail!("candidate run {} was empty", path.display());
        }
        Ok(cursor)
    }

    fn advance(&mut self) -> Result<()> {
        let mut line = String::new();
        let count = self.reader.read_line(&mut line)?;
        if count == 0 {
            self.current = None;
            return Ok(());
        }
        let record: CandidateRunRecord =
            serde_json::from_str(&line).context("candidate run contained invalid JSON")?;
        if record.occurrence_count == 0 {
            bail!("candidate run contained a zero occurrence count");
        }
        if self
            .previous_vectors
            .as_ref()
            .is_some_and(|previous| previous >= &record.vectors)
        {
            bail!("candidate run was not strictly sorted");
        }
        self.previous_vectors = Some(record.vectors.clone());
        self.current = Some(record);
        Ok(())
    }
}

/// In-memory exact aggregate with deterministic first-occurrence evidence.
pub(crate) struct CandidateSpill {
    destination: PathBuf,
    buffer_cap: usize,
    buffer: BTreeMap<Vec<Vec<i64>>, CandidateRunRecord>,
    run_paths: Vec<PathBuf>,
    unique_nonce: u128,
    next_temporary_index: u64,
}

impl CandidateSpill {
    /// Prepare a spill without creating or replacing the final artifact.
    pub(crate) fn new(destination: &Path, buffer_cap: usize) -> Result<Self> {
        if buffer_cap == 0 {
            bail!("candidate spill buffer cap must be positive");
        }
        if !destination.is_absolute() {
            bail!("candidate artifact path must be absolute");
        }
        if destination.exists() {
            bail!(
                "candidate artifact destination already exists: {}",
                destination.display()
            );
        }
        let parent = destination
            .parent()
            .context("candidate artifact destination has no parent directory")?;
        if !parent.is_dir() {
            bail!(
                "candidate artifact parent is not a directory: {}",
                parent.display()
            );
        }
        let unique_nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .context("system clock is before the Unix epoch")?
            .as_nanos();
        Ok(Self {
            destination: destination.to_path_buf(),
            buffer_cap,
            buffer: BTreeMap::new(),
            run_paths: Vec::new(),
            unique_nonce,
            next_temporary_index: 0,
        })
    }

    /// Add one exact occurrence, spilling before admitting a new key at cap.
    pub(crate) fn record(
        &mut self,
        vectors: Vec<Vec<i64>>,
        event_index: u64,
        left_incidence_id: &str,
        right_incidence_id: &str,
        representative: &[u32],
    ) -> Result<()> {
        if let Some(existing) = self.buffer.get_mut(&vectors) {
            existing.occurrence_count = existing
                .occurrence_count
                .checked_add(1)
                .context("candidate occurrence count overflow")?;
            return Ok(());
        }
        if self.buffer.len() == self.buffer_cap {
            self.flush_run()?;
        }
        self.buffer.insert(
            vectors.clone(),
            CandidateRunRecord {
                vectors,
                occurrence_count: 1,
                first_event_index: event_index,
                witness_left_incidence_id: left_incidence_id.to_owned(),
                witness_right_incidence_id: right_incidence_id.to_owned(),
                witness_representative: representative.to_vec(),
            },
        );
        Ok(())
    }

    fn temporary_file(&mut self, kind: &str) -> Result<(PathBuf, File)> {
        let parent = self
            .destination
            .parent()
            .context("candidate artifact destination has no parent directory")?;
        for _ in 0..1_000 {
            let index = self.next_temporary_index;
            self.next_temporary_index += 1;
            let path = parent.join(format!(
                ".voronoi-candidate-{kind}-{}-{}-{index}",
                std::process::id(),
                self.unique_nonce
            ));
            match OpenOptions::new().write(true).create_new(true).open(&path) {
                Ok(file) => return Ok((path, file)),
                Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
                Err(error) => {
                    return Err(error).with_context(|| {
                        format!(
                            "could not create temporary candidate file {}",
                            path.display()
                        )
                    });
                }
            }
        }
        bail!("could not allocate a unique temporary candidate file")
    }

    fn flush_run(&mut self) -> Result<()> {
        if self.buffer.is_empty() {
            return Ok(());
        }
        let (path, file) = self.temporary_file("run")?;
        let write_result = (|| -> Result<()> {
            let mut writer = BufWriter::new(file);
            for record in self.buffer.values() {
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
        if let Err(error) = write_result {
            let _ = fs::remove_file(&path);
            return Err(error);
        }
        self.buffer.clear();
        self.run_paths.push(path);
        Ok(())
    }

    /// Merge every sorted run to a non-overwriting final JSON-lines artifact.
    pub(crate) fn finish(
        &mut self,
        noether_contract: &BTreeMap<String, String>,
        lower_index: usize,
        ambient_rank: usize,
        target_dimension: usize,
        input_sha256: &str,
        event_stream_sha256: &str,
    ) -> Result<CandidateArtifactSummary> {
        self.flush_run()?;
        let mut cursors = self
            .run_paths
            .iter()
            .map(|path| RunCursor::open(path))
            .collect::<Result<Vec<_>>>()?;
        let mut heap = BinaryHeap::new();
        for (run_index, cursor) in cursors.iter().enumerate() {
            let record = cursor
                .current
                .as_ref()
                .context("candidate run unexpectedly omitted its first record")?;
            heap.push(HeapEntry {
                vectors: record.vectors.clone(),
                run_index,
            });
        }

        let (temporary_path, file) = self.temporary_file("artifact")?;
        let merge_result = (|| -> Result<CandidateArtifactSummary> {
            let mut writer = BufWriter::new(file);
            let mut digest = Sha256::new();
            let header = CandidateArtifactHeader {
                r#type: CANDIDATE_ARTIFACT_SCHEMA,
                noether_contract,
                lower_index,
                ambient_rank,
                target_dimension,
                input_sha256,
                event_stream_sha256,
            };
            write_hashed_json_line(&mut writer, &mut digest, &header)?;

            let mut distinct_candidate_count = 0u64;
            let mut candidate_occurrence_count = 0u64;
            let mut previous_vectors: Option<Vec<Vec<i64>>> = None;
            while let Some(entry) = heap.pop() {
                let vectors = entry.vectors;
                if previous_vectors
                    .as_ref()
                    .is_some_and(|previous| previous >= &vectors)
                {
                    bail!("external candidate merge did not advance lexically");
                }
                let mut run_indices = vec![entry.run_index];
                while heap.peek().is_some_and(|next| next.vectors == vectors) {
                    run_indices.push(
                        heap.pop()
                            .context("candidate heap unexpectedly became empty")?
                            .run_index,
                    );
                }

                let mut aggregate: Option<CandidateRunRecord> = None;
                for run_index in run_indices {
                    let cursor = &mut cursors[run_index];
                    let record = cursor
                        .current
                        .take()
                        .context("candidate heap referenced an exhausted run")?;
                    if record.vectors != vectors {
                        bail!("candidate heap key disagreed with its run record");
                    }
                    if let Some(existing) = &mut aggregate {
                        existing.occurrence_count = existing
                            .occurrence_count
                            .checked_add(record.occurrence_count)
                            .context("merged candidate occurrence count overflow")?;
                        if record.first_event_index < existing.first_event_index {
                            existing.first_event_index = record.first_event_index;
                            existing.witness_left_incidence_id = record.witness_left_incidence_id;
                            existing.witness_right_incidence_id = record.witness_right_incidence_id;
                            existing.witness_representative = record.witness_representative;
                        }
                    } else {
                        aggregate = Some(record);
                    }
                    cursor.advance()?;
                    if let Some(next) = &cursor.current {
                        heap.push(HeapEntry {
                            vectors: next.vectors.clone(),
                            run_index,
                        });
                    }
                }

                let aggregate = aggregate.context("candidate merge produced no aggregate")?;
                let candidate_id = candidate_id(&aggregate.vectors)?;
                let output = CandidateArtifactRecord {
                    r#type: CANDIDATE_RECORD_SCHEMA,
                    candidate_id,
                    vectors: &aggregate.vectors,
                    occurrence_count: aggregate.occurrence_count,
                    first_event_index: aggregate.first_event_index,
                    witness_left_incidence_id: &aggregate.witness_left_incidence_id,
                    witness_right_incidence_id: &aggregate.witness_right_incidence_id,
                    witness_representative: &aggregate.witness_representative,
                };
                write_hashed_json_line(&mut writer, &mut digest, &output)?;
                distinct_candidate_count = distinct_candidate_count
                    .checked_add(1)
                    .context("distinct candidate count overflow")?;
                candidate_occurrence_count = candidate_occurrence_count
                    .checked_add(aggregate.occurrence_count)
                    .context("artifact candidate occurrence count overflow")?;
                previous_vectors = Some(vectors);
            }

            let content_sha256 = format!("{:x}", digest.finalize());
            let footer = CandidateArtifactFooter {
                r#type: CANDIDATE_FOOTER_SCHEMA,
                content_sha256: &content_sha256,
                distinct_candidate_count,
                candidate_occurrence_count,
            };
            serde_json::to_writer(&mut writer, &footer)?;
            writer.write_all(b"\n")?;
            writer.flush()?;
            writer
                .into_inner()
                .map_err(|error| error.into_error())?
                .sync_all()?;
            Ok(CandidateArtifactSummary {
                r#type: CANDIDATE_SUMMARY_SCHEMA,
                content_sha256,
                distinct_candidate_count,
                candidate_occurrence_count,
            })
        })();

        let summary = match merge_result {
            Ok(summary) => summary,
            Err(error) => {
                let _ = fs::remove_file(&temporary_path);
                return Err(error);
            }
        };
        fs::hard_link(&temporary_path, &self.destination).with_context(|| {
            format!(
                "could not publish candidate artifact without replacing {}",
                self.destination.display()
            )
        })?;
        fs::remove_file(&temporary_path).with_context(|| {
            format!(
                "could not remove candidate artifact temporary link {}",
                temporary_path.display()
            )
        })?;
        self.cleanup_runs()?;
        Ok(summary)
    }

    fn cleanup_runs(&mut self) -> Result<()> {
        for path in self.run_paths.drain(..) {
            fs::remove_file(&path)
                .with_context(|| format!("could not remove candidate run {}", path.display()))?;
        }
        Ok(())
    }
}

impl Drop for CandidateSpill {
    fn drop(&mut self) {
        for path in self.run_paths.drain(..) {
            let _ = fs::remove_file(path);
        }
    }
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

fn candidate_id(vectors: &[Vec<i64>]) -> Result<String> {
    Ok(format!(
        "sha256:{:x}",
        Sha256::digest(serde_json::to_vec(vectors)?)
    ))
}
