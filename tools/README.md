# Operational commands and retained experiments

Maintained workspace operations live in `tools/ops`. Retained benchmark and API
experiments live in `tools/experiments`. Their package initializers do no work.
Library callers import these canonical owners. Historical evidence keeps its
original command paths and measurements.

| Owner | Purpose |
| --- | --- |
| `tools.ops.deploy` | Verified committed-source publication and native update supervision |
| `tools.ops.offline_input_copy` | Exact-byte private input materialization; no command entry |
| `tools.ops.prepared_input_coverage` | Read-only prepared-input coverage; no command entry |
| `tools.ops.setup_numerical_native` | Explicit offline native toolchain setup |
| `tools.ops.repair_market` | Explicit SPY and Treasury repair |
| `tools.ops.list_stops`, `tools.ops.classify_stops` | Retained stop inspection commands |
| `tools.experiments.bench_*` | Retained source-bound benchmark and fixture machinery |
| `tools.experiments.parallel_comparison` | Scoped private comparison and its fixed child |
| `tools.experiments.probe*`, `download_one`, `fetch_bulk` | Retained API acquisition experiments |

The existing documented deployment, setup, repair, benchmark, probe and download
command paths remain thin entries. `scripts/list_stops.py` and
`scripts/classify_stops.py` also remain commands. Private workers and library
modules have no forwarding entries. Numerical policy, decisions, process
ownership and Numba implementation belong to `backtest`, not to tools.

The deployment entry also supports an old running controller. That controller
extracts only `tools/deploy.py` from its selected commit. The entry verifies the
request-bound archive hash. It extracts only the bounded regular
`tools/ops/deploy.py` helper. The helper loads support from the verified selected
payload before it publishes source. Source ownership still precedes cache
ownership. Interrupted publication still uses the existing journal.

Importing tool packages does not read credentials or make requests. Explicit
acquisition generally requires `~/.grok/secrets/fmp_api_key`. Offline fixtures
need neither credentials nor network access. Do not run acquisition to recompute
saved results or rebuild the website. Use `scripts/revalue.py` and
`website/build.py`. Real benchmark admission remains closed.

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


## Captured input workspace

`bench_execution_inputs.CapturedWorkspace` consumes an explicit wave11 capture,
an explicit matching source tree and a fresh experiment directory. It validates
the fixed research/daily/report artifacts and captured financial coherence.
It copies actual source bytes into private storage and checks their captured
hashes. It opens the captured databases read-only. `writable_daily()` creates a
fresh SQLite backup under that workspace. Saved books are retained initially.
All borrowed handles and derivatives close before workspace ownership ends.
Completed and failed workspace evidence remains available.

This bounded input abstraction does not import financial engines, construct a
PolicyProgram, discover installed paths or attach either runner. Its freshness
evidence describes capture time. It does not substitute for current request-time
raw checks. Metadata is never rewritten to make a different root look current.
The owner takes no stable financial lock. Synthetic cooperative caps do not
admit the existing real capture or qualify resources. Do not create real
workspaces or derivatives before later resource/cancellation admission.

See [wave12](../docs/plans/compiled-backtest/phases/CB-02/wave12/README.md).
The next engine facade must consume this owner, bind both engines and actual
policy to its generation, and preserve immediate edit detection with live
priority. Benchmark admission stays closed.

## Isolated captured policy

`bench_execution_policy.CapturedPolicy` consumes an active CapturedWorkspace.
It owns one source-only child and its verified benchmark tools beneath the
workspace. The child imports actual application modules from private source and
constructs the actual PolicyProgram. Its immutable binding joins policy/source
evidence to the captured financial generation. It does not rewrite application
paths or captured metadata. It exposes no financial command or application
module. Parent imports and logging stay separate. Outer workspace closure also
closes an escaped policy scope before releasing ownership. Stop-signal and
evidence-write errors cannot bypass child/reader/handle cleanup. If cleanup
cannot be confirmed, the workspace retains its owned resources and lock. Retry
its context exit after resolving the cleanup failure. Retain the workspace object
and call `inputs.__exit__(None, None, None)` to finish that suspended outer exit.
Closing only the policy does not finish the outer exit. A caller exception keeps
its original identity; it does not grant early ownership release.

The source-derived program belongs to
`backtest.engines.numerical.policy.PolicyProgram`. Financial formulas and signatures stay unchanged. Construction
needs no NumPy. Existing numerical methods import NumPy when called. The retained
candidate runner's source inventory also hashes the extracted implementation.
A changed implementation rejects attachment before database or executor access.

Only bounded synthetic fixtures are qualified here. Existing workspace caps stay
unchanged. The child has a ten-second attachment deadline and a sampled 128 MiB
memory limit. These checks do not establish hard CPU/disk isolation or transient
peaks. See [wave13](../docs/plans/compiled-backtest/phases/CB-02/wave13/README.md).
Reference controls, NumericInputs, current request-time freshness and general
execution lifecycle still need the isolated engine facade. No real capture,
derivative, request or benchmark is admitted.


## Measured-execution hardening (source only)

`bench_execution.MeasurementExecution` owns the actual private reference and
Numba adapters, current observations, private derivatives, compiler files,
results and confirmed closure. `bench_execution_observation.CurrentObservation`
shares fixture and coordinated checks. Coordinated mode requires verified
participating cache-access source. It takes source ownership before short cache
ownership and yields to live-intent leases. It releases both before calculation.
This is cooperative priority, not zero-delay access or installed compatibility.

`backtest.runtime.process_owner.OwnedProcess` bounds transport and records separate
closure facts. Native Job Objects limit committed memory, processes and CPU
share. Resident-memory, thread and disk enforcement remain incomplete. Linux
sessions do not prevent escape. Full resource qualification stays open.

Validate the prospective declaration without reading runtime assets:

```text
python3 tools/bench_comparison.py < docs/plans/compiled-backtest/phases/CB-02/execution/prospective-comparison.json
```

This validates arithmetic and protocol shape only. It cannot verify caller
qualification claims, discover the runtime, admit execution or resume a stopped
pair. The declaration retains pending real bindings. No real pilot is authorized.
See the [hardening record](../docs/plans/compiled-backtest/phases/CB-02/execution/hardening.md).
