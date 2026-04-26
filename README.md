# voronoi

Computational attack on K_12(Z) via Voronoi complexes of GL_N(Z).

## Goal

Extend the Dutour Sikirić / Elbaz-Vincent / Kupers / Martinet program
(arXiv:1910.11598, which proves K_8(Z) = 0) to compute H_12(Vor_{GL_N})
for the N values where it's currently open. Combined with the
Voronoi → Borel-Serre → Quillen pipeline, this delivers a theorem on
K_12(Z).

## Status

**Milestone — K_8(Z) reproduction closed (Phase A done at minimum
sufficiency):** Per Kupers' [Kup19] short-proof argument (his Remark
2.4), the strict input to `K_8(Z) = 0` via the Voronoi route is
`Σ_n=8(GL_8) = ∅` — equivalently `H_1(GL_8(Z); St_8) = 0 mod S_9` via
DSEKM Prop 1.5 (`H_q(GL_p; St_p) ≅ H_{q+p-1}(Vor_{GL_p}) mod S_{p+1}`,
collapsing `V_8 = 0` makes `H_8(Vor_{GL_8}) = 0` trivially). Combined
with Lee-Szczarba (`p ≤ 4`), Elbaz-Vincent–Gangl–Soulé (`p ∈ {5, 6, 7}`),
and Borel's `K_4i(Z)`-is-finite-torsion-at-irregular-primes>10⁸, this
closes `K_8(Z) ⊗ Z[1/7!] = 0` per Kupers' spectral-sequence argument.

Our reproduction at (N=8, n=8) gives both pieces: 13 cells enumerated
from scratch via Watson code theory matching the published 13 orbits,
and `Σ_n=8(GL_8) = 0` verified via the exact signed-permutation
orientation tally. Bonus DSEKM-style verification: `Σ_n=9(GL_8) = 0`
(106 cells, 0.34s) and `Σ_n=10(GL_8) = 0` (783 cells, ~28s) also
reproduced. `Σ_n=11(GL_8)` and `Σ_n=12(GL_8)` are not strictly required
for `K_8(Z) = 0` and remain pending — brute force has worst-case cells
that don't terminate practically; the BFS-over-Aut variant we tried
gave false negatives for unresolved reasons (PARI |Aut| matches across
both qfauto paths, so the bug is somewhere downstream). Reach for
Schreier-Sims if/when needed.

**Phase B — K_12(Z) — in progress.** The K_12(Z) program (per the
strategy distilled from DSEKM + Kupers Remark 2.6) needs three
specific Voronoi vanishings:

| Group | ≅ via Prop 1.5 | mod |
|-------|----------------|-----|
| H_2(GL_11, St_11) | H_12(Vor_{GL_11}) | S_12 |
| H_3(GL_10, St_10) | H_12(Vor_{GL_10}) | S_11 |
| H_4(GL_9, St_9)   | H_12(Vor_{GL_9})  | S_10 |

If `Σ_n=12(GL_N) = ∅` for `N ∈ {9, 10, 11}`, all three groups vanish.
Combined with `H_1(GL_12; St_12) = 0 mod S_12` (Church-Putnam
extension), `H_5(GL_8; St_8) = 0 mod S_9` (DSEKM, ours reproduces),
`H_6(GL_7; St_7) = Z` (EVGS), and the DSEKM kernel-of-Hurewicz lemma
(ker(K_12(Z) → H_13(BQ; Z)) ⊂ S_7) and Borel (`K_12(Z) ⊗ Q = 0`),
this places `K_12(Z)` in `S_max(7, k)` torsion only — same picture
DSEKM and Kupers both lay out.

The hard piece is the cell enumeration at `(N, n=12)` for `N ∈ {9,
10, 11}` — DSEKM Table 4 has `?` at these entries. Watson code theory
only handles `n = N`; for `n > N` we need the LP-feasibility / vector-
configuration extension machinery from DSEKM §3, which we have all the
primitives for (LP, qfminim, qfisom, realizability oracle) but no
driver.

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

1. **Schreier-Sims over Aut(G) generators** to unblock n=11, n=12. The
   correct PARI invocation `qfauto(G)` (no SHV) gives Aut(G) generators
   directly; coset enumeration over those generators yields the
   SetStab(±V) ∩ Aut(G) subgroup, which contains the cell's true
   stabilizer. ~200-400 lines of focused work.
2. Extend the orientation tally to N=9, 10, 11 once Phase A completes
   (uses the published partial database for these N).
3. **Phase B foundations**: LLL, Plesken-Pohst canonical form, Voronoi
   neighbor algorithm. Each is a noether `api.lattice` addition.

See `PLAN.md` for the full open-questions list.
