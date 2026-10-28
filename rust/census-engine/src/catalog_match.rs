// SPDX-License-Identifier: MIT
//! Compare a recovered census with a named reference catalog, retaining transports.

use std::collections::{BTreeMap, BTreeSet};

use anyhow::{ensure, Context, Result};
use noether::linalg::{IntegralLineAutomorphismGroup, IntegralLineConfiguration};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use super::{
    configuration, i64_vectors, noether_contract, orbit_artifact::equivalence_fingerprint,
};

pub const CATALOG_MATCH_TASK_SCHEMA: &str = "voronoi/catalog-match-task@1";
pub const CATALOG_MATCH_REPORT_SCHEMA: &str = "voronoi/catalog-match-report@1";
const MAX_CATALOG_SIZE: usize = 10_000;

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CatalogEntry {
    pub id: String,
    pub vectors: Vec<Vec<i64>>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CatalogMatchTask {
    pub r#type: String,
    pub noether_contract: BTreeMap<String, String>,
    pub ambient_rank: usize,
    pub cone_dimension: usize,
    pub sources: Vec<CatalogEntry>,
    pub references: Vec<CatalogEntry>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct CatalogMatch {
    pub source_id: String,
    pub reference_id: String,
    pub transformation: Vec<Vec<String>>,
    pub line_permutation: Vec<u32>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct CatalogMatchReport {
    pub r#type: String,
    pub noether_contract: BTreeMap<String, String>,
    pub input_sha256: String,
    pub source_count: usize,
    pub reference_count: usize,
    pub reference_orbits_verified_distinct: bool,
    pub matches: Vec<CatalogMatch>,
    pub unmatched_source_ids: Vec<String>,
    pub unused_reference_ids: Vec<String>,
}

struct Reference {
    id: String,
    configuration: IntegralLineConfiguration,
    automorphisms: Option<IntegralLineAutomorphismGroup>,
}

impl Reference {
    fn equivalence(
        &mut self,
        source: &IntegralLineConfiguration,
    ) -> Result<Option<noether::linalg::IntegralLineEquivalence>> {
        if self.automorphisms.is_none() {
            self.automorphisms = Some(self.configuration.automorphism_group()?);
        }
        Ok(source.equivalence_to_with_target_automorphisms(
            &self.configuration,
            self.automorphisms
                .as_ref()
                .context("missing reference automorphisms")?,
        )?)
    }
}

fn checked_entries(
    entries: &[CatalogEntry],
    task: &CatalogMatchTask,
) -> Result<Vec<IntegralLineConfiguration>> {
    ensure!(
        entries.len() <= MAX_CATALOG_SIZE,
        "catalog exceeds entry cap"
    );
    let mut ids = BTreeSet::new();
    entries
        .iter()
        .map(|entry| {
            ensure!(
                !entry.id.is_empty() && ids.insert(&entry.id),
                "empty or duplicate catalog ID"
            );
            let config = configuration(&entry.vectors, task.ambient_rank)?;
            ensure!(
                config.is_spanning(),
                "catalog entry does not span ambient space"
            );
            ensure!(
                config.perfection_rank() == task.cone_dimension,
                "wrong catalog cone dimension"
            );
            ensure!(
                i64_vectors(&config)? == entry.vectors,
                "catalog vectors are not canonical"
            );
            Ok(config)
        })
        .collect()
}

/// Exact equivalence is decisive; maximal-minor fingerprints only select comparisons.
/// No claim of global census coverage or minimum realizability follows from a match.
pub fn match_catalog(task: &CatalogMatchTask) -> Result<CatalogMatchReport> {
    ensure!(
        task.r#type == CATALOG_MATCH_TASK_SCHEMA,
        "unsupported catalog task schema"
    );
    ensure!(
        task.noether_contract == noether_contract(),
        "different Noether contract"
    );
    let reference_configs = checked_entries(&task.references, task)?;
    let source_configs = checked_entries(&task.sources, task)?;
    let mut groups: BTreeMap<String, Vec<Reference>> = BTreeMap::new();
    for (entry, config) in task.references.iter().zip(reference_configs) {
        let fingerprint = equivalence_fingerprint(&entry.vectors, task.ambient_rank)?;
        let group = groups.entry(fingerprint).or_default();
        for existing in group.iter_mut() {
            if let Some(equivalence) = existing.equivalence(&config)? {
                equivalence.verify()?;
                anyhow::bail!(
                    "equivalent reference entries {} and {}",
                    existing.id,
                    entry.id
                );
            }
        }
        group.push(Reference {
            id: entry.id.clone(),
            configuration: config,
            automorphisms: None,
        });
    }
    let mut matches = Vec::new();
    let mut unmatched_source_ids = Vec::new();
    let mut used = BTreeSet::new();
    for (entry, config) in task.sources.iter().zip(source_configs) {
        let fingerprint = equivalence_fingerprint(&entry.vectors, task.ambient_rank)?;
        let mut found = false;
        if let Some(group) = groups.get_mut(&fingerprint) {
            for reference in group {
                if let Some(equivalence) = reference.equivalence(&config)? {
                    equivalence.verify()?;
                    matches.push(CatalogMatch {
                        source_id: entry.id.clone(),
                        reference_id: reference.id.clone(),
                        transformation: equivalence
                            .transformation()
                            .rows()
                            .map(|row| row.into_iter().map(|entry| entry.to_string()).collect())
                            .collect(),
                        line_permutation: equivalence.line_permutation().images().to_vec(),
                    });
                    used.insert(reference.id.clone());
                    found = true;
                    break;
                }
            }
        }
        if !found {
            unmatched_source_ids.push(entry.id.clone());
        }
    }
    Ok(CatalogMatchReport {
        r#type: CATALOG_MATCH_REPORT_SCHEMA.to_owned(),
        noether_contract: noether_contract(),
        // Value canonicalizes object key order, agreeing with Python sort_keys=True.
        input_sha256: format!(
            "{:x}",
            Sha256::digest(serde_json::to_vec(&serde_json::to_value(task)?)?)
        ),
        source_count: task.sources.len(),
        reference_count: task.references.len(),
        reference_orbits_verified_distinct: true,
        matches,
        unmatched_source_ids,
        unused_reference_ids: task
            .references
            .iter()
            .filter(|entry| !used.contains(&entry.id))
            .map(|entry| entry.id.clone())
            .collect(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn entry(id: &str, vectors: Vec<Vec<i64>>) -> CatalogEntry {
        let config = configuration(&vectors, 2).unwrap();
        CatalogEntry {
            id: id.to_owned(),
            vectors: i64_vectors(&config).unwrap(),
        }
    }

    fn task() -> CatalogMatchTask {
        CatalogMatchTask {
            r#type: CATALOG_MATCH_TASK_SCHEMA.to_owned(),
            noether_contract: noether_contract(),
            ambient_rank: 2,
            cone_dimension: 2,
            references: vec![entry("axes", vec![vec![1, 0], vec![0, 1]])],
            sources: vec![
                entry("sheared", vec![vec![1, 1], vec![1, 2]]),
                entry("index-two", vec![vec![1, 1], vec![1, -1]]),
            ],
        }
    }

    #[test]
    fn matches_integral_transports_and_accounts_for_unmatched_sources() {
        let report = match_catalog(&task()).unwrap();
        assert_eq!(report.matches.len(), 1);
        assert_eq!(report.matches[0].source_id, "sheared");
        assert_eq!(report.matches[0].reference_id, "axes");
        assert_eq!(report.unmatched_source_ids, ["index-two"]);
        assert!(report.unused_reference_ids.is_empty());
    }

    #[test]
    fn rejects_equivalent_reference_entries_and_wrong_rank() {
        let mut task = task();
        task.references.push(task.sources[0].clone());
        assert!(match_catalog(&task)
            .unwrap_err()
            .to_string()
            .contains("equivalent reference"));
        task.references.pop();
        task.cone_dimension = 3;
        assert!(match_catalog(&task)
            .unwrap_err()
            .to_string()
            .contains("wrong catalog cone dimension"));
    }

    #[test]
    fn fingerprint_collision_does_not_become_an_equivalence() {
        let mut task = task();
        let first = entry("index-11-a1", vec![vec![1, 0], vec![1, 11]]);
        let second = entry("index-11-a2", vec![vec![1, 0], vec![2, 11]]);
        assert_eq!(
            equivalence_fingerprint(&first.vectors, 2).unwrap(),
            equivalence_fingerprint(&second.vectors, 2).unwrap(),
        );
        task.references = vec![first];
        task.sources = vec![second];
        let report = match_catalog(&task).unwrap();
        assert!(report.matches.is_empty());
        assert_eq!(report.unmatched_source_ids, ["index-11-a2"]);
        assert_eq!(report.unused_reference_ids, ["index-11-a1"]);
    }
}
