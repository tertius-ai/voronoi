# voronoi

## What this is

A computational attack on K_12(Z) via Voronoi complexes of GL_N(Z).
Dogfoods the `noether` library; anything missing from noether that
we need gets added there, not here.

Read `PLAN.md` for the three-layer roadmap. Read `README.md` for
the short version.

## Rules

- **noether first.** Lattice / PARI / homology primitives belong in
  noether under `noether.api.lattice.*`, `noether.api.convex.*`,
  `noether.api.smooth_snf`. This repo consumes them. If a primitive
  doesn't exist yet, add it to noether (branch `noether-lattice` or
  similar) rather than inlining a fix here.
- **libpari via Rust FFI**, not cypari2. cypari2 conflicts with the
  Rust engine's libpari singleton; we want both PARI (for qfauto /
  qfisom / qflll / qfminim) and the engine (for smooth_snf / rank
  mod p) live in the same process.
- **Research artefacts live in validation/.** Expected Σ_n tallies,
  reference orbit counts, etc. Actual data (the database clone) is
  under `data/` and gitignored.
- **No scratch Python files at the repo root.** Tests go in
  `tests/`, utilities under `src/voronoi/`, reproducibility drivers
  under `src/voronoi/cli.py`.

## Getting the public database

```
scripts/fetch_database.sh
```

Pulls elbazvip/Voronoi-complexes-database into `data/` (gitignored).

## Key files

- `PLAN.md` — three-layer roadmap (reproducibility → enumeration → homology)
- `README.md` — short description + layout
- `src/voronoi/` — package
- `tests/` — pytest suite
- `validation/` — corpora + expected outputs for reproducibility
- `data/` — gitignored; raw published databases

## Principles

- This is research, not product. Build slowly and carefully, one
  layer at a time. Don't skip to Layer B before Layer A is solid.
- All randomness explicit.
- Every result carries a certificate — a proof-of-correctness check
  that an external reader can independently verify.
- Tests must run without libpari built (they can be skip-gated).
