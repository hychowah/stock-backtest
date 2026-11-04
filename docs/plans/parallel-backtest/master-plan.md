# Parallel experimental backtest

Status: complete

Frozen: the website does not offer the experimental engine and has no Prepare action (AGENTS.md, Engines).

## Outcome

The experimental engine runs random-date trials in parallel processes. Compiled
Numba is its only production complete-book provider. The default layout is two
workers with two numerical threads each. Observed CPU and memory headroom can
reduce it. Backend, worker and thread settings stayed internal.

The parts are:

- **CB-19A:** a worker attaches the coordinator's exact immutable generation.
  It does no recovery, preparation or financial locking.
- **CB-19B:** one recorded-trial evaluator serves eager and streaming requests.
  It writes a sealed artifact that keeps every holding and the actual trial number.
- **CB-19C:** a persistent, bounded, contained worker pool.
- **CB-19D:** one parent coordinator recovers, checkpoints and orders trials.
- **CB-19E:** one typed candidate boundary for compiled Numba and Rust.
- **CB-19F/G:** a scoped comparison, then selection and integration.

The Rust comparison provider and its build tooling were removed after CB-19G.
Normal startup, preparation and calculation need no compiler. CB-19 deployed nothing and
restarted no installed server.

## Key decisions

- **The trial is the unit of parallel work.** Trials are already the unit of
  checkpoint and financial aggregation. A shared book graph across trials was
  rejected. It needs cross-trial planning, a second book store and a second
  recovery model.
- **A shared reader-gate lock protects worker attachment.** Each generation has
  a stable `gates/<identity>.lock`. Retirement takes it exclusively. Per-worker
  UUID leases were rejected because registration can race retirement after
  parent death.
- **One incremental evaluator.** Separate eager and streaming implementations
  were rejected. They duplicate logic and keep a whole trial in worker memory.
- **One runtime with persistent workers.** Several independent runtimes were
  rejected. They duplicate financial ownership and compete for locks. The
  historical benchmark executor's pickle/export protocol was not imported.
- **Recovery precedes startup.** Identity binds configured capacity, threads,
  backend and provider limits. Actual starts and memory samples are diagnostics.
  A full checkpoint hit starts no worker, builds no provider and compiles no
  kernel. Fresh trials save in completion order and present in recorded order.
- **Python keeps planning, SQL selection, the reducer and checkpoints.** Rust
  replaced only the source-derived candidate calculation. Translating the whole
  period into Rust, or a Rust request service (G option 1), was rejected. It
  duplicates financial and SQL policy and another recovery protocol.
- **Historical limits are not machine limits.** The hidden four-thread clamp
  was removed. Four workers, 25% CPU, 2 GiB and 1,800 seconds describe old
  experiments only. Kept: 64 MiB workspace and 16 MiB matrix cache per live
  provider, 64 MiB per pending artifact slot, 1 MiB piece and 8 MiB record codec
  maxima, 120 s start and 30 s close defaults.
- **F settings.** Private native Windows, 16 logical CPUs, no job quota. Plan:
  24 seed-42 annual trials, 2010–2019, cached pool, ranks 1–50, EBITDA/EV,
  filter-first, 240 periods, 12,000 holdings. Clock: Candidate/Original adapter
  call through complete holdings and confirmed closure.
- **F first observations:** Original with four book workers 71.02 s; compiled
  Numba 1×4 65.47 s, 2×2 61.46 s, 4×1 71.49 s, 2×4 60.24 s; Rust 1×4 61.47 s.
  Four workers lost to serial readiness. Eight lanes (2×4) gave no gain over 2×2
  variation.
- **F provisionally chose Rust 2×2.** Balanced R–C–C–R medians: Rust 51.98 s,
  compiled Numba 59.52 s (12.66%). The gain came from build reuse and faster
  worker readiness (about 5.2 s against 9 s per worker), not arithmetic. Warm
  initialized-runtime requests were nearly equal (14.72 s against 14.82 s).
- **G chose compiled Numba 2×2 over Rust.** Same plan, with managed Rust
  availability and concurrent worker startup. Medians: 2×2 Numba 117.43 s
  against Rust 123.55 s; 4×1 Numba 122.02 s against Rust 125.46 s. Rust status
  alone took 4.17 s against Numba's 1.77 s. Rust needs a managed compiler
  installation. F and G clocks have different source scopes; do not compare them.
- **Default memory admission.** A 256 MiB readiness estimate rounds up the
  measured cold private samples (152.3–152.7 MB). The first worker's actual
  sample gates the others, which then start concurrently. Unknown memory
  headroom selects one worker. This is not an RSS limit.
- **Windows publication retries.** One F Rust run committed all trials, then
  failed with `PermissionError` while publishing statistics. Shared atomic
  publication now retries only Windows errors 5, 32 and 33. Seven cancellable
  retries wait 1.95 s in total. Prior content survives a failure.
- **Rust threads need explicit joins.** Automatic scoped-thread joins do not
  wait for thread-local destructors. Native loops join every handle before
  return.
- **Final normal Selectable request (same plan):** fresh 120.69 s; new-runtime
  full hit 51.41 s with zero workers, providers and compilations; partial
  recovery 123.27 s, with 3 trials recovered and 21 calculated. All outputs
  agree with Original at zero difference (tolerance `1e-12`). Zero numerical
  work is not zero latency.

## Where the current contracts live

- [Current execution ownership](../../numerical-generations.md#current-execution-ownership-cb-19g),
  [worker attachment](../../numerical-generations.md#exact-generation-worker-attachment-cb-19a),
  [persistent trial workers](../../numerical-generations.md#persistent-trial-workers-cb-19c),
  [ordered coordinator](../../numerical-generations.md#ordered-random-coordinator-cb-19d)
  and [candidate boundary](../../numerical-generations.md#complete-period-comparison-cb-19e).
- [Parallel checkpoint coordination](../../trial-checkpoints.md#parallel-ordered-coordination-cb-19d).
- [Selected preparation](../../candidate-startup.md#current-selected-preparation-cb-19g).
- [Architecture guide](../../architecture-guide/dist/index.html).
- F evidence: [README](../../../results/experiments/parallel-comparison-2026-11-01/README.md),
  [decision](../../../results/experiments/parallel-comparison-2026-11-01/decision.json),
  [long comparison](../../../results/experiments/parallel-comparison-2026-11-01/long-comparison.json),
  [short comparison](../../../results/experiments/parallel-comparison-2026-11-01/short-comparison.json),
  [long workload](../../../results/experiments/parallel-comparison-2026-11-01/long-workload.json).
- G evidence: [README](../../../results/experiments/parallel-qualification-2026-11-01/README.md),
  [backend decision](../../../results/experiments/parallel-qualification-2026-11-01/profiles-decision.json),
  [final qualification](../../../results/experiments/parallel-qualification-2026-11-01/final-qualification.json),
  [final comparison](../../../results/experiments/parallel-qualification-2026-11-01/final-comparison.json).
- Source: `backtest/engines/numerical/` (`execution.py`, `trial.py`,
  `trial_pool.py`, `trial_worker.py`, `random.py`, `session.py`,
  `generation.py`, `candidates.py`). Comparison runner:
  `tools/parallel_comparison.py`.

## Known limits and open items

- This is source only. Installed readiness and installed latency are not
  established. Deployment needs separate authorization.
- The evidence is finite: one Windows machine, two workloads, an unflushed file
  cache. It proves no global optimum or sustained speed.
- A fresh experimental request is only modestly faster than Original (F: 61.46 s
  against 71.02 s). Original replays prepared books in 1.5 s (short plan) to
  7.6 s (long plan).
- The external cause of F's `PermissionError` is unproven.
- A native Rust suite crashed with `0xC0000005` before the thread-join repair.
  The causal link is unproven.
- Rust compiler installation time was not measured.
- Current dispatch rejects historical Rust and source-guard configurations.
  Reproducing them needs the exact archived source in the G evidence.
