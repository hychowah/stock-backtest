# Experiment summaries

These summaries are separate from the canonical `results/summary-exits.txt`.
Each one keeps its original settings. Old timings are historical measurements,
not current-source speed guarantees. Raw logs, holdings and benchmark output
stay in ignored `tmp/` under the [records policy](../../docs/records-policy.md).
The source has no benchmark harness or engine comparison runner.

## Original engine speed work

The backtest experiments below use the original candidate pool, current
EV/EBITDA, default top-50 filters and seed `20261022`, from 1996-01-01 to
2026-10-20. Every variant starts with no dated books and runs the same sampled
dates. Benchmark-only cache cloning and report generation are excluded. The OS
page cache is not flushed. All runs matched every selected holding, value,
status and trial outcome exactly.

- `backtest-benchmark-summary.json`: 100 trials on native Windows. The eager
  reference took 467.0 seconds. Requested-pool preparation took 132.1 seconds
  (3.5× faster). A combined in-memory prototype took 105.9 seconds, including
  loading. Requested-pool preparation was faster at the default 24 trials.
- Applied requested-pool engine: all 100 trials in 133.1 seconds.
- Upfront planning with one short read transaction per book: 103.4, 62.0, 40.9
  and 33.2 seconds with 1, 2, 4 and 8 workers. A rejected autocommit-read
  prototype took 261.4, 178.6, 163.3 and 155.0 seconds. A four-worker run of
  the applied code took 43.2 seconds, including worker cleanup after forced
  parent termination. No run here measures the current default of up to eight
  workers for at least 16 missing books.
- `performance.json`: local preparation, query and build timings for the
  research database.

## Experimental engine comparison

- [Parallel comparison](parallel-comparison-2026-11-01/README.md): CB-19F
  scoped comparison of Original and the experimental engine. With 24 fresh
  trials over 2010–2019, Original took 71.0 seconds and Numba 59.8 seconds.
- [Parallel qualification](parallel-qualification-2026-11-01/README.md): CB-19G
  final source qualification. It compares the Numba and Rust backends and
  selects Numba. The Rust backend is removed.

## Downloads

- `fmp-download-benchmark.json`: native Windows FMP transport experiment and its
  limits.
- `fmp-throughput-2026-10-23.json`: transport experiment that supports the
  32-worker, 45-starts-per-second defaults. It is not a sustained-rate or full
  application benchmark.
