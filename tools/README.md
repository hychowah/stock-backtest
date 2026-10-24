# Data acquisition and diagnostics

These are diagnostics, retained API experiments and maintenance tools, not the normal workflow. The offline backtest benchmark needs no key or network. Acquisition scripts generally require `~/.grok/secrets/fmp_api_key`.

| Script | Purpose |
| --- | --- |
| `bench_baseline.py` | Freeze CB-01 workloads and resume the production-engine baseline on disposable copies |
| `bench_backtest.py` | Offline end-to-end random-date benchmarks on disposable SQLite copies; checks exact holding/result parity |
| `bench_metrics.py` | Time per-symbol metrics requests |
| `download_one.py` | Download one exploratory bulk file into `raw/archive/` |
| `fetch_bulk.py` | Legacy bulk downloader; outputs to `raw/archive/` |
| `probe.py` | Inspect bulk response shapes |
| `probe_list.py` | Inspect stock-list pagination |
| `probe_span.py` | Check history request date windows |
| `repair_market.py` | Replace active SPY and Treasury caches using short request windows |

Do not run these just to recompute results or rebuild the website. Use `scripts/revalue.py` and `website/build.py` instead. Bulk downloads can be refused by the provider, and long histories can be truncated. The main missing-data workflow lives in `scripts/run.py` and retains its older exit rule.

For a full-history performance comparison, run:

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

Match the interpreter used by the launcher when comparing timings. For Windows
`start.cmd`, run the benchmark in Windows Python, for example:

```bat
py -3 tools\bench_backtest.py --trials 100 --modes production --worker-counts 1 2 4 8 --reference-report results\experiments\backtest-benchmark-applied.json --output results\experiments\backtest-benchmark-parallel.json
```

WSL accessing the Windows-mounted project can have substantially different I/O
costs. `--workdir` permits a separate filesystem control; do not mix such runs
into a same-filesystem speedup claim.

## Frozen production baseline

`bench_baseline.py` is the CB-01 measurement protocol. The older harness above
retains its historical experiments. The new harness runs only the current
production engine. It does not change financial calculations or download data.
Use native Windows Python and the committed Windows runtime for measured runs:

```bat
py -3 tools\bench_baseline.py freeze --runtime <windows-runtime> --manifest tmp\cb01-baseline\workloads.json
py -3 tools\bench_baseline.py run --runtime <windows-runtime> --manifest tmp\cb01-baseline\workloads.json --limit 6
py -3 tools\bench_baseline.py run --runtime <windows-runtime> --manifest tmp\cb01-baseline\workloads.json
py -3 tools\bench_baseline.py verify --runtime <windows-runtime> --manifest tmp\cb01-baseline\workloads.json
```

Run these commands from the Windows runtime. An explicit `--workdir` must be
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

## WSL deployment

`deploy.py` publishes a committed source revision from the WSL checkout to the
registered native Windows runtime. It also starts that runtime, dispatches
saved-data checks, and explicitly collects a verified report revision. It does
not download market data. See [workspace commands](../docs/workspaces.md).
