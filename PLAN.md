# Research plan

## Objective

Determine the degree-12 Voronoi homology needed in the $K_{12}(\mathbb Z)$
program. The notation throughout the code is:

- $N$: ambient lattice rank;
- $r$: cone dimension, the rank of the forms $vv^t$;
- $s$: number of primitive lines modulo sign.

The target configurations have $r=12$ and $N\in\{9,10,11\}$. The expected
Steinberg degrees are $4,3,2$, respectively. The final theorem must state the
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
coverage, and its evidence has not been fully replayed under 0.3.2.

## Next: finish the rank-eight census (M4)

1. Audit the recovered historical artifacts and define how verified evidence
   will be reused with the current engine.
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

- **$N=10,r=12$:** first new simplicial target. Establish exhaustive gluing and
  verify the resulting orbit and orientation lists.
- **$N=9,r=12$:** account for non-simplicial completions. A single witness is
  insufficient when several target configurations can complete a seed.
- **$N=11$:** first make the $r=11$ base unconditional. The published 6,674
  configurations were obtained through index 45; their completeness was not
  proved. Establish and exhaust a finite bound, or supply an equivalent
  classification proof, before claiming an unconditional $r=12$ result.

The simplicial ranges and the bounded rank-eleven base are discussed in
[DSEKM19, §§3.2–3.3](https://arxiv.org/html/1910.11598).

## Boundary, homology, and theorem assembly (M7–M8)

If orientation kills every relevant cell, record that evidence explicitly.
Otherwise construct the adjacent incidence layers, transport and boundary
signs, verify $d^2=0$, and compute the surviving homology using Noether's
checked exact linear algebra. Boundary and homology assembly are future work;
there are no placeholder APIs promising these computations.

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
