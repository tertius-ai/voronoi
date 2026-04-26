# voronoi

Computational attack on K_12(Z) via Voronoi complexes of GL_N(Z).

## Goal

Extend the Dutour Sikirić / Elbaz-Vincent / Kupers / Martinet program
(arXiv:1910.11598, which proves K_8(Z) = 0) to compute H_12(Vor_{GL_N})
for the N values where it's currently open. Combined with the
Voronoi → Borel-Serre → Quillen pipeline, this delivers a theorem on
K_12(Z).

## Status

**Phase A (reproduce K_8(Z) = 0): ~80%.** The (N=8, n=8) corner is
fully reproduced from scratch — Watson cell enumeration matches the
published 13 orbits and the orientation tally gives Σ_n=8(GL_8) = 0
matching DSEKM Table 4. The (n=9..12) tallies are next.

**Phase B (compute K_12(Z)): not started.** Requires extending the
enumeration to (N=9, 10, 11; n=12) and assembling boundary maps for
SNF.

## Phase A roadmap & progress

The pipeline is: enumerate cells → orientation tally (kills cells
mod 2-torsion) → boundary maps (only needed if Σ_n ≠ ∅) → SNF.

### Cell enumeration ✅ at (N=8, n=8)

`voronoi.enumerate.watson` reproduces all 13 (N=8, n=8) orbits from
scratch via Watson index theory ([DSEKM19] §2.2, Table 2). Each index
class has its own helper, all converging into a single
`enumerate_all_n_eq_N_cells(n)` entry point:

| Index | Code structure | Cells |
|------:|----------------|------:|
| d=1 | trivial Z^n | 1 |
| d=2 | binary, weight 5..8 | 4 |
| d=3 | Z/3, weight 7..8 | 2 |
| d=4 cyclic | Z/4 compositions | 4 |
| d=2² Klein | binary {5²,6} | 1 |
| d=5 | Z/5, weight 11 | 1 |
| **Total** | | **13** |

Each enumerated cell matches a unique published cell via qfisom on
centroid Gram forms. End-to-end runs in ~2.5 minutes.

### Orientation tally ✅ at (N=8, n=8), 📋 at higher n

`voronoi.orientation.has_orientation_reversing_exact` gives the
authoritative orientation character via signed-permutation enumeration:

- For each `(π, ε) ∈ S_n × {±1}^n`, candidate `g = W · adj(V) / det(V)`
  is integer iff divisible — checked exactly in numpy.
- Vectorized over the 2^n sign axis; early termination on first
  orientation-reversing element found.
- All 13 (n=8, N=8) cells have an orientation-reversing g → `Σ_n=8 = 0`.

This bypasses a documented PARI quirk: `qfauto([G, M])` does **not**
compute SetStab(±M); it computes the simultaneous Aut group of G and
M as Gram forms (per PARI 2.15 `src/basemath/qfisom.c`). The proper
SHV path goes through `qfisominit(G, fl, m)` with `m` = all vectors
of norm ≤ max(diag G), not just our cell's chosen min vectors. See
`voronoi/stab.py` docstrings.

Limitation: current implementation requires `n = N` (square M).
Extending to `n > N` (non-square M) is the next sub-task.

### Boundary maps + SNF 📋 not started

Only matters when Σ_n ≠ ∅. For Phase A this isn't needed at any (N=8,
n) per DSEKM Table 4 (Σ_n = 0 across the board). For Phase B it'll
become critical.

## Validation

Two independent regression tests against the published database:

```
voronoi/tests/test_orbit_dedupe_published.py
  — pairwise qfisom on centroid Gram forms confirms the published
    13 are 13 distinct GL_8(Z) orbits.

voronoi/tests/test_realizable_published.py
  — all 13 (N=8, n=8) cells flagged realizable by noether's M2 LP.
  — Σ_n=8(GL_8) = 0 matches DSEKM Table 4.

voronoi/tests/test_enumerate_watson.py
  — Watson enumerate_all_n_eq_N_cells(8) produces 13 cells matching
    13 distinct database entries.
```

## Layout

```
src/voronoi/
  parse/             — parsers for the published orbit databases
  cells.py           — VoronoiCell scitype
  stab.py            — Stab(σ) via noether qfauto (caveats documented)
  orientation.py     — χ_σ : Stab(σ) → {±1}
                       has_orientation_reversing_exact (signed-perm brute force)
  enumerate/
    watson.py        — Watson code enumeration (d=1, 2, 3, 4-cyclic, 2², 5)
  complex.py         — boundary map assembly (stub; Layer C)
  homology.py        — delegates to noether.api.smooth_snf (stub)
  cli.py             — `voronoi reproduce`, `voronoi extend`
tests/
  test_enumerate_watson.py
  test_orbit_dedupe_published.py
  test_realizable_published.py
validation/          — expected tallies, reproducibility corpora
data/                — gitignored; pulled via scripts/fetch_database.sh
```

## Dogfooding noether

`noether.api.lattice` provides the lattice / PARI primitives used here.
Recently shipped:

- `automorphism_group(gram)` → PARI `qfauto` (with documented caveats
  about the `min_vectors=` keyword)
- `isometry(g1, g2)` → PARI `qfisom`
- `short_vectors(gram, bound, max_count)` → PARI `qfminim`
- `is_realizable_min_vector_set(V)` / `realize_min_vector_set(V)` →
  decides whether V is the exact min-vector set of some PD form on
  Z^N, via the [DSEKM19] §3.1 LP loop (uses
  `noether.api.convex.lp_solve` over QSopt-Ex).

Pending in noether (Phase B prerequisites):

- `noether.api.lattice.lll` → PARI `qflll`
- `noether.api.lattice.canonical_form` → Plesken-Pohst canonical form
- `noether.api.convex.lp` already shipped; will be heavily consumed by
  Layer B's small-cell enumeration.

## What's next

1. Extend `has_orientation_reversing_exact` to `n > N` (rectangular M)
   so we can run the (N=8, n=9) tally as a sanity check.
2. Run (N=8, n=9, 10, 11) tallies. Schreier-Sims pass for n=12
   (50645 cells, brute force infeasible).
3. Layer B foundations: LLL, Plesken-Pohst canonical form, Voronoi
   neighbor algorithm.

See `PLAN.md` for the full open-questions list.
