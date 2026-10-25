# Prepared-data experiments

These reports are separate from the canonical `results/summary-exits.txt`.

Current WSL benchmark execution is closed. Wave9 adds one admission policy to
benchmark orchestration and timed request adapters. Historical command examples
are unavailable for current execution. Source-only attachment and numerical
fixture helpers remain available. Consistent bound-input ownership, safe capture
and resource/availability qualification remain deferred. See the
[wave9 record](../../docs/plans/compiled-backtest/phases/CB-02/wave9/README.md).
This source safeguard does not change installed tools or the running website.
Wave10 adds a synthetic-only immutable input store and separately writable daily
clones in a linked feature worktree. It has no live capture adapter, raw-data
attachment or execution admission. See the
[wave10 record](../../docs/plans/compiled-backtest/phases/CB-02/wave10/README.md).
Real-data copies remain deferred pending a qualified producer and capture gates.

CB-02's [third experiment](../../docs/plans/compiled-backtest/phases/CB-02/wave3/README.md)
compares Numba, bulk Python, whole-batch DuckDB, persistent workers, Polars and
Rust over shared source-derived financial policy. Its phase record binds the
native artifacts and separates primary timing, setup and correctness checks.
All six completed with exact agreement. Numba and Rust took about 17.6 seconds
on the original-pool pilot. No 5× gate passed; full qualification remains pending.

CB-02's [second experiment](../../docs/plans/compiled-backtest/phases/CB-02/wave2/README.md)
tests indexed annual-report selection and unused threshold omission. Its record
keeps native controls, correctness evidence and the performance decision separate
from the first lookup pilot and from production behavior.

The compiled-engine program's CB-01 baseline has its own
[phase record](../../docs/plans/compiled-backtest/phases/CB-01/).
Its frozen workloads cover 24 trials over 1997–2025, both pools, three filter
profiles and three seeds. `tools/bench_baseline.py` retains that historical
protocol; its execution is closed.
Full holding evidence and disposable databases remain under the Windows
runtime's ignored `tmp/cb01-final/`. The earlier `tmp/cb01-baseline/` folder
contains superseded diagnostics. The phase report records completed and
pending runs. The older timings below remain historical measurements.

- `top100-2015-2020.json`: an example top-100 query for six January books using the original 250-candidate screen and current last-price exit treatment. It includes the full selected holdings and settings. Additional early stops outside the original top 50 have not received the earlier manual bankruptcy review.
- `performance.json`: measured local preparation/query/build timings for the new data layer. These are observations from this environment, not performance guarantees.
- `backtest-benchmark-windows-full.json`: native Windows comparison of five engines over eight full-history, annually rebalanced random-date trials. Fresh-book timings include data loading, shared SQL selection and per-trial commits; holding results are compared exactly.
- `backtest-benchmark-windows-100.json`: native Windows 100-trial full-history comparison of the reference engine, requested-pool preparation and requested-pool preparation with shared in-memory data.
- `backtest-benchmark-applied.json`: the applied production engine reran all 100 trials on native Windows in 133.1 seconds (3.5× faster than the saved 467.0-second reference). Every selected holding/value/status and trial outcome matches the pre-change reference exactly; this run includes durable per-pool completion tracking and cached replays.
- `backtest-benchmark-parallel.json`: upfront planning and short book read transactions, using 1/2/4/8 workers on native Windows. The 100-trial measurements were 103.4/62.0/40.9/33.2 seconds, with a fresh serial requested-pool control of 133.3 seconds. Every holding/result digest and outcome matched exactly. Four workers are the default.
- `backtest-benchmark-parallel-applied.json`: final four-worker run: 43.2 seconds (3.1× faster than the serial requested-pool engine), including worker cleanup after forced parent termination. Timings include Windows startup, calculation, transfers, staging and trial saves.
- `parallel-book-summary.json`: compact comparison, applied source hashes, default-worker policy and exact-parity outcome.
- `parallel-book-upgrade.json`: compatible version-2 to version-3 upgrade of the real cache. All 2,581 existing dated periods and 2,881 pool markers retain identical digests; financial/result counts also match.
- `backtest-benchmark-parallel-locking.json`: rejected autocommit-read prototype, 261.4/178.6/163.3/155.0 seconds with 1/2/4/8 workers. It demonstrates why price queries need one short read transaction per book. All results matched, but none beat the committed serial engine.
- `requested-pool-upgrade.json`: the real daily cache upgraded from version 1 to 2, retaining all 300 existing dated books and marking their 600 completed pools without reparsing JSON prices.
- `backtest-benchmark-summary.json`: compact timing comparisons, exact-parity verification and source hashes. The 100-trial reference took 467.0 seconds, requested-pool preparation 132.1 seconds (3.5× faster), and the combined in-memory prototype 105.9 seconds (4.4× faster, including loading). Requested-pool preparation was faster at the default 24 trials because it avoided the in-memory loading cost.
- `backtest-benchmark-wsl-pilot.json` and `backtest-benchmark-wsl-full.json`: separate WSL diagnostics. The full run was stopped after the reference measurement when the user confirmed Windows `start.cmd` is the real launch method. Do not use WSL timings as the Windows baseline.

The earlier backtest experiments listed above use the original candidate pool, current EV/EBITDA,
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
