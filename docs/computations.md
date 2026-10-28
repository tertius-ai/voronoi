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
hashes identify local evidence. It used a pre-0.3.2 runtime. The subsequent
[full ledger replay](../validation/n8-r10-ledger-replay-2026-10-28.json)
checked every saved verdict under the current engine, after the separate
orbit audit. Earlier coface-pair generation has not been independently repeated.

## Stage boundaries

| Command | Input | Output |
|---|---|---|
| `doctor` | Python installation and Rust worker | Compiled versions and semantic-contract check |
| `census-pairs` | Published lower and middle catalogs | Candidate JSONL and pair report |
| `census-orbit-key` | Candidates and pair report | Keyed JSONL and key report |
| `census-orbits` | Keyed candidates and key report | Orbit JSONL and exact equivalence evidence |
| `census-audit-orbits` | Saved keyed/orbit artifacts and their reports | Native replay report, bound task, and worker identity |
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

## Audit the historical positive shells

The bounded audit reads the historical SQLite ledgers in read-only transactions,
checks terminal index coverage and metadata, verifies the original orbit-file
content digest, and binds every positive row to its original representative.
It then compares those shells with the locked published cone-rank-10 catalog
using Noether 0.3.2 exact equivalences. It freshly realizes each matched
reference configuration, pulls its Gram matrix back through the retained
column transport $T$ as $T^tGT$, and re-enumerates the original complete shell.
Unmatched sources are realized directly. Using the published coordinates
avoids expensive cutting-plane searches in less convenient bases.

```bash
.venv/bin/python -m voronoi.historical_audit \
  --output-dir artifacts/n8-r10/audit-NEW-RUN
```

The output directory must be new. It contains the source snapshot, a named
catalog task and report, fresh exact-shell realization tasks and evidence,
the pulled-back Gram witnesses in the original coordinates,
and a hashed summary. At most four batches run concurrently (`--workers 1`
selects serial execution). Each batch has a 60-second timeout and a
4 GiB memory ceiling; a timeout records no mathematical verdict. Fingerprints
only select comparisons. The native catalog matcher checks that the reference
orbits are distinct and supplies unimodular matrices and line permutations;
Python replays every positive transport. Catalog matching does not itself
prove minimum realizability or global census coverage.

Current completion reports use `completion-batch-report@4`: every positive
retains its integral Gram matrix and exact minimum in `realization_witness`.
Python re-enumerates its complete shell using Noether before accepting it.
The canonical Noether value is also retained, but its positive configuration
identity omits the Gram matrix. Historical positive payloads therefore need
fresh witnesses; checking their canonical-byte hashes alone cannot replay
minimum realizability. Existing ledgers and artifact labels remain intact.

To retain progress from an earlier or interrupted positive audit, pass
`--reuse-audit artifacts/PREVIOUS-RUN` (repeatable). Each reused Gram is
re-enumerated against the original source shell with the current Noether
runtime; its original file path and hash are retained. Saved status labels
or canonical identity bytes alone are never accepted as positive witnesses.

Replay a completed bundle independently, without repeating the LP searches:

```bash
.venv/bin/python scripts/verify_positive_audit.py artifacts/COMPLETED-AUDIT
```

This checks every evidence-file hash, replays the catalog transports, and
re-enumerates every original source shell from its saved Gram witness.

This audit counts the saved negative statuses but does not replay their
certificates. It checks the original orbit-file bytes without replaying all
historical orbit-reduction transports. The evidence stays local under
`artifacts/`; a small dated result in `validation/` is an index to that evidence,
not a replacement for publishing it.

## Replay an orbit reduction

`census-audit-orbits` reads both input artifacts without modifying them. It
checks their headers, byte digests, exact candidate provenance, occurrence
counts, and group coverage. Noether replays every saved unimodular matrix and
its line permutation. It recomputes each representative's minor fingerprint;
member fingerprints follow from the checked equivalences. Multiple
representatives sharing a fingerprint are checked for inequivalence, since a
fingerprint collision alone cannot separate orbits.

```bash
.venv/bin/voronoi census-audit-orbits \
  --keyed-artifact artifacts/n8-r10/lower-000-keyed.jsonl \
  --orbit-artifact artifacts/n8-r10/lower-000-orbits.jsonl \
  --pair-report artifacts/n8-r10/lower-000-report.json \
  --key-report artifacts/n8-r10/lower-000-orbit-key-report.json \
  --orbit-report artifacts/n8-r10/lower-000-orbit-report.json \
  --output-report artifacts/n8-r10/orbit-audit-NEW.json
```

The new report retains the task and worker hash. Existing output is never
replaced. Defaults are 4 GiB, 1,800 seconds, and at most 10,000 candidates per
fingerprint group. A resource failure produces no accepted audit report.
This verifies reduction relative to the named keyed input; regenerate keys
with `census-orbit-key` to check the candidate-to-keyed stage too. It does not
replay the earlier coface-pair enumeration or establish global census coverage.

## Historical negative evidence under Noether 0.3.2

Saved exact-shell negatives include their configurations, obstacle vectors,
and rational multipliers in Noether's canonical wire format. The 0.3.2 public
`MinimumNonrealizabilityCertificate` API exposes inspection and `verify()`,
but no checked constructor or deserializer for importing that saved data.
Voronoi's inspector checks structural provenance and extracts source
configurations. Its separate native checker interprets the proof data and
verifies the exact linear identities, signs, and bounds using public Noether
operations. It never reconstructs Noether's opaque certificate objects. See
[the mathematical checks](negative-certificates.md) for the four proof kinds,
outsider validation, and supported historical row-scaling conventions.

Replay the complete historical ledger into a new audit workspace:

```bash
.venv/bin/python -m voronoi.negative_replay \
  --output-dir artifacts/n8-r10/ledger-replay-NEW --workers 4
```

The command requires the saved orbit artifact, 64 historical SQLite shards,
and the completed positive-audit bundle. Use `--artifact-root` and
`--positive-audit` for other locations. It opens every source database read-only,
freezes the worker executable, and streams disjoint index partitions without
copying the large ledger payloads to another database. Each worker has a 4 GiB
memory ceiling and a one-hour time limit. A failure produces no accepted
complete report. The sources are never overwritten.

Every negative proof is bound to the corresponding orbit representative.
Positive cases are re-enumerated from the saved source Gram witnesses. Receipt
files are published only after input digests and terminal coverage agree;
their persisted hashes and index coverage are checked separately. These are
exact-shell verdicts, not claims about larger same-rank completions.

The bounded calibration command selects one negative per shard, distributed
across the full candidate-index range, and obtains fresh Noether results:

```bash
.venv/bin/python scripts/calibrate_historical_negatives.py \
  --output-dir artifacts/n8-r10/negative-calibration-NEW
```

It uses four workers, a 30-second case timeout, 200 iterations, and a 4 GiB
worker ceiling. It preserves the original payload hashes and fresh tasks and
certificates. A regenerated negative is verified natively before acceptance;
an inconclusive result or timeout remains unresolved. This is a 64-case
regeneration check, not a replay or validation of all 924,184 old negatives.

The native checker reconstructs the relevant equal-norm and outsider constraints
and checks their exact linear identities, multiplier signs, and bounds. The certificate schema,
constraint conventions, historical normalization rules, and interpretation of
the four proof kinds belong here. Use Noether's exact matrix/vector operations
for the algebra; add no second arithmetic or elimination kernel.

Any Noether extension should supply an independently useful operation. The
project certificate loader and replay policy remain in Voronoi. The existing
Noether primitives sufficed for the full replay, and the integration remains
pinned to 0.3.2.
