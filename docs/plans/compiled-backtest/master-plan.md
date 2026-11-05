# Faster stock backtest engine

Status: complete

Deleted: the experimental engine source, its tests and the comparison runner were deleted on 2026-11-05. The website runs only Original.

## Outcome

The program adds a second engine for custom dated backtests. The website calls
it **New engine — experimental**. It runs compiled NumPy/Numba kernels over an
immutable numerical generation. Python keeps recorded date plans, the shared SQL
selector, the financial reducer, checkpoints and process lifetime. Original is
the default. An omitted engine means Original. Each submission pins its engine
through jobs, queue records, retries and recovery. An unsupported experimental
request fails with a named error. There is no fallback to Original.

Both engines support fixed, explicit-date and random dated runs with version-1
week/month calendars, both pools, both ranking metrics, all threshold filters
and both selection orders. January and latest views stay shared prepared-data
views. New results record their producer. Stored results open without
calculation or numerical packages.

Normal startup needs no numerical packages. The user installs
`requirements-numerical.txt` (NumPy 2.5.4, Numba 0.68.0, llvmlite 0.50.0;
CPython 3.12 or 3.14). Then the data-panel action **Prepare experimental engine**
prepares and verifies the engine. The source is integrated into `main`. This
program did not publish it or qualify the installed runtime. The follow-on
[parallel backtest program](../parallel-backtest/master-plan.md) (CB-19) owns
the current worker policy and provider choice.

## Key decisions

- **Numba is the method (CB-02, user decision).** The wave3 pilot used the
  frozen CB-01 case: 24 annual random trials, 1997–2025, original pool, current
  EV/EBITDA, ranks 1–50, native Windows, four threads. Requests took Numba
  17.55 s, Rust 17.65 s, persistent Python workers 21.58 s, bulk Python 25.94 s,
  Polars 29.06 s and DuckDB 101.81 s. All six matched Original exactly. Adjacent
  Original controls took 48.84–121.22 s.
- **Rejected approaches.** DuckDB per-book ASOF lookup exceeded its 180 s
  request budget in the first pilot. Whole-batch DuckDB spent 80.89 s in price
  lookup. Polars needed expression simplification disabled to keep rounding.
  Persistent Python workers peaked at 3.84 GiB working set. Rust tied Numba but
  adds a native build pipeline. Do not develop two production providers.
- **The full matrix passed correctness, not the speed gate (wave5).** It had
  18 cases (two pools × F0/F1/F2 × three seeds) with exact agreement. Numba
  median ratios were 4.66×–7.74×. Broader-pool F2 failed the then-current 5×
  gate: Numba 4.66×, Rust 4.53×. The user later retired the 5×, 10× and 4× gates
  and accepted Numba. These ratios are historical, not current-source results.
- **Two bounded optimizations failed.** Requested-metric SQL staging (wave6)
  removed 1,412,574 rows but cut request time by only 3.92% (target 10%).
  Compiled guard/assembly (wave7) never ran: the 2,700 s watchdog stopped during
  its first control. Compiled-guard translation stays optional and unmeasured.
- **Performance direction (CB-14).** Aim for about 4× over Original, or close.
  There is no absolute waiting-time limit. Stop work that gives only small gains.
- **Freshness stays at request time.** Every request repeats the
  path/size/mtime inventory scan. Startup-only detection was rejected. In wave3
  the full scan took about 10.5 s, about 60% of the warm Numba request.
- **Shared SQL selection is retained (CB-07).** `research._select` ranks and
  filters both engines. Generic native selection is not implemented. No
  measurement showed a selection limit. Period eligibility applies before
  ranking.
- **Data shape.** Use sparse sorted price series and bounded entry-date
  batches. A full daily factor cube was rejected: 18 fields over all sessions
  and symbols need about 7.60 GB in float64. Generations are immutable
  directories behind an atomic pointer.
- **Exact arithmetic.** Use float64, `fastmath=False` and no Numba disk cache.
  The compiler identity binds source, policy, versions, platform and CPU. The
  tolerance stays `1e-12`. Symbols, ranks, dates and statuses match exactly.
- **One child per call (CB-14).** Each experimental call starts, uses and closes
  its own runtime before it publishes an outcome. No idle child holds financial
  ownership. Disk checkpoints are reusable; compiler memory is not.
- **Annual history repair (CB-14).** Removing unused history loads changed a
  fresh three-trial annual request (seed 43, 87 periods, 4,350 holdings) to
  70.42 s versus Original 167.81 s (2.38×). Before the repair, a one-trial pair
  was 0.93×.
- **Exact seeded comparison (CB-17).** The settings were 100 annual trials,
  2013-01-01 to 2026-10-21, seed 2607948532, cached pool, ranks 1–30, operating
  yield spread > 0, P/B < 1.5 and FCF yield > 3%. Both engines agree on 1,400
  periods and 42,000 holdings with zero differences. Both first attempts hit
  the 1,800 s watchdog. Totals over all attempts were 2,092 s Experimental versus
  4,367 s Original (2.09×). Nested Windows job caps limited each run to 6.25% of
  system CPU. No uninterrupted ratio exists.
- **Operating yield spread (CB-16).** The experimental engine uses Original's
  calculator during annual specialization. Generations carry `treasury10`, with
  the latest yield on or before entry.

## Where the current contracts live

- [Dated result contract](../../portfolio-results.md) and
  [schedule calendar](../../schedule-calendar.md)
- [Bounded evidence format](../../result-evidence.md),
  [durable snapshots](../../durable-evidence.md) and
  [acquired readers](../../evidence-views.md)
- [Workspaces](../../workspaces.md) and the
  [architecture guide](../../architecture-guide/dist/index.html)
- Root [AGENTS.md](../../../AGENTS.md#feature-contracts): the Engines and
  Result access contracts
- [Experiment records](../../../results/experiments/README.md), including the
  pre-program [benchmark summary](../../../results/experiments/backtest-benchmark-summary.json)

## Known limits and open items

- Original is the only engine the website runs.
- The approximate 4× goal is not shown on current source. No matched
  uninterrupted full-batch timing exists.
- Capacity is not qualified. Over the full 1997–2025 window, these plans exceed
  the 256 MiB eager result estimate: 100 annual trials (ranks 1–50), 24 annual
  trials (ranks 1–100) and 24 or 100 weekly trials. Holding records alone need
  about 655 MB for 24 weekly trials and 2.73 GB for 100.
- Version-3 durable evidence needs current readers. Source from before version 3
  is not a safe rollback target.
- The scan does not detect a same-size edit with a restored timestamp.
- The cached pool is not the full universe. Its extra holdings had no manual
  bankruptcy review.
- The benchmark harness was later removed. The comparison runner was deleted
  with the engine.
