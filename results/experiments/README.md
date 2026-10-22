# Prepared-data experiments

These reports are separate from the canonical `results/summary-exits.txt`.

- `top100-2015-2020.json`: an example top-100 query for six January books using the original 250-candidate screen and current last-price exit treatment. It includes the full selected holdings and settings. Additional early stops outside the original top 50 have not received the earlier manual bankruptcy review.
- `performance.json`: measured local preparation/query/build timings for the new data layer. These are observations from this environment, not performance guarantees.
- `backtest-benchmark-windows-full.json`: native Windows comparison of five engines over eight full-history, annually rebalanced random-date trials. Fresh-book timings include data loading, shared SQL selection and per-trial commits; holding results are compared exactly.
- `backtest-benchmark-windows-100.json`: native Windows 100-trial full-history comparison of the reference engine, requested-pool preparation and requested-pool preparation with shared in-memory data.
- `backtest-benchmark-applied.json`: the applied production engine reran all 100 trials on native Windows in 133.1 seconds (3.5× faster than the saved 467.0-second reference). Every selected holding/value/status and trial outcome matches the pre-change reference exactly; this run includes durable per-pool completion tracking and cached replays.
- `requested-pool-upgrade.json`: the real daily cache upgraded from version 1 to 2, retaining all 300 existing dated books and marking their 600 completed pools without reparsing JSON prices.
- `backtest-benchmark-summary.json`: compact timing comparisons, exact-parity verification and source hashes. The 100-trial reference took 467.0 seconds, requested-pool preparation 132.1 seconds (3.5× faster), and the combined in-memory prototype 105.9 seconds (4.4× faster, including loading). Requested-pool preparation was faster at the default 24 trials because it avoided the in-memory loading cost.
- `backtest-benchmark-wsl-pilot.json` and `backtest-benchmark-wsl-full.json`: separate WSL diagnostics. The full run was stopped after the reference measurement when the user confirmed Windows `start.cmd` is the real launch method. Do not use WSL timings as the Windows baseline.

The backtest experiments use the original candidate pool, current EV/EBITDA,
default top-50 filters and seed `20261022`, from 1996-01-01 to 2026-10-20 (the
latest session in the saved daily database). Every variant starts with no dated
books and runs the same sampled dates. Ordinary completed-book replays are timed
separately. Benchmark-only cache cloning/reset and report generation are excluded;
the OS page cache is not flushed. See `tools/bench_backtest.py` and `tools/README.md`.
The initial comparison reports left production code and the daily cache
unchanged. Requested-pool preparation is now applied in `scripts/schedules.py`,
and the compatible daily cache has upgraded in place. Raw inputs and canonical
reports are unchanged. `sqlite_128mb` now denotes the retained eager reference
in the benchmark harness; `production` tests the applied engine.

Regenerate the sample with:

```bash
python3 scripts/research.py screen --top 100 --first 2015 --last 2020 --output results/experiments/top100-2015-2020.json
```

The first January book has fewer than 100 usable names in the original 250-candidate pool. Full-universe top-100 claims require broader price coverage and exit review. Use `status` and inspect short-year output before interpreting an experiment.
