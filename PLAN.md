# Research plan

## Objective

Determine the degree-12 Voronoi homology needed in the $K_{12}(\mathbb Z)$
program. The notation throughout the code is:

- $N$: ambient lattice rank;
- $r$: cone dimension, the rank of the forms $vv^t$;
- $p=r-1$: projective cell dimension, the cellular chain degree;
- $s$: number of primitive lines modulo sign.

The degree-12 target configurations have $r=13$ and $N\in\{9,10,11\}$.
The Steinberg degrees $p-N+1=r-N$ are $4,3,2$, respectively. The
[grading audit](docs/mathematical-grading.md) records a source-indexing
inconsistency and the external inputs that must be reconciled before claiming
that these three computations suffice. The final theorem must state the
localization and torsion hypotheses used to pass to K-theory.

## Established implementation

The Noether 0.3.2 integration, exact line configurations, Watson base
reconstruction, minimum realization, equivalence, and orientation regressions
are implemented. The census engine supports incidence transports, pair
orbits, disk-backed candidate reduction, and transactional completion shards.
These are the former M0–M3 foundations and the implemented portion of M4.

The historical lower-000 computation at $(N,r)=(8,10)$ reached terminal
coverage of its 924,637 candidate orbits. Its summary and provenance are in
[`validation/historical-n8-r10.json`](validation/historical-n8-r10.json).
It used an older frozen Noether runtime. It does not establish global census
coverage. Its saved verdict and orbit evidence has now been replayed under
0.3.2; independently regenerating its earlier coface-pair input remains open.

The [2026-10-28 audit](validation/n8-r10-positive-audit-2026-10-28.json)
checked all 64 ledger metadata/index partitions, the original orbit-file byte
digest, and positive parentage. All 453 positive shells now have independently
replayed Noether 0.3.2 Gram witnesses and exact transports to 453 distinct
published cone-rank-10 orbits. The other 330 published orbits were not covered
by this lower-cell result. The audit did not replay the 924,184 historical
negative certificates or the historical orbit-reduction transports.

The subsequent [orbit audit](validation/n8-r10-orbit-audit-2026-10-28.json)
regenerated the keyed artifact byte for byte from all 2,007,344 embedded
candidates. Native replay checked all 1,082,707 transports, exact coverage and
provenance, and all 924,637 representative fingerprints. This verifies the
reduction relative to the historical candidate artifact; the earlier coface-pair
enumeration has not been independently regenerated here.

A stratified 64-case negative regeneration check produced 64 fresh verified
negative certificates. It is not validation of the entire negative population.
Saved-certificate decoding, constraint reconstruction, and proof checks belong
in Voronoi, composed from public Noether exact operations. See
[the replay boundary](docs/computations.md#historical-negative-evidence-under-noether-032).

The [full ledger replay](validation/n8-r10-ledger-replay-2026-10-28.json)
subsequently checked all 924,184 saved negative proofs and re-enumerated all
453 positive Gram witnesses. Every verdict was bound to its original orbit
index and configuration. Four streamed partitions and independently checked
receipts cover all 924,637 representatives. No Noether extension was needed.

## Next: finish the rank-eight census (M4)

1. Independently audit or regenerate the earlier coface-pair enumeration and
   its coverage relative to the named input catalogs. Saved minimum verdicts
   and orbit transports now have fully checked reuse paths under 0.3.2.
2. Complete the incidence and completion stages across every lower cell.
3. Merge realized configurations by exact integral equivalence, retaining
   coordinate transports and parentage.
4. Independently vary sharding and compare coverage and mathematical results.
5. Reconstruct the published staircase with a coverage certificate for each
   layer, rather than accepting agreement of counts alone.

| Cone dimension $r$ | Published $N=8$ orbit count |
|---:|---:|
| 8 | 13 |
| 9 | 106 |
| 10 | 783 |
| 11 | 6,167 |
| 12 | 50,645 |

These are the reference counts from [DSEKM19, Tables 3–4](https://arxiv.org/html/1910.11598).
The parsed database and a new census have different provenance.

## Degree-12 targets (M5–M6)

- **$N=10,r=12$:** useful simplicial intermediate layer, of projective degree 11.
  Establish exhaustive gluing and verify the orbit and orientation lists.
- **$N=9,10,r=13$:** handle non-simplicial cells and prove seed coverage.
  Fixed-rank completion of a given seed is unique when it exists; that fact
  does not prove that the census visits a seed in every target cell.
- **$N=11$:** first make the $r=11$ base unconditional. The published 6,674
  configurations were obtained through index 45; their completeness was not
  proved. Establish and exhaust a finite bound, or supply an equivalent
  classification proof, before claiming an unconditional $r=13$ result.

The simplicial ranges and the bounded rank-eleven base are discussed in
[DSEKM19, §§3.2–3.3](https://arxiv.org/html/1910.11598).

## Boundary, homology, and theorem assembly (M7–M8)

If orientation kills every relevant cell, record that evidence explicitly.
Otherwise construct the adjacent incidence layers, transport and boundary
signs, verify $d^2=0$, and compute the surviving homology using Noether's
checked exact linear algebra. Boundary and homology assembly are future work;
there are no placeholder APIs promising these computations.
Degree 12 uses cone ranks 12, 13, and 14 for its outgoing and incoming
boundaries, unless vanishing of the oriented degree-12 chain group suffices.

The final output must include the orbit database, realization and equivalence
witnesses, stabilizer and orientation evidence, complete run coverage, any
boundary/homology evidence, and a theorem report separating unconditional,
conditional, and incomplete conclusions.

## Enumeration and evidence contract

Production enumeration glues known lower-dimensional configurations through
finite incidence and pair orbits. It retains embeddings and coordinate
transports, realizes the target configurations, and resolves orbit collisions
with exact unimodular witnesses. The diagnostic radius experiment is not a
replacement for a completeness argument.

- Distinguish $N$, $r$, and $s$ in data and proofs.
- Capped enumeration must report incomplete coverage unless exhaustion is proved.
- Work limits and timeouts never become mathematical negatives.
- Fingerprints partition candidates; exact witnesses establish equivalence.
- Every accepted realization or negative needs replayable exact evidence.
- Relative completeness is always relative to named input catalogs.
- Global completeness requires every incidence, completion subproblem, and shard
  to have terminal coverage, together with a proof that the inputs are exhaustive.

Per-cell records retain canonical lines, an exact Gram witness and minimum
shell, equivalence transports, stabilizers, parent incidences, and orientation
evidence. Run records retain immutable input hashes, software versions,
explicit seeds where relevant, shard parameters, terminal counts, and output
hashes. See [the computation guide](docs/computations.md) for the implemented
artifact boundaries and [CONTRIBUTING.md](CONTRIBUTING.md) for ownership.
