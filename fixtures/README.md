# Fixtures

The expected results and inputs that specify this program. They were generated
from the Python product that this program replaced, at the git tag
`python-oracle`, and are never regenerated: a change to a fixture is a change
of specification. All data is fictional.

- `numbers/`: number results of the Python product (sums, statistics,
  percentiles, random choices, SQLite reals, number spelling, annual CAGR,
  selection order, thresholds, built-in PEG, legacy ranking, JSON as Python
  reads it); read by the tests of the `numbers` and `engine` crates and by the
  `market-data` tests and unit tests of built-in values, ranking and raw JSON.
- `formulas/`: formula texts with their canonical form, tree, unit and errors;
  read by `crates/engine/tests/formulas.rs`.
- `fictional/raw/`: a raw provider cache for the US, Hong Kong and Tokyo; read
  by the `bt`, `engine` and `market-data` tests and by the website's browser
  checks.
- `fictional/cases/`: strategy files with the schedule of each run
  (`run.json`); read by `l3.rs`, `cross_section.rs`, `results.rs` and
  `views.rs` of `bt`, the `engine` strategy test and the website's tests.
- `fictional/expected/`: the expected prepared tables of each market
  (`us`, `hk`, `jp`, read by `prepared.rs`; `hk/candidates.jsonl` also by
  `views.rs`) and the expected tables of the runs of `cases/` (`runs`, read by
  `l3.rs` and, for `formula_values`, `cross_section.rs`).
- `fictional/update/`: cases of the data update (raw files before and after,
  the provider's replies, the requests made and the end record); read by
  `crates/bt/tests/update.rs`.
