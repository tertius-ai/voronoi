# Bibliography

Canonical references for the Voronoi complex / GL_N(Z) cohomology / K_*(Z)
program. PLAN.md cross-references these.

Citation keys here are used elsewhere in the repo (PLAN.md, code comments).

---

## [DSEKM19] Dutour Sikirić, Elbaz-Vincent, Kupers, Martinet

**"Voronoi complexes in higher dimensions, cohomology of GL_N(Z) for
N ≥ 8 and the triviality of K_8(Z)"**

- arXiv:1910.11598 (v1, 25 Oct 2019)
- J. Inst. Math. Jussieu 25 (2026), no. 1, 565–590.
  DOI: [10.1017/S1474748025101394](https://doi.org/10.1017/S1474748025101394)

The canonical paper for this project. The published `data/` orbit database is
its computational byproduct. Key conventions, lifted verbatim from the paper:

- **Cells.** Given v ∈ Z^N − {0}, write v̂(x) = (v|x)² ∈ C*_N. For a perfect
  form h, σ(h) = convex hull of m(h) inside X*_N. A face τ ⊂ σ(h) has
  m(τ) = {v ∈ m(h) : v̂ ∈ τ}.
- **Action.** Γ = SL_N(Z) or GL_N(Z) acts on the right by h·γ = γᵀ h γ.
- **Orientation of σ** = an orientation of the real vector space
  R(σ) ⊂ Sym²(R^N) of symmetric matrices spanned by {v̂ : v ∈ m(σ)}. [§1.2.1]
- **Σ⋆_n / Σ_n.** Σ⋆_n = Γ-orbit representatives of n-cells meeting X_N;
  Σ_n ⊂ Σ⋆_n = those σ for which **every** g ∈ Γ_σ preserves orientation of R(σ).
- **Differential** d_n(σ) = Σ_τ [σ:τ] τ with [σ:τ] = Σ_{τ'} η(τ,τ')·ε(τ',σ),
  η compatible-orientation sign, ε face-extension sign.
- **Borel–Serre / Steinberg.** Modulo S_{N+1},
  H_{m−N+1}(Γ; St_N) ≅ H_m(Vor_Γ).  [Prop. 1.5]

For (N=8, n=8…12) they show Σ_n = ∅ for all relevant n, hence H_*(Vor_{GL_8})
vanishes mod S_2 in this range — the input that drives K_8(Z) = 0.

Other useful pieces:

- §2 — Watson index theory + minimal classes; the small-cell enumeration
  technique for s = n (kissing number = lattice rank).
- §3 — Linear-programming-based realizability test for vector families,
  the engine for cell enumeration at N ≥ 9. The dual-feasibility heuristic
  is the practical algorithm we'd reimplement in `noether.api.convex.lp`.
- §4 — Partial Voronoi data for 8 ≤ N ≤ 12, including the (N=8, n=12) =
  50645 conjectural-but-now-shipped count.

**Direct relevance to OQ6.** §1.2.1 is the canonical definition of the
orientation character. Since g acts on basis {v̂ : v ∈ m(σ)} of R(σ) by an
*unsigned* permutation π of pairs {±v} (because v̂ = (−v)̂), the induced sign
on R(σ) is exactly sign(π). The εⱼ factor in our `orientation.py` is wrong
under this convention.

**Direct relevance to OQ1.** The paper does not spell out a Gram-matrix-for-σ
recipe; it works in lattice-language (Watson index theory) for low-perfection
classes and uses LP for higher ones. It does *not* compute Stab(σ) by running
qfauto on M^T M for non-perfect cells.

---

## [Kup19] Kupers

**"A short proof that K_8(Z) ≅ 0"**

- Note dated 21 Oct 2019, on Kupers' website.
  [PDF](https://www.utsc.utoronto.ca/people/kupers/wp-content/uploads/sites/50/2021/01/k8zshorter.pdf)
- Independent re-derivation (found in 2017) of the K_8(Z) = 0 result.

Does **not** depend on the (N=8, n=8…12) Voronoi enumeration of [DSEKM19].
Strategy:

1. Reduce to K_8(Z) ⊗ Z[1/7!] via [Wei13, VI.10]: K_4i(Z) is f.g. torsion at
   irregular primes ℓ > 10⁸.
2. Quillen exact couple gives a spectral sequence
   E¹_{p,q} = H_q(GL_p(Z); St_p) ⇒ H_{p+q}(BQ; Z) where BQ ≃ Ω^{∞-1} K(Z).
3. Need to determine the diagonal p+q = 9 of E¹ ⊗ Z[1/7!] vanishes.
   - Cells p ≤ 4: [LS78] Lee-Szczarba H_*(GL_p(Z); St_p).
   - Cells p ∈ {5,6,7}: [EVGS13] Theorem 4.3.
   - Top two rows for p > 7: H_0(GL_p; St_p) = 0 ([LS76] Thm 1.3),
     H_1(GL_p; St_p ⊗ Z[1/p!]) = 0 ([CP17] Theorem A, Z[1/p!] extension
     proven in §2 of this note).
4. K_8(Z) ⊗ Z[1/7!] = 0 follows by a standard Postnikov-tower / Hurewicz
   argument on the homotopy fiber of S ∨ Σ⁵S → K(Z).

**Crucial Remark 2.6 (verbatim):**

> If Conjecture 2 of [CFP14] were true with coefficients in Z[1/(n+1)!]
> instead of Q, it could be used to prove that K_12(Z) ≅ 0 in a similar
> manner.

This would be a direct path to K_12(Z) = 0 that bypasses the (N=9,10,11; n=12)
Voronoi enumeration entirely — but the conjecture is still open (see [CFP14]
below) and there is no obvious route to it. Layer B remains the actionable
plan.

---

## [CFP14] Church, Farb, Putman

**"A stability conjecture for the unstable cohomology of SL_n Z, mapping
class groups, and Aut(F_n)"**

- arXiv:1208.3216 (v3, 23 Nov 2013)
- Algebraic topology: applications and new directions, Contemp. Math. 620,
  AMS 2014, pp. 55–70.

The source of "Conjecture 2" cited in Kupers' Remark 2.6. Verbatim:

> **Conjecture 1 (Stable instability).** For each i ≥ 0 the group
> H^{(n choose 2) − i}(SL_n Z; Q) does not depend on n for n > i + 1.
>
> **Conjecture 2 (Vanishing Conjecture).** H^{(n choose 2) − i}(SL_n Z; Q) = 0
> for all i < n − 1.

Conjecture 2 says the unstable rational cohomology vanishes in a
codimension-(n−1) range below the virtual cohomological dimension
vcd(SL_n Z) = (n choose 2). Status:

- i = 0: theorem of Lee–Szczarba [LS] (= [LS78] above).
- i = 1: proven in [CP17] (Church–Putman, "The codimension-one cohomology
  of SL_n Z").
- i ≥ 2: **open**, with no obvious route. Computational evidence
  through SL_7 Z (Table 1 of [CFP14]) is consistent.

For Kupers' K_12(Z) ≅ 0 strategy via Remark 2.6 we'd need an integral
(Z[1/(n+1)!]-coefficient) version *and* the i = 2 case — neither is
available. Layer B (direct enumeration of (N, n=12) cells for N = 9, 10, 11)
remains the actionable plan.

§5–§7 also contain analogous conjectures for mapping class groups Mod_g
and Aut(F_n) — out of scope for Samurai 1, but illustrate the broader
stability picture.

---

## [Bro23] Brown

**"Bordifications of the moduli spaces of tropical curves and abelian
varieties, and unstable cohomology of GL_g(ℤ) and SL_g(ℤ)"**

- arXiv:2309.12753 (v1, 22 Sep 2023; latest revision Feb 2025)

Constructs bordifications of moduli spaces of tropical curves and tropical
abelian varieties, extends the tropical Torelli map to those
compactifications, and uses bi-invariant differential forms (canonical
classes for symmetric spaces) to produce **infinitely many new non-zero
unstable cohomology classes** in GL_g(ℤ) and SL_g(ℤ). Also gives a new
geometric proof of Borel's stable-range theorem and equips part of
H*(GL_g(ℤ); ℚ) with a motivic structure.

**Relevance to this project — limited.** The classes Brown constructs
are *non-vanishing* unstable classes; our path to K_12(ℤ) needs
*vanishing* information about H_*(Vor_{GL_N}) ≅ H_{*-N+1}(GL_N(ℤ); St_N)
in low degrees, and Brown's classes live elsewhere (the cohomological
ranges differ from where Kupers' spectral sequence in [Kup19] needs
input). The paper does *not* give an alternate route to K_12(ℤ), nor does
it weaken [CFP14] Conjecture 2 in our codimension. Worth tracking in case
later refinements interact with the Voronoi/Borel–Serre dictionary.

---

## [EVGS13] Elbaz-Vincent, Gangl, Soulé

**"Perfect forms, K-theory and the cohomology of modular groups"**

- arXiv:1001.0789 (v1, 5 Jan 2010)
- Adv. Math. 245 (2013), 587–624.
  DOI: [10.1016/j.aim.2013.06.014](https://doi.org/10.1016/j.aim.2013.06.014)

Long-form predecessor of [DSEKM19]; sets every convention DSEKM follows
verbatim. §3 defines the Voronoi complex Vor_Γ with the same orientation
character as DSEKM (R(σ) span of v̂'s). Theorem 4.3 gives the homology
H_*(Vor_Γ) for Γ = SL_N(Z), GL_N(Z) with N = 5, 6, 7 — these are the
columns p ∈ {5,6,7} that Kupers' spectral sequence consumes directly.

Useful artefacts:

- §4 + Figures 1–2 + Tables 1–5: full Σ_n / Σ⋆_n cardinalities and SNF
  invariants of d_n for N = 5, 6, 7.
- §4.5: mass formula from virtual Euler characteristic of SL_N(Z) — a
  cross-check we can apply to our reproductions.
- §6: splitting Vor_{GL_N} from Vor_{GL_{N+1}} for small N — a hint at
  reduction we may exploit when going to N ≥ 9.

**Relevance to OQ6.** Same orientation convention as [DSEKM19]; reading both
together makes the convention authoritative.

---

## [EVGS02] Elbaz-Vincent, Gangl, Soulé

**"Quelques calculs de la cohomologie de GL_N(Z) et de la K-théorie de Z"**

- arXiv:math/0207067 (v1, 6 Jul 2002)
- C. R. Math. Acad. Sci. Paris 335 (2002), no. 4, 321–324.

Short CRAS announcement of the EVGS13 program. Same orientation /
Voronoi-complex setup; main results announced: K_5(Z) = Z, K_6(Z) has
only 3-torsion. For full proofs use [EVGS13]. Useful mostly as historical
context — establishes the project in 2002, first computer assist for
N = 5, 6.

---

## [DEGU07] Dumas, Elbaz-Vincent, Giorgi, Urbańska

**"Parallel computation of the rank of large sparse matrices from algebraic K-theory"**

- arXiv:0704.2351 (v2, 24 Apr 2007)
- PASCO '07: Proceedings of the 2007 International Workshop on Parallel
  Symbolic Computation, ACM, pp. 43–52.
  DOI: [10.1145/1278177.1278186](https://doi.org/10.1145/1278177.1278186)

The infrastructure paper for large-scale Voronoi homology. For GL_7(Z) they
enumerate Σ_n / Σ⋆_n through n = 27 (Figure 2):

| N=7 | total cells Σ⋆ | orientation-preserving Σ |
|-----|---------------:|-------------------------:|
| n = 21 | 876,385 | 822,922 |
| n = 22 | 374,826 | 349,443 |
| total all n | 10,722,899 | 9,798,279 |

Differential matrices have 8M–37M nonzeros; the largest rank computation
took 35 days on 50 processors. Algorithmic backbone:

- **Coppersmith block Wiedemann** for rank: parallelize the block matrix
  sequence {X^T A^i Y} over the s vectors of Y.
- **SNF prime sweep** for torsion: ranks mod p for a battery of small primes,
  reconstructed into the Smith form via [DSV01] / Storjohann-style algorithms.

This is the **inspirational reference** for our `noether.api.smooth_snf`
prime-sweep architecture; the parallelism strategy maps directly onto
our Slurm / Modal / TCP-coordinator dispatch.

The companion "Sparse Integer Matrix Collection" they reference
(`ljk.imag.fr/membres/Jean-Guillaume.Dumas/simc.html`) is the canonical
benchmark suite for sparse SNF — useful as cross-validation corpus once
our pipeline lands.

---

## [PS97] Plesken, Souvignier (referenced for context)

**"Computing isometries of lattices"**

- J. Symbolic Comput. 24 (1997), no. 3-4, 327–334.
  DOI: [10.1006/jsco.1996.0130](https://doi.org/10.1006/jsco.1996.0130)

Algorithmic foundation for PARI's `qfauto` / `qfisom`, which our engine wraps
via `engine_qfauto` / `engine_qfauto_with_shv`. Plesken–Pohst-style
backtracking on partial isometries, pruned by short-vector / scalar-product
invariants. Handled the Leech lattice (dim 24) in < 30 min on a 1996
workstation. With an optional vector list, the algorithm constrains the
search to isometries permuting that set; this is the SHV variant we use
for set-stabilizer queries.

**Relevance to OQ1.** The algorithm assumes the input vectors are vectors of
a specific norm class — typically the minimum vectors of the form. Behavior
when the input is *not* the full minimum-vector set of the Gram form is
implementation-defined. This is the algorithmic root of OQ1: for
non-perfect cells σ, M^T M has additional shortest vectors beyond ±M, and
qfauto-with-shv may not return the Voronoi-cell stabilizer Stab(σ) we want.

---

## Cross-references (cited above, not summarized here)

- [LS76] Lee, Szczarba. *On the homology and cohomology of congruence
  subgroups.* Invent. Math. 33 (1976), 15–53.
- [LS78] Lee, Szczarba. *On the torsion in K_4(Z) and K_5(Z).*
  Duke Math. J. 45 (1978), 101–129.
- [CP17] Church, Putman. *The codimension-one cohomology of SL_n Z.*
  Geom. Topol. 21 (2017), 999–1032. arXiv:1507.06306.
- [Wei13] Weibel. *The K-book.* AMS Graduate Studies in Mathematics 145.
- [Rog00] Rognes. *K_4(Z) is the trivial group.* Topology 39 (2000), 267–281.
- [DSV01] Dumas, Saunders, Villard. *On efficient sparse integer matrix
  Smith normal form computations.* J. Symbolic Comput. 32 (2001), 71–99.
