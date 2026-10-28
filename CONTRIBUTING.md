# Contributing

This is a research codebase. Contributions should make a mathematical result,
its coverage, or its independent verification easier to assess. Start with
[the setup instructions](README.md#build) and [the current plan](PLAN.md).

## Ownership

Noether 0.3.2 owns reusable exact mathematics in its public Rust facade and
typed Python domains. Changes to lattice enumeration, minimum realization,
linear algebra, group algorithms, or certificate verification belong there.
Do not introduce a second mathematical implementation in Voronoi's Python code.

Voronoi owns cell interpretation, published labels, Watson and incidence
playbooks, exact orbit gluing, orientation, coverage manifests, storage, and
research-specific compiled loops. The Python application and Rust worker must
use the same Noether release. Avoid `noether.api` and private Noether imports.

## Evidence and tests

Use a small hand-checkable example when developing an algorithm. Keep the
triggering example when fixing a correctness issue, and include a nearby case
that distinguishes the fix from the same incorrect shortcut.

Before submitting a change, run the checks relevant to it:

```bash
make doctor
make test-fast
make lint
make test-rust
```

Use `scripts/fetch_database.sh` and `make test-corpus` for changes affecting
mathematics or census coverage. The full suite includes the published parser,
Watson, realization, orientation, and rank-eight incidence regressions. Record
skips honestly. Changing documentation does not require rerunning computations.

A pull request should state the problem, the resulting behavior, the
mathematical assumptions, and the checks performed. Distinguish an exact
certificate from a hash, a heuristic filter, a work-limited checkpoint, and a
coverage proof. Budget exhaustion never certifies nonexistence.

## Reference data and research outputs

`validation/reference-database.json` records the upstream revision and SHA-256
hashes used by the corpus tests. The fetch script preserves local modifications
and never advances to an unrecorded upstream revision. To update the corpus,
review the new revision and counts, update the lock and tests together, and
record the validation performed. Retain the upstream license with its data.

Keep generated databases, binaries, run logs, runtime snapshots, and SQLite
ledgers in the ignored `data/`, `target/`, and `artifacts/` directories.
`validation/` contains small expectations and dated records suitable for review.
A published result needs its own accessible evidence bundle and provenance;
a local path in a summary does not make that evidence available to collaborators.

Historical research artifacts should remain intact. New Noether 0.3.2 runs use
a separate workspace. Any reuse of historical mathematical evidence must be
explicitly verified and retain its original provenance.

## Documentation

Keep the README focused on current capabilities and getting started. Put
computation procedures in `docs/computations.md`, remaining mathematical work
in `PLAN.md`, references in `BIBLIOGRAPHY.md`, and dated validation in
`validation/`. Development diaries and superseded implementation notes belong
outside the public source tree. Describe unfinished mathematics as research
work rather than adding functions or commands that only raise an error.
