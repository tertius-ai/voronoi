# voronoi

Computational attack on K_12(Z) via Voronoi complexes of GL_N(Z).

## Goal

Extend the Dutour Sikirić / Elbaz-Vincent / Kupers / Martinet program
(arXiv:1910.11598, which proves K_8(Z) = 0) to compute H_12(Vor_{GL_N})
for the N values where it's currently open. Combined with the
Voronoi → Borel-Serre → Quillen pipeline, this delivers a theorem on
K_12(Z).

## Status

Layer A (reproducibility) in progress.

## Layers

- **A. Reproducibility.** Recompute Σ_n(GL_8) = 0 for n ∈ {8..12} from
  the published orbit database (elbazvip/Voronoi-complexes-database).
  Also run sparse Z-homology on the N=8 chain complex through
  `noether.api.smooth_snf` to confirm H_k(Vor_{GL_8}) = 0 mod S_2 for
  k ≤ 12.
- **B. Enumeration.** Extend the orbit table. Priority rows: (N=9,
  n=12), (N=10, n=12), (N=11, n=12). The hot primitives are exact LP
  feasibility, lattice canonical form, and lattice isometry testing.
- **C. Homology.** For each newly enumerated (N, n), run the
  orientation tally. Any orbit whose stabilizer is orientation-
  preserving forces integer homology of a sparse integer complex
  — straight into noether's `smooth_snf` pipeline.

## Layout

```
src/voronoi/
  parse/        — parsers for the published orbit databases
  cells.py      — VoronoiCell, CellOrbit
  stab.py       — Stab(σ) via noether.api.lattice.automorphism
  orientation.py— χ_σ : Stab(σ) → {±1}
  enumerate/    — layer-B facet flip + canonical forms + dedupe
  complex.py    — boundary map assembly
  homology.py   — delegates to noether.api.smooth_snf / snf
  cli.py        — `voronoi reproduce`, `voronoi extend`
validation/     — expected tallies, reproducibility corpora
data/           — gitignored; pulled via scripts/fetch_database.sh
```

## Dogfooding noether

This repo is a consumer of the `noether` library. Any lattice /
PARI / chain-complex primitive we need here is either already in
noether or gets added there — not duplicated in this repo. The
first expected noether additions:

- `noether.api.lattice.automorphism(gram_matrix)` → PARI `qfauto`
- `noether.api.lattice.isometry(G1, G2)` → PARI `qfisom`
- `noether.api.lattice.short_vectors(Q, c)` → PARI `qfminim`
- `noether.api.lattice.lll(M)` → PARI `qflll`

See PLAN.md for the full roadmap.
