# Exact replay of minimum-shell obstructions

Voronoi owns the historical wire adapter, constraint conventions, and proof
interpretation below. All arithmetic, matrix products, and rational row
reduction use Noether's public Rust facade. Replay does not invoke the
minimum-realization solver or construct Noether's opaque certificate objects.

## Claim and admissible input

Let $S$ be the stored canonical primitive lines in $\mathbb Z^N$, represented
once modulo sign. The claim being refuted is existence of a positive-definite
Gram matrix whose complete minimum shell is exactly $\pm S$. This is an
**exact-shell** obstruction; it does not rule out a larger minimum shell
containing $S$.

An obstacle is any nonzero integer vector outside $\pm S$. Nonprimitive
obstacles such as $2v$ are allowed. Repeated obstacles retain their positions
and multipliers. Zero vectors and either sign of a source minimum are rejected:
allowing a source minimum as an obstacle could falsely imply a nonpositive
outsider margin even for the identity Gram matrix.

The adapter checks the wire type identities, tuple shapes, vector dimensions,
source canonicalization and spanning, integer/rational parsing, content-based
candidate identity, and original evidence digest. During ledger replay, the
source configuration must also equal the representative at that exact index
in the hashed orbit artifact.

## Quadratic coordinates

Write $g=(G_{ij})_{i\leq j}$. The row $q(v)$ has diagonal coefficients $v_i^2$
and off-diagonal coefficients $2v_iv_j$, so $q(v)g=v^tGv$.
Let $E$ have the rows $q(v)$ for $v\in S$.
Scaling a proposed minimum to one gives $Eg=\mathbf1$.

Noether computes the rational reduced row-echelon form of
$[E\mid\mathbf1]$. The adapter extracts the historical affine coordinates
$g=g_0+Dy$: free columns are ordered increasingly, and the free coordinates of
$g_0$ are zero. It implements no separate elimination algorithm.

For obstacle $w_i$, a positive outsider margin requires

$$-q(w_i)Dy+\delta\leq q(w_i)g_0-1.$$

These inequalities form $Ax\leq b$ for $x=(y,\delta)$, with objective
$c^tx=\delta$. They are necessary conditions for the claimed complete shell;
positive definiteness need not be tested to establish an obstruction.

## Four stored proof kinds

1. **`inconsistent_equal_norms`:** signed rational weights $u$ must satisfy
   $E^tu=0$ and $\mathbf1^tu\ne0$. Multiplying $Eg=\mathbf1$ by $u^t$ then
   gives a contradiction. These weights need not be nonnegative.

2. **`nonpositive_outsider_margin`:** require $u\geq0$, $A^tu=c$, and
   $b^tu\leq0$. Every feasible point then has $\delta\leq0$, contradicting
   the strictly positive margin of an exact minimum shell.

3. **`farkas_infeasible`:** require $u\geq0$, $A^tu=0$, and $b^tu<0$.
   Their weighted sum would give $0<0$. For the current affine-margin
   encoding with consistent norm equations, a sufficiently negative free
   margin always makes the finite system feasible, so such a certificate
   cannot be valid. The checker still checks the stored kind's strict dual
   conditions and rejects false claims.

4. **`homogeneous_minimum_at_least_one`:** the legacy variables are $(g,\lambda)$.
   Each source equality $q(v)g=\lambda$ contributes both weak inequalities;
   obstacles contribute $-q(w_i)g\leq-1$, and one final row imposes
   $-\lambda\leq0$. With objective $c^tx=-\lambda$, require
   $u\geq0$, $A^tu=c$, and $b^tu\leq-1$. This forces $\lambda\geq1$.
   An exact shell could instead be scaled so that its finitely many outside
   obstacles have length at least one while $0<\lambda<1$, a contradiction.

## Historical row scaling

Two outsider-row encodings are supported: the unscaled inequalities above,
and the convention dividing a row and its right-hand side by their maximum
absolute entry when that entry exceeds $10^6$. The divisor is positive, so
both encodings describe the same necessary conditions. A proof is accepted
only if its full exact dual identity, signs, and bound check in a supported
encoding. The selected encoding is retained in the replay receipt.

## Complete ledger binding

The replay driver opens the old SQLite databases read-only and checks their
metadata against the named pair/orbit reports. It merges rows in candidate
index order and streams them into bounded native workers. Each worker checks
its exact index partition against the original orbit stream, verifies every
negative proof, and re-enumerates every positive Gram witness it encounters.
It also hashes the complete orbit input and the streamed ledger data.

Receipts are published only after proof checks, input digests, terminal counts,
and complete partition coverage agree. Missing, repeated, nonterminal, or
misbound rows and process failures produce no successful replay report.
The resulting coverage is relative to the historical candidate-orbit input;
earlier coface-pair generation and global census completeness are separate.
