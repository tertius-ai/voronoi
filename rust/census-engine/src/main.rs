// SPDX-License-Identifier: MIT
use std::io::{self, BufRead, BufReader, Read};

use anyhow::{Context, Result};
use voronoi_census_engine::{
    audit_orbit_artifact, check_negative_batch, complete_candidate_batch, enumerate_coface_pairs,
    key_candidate_artifact, match_catalog, reduce_keyed_artifact, replay_ledger_stream,
    CatalogMatchTask, CofacePairTask, CompletionBatchTask, LedgerReplayTask, NegativeCheckTask,
    OrbitAuditTask, OrbitKeyTask, OrbitReductionTask, CATALOG_MATCH_TASK_SCHEMA,
    COMPLETION_TASK_SCHEMA, NEGATIVE_CHECK_TASK_SCHEMA, ORBIT_AUDIT_TASK_SCHEMA,
    ORBIT_KEY_TASK_SCHEMA, ORBIT_REDUCTION_TASK_SCHEMA, TASK_SCHEMA,
};

fn main() -> Result<()> {
    let arguments: Vec<_> = std::env::args_os().skip(1).collect();
    if arguments == ["--version"] {
        serde_json::to_writer(
            io::stdout(),
            &serde_json::json!({
                "type": "voronoi/census-engine-runtime@1",
                "version": env!("CARGO_PKG_VERSION"),
                "noether_version": noether::VERSION,
            }),
        )?;
        println!();
        return Ok(());
    }
    if arguments == ["--replay-ledger-stream"] {
        let mut source = BufReader::new(io::stdin().lock());
        let mut header = Vec::new();
        source.read_until(b'\n', &mut header)?;
        anyhow::ensure!(
            header.ends_with(b"\n"),
            "ledger replay task is not newline terminated"
        );
        let task: LedgerReplayTask = serde_json::from_slice(&header)?;
        serde_json::to_writer(
            io::stdout(),
            &replay_ledger_stream(&task, &header, &mut source)?,
        )?;
        println!();
        return Ok(());
    }
    anyhow::ensure!(
        arguments.is_empty(),
        "expected --version or a JSON task on stdin"
    );
    let mut input = String::new();
    io::stdin()
        .read_to_string(&mut input)
        .context("could not read the coface-pair task from stdin")?;
    let payload: serde_json::Value =
        serde_json::from_str(&input).context("invalid census-engine task JSON")?;
    let task_type = payload
        .get("type")
        .and_then(serde_json::Value::as_str)
        .context("census-engine task omitted its string type")?;
    let output = match task_type {
        TASK_SCHEMA => {
            let task: CofacePairTask = serde_json::from_value(payload)?;
            serde_json::to_value(enumerate_coface_pairs(&task)?)?
        }
        COMPLETION_TASK_SCHEMA => {
            let task: CompletionBatchTask = serde_json::from_value(payload)?;
            serde_json::to_value(complete_candidate_batch(&task)?)?
        }
        ORBIT_KEY_TASK_SCHEMA => {
            let task: OrbitKeyTask = serde_json::from_value(payload)?;
            serde_json::to_value(key_candidate_artifact(&task)?)?
        }
        ORBIT_REDUCTION_TASK_SCHEMA => {
            let task: OrbitReductionTask = serde_json::from_value(payload)?;
            serde_json::to_value(reduce_keyed_artifact(&task)?)?
        }
        CATALOG_MATCH_TASK_SCHEMA => {
            let task: CatalogMatchTask = serde_json::from_value(payload)?;
            serde_json::to_value(match_catalog(&task)?)?
        }
        ORBIT_AUDIT_TASK_SCHEMA => {
            let task: OrbitAuditTask = serde_json::from_value(payload)?;
            serde_json::to_value(audit_orbit_artifact(&task)?)?
        }
        NEGATIVE_CHECK_TASK_SCHEMA => {
            let task: NegativeCheckTask = serde_json::from_value(payload)?;
            serde_json::to_value(check_negative_batch(&task)?)?
        }
        _ => anyhow::bail!("unsupported census-engine task type {task_type}"),
    };
    serde_json::to_writer(io::stdout(), &output).context("could not write report JSON")?;
    println!();
    Ok(())
}
