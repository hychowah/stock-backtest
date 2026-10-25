# Data acquisition and diagnostics

These are diagnostics, retained API experiments and maintenance tools, not the normal workflow. Offline benchmark fixtures need no key or network. Acquisition scripts generally require `~/.grok/secrets/fmp_api_key`.

| Script | Purpose |
| --- | --- |
| `bench_capture_offline.py` | Stopped-runtime SQLite-safe research/daily/report copy under exclusive source/cache ownership; no benchmark admission |
| `bench_input_store.py` | Synthetic-only immutable research/daily/report store and owned writable clones; no live capture or execution admission |
| `bench_admission.py` | Closed execution policy; no runtime is admitted until bound inputs and resources are qualified |
| `bench_candidates_run.py` | Retained historical six-method comparison protocol; execution is closed |
| `bench_methods.py` | Retained historical price-engine comparison protocol; execution is closed |
| `bench_baseline.py` | Retained historical CB-01 freeze/run/verify protocol; execution is closed |
| `bench_backtest.py` | Retained historical end-to-end random-date protocol; execution is closed |
| `bench_metrics.py` | Time per-symbol metrics requests |
| `download_one.py` | Download one exploratory bulk file into `raw/archive/` |
| `fetch_bulk.py` | Legacy bulk downloader; outputs to `raw/archive/` |
| `probe.py` | Inspect bulk response shapes |
| `probe_list.py` | Inspect stock-list pagination |
| `probe_span.py` | Check history request date windows |
| `repair_market.py` | Replace active SPY and Treasury caches using short request windows |

Do not run these just to recompute results or rebuild the website. Use `scripts/revalue.py` and `website/build.py` instead. Bulk downloads can be refused by the provider, and long histories can be truncated. The main missing-data workflow lives in `scripts/run.py` and retains its older exit rule.

## Current benchmark admission

Wave9 closes executable benchmark orchestration and timed request adapters in
WSL source. They raise `BenchmarkAdmissionError` before financial access or
output work. No flag, environment variable, marker or copied database admits a
run. This source change does not alter installed tools or the running website.
Source-only attachment and numerical fixture helpers remain available. Synthetic
tests patch the policy only within disposable fixture scopes.

Wave10 adds `bench_input_store.py` for synthetic owned generations and separate
writable daily clones. Producers construct private inputs and close their writers
before immutable publication. The store validates database/report coherence and
receipts. It has no production capture adapter and does not admit execution.

Complete bound execution ownership, safe live capture, independent experimental
resources and resource/availability qualification remain deferred. See the
[wave9 record](../docs/plans/compiled-backtest/phases/CB-02/wave9/README.md).
Do not run the retained live-cache-locking protocols against the stable runtime.
See the [wave10 store record](../docs/plans/compiled-backtest/phases/CB-02/wave10/README.md)
for its API, synthetic ownership proofs and cooperative resource limits.

## Historical end-to-end protocol

The commands and protocol descriptions below retain the earlier measurement
boundary. They are historical examples, unavailable for current execution.
They do not authorize a capture, pilot or change to the live website.

The full-history comparison used:

```bash
python3 tools/bench_backtest.py --trials 8 --output results/experiments/backtest-benchmark-full.json
```

By default the benchmark compares the former eager two-pool engine
(`sqlite_128mb`) with the applied requested-pool engine (`production`). Additional
modes test a 512 MiB cache, memory-mapped reads and compact in-memory price arrays
with shared report histories against the eager reference. Each engine starts without prepared books, uses the same seeded dates,
and retains ordinary filtering, metric calculation and per-trial saving. Opening
and loading are included; common benchmark-only cloning/reset is excluded. The
OS page cache is not flushed. Each engine also replays the completed batch.

`--modes` selects experiments. `production` runs the current upfront planner and
parallel engine. `--worker-counts 1 2 4 8` compares process counts sequentially,
including Windows spawn, report loading, inter-process transfer and saving.
`selected_pool` preserves the serial requested-pool loop with durable per-pool
completion tracking. `arrays_selected_pool` combines that loop with shared report histories and
in-memory prices. The benefit depends on the requested pool; avoiding the broad
pool mostly helps the original candidate set.
No experiment changes production engine code or the real daily database.
Temporary database copies sit beside the daily cache for filesystem parity and
are removed on normal completion. Long batches can take several minutes.

The historical measurements matched the launcher interpreter. The Windows
`start.cmd` comparison used native Windows Python, for example:

```bat
py -3 tools\bench_backtest.py --trials 100 --modes production --worker-counts 1 2 4 8 --reference-report results\experiments\backtest-benchmark-applied.json --output results\experiments\backtest-benchmark-parallel.json
```

WSL accessing the Windows-mounted project can have substantially different I/O
costs. `--workdir` permits a separate filesystem control; do not mix such runs
into a same-filesystem speedup claim.

## Historical frozen production baseline

`bench_baseline.py` retains the CB-01 measurement protocol. The older harness
above retains its earlier experiments. CB-01 measured the production engine
without changing financial calculations or downloading data. Its historical
commands used native Windows Python and the committed Windows runtime:

```bat
py -3 tools\bench_baseline.py freeze --runtime <windows-runtime> --manifest tmp\cb01-baseline\workloads.json
py -3 tools\bench_baseline.py run --runtime <windows-runtime> --manifest tmp\cb01-baseline\workloads.json --limit 6
py -3 tools\bench_baseline.py run --runtime <windows-runtime> --manifest tmp\cb01-baseline\workloads.json
py -3 tools\bench_baseline.py verify --runtime <windows-runtime> --manifest tmp\cb01-baseline\workloads.json
```

Those historical commands ran from the Windows runtime. An explicit `--workdir` was
a dedicated directory below that runtime's `tmp/`. The default is
`tmp/cb01-baseline`. `--report` defaults to `baseline.json` in that directory.
For source review, copy the generated manifest and compact report to the phase
record. Keep evidence JSON, checkpoints and disposable SQLite files in `tmp/`.

The manifest freezes 24 annual random trials over 1997–2025. It includes three
seeds, both pools and three filter profiles. All request defaults and exact date
lists are explicit. The first six cases use seed 42 and form the pilot matrix.
The remaining cases complete the 18-run matrix. A limit runs only that many
pending cases. A changed workload, source, tool, environment or input identity
rejects old checkpoints. Use a new work directory for a different protocol.
An interrupted case starts again with a fresh copy. Completed cases are reused
only after their evidence hashes pass verification.

Each measured fresh request starts with zero derived rows. It includes the
ordinary source scan, automatic worker startup, calculation, selection,
per-trial saving, response encoding and local socket receipt. The adapter uses
the website's NDJSON event shapes. It does not measure an HTTP server or browser.
Readiness, cloning, evidence JSON writing and invariance scans are excluded.
Worker initialization overlaps calculation wait. Selection and source-scan
timers overlap validation. Do not add these times as independent stages.

Every case separately replays saved books and compares all ordered holding
fields and aggregate results exactly. The first case also repeats its frozen
dates on another fresh copy. Native memory, thread, process and I/O values are
sampled at 200 milliseconds. Short-lived processes or final child I/O can be
missed. Sampling, observation and progress output are included in request time.
The OS file cache is not cleared. Installation and compiler startup are separate
measurements and are not claimed here.

Timed validation also counts rows in each derived table. Fresh tables are empty.
Replay counts scan saved rows and can materially increase validation time.
Replay times describe this adapter. Do not present them as production replay
latency.

Shared source ownership starts before application imports. The financial
coordinator stays held through worker shutdown, database closure and verification.
Raw invariance uses a full path/size/mtime inventory. It is not a raw-content
hash. Prepared database, sidecar, canonical report and application source content
hashes must stay unchanged. Existing production books are preserved. Stale
prepared inputs or unfinished publication stop measurement; use the supported
preparation or recovery command before freezing a new baseline.

The correctness inventory also names mixed filters, three-year ranking,
top 100 and empty selection. Listing those cases does not claim real-data
qualification. The phase report states which cases were actually run.

## Historical comparative methods

The comparative experiment used `bench_methods.py --runtime <native-root>
--workdir <dedicated-native-tmp-folder>`. It consumes the CB-01 workload.
Method modules are benchmark-only. They do not change production selection.
The experiments used dependencies in a separate native temporary environment.
The normal application environment stayed unchanged. See
[`CB-02`](../docs/plans/compiled-backtest/phases/CB-02/README.md) for exact commands,
paired controls, tested scope and qualification limits.

`--methods indexed` selects the retained second-wave report-selection experiment. It uses the
array price resolver and indexes both annual-report pools. It preserves the
original buffer order before price-coverage filtering. With no threshold
conditions, it skips unused threshold calculations and their trailing-price
lookups. With any condition, it calls the complete existing threshold calculator.
It still evaluates the full ranking catalog and uses the existing financial
policy and SQL selector. The full freshness scan stays inside request time.
See the separate [second-wave record](../docs/plans/compiled-backtest/phases/CB-02/wave2/README.md).
The normal application does not use this evaluator.

The [third-wave comparison](../docs/plans/compiled-backtest/phases/CB-02/wave3/README.md)
uses `bench_candidates_run.py --runtime <native-root> --workdir <new-native-tmp-folder>`.
Its explicit method order is `--methods numba python duckdb persistent polars rust`.
Executors share immutable numerical inputs and source-derived financial arithmetic.
They own report selection, sparse price searches and factor batches. Final SQL
selection and portfolio assembly remain common. The full freshness check stays
inside primary timing. Six additional requests per method check both pools,
financial filters, trailing filters and mixed three-year ranking without a
performance claim. Loading and compilation are separate costs. The parent
contains native work in an owned process tree and retains committed evidence
on timeout. Budgets are configurable with `--setup-budget`, `--request-budget`
and `--smoke-budget`. Existing comparison directories are rejected.

## WSL deployment

`deploy.py` publishes a committed source revision from the WSL checkout to the
registered native Windows runtime. It also starts that runtime, dispatches
saved-data checks, and explicitly collects a verified report revision. It does
not download market data. See [workspace commands](../docs/workspaces.md).


## Offline database capture

`bench_capture_offline.py` is separate from the closed benchmark entry points.
Use it only in a user-authorized stopped-server window. It acquires exclusive
source ownership before financial ownership with no wait. SQLite backup preserves
the research/daily/report set and all saved books. It rejects pending publications,
sidecars and WAL source format; no original normalization or preparation runs.
A source or data owner makes capture fail. A new server start can wait until
capture completes. The tool never stops or starts a server.

Keep output in a dedicated ignored native Windows experiment directory. Captured
freshness metadata is retained, not rebased. The output confers no execution
admission. See [wave11](../docs/plans/compiled-backtest/phases/CB-02/wave11/README.md)
for source/receipt validation, limits, actual capture evidence and attachment gaps.
