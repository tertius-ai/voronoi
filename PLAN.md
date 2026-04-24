# voronoi — plan

## Long-term goal

Determine K_12(Z). Specifically: compute H_12(Vor_{GL_N}) for the N
values where it is open (conservatively, N ∈ {9, 10, 11}), apply
Borel-Serre duality + Arlettaz's Hurewicz control + Quillen-Lichtenbaum
at odd regular primes, and output either "K_12(Z) = 0" or "K_12(Z)
contains p-torsion for p ∈ S."

## What the paper leaves open

Per arXiv:1910.11598 (Dutour Sikirić-Elbaz-Vincent-Kupers-Martinet):

Shipped cell orbit counts in the public database:

| N  | dims shipped | counts                        |
|----|--------------|-------------------------------|
| 8  | 8–12         | 13, 106, 783, 6167, 50645     |
| 9  | 9–11         | 44, 759, 13437                |
| 10 | 10–11        | 283, 16062                    |
| 11 | 11 only      | 6674 (conjectural)            |

For K_12(Z) the missing groups are H_12(Vor_{GL_N}) at N ∈ {9, 10, 11}
— i.e. the **n=12 column** of the table. vcd(GL_N) = N(N-1)/2, so
cells in dimensions > 12 also exist in principle; the paper does not
enumerate past n=12 anywhere. For K_12 we only need the n=12 column.

## Why this isn't "just run noether"

The linear algebra is largely solved: `engine_rank_mod_p_sparse` +
Mersenne-cover + pwvla Z/p^n handle the sparse integer homology at
the ~10^5 scale we expect. The **research wall** is the combinatorial
cell enumeration at the missing (N, n) pairs — an LP-and-lattice
problem, not a matmul problem.

## Three-layer plan

### Layer A — Reproducibility (landable in 1–2 weeks)

Goal: recompute the paper's Σ_n(GL_8) = 0 result cell-by-cell from
the published database. This shakes out the full pipeline (parsing,
stabilizers, orientation, boundary, homology) before we extend.

Tasks:

1. Parser for the `DATA_pari/ListSHV_n{N}_rank{n}` files (GP list
   of integer matrices whose rows are minimum vectors).
2. `VoronoiCell` scitype with invariants (min-vector matrix, lattice
   rank N, cell dim n).
3. `noether.api.lattice.automorphism` via libpari FFI (new in
   noether; wraps `qfauto`). Returns generators of Aut.
4. `Stab(σ)` = automorphisms of the min-vector set, using 3.
5. Orientation character χ_σ : Stab(σ) → {±1} from the signed-
   permutation action on the rows of the min-vector matrix.
6. Tally driver: for each (N, n) in the corpus, count cells where
   χ_σ is identically +1. Expected: 0 for (N=8, n=8..12).
7. Also: build boundary maps ∂_n : C_n → C_{n-1}, feed to
   `noether.api.smooth_snf`, confirm H_k(Vor_{GL_8}) vanishes
   (mod S_2) for k ≤ 12. First real-corpus run of smooth_snf in
   the project.

Graduation: one command `voronoi reproduce --N 8` prints the
tally matching Prop 1215 / Thm 1371 of the paper.

### Layer B — Enumeration (the research wall; months of work)

Goal: fill in missing rows of the orbit table. Priority (N=9, n=12)
then (N=10, n=12) then (N=11, n=12).

Algorithm: Voronoi's neighbor algorithm. Start from known cells at
(N, n-1) (shipped in the database). For each cell σ at dim n-1,
enumerate facet-adjacent cells at dim n by LP-based facet
enumeration on the Voronoi cone. Canonicalize under GL_N(Z) action
(via LLL + qfisom). Dedupe against seen orbits.

Missing primitives (new in noether unless noted):

- `noether.api.convex.lp` — exact LP feasibility (wrap `cdd` /
  `GLPK` subprocess initially; native Rust later).
- `noether.api.lattice.isometry(G1, G2)` — via PARI `qfisom`.
- `noether.api.lattice.canonical_form(L)` — Plesken-Pohst canonical
  lattice form (LLL-reduced + qfisom into a canonical basis).
- Cell-enumeration driver lives in this repo under
  `src/voronoi/enumerate/`.

Graduation: independently reproduce the (N=8, n=12) count of 50645
orbits starting from (N=8, n=11) + a Voronoi seed. Only then start
(N=9, n=12).

### Layer C — Homology of extended complexes

Goal: for each newly enumerated (N, n), decide H_12 contribution.

Two paths per cell orbit:

1. **Orientation collapses.** If χ_σ hits −1 for every σ at dim n,
   contribution is 0 mod S_2. (Paper's N=8 argument.) Cheap.
2. **Orientation survives.** Build ∂_{n+1} and ∂_n, feed to
   smooth_snf prime sweep. Since we don't know a priori where
   torsion lives, sweep primes up to a Borel-style bound (for
   GL_N(Z), torsion is only at primes p with an element of order
   p in GL_N(Z), equivalently p ≤ some function of N; for N ≤ 12
   this is p ≤ 13 or so). Output: H_12 = Z^b ⊕ torsion structure.

## What graduates to noether

As we hit primitives that are general-purpose, they land in noether
rather than the voronoi repo:

| Primitive | Noether home | Status |
|---|---|---|
| `qfauto` via libpari FFI | `engine.pari.qfauto` + `api.lattice.automorphism` | new |
| `qfisom` via libpari FFI | `engine.pari.qfisom` + `api.lattice.isometry` | new |
| `qflll` via libpari FFI | `engine.pari.qflll` + `api.lattice.lll` | new |
| `qfminim` via libpari FFI | `engine.pari.qfminim` + `api.lattice.short_vectors` | new |
| Exact LP primitive | `api.convex.lp` | new |
| Canonical lattice form | `api.lattice.canonical_form` | new |
| LatticeZ^N scitype | `scitype.math.la.lattice` | extend existing |
| Chain-complex scitype | `scitype.math.at.chain` (generalized) | extend existing |
| Sparse Z-homology pipeline | `api.smooth_snf` | shipped |

## Open questions

1. **Gram matrix for Stab(σ).** For a cell σ with min-vector matrix
   M, naive ``G = M^T M`` does NOT have {±rows of M} as its shortest
   vectors, and ``Aut(G) ∩ SetStab(± M)`` is strictly smaller than
   the true Stab(σ) for lower-dim cells (empirically: some cells at
   (N=8, n=8) collapse to |Stab| = 2 = {±I} when they clearly have
   more symmetry from inspection). The actual perfect form ``Q_σ``
   for the cell's interior is what we need. Reconstructing Q_σ from
   M is an n(n+1)/2 − N(N+1)/2 underdetermined linear system in
   general; Plesken-Pohst's classical recipe uses a specific
   parameterization we haven't implemented yet. **Blocking Layer A
   orientation tally.**
2. Performance of `qfauto` on the 50645-orbit N=8 n=12 corpus — is
   PARI fast enough, or do we need a native Plesken-Pohst port?
3. Does the orientation-reversing argument extend to (N=9, n=12)?
   Unknown; tallied cell-by-cell once Layer B lands.
4. Start of the Voronoi seed for (N=9, n=12): which perfect forms
   are the natural starting points? (E_8, D_9 relatives, etc.)
5. Enumeration hardness scaling from (N=8, n=12) [50k orbits] to
   (N=9, n=12) [likely 10^5–10^6]. May need distributed.
6. **Orientation character convention.** The action of g ∈ Stab on
   σ's generators {v_i v_i^T} is by **unsigned** permutation
   (v_i v_i^T = (-v_i)(-v_i)^T), so χ_σ(g) = sign(π) where π is the
   induced permutation of min-vector pairs. Our `orientation.py`
   currently computes det of the *signed* permutation. Fix before
   re-running the tally.

## References

- Dutour Sikirić, Elbaz-Vincent, Kupers, Martinet. "Voronoi
  complexes in higher dimensions, cohomology of GL_N(Z) for N ≥ 8
  and the triviality of K_8(Z)." arXiv:1910.11598.
- Elbaz-Vincent, Gangl, Soulé. "Perfect forms, K-theory and the
  cohomology of modular groups." Adv. Math. 245 (2013).
  arXiv:1001.0789.
- Dutour Sikirić, Schürmann, Vallentin. "Classification of eight-
  dimensional perfect forms." ERA-AMS 13 (2007). arXiv:math/0609388.
- Public orbit database:
  https://github.com/elbazvip/Voronoi-complexes-database
- Older Elbaz-Vincent/Gangl/Soulé database (N < 8):
  https://pev.perso.math.cnrs.fr/Voronoi/Voronoi_complexes_database/
