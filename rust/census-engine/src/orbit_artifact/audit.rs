// SPDX-License-Identifier: MIT
//! Read-only replay of saved orbit transports against their complete keyed input.

use super::*;
use anyhow::ensure;

pub const ORBIT_AUDIT_TASK_SCHEMA: &str = "voronoi/orbit-audit-task@1";
pub const ORBIT_AUDIT_REPORT_SCHEMA: &str = "voronoi/orbit-audit-report@1";

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct OrbitAuditTask {
    pub r#type: String,
    pub noether_contract: BTreeMap<String, String>,
    pub keyed_artifact_path: PathBuf,
    pub orbit_artifact_path: PathBuf,
    pub candidate_content_sha256: String,
    pub keyed_content_sha256: String,
    pub orbit_content_sha256: String,
    pub pair_input_sha256: String,
    pub event_stream_sha256: String,
    pub lower_index: usize,
    pub ambient_rank: usize,
    pub cone_dimension: usize,
    pub candidate_count: u64,
    pub candidate_occurrence_count: u64,
    pub fingerprint_group_count: u64,
    pub orbit_count: u64,
    pub exact_equivalence_count: u64,
    pub max_fingerprint_group_size: usize,
}

#[derive(Debug, Serialize)]
pub struct OrbitAuditReport {
    pub r#type: &'static str,
    pub noether_contract: BTreeMap<String, String>,
    pub input_sha256: String,
    pub keyed_content_sha256: String,
    pub orbit_content_sha256: String,
    pub candidate_count: u64,
    pub candidate_occurrence_count: u64,
    pub fingerprint_group_count: u64,
    pub orbit_count: u64,
    pub exact_transports_replayed: u64,
    pub representative_fingerprints_recomputed: u64,
    pub representative_inequivalence_checks: u64,
    pub largest_fingerprint_group: usize,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct SavedOrbit {
    r#type: String,
    fingerprint_sha256: String,
    representative: OrbitCandidate,
    equivalent_members: Vec<EquivalentMember>,
    member_count: u64,
    candidate_occurrence_count: u64,
}

fn take_candidate(
    expected: &mut BTreeMap<String, OrbitCandidate>,
    candidate: &OrbitCandidate,
    ambient_rank: usize,
) -> Result<IntegralLineConfiguration> {
    let original = expected
        .remove(&candidate.candidate_id)
        .context("orbit candidate is absent from keyed input or occurs repeatedly")?;
    ensure!(
        &original == candidate,
        "orbit candidate changed its keyed provenance"
    );
    configuration(&candidate.vectors, ambient_rank)
}

fn replay_transport(
    source: &IntegralLineConfiguration,
    target: &IntegralLineConfiguration,
    member: &EquivalentMember,
) -> Result<()> {
    let transformation = Matrix::from_rows(
        Z,
        member
            .transformation_to_representative
            .iter()
            .map(|row| {
                row.iter()
                    .map(|entry| entry.parse::<noether::Integer>())
                    .collect::<std::result::Result<Vec<_>, _>>()
            })
            .collect::<std::result::Result<Vec<_>, _>>()?,
    )?;
    ensure!(
        source.transform(&transformation)? == *target,
        "saved orbit transformation does not reach its representative"
    );
    // Apply T to all columns in one native matrix operation. Canonical signs
    // remain Noether's responsibility, including the individual line images.
    let columns = Matrix::from_rows(Z, source.vectors().to_vec())?.transpose();
    let images = transformation.matmul(&columns)?;
    let rows = images.rows().collect::<Vec<_>>();
    let mut permutation = Vec::with_capacity(source.line_count());
    for index in 0..source.line_count() {
        let image = IntegralLineConfiguration::new(
            source.ambient_rank(),
            [rows
                .iter()
                .map(|row| row[index].clone())
                .collect::<Vec<_>>()],
        )?;
        let position = target
            .vectors()
            .binary_search(&image.vectors()[0])
            .map_err(|_| anyhow::anyhow!("transported line is absent from representative"))?;
        permutation.push(u32::try_from(position)?);
    }
    ensure!(
        permutation == member.line_permutation,
        "saved orbit line permutation is wrong"
    );
    Ok(())
}

/// Recompute representative invariants, replay every exact member transport,
/// and check equality with the full keyed input, group by group. A member's
/// fingerprint follows from its checked GL equivalence to the representative.
pub fn audit_orbit_artifact(task: &OrbitAuditTask) -> Result<OrbitAuditReport> {
    ensure!(
        task.r#type == ORBIT_AUDIT_TASK_SCHEMA,
        "unsupported orbit audit schema"
    );
    ensure!(
        task.noether_contract == noether_contract(),
        "different Noether contract"
    );
    ensure!(
        task.max_fingerprint_group_size > 0,
        "fingerprint group cap must be positive"
    );
    validate_source(&task.keyed_artifact_path)?;
    validate_source(&task.orbit_artifact_path)?;
    let mut keyed = BufReader::new(File::open(&task.keyed_artifact_path)?);
    let mut orbits = BufReader::new(File::open(&task.orbit_artifact_path)?);
    let keyed_header_line = read_required_line(&mut keyed, "keyed header")?;
    let keyed_header: OwnedKeyedHeader = serde_json::from_slice(&keyed_header_line)?;
    let orbit_header_line = read_required_line(&mut orbits, "orbit header")?;
    let mut orbit_header: serde_json::Value = serde_json::from_slice(&orbit_header_line)?;
    ensure!(
        orbit_header["type"] == ORBIT_ARTIFACT_SCHEMA
            && orbit_header["keyed_content_sha256"] == task.keyed_content_sha256,
        "orbit audit header has wrong schema or keyed digest"
    );
    let object = orbit_header
        .as_object_mut()
        .context("orbit header is not an object")?;
    object.remove("keyed_content_sha256");
    object.insert("type".to_owned(), KEYED_ARTIFACT_SCHEMA.into());
    let orbit_scope: OwnedKeyedHeader = serde_json::from_value(orbit_header)?;
    for header in [&keyed_header, &orbit_scope] {
        ensure!(
            header.r#type == KEYED_ARTIFACT_SCHEMA
                && header.noether_contract == noether_contract()
                && header.fingerprint_schema == ORBIT_FINGERPRINT_SCHEMA
                && header.candidate_content_sha256 == task.candidate_content_sha256
                && header.input_sha256 == task.pair_input_sha256
                && header.event_stream_sha256 == task.event_stream_sha256
                && header.lower_index == task.lower_index
                && header.ambient_rank == task.ambient_rank
                && header.target_dimension == task.cone_dimension,
            "orbit audit artifact scope or provenance disagrees"
        );
    }
    let mut key_digest = Sha256::new();
    key_digest.update(&keyed_header_line);
    let mut orbit_digest = Sha256::new();
    orbit_digest.update(&orbit_header_line);
    let mut key_line = read_required_line(&mut keyed, "keyed record or footer")?;
    let mut orbit_line = read_required_line(&mut orbits, "orbit record or footer")?;
    let mut previous_key = None;
    let mut previous_orbit = None;
    let mut candidate_count = 0u64;
    let mut occurrences = 0u64;
    let mut groups = 0u64;
    let mut orbit_count = 0u64;
    let mut transports = 0u64;
    let mut inequivalences = 0u64;
    let mut largest_group = 0;
    let key_footer = loop {
        let value: serde_json::Value = serde_json::from_slice(&key_line)?;
        if value["type"] == KEYED_FOOTER_SCHEMA {
            break serde_json::from_value::<OwnedKeyedFooter>(value)?;
        }
        let first: KeyedRecord = serde_json::from_value(value)?;
        let fingerprint = first.fingerprint_sha256.clone();
        let mut expected = BTreeMap::new();
        loop {
            let value: serde_json::Value = serde_json::from_slice(&key_line)?;
            if value["type"] == KEYED_FOOTER_SCHEMA || value["fingerprint_sha256"] != fingerprint {
                break;
            }
            let record: KeyedRecord = serde_json::from_value(value)?;
            validate_keyed_record(&record, task.ambient_rank, previous_key.as_ref())?;
            previous_key = Some((fingerprint.clone(), record.vectors.clone()));
            candidate_count = candidate_count
                .checked_add(1)
                .context("candidate count overflow")?;
            occurrences = occurrences
                .checked_add(record.occurrence_count)
                .context("occurrence count overflow")?;
            let candidate: OrbitCandidate = record.into();
            ensure!(
                expected
                    .insert(candidate.candidate_id.clone(), candidate)
                    .is_none(),
                "repeated keyed candidate ID"
            );
            ensure!(
                expected.len() <= task.max_fingerprint_group_size,
                "fingerprint group exceeds audit cap"
            );
            key_digest.update(&key_line);
            key_line = read_required_line(&mut keyed, "keyed record or footer")?;
        }
        largest_group = largest_group.max(expected.len());
        groups += 1;
        let mut representatives: Vec<IntegralLineConfiguration> = Vec::new();
        loop {
            let value: serde_json::Value = serde_json::from_slice(&orbit_line)?;
            if value["type"] == ORBIT_FOOTER_SCHEMA || value["fingerprint_sha256"] != fingerprint {
                break;
            }
            let record: SavedOrbit = serde_json::from_value(value)?;
            ensure!(
                record.r#type == ORBIT_RECORD_SCHEMA,
                "unsupported orbit record"
            );
            let current = (
                record.fingerprint_sha256.clone(),
                record.representative.vectors.clone(),
            );
            ensure!(
                previous_orbit
                    .as_ref()
                    .is_none_or(|previous| previous < &current),
                "orbit representatives are not strictly ordered"
            );
            previous_orbit = Some(current);
            let target = take_candidate(&mut expected, &record.representative, task.ambient_rank)?;
            ensure!(
                target.is_spanning() && target.perfection_rank() == task.cone_dimension,
                "orbit representative has wrong ambient span or cone dimension"
            );
            ensure!(
                equivalence_fingerprint(&record.representative.vectors, task.ambient_rank)?
                    == fingerprint,
                "orbit representative has wrong equivalence fingerprint"
            );
            for earlier in &representatives {
                ensure!(
                    target.equivalence_to(earlier)?.is_none(),
                    "equivalent representatives split across orbits"
                );
                inequivalences += 1;
            }
            let mut orbit_occurrences = record.representative.occurrence_count;
            ensure!(
                record.member_count == 1 + record.equivalent_members.len() as u64,
                "orbit member count disagrees"
            );
            for member in &record.equivalent_members {
                let source = take_candidate(&mut expected, &member.candidate, task.ambient_rank)?;
                replay_transport(&source, &target, member)?;
                orbit_occurrences = orbit_occurrences
                    .checked_add(member.candidate.occurrence_count)
                    .context("orbit occurrence count overflow")?;
                transports += 1;
            }
            ensure!(
                record.candidate_occurrence_count == orbit_occurrences,
                "orbit occurrence count disagrees"
            );
            representatives.push(target);
            orbit_count += 1;
            orbit_digest.update(&orbit_line);
            orbit_line = read_required_line(&mut orbits, "orbit record or footer")?;
            if orbit_count % 10_000 == 0 {
                eprintln!("orbit audit progress: orbits={orbit_count} transports={transports}");
            }
        }
        ensure!(
            expected.is_empty(),
            "orbit records do not cover their keyed fingerprint group"
        );
    };
    let keyed_sha256 = format!("{:x}", key_digest.finalize());
    ensure!(
        key_footer.r#type == KEYED_FOOTER_SCHEMA
            && key_footer.content_sha256 == keyed_sha256
            && keyed_sha256 == task.keyed_content_sha256
            && key_footer.candidate_count == candidate_count
            && candidate_count == task.candidate_count
            && key_footer.candidate_occurrence_count == occurrences
            && occurrences == task.candidate_occurrence_count
            && key_footer.fingerprint_group_count == groups
            && groups == task.fingerprint_group_count,
        "keyed audit footer, digest, or coverage disagrees"
    );
    let footer: serde_json::Value = serde_json::from_slice(&orbit_line)?;
    let orbit_sha256 = format!("{:x}", orbit_digest.finalize());
    let expected_footer = serde_json::json!({
        "type": ORBIT_FOOTER_SCHEMA, "content_sha256": orbit_sha256,
        "candidate_count": candidate_count, "candidate_occurrence_count": occurrences,
        "fingerprint_group_count": groups, "orbit_count": orbit_count,
        "duplicate_candidate_count": candidate_count.checked_sub(orbit_count).context("too many orbits")?,
        "exact_equivalence_count": transports,
    });
    ensure!(
        footer == expected_footer
            && orbit_sha256 == task.orbit_content_sha256
            && orbit_count == task.orbit_count
            && transports == task.exact_equivalence_count
            && transports == candidate_count - orbit_count,
        "orbit audit footer, digest, or coverage disagrees"
    );
    ensure!(
        keyed.fill_buf()?.is_empty() && orbits.fill_buf()?.is_empty(),
        "artifact has data after footer"
    );
    Ok(OrbitAuditReport {
        r#type: ORBIT_AUDIT_REPORT_SCHEMA,
        noether_contract: noether_contract(),
        input_sha256: format!(
            "{:x}",
            Sha256::digest(serde_json::to_vec(&serde_json::to_value(task)?)?)
        ),
        keyed_content_sha256: keyed_sha256,
        orbit_content_sha256: orbit_sha256,
        candidate_count,
        candidate_occurrence_count: occurrences,
        fingerprint_group_count: groups,
        orbit_count,
        exact_transports_replayed: transports,
        representative_fingerprints_recomputed: orbit_count,
        representative_inequivalence_checks: inequivalences,
        largest_fingerprint_group: largest_group,
    })
}
