# Running and auditing computations

## Inputs and evidence availability

The reference cell database is fetched separately with
`scripts/fetch_database.sh`. The script checks out the revision in
[`validation/reference-database.json`](../validation/reference-database.json)
and verifies the recorded file hashes. The upstream database includes its own
GPLv3 `LICENSE`; fetched data is ignored by this repository.

Census outputs, SQLite ledgers, logs, and native runtime snapshots are local
research artifacts under `artifacts/`. They are excluded from Git and Python
source distributions. A clone contains neither the historical census nor its
certificate bundle. Collaborators can run new computations from the reference
inputs; sharing historical results requires an explicitly distributed bundle.

The [historical summary](../validation/historical-n8-r10.json) records the
September 2, 2026 lower-000 audit: 924,637 representatives, 453 realizations,
924,184 certified negatives, and no unresolved cases. Its input and runtime
hashes identify local evidence. It used a pre-0.3.2 runtime, and those results
have not all been replayed under the current engine.

## Stage boundaries

| Command | Input | Output |
|---|---|---|
| `doctor` | Python installation and Rust worker | Compiled versions and semantic-contract check |
| `census-pairs` | Published lower and middle catalogs | Candidate JSONL and pair report |
| `census-orbit-key` | Candidates and pair report | Keyed JSONL and key report |
| `census-orbits` | Keyed candidates and key report | Orbit JSONL and exact equivalence evidence |
| `census-complete-orbits` | Orbits, keys, and their reports | Transactional SQLite shard and completion JSONL |
| `census-complete` | Raw candidates and pair report | Raw-candidate calibration shard |

Use `.venv/bin/voronoi COMMAND --help` for all options. Artifact publication
refuses to overwrite existing files. Orbit fingerprints only group candidates;
collisions are resolved by exact unimodular transformations.

The mathematical schemas are versioned independently of Noether's release.
Reports carry Noether semantic type identities, immutable input hashes, and
coverage counts. Schema identities remain unchanged by the 0.3.2 integration.

## Producing a lower-cell slice

After `make doctor` and fetching the database, generate an unpublished output
directory and choose a small known layer. For example, the following computes
one lower-cell slice at $(N,r)=(8,10)$; even a single slice can produce millions
of candidates. It is a production-size example, not a quick installation test:

```bash
.venv/bin/voronoi census-pairs --N 8 --lower-dimension 8 --lower-index 0 \
  --output-dir artifacts/n8-r10 --memory-gib 4 --timeout-seconds 1800
.venv/bin/voronoi census-orbit-key \
  --candidate-artifact artifacts/n8-r10/lower-000-candidates.jsonl \
  --pair-report artifacts/n8-r10/lower-000-report.json \
  --output-dir artifacts/n8-r10
.venv/bin/voronoi census-orbits \
  --keyed-artifact artifacts/n8-r10/lower-000-keyed.jsonl \
  --key-report artifacts/n8-r10/lower-000-orbit-key-report.json \
  --output-dir artifacts/n8-r10
```

For a quick check, use `make test-fast`. The controller test constructs a
small three-dimensional census and exercises all 64 completion shards in a
temporary directory; it does not use historical production ledgers.

## Completion, interruption, and audit

Completion commands resume the same SQLite workspace transactionally. They
retain terminal results, superseded checkpoints, and execution attempts.
`--max-new-batches 0` verifies the source/workspace and starts no new completion
work. It can still be an expensive artifact scan and can initialize a new
workspace; it is not a blanket read-only filesystem operation.

`--retry-unresolved-only` revisits unresolved checkpoints, while
`--retry-timeouts` also permits another attempt at recorded execution timeouts.
A timeout remains an execution outcome rather than a mathematical verdict.
Use the same immutable inputs and shard policy when resuming a workspace.

For the lower-000 orbit artifact, the controller runs 64 shards with a bounded
number of concurrent workers:

```bash
scripts/run-n8-r10-completion.sh 4
scripts/run-n8-r10-completion-retry.sh 4
```

These commands launch computation. The default output workspace is
`artifacts/n8-r10/orbit-production-64-noether-0.3.2`; a fresh workspace recomputes
its assigned representatives. The historical `orbit-production-64` is retained.

| Setting | Default |
|---|---|
| `VORONOI_ARTIFACT_ROOT` | `artifacts/n8-r10` |
| `VORONOI_COMPLETION_WORKSPACE` | Versioned directory above |
| `VORONOI_NOETHER_PYTHON` | `../noether/python` |
| `VORONOI_CENSUS_ENGINE` | `target/release/voronoi-census-engine` |
| `VORONOI_COMPLETION_MAX_ITERATIONS` | 200; retry script uses 1,000 |
| `VORONOI_CANDIDATE_TIMEOUT_SECONDS` | 120; retry script uses 600 |
| `VORONOI_SHARD_TIMEOUT_SECONDS` | 21,600 |

Each candidate has a 4 GiB address-space ceiling. The controller holds a
workspace lock, checks both Noether versions, snapshots the Voronoi and
Noether Python sources, native extension, FLINT/GMP/MPFR libraries, and Rust
worker, and verifies the snapshot hashes before each queued shard. Runtime
copies and per-shard logs are retained under the run directory.

## Before resuming research

The historical 382-case timeout tail was closed by subsequent retries and the
September audit. Review the recovered evidence and its reuse under 0.3.2,
then complete exact merging across lower cells. The remaining global census
and theorem requirements are in [PLAN.md](../PLAN.md).
