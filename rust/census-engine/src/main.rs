// SPDX-License-Identifier: MIT
use std::io::{self, Read};

use anyhow::{Context, Result};
use voronoi_census_engine::{
    complete_candidate_batch, enumerate_coface_pairs, key_candidate_artifact,
    reduce_keyed_artifact, CofacePairTask, CompletionBatchTask, OrbitKeyTask, OrbitReductionTask,
    COMPLETION_TASK_SCHEMA, ORBIT_KEY_TASK_SCHEMA, ORBIT_REDUCTION_TASK_SCHEMA, TASK_SCHEMA,
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
        _ => anyhow::bail!("unsupported census-engine task type {task_type}"),
    };
    serde_json::to_writer(io::stdout(), &output).context("could not write report JSON")?;
    println!();
    Ok(())
}
