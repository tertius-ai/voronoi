# Grading and theorem audit

This audit fixes the convention used by the implementation. It does not
establish the reduction from the remaining computations to a theorem about
$K_{12}(\mathbb Z)$.

## Cone rank and cellular degree

For primitive lines represented by $v_i\in\mathbb Z^N$, put
$W=\operatorname{span}_{\mathbb R}\{v_iv_i^t\}$ and $r=\dim W$.
The generated cone has dimension $r$. The trace is strictly positive on
every nonzero point of this cone. Its trace-one slice therefore represents
the quotient by positive scaling and has affine dimension $p=r-1$.
This argument does not assume that the number $s$ of rays equals $r$.

`VoronoiCell.cone_dimension` and the legacy `dim` alias return $r$.
`projective_dimension` returns $p$. Published `ListSHV_nN_rankr` filenames,
census `target_dimension` fields, artifact identities, and existing paths
retain the cone-rank convention. No historical artifact is relabeled.

The projective cell definition in DSEKM19 §1.2.1 and its Steinberg comparison
in §1.2.3, equation (4), give

$$H_p(\operatorname{Vor}_{GL_N})
  \cong H_{p-N+1}(GL_N(\mathbb Z);\operatorname{St}_N)$$

modulo the Serre class of finite groups supported at primes at most $N+1$.
Thus the Steinberg degree is $r-N$, not $r-N+1$.

| Ambient rank $N$ | Projective degree $p$ | Cone rank $r$ | Steinberg degree |
|---:|---:|---:|---:|
| 9 | 12 | 13 | 4 |
| 10 | 12 | 13 | 3 |
| 11 | 12 | 13 | 2 |

If the oriented degree-12 chain group vanishes, its homology vanishes.
Otherwise degree-12 homology requires the boundary maps involving cone ranks
12, 13, and 14. Cone rank 12 alone is not the degree-12 target.

## Published labels require reconciliation

The [author-hosted DSEKM paper](https://jamartin.perso.math.cnrs.fr/Publications/DEKM.pdf)
defines projective cells on page 4 and states the degree shift on page 5.
Its Table 3 lists the rank-eight counts 13, 106, 783, 6,167, and 50,645 in
cone ranks 8 through 12, as do the database filenames and our exact rank
checks. Table 4 on page 15 labels these same counts by cellular indices 8
through 12. Under the projective definition they belong to degrees 7
through 11. These labels are not reconciled here.

Theorem 4.5 states a rank-eight vanishing range through degree 12, while
Remark 6.6 identifies $H_{12}(\operatorname{Vor}_{GL_N})$ for $N=9,10,11$
as the remaining computations for $K_{12}$. We may cite the theorem as an
external input, but the supplied cone-rank-8-through-12 files alone do not
reproduce its degree-12 endpoint. Before theorem assembly, resolve this
indexing issue and audit all lower-rank and spectral-sequence inputs. If an
independent rank-eight degree-12 verification is needed, it requires cone
rank 13 as well.

The source is also available as [arXiv:1910.11598](https://arxiv.org/html/1910.11598).
The repo's reference counts are expectations relative to the locked database,
not independent completeness proofs or a reproduction of every cited theorem.

## Fixed-rank completion and coverage

Normalize the required minimum of a seed to one. The equalities
$\langle G,v_iv_i^t\rangle=1$ determine $G|_W$ uniquely whenever they are
consistent. A completion with the same perfection rank still spans $W$.
Consequently every integral line $z$ with $zz^t\in W$ has a forced length;
all such lines of length one must occur in any complete minimum shell.
Lines outside $W$ would raise the perfection rank. Hence a fixed-rank
completion, when it exists, is unique, even for a non-simplicial shell.

Noether's checked completion supplies the shell and its evidence. This
uniqueness does not prove global coverage: the gluing procedure must still
be shown to encounter a seed in every target orbit. The simplicial range
$r\leq N+2$ covers the $N=10,r=12$ intermediate layer and the $N=11,r=13$
target. It does not cover the $N=9,10,r=13$ targets. The bounded published
$N=11,r=11$ base also remains a separate completeness issue.

## K-theory proof obligations

The three rows above lie on total degree 13 of the Quillen rank spectral
sequence, since $K_{12}(\mathbb Z)=\pi_{13}(BQ)$. Turning cell information
into a K-theory result additionally requires the relevant differentials,
lower-rank terms, localization, Hurewicz comparison, and small-prime inputs.
A common localization for the three Steinberg comparisons inverts primes
2, 3, 5, 7, and 11; this does not by itself dispose of those primary parts
of integral K-theory.

Do not replace these obligations with a claim that $H_{13}(BQ;\mathbb Q)$
vanishes: it has a decomposable contribution from the degree-one class and
the square of the degree-six class. The final argument must handle that
contribution and torsion explicitly. No completed theorem report is claimed.
