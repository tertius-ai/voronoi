# Voronoi

Exact Voronoi-complex computations for research on $K_{12}(\mathbb Z)$,
built on [Noether 0.3.2](https://github.com/tertius-ai/noether/tree/v0.3.2).
The degree-12 census and the final K-theory argument remain unfinished.

The research targets are cone dimension $r=12$ in ambient lattice ranks
$N=9,10,11$. Here $r=\operatorname{rank}\{vv^t\}$ and $s$ is the number
of minimum-vector pairs; configurations need not satisfy $r=s$.

## What works

- Published database parsing with exact dimension checks.
- Watson reconstruction of the 13 rank-eight base orbits, certified minimum
  realization, exact equivalence, stabilizers, and orientation checks.
- Incidence and coface-pair enumeration, disk-backed orbit reduction, and
  resumable completion ledgers with process memory and time limits.
- Separate accounting for verified realizations, certified negatives,
  inconclusive checkpoints, and execution timeouts.

The exhaustive Watson entry point currently supports only $N=8$. Individual
index-family constructors at other ranks do not establish exhaustive coverage.

A historical single-lower-cell computation at $(N,r)=(8,10)$ covered 924,637
candidate orbits: 453 realizations and 924,184 certified negatives. The saved
September 2026 audit closed its timeout tail. This is a partial research stage;
the complete rank-eight census has not been reconstructed from scratch.
The [historical summary](validation/historical-n8-r10.json) identifies the
local evidence, which is not bundled with a clone.

See the [research plan](PLAN.md) for remaining work and the
[bibliography](BIBLIOGRAPHY.md) for mathematical references.

## Build

Use sibling checkouts of this repository and Noether's `v0.3.2` source tag.
Requirements: Linux, Python 3.11+, `uv`, a C/C++ toolchain, `pkg-config`,
`make`, and Rust with `rustup`. The pinned Rust toolchain is 1.94.0.
Census subprocesses also use `prlimit`, `flock`, GNU `time`, and `timeout`.

```bash
git clone --branch v0.3.2 --depth 1 https://github.com/tertius-ai/noether.git noether
git clone https://github.com/tertius-ai/voronoi.git voronoi
cd voronoi
(cd ../noether && scripts/install-flint.sh)
make sync
make engine
make doctor
```

For existing checkouts, retain local work and select the matching Noether
source. `make sync` builds the editable Python dependency, installs its native
libraries, and generates its runtime index. Both Python and Rust require
Noether 0.3.2. `make doctor` checks their compiled versions and semantic types.
`FLINT_PREFIX` can select another compatible FLINT 3.6+ installation.

## Check a change

```bash
make test-fast                 # small cases; no reference database needed
make lint
scripts/fetch_database.sh       # fetch the locked reference revision
make test-corpus                # all Python tests, including the full incidence pass
make test-rust
```

The reference database is locked by revision and file hashes in
[`validation/reference-database.json`](validation/reference-database.json).
Its upstream `LICENSE` is separate from this project's source license.
The [Noether migration record](validation/noether-0.3.2.json) records the
completed 0.3.2 checks. A skipped database test is not a verified result.

## Use and contribute

```bash
.venv/bin/voronoi --help
.venv/bin/voronoi doctor
```

The [computation guide](docs/computations.md) explains census commands,
artifact formats, resource limits, and restart behavior. It distinguishes
reference data, locally retained historical evidence, and new computations.

Read [CONTRIBUTING.md](CONTRIBUTING.md) for code ownership and evidence rules.
Useful starting points are exact merging across lower cells, independent
coverage audits, and the remaining degree-12 targets in [PLAN.md](PLAN.md).

## Source map

| Path | Responsibility |
|---|---|
| `src/voronoi/` | Cells, parsing, Watson enumeration, orientation, census orchestration |
| `rust/census-engine/` | Streaming pair enumeration, orbit reduction, isolated completion |
| `tests/` | Small exact cases, artifact integrity, resume behavior, corpus regressions |
| `validation/` | Reference expectations, input lock, and dated validation records |
| `data/`, `artifacts/` | Ignored reference data and computation outputs |

Noether owns reusable exact mathematics. Voronoi owns the research-specific
census, its evidence, and its coverage accounting. The radius-based extension
experiment remains available in `voronoi.enumerate.lp_extend` for diagnosis;
it does not establish exhaustive census coverage.
