# Repository guidance

Read `README.md` for setup, `CONTRIBUTING.md` for the evidence contract, and
`PLAN.md` for remaining research. The repository targets Noether 0.3.2 from
the sibling `../noether` checkout in both languages.

- Reusable mathematics belongs in Noether's public Rust facade and typed
  Python domains. Voronoi owns research-specific enumeration and accounting.
- Keep ambient rank `N`, perfection rank `r`, and ray count `s` distinct.
- Native exact evidence is required for accepted mathematical verdicts.
  Timeouts, heuristic filters, and work limits never certify nonexistence.
- Retain exact transports, witnesses, and relative coverage. Matching an orbit
  count alone does not prove an exhaustive census.
- Preserve historical `artifacts/` and SQLite ledgers. Use a separate workspace
  for current runs; retain original provenance when reusing evidence.
- Keep generated output in ignored directories. Retain small reference locks,
  expectations, and dated validation in `validation/`.
- Do not add placeholder APIs or CLI commands for unfinished mathematics.
- Use `make doctor`, scoped tests, and `make lint`. Use `make test-rust` and
  `make test-corpus` when a change affects mathematics or census coverage.
  A skipped required corpus check is unverified.

Noether's own `AGENTS.md` applies when changing that sibling repository.
