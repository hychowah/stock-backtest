# Data acquisition and diagnostics

These are diagnostics, retained API experiments and maintenance tools, not the normal workflow. The offline backtest benchmark needs no key or network. Acquisition scripts generally require `~/.grok/secrets/fmp_api_key`.

| Script | Purpose |
| --- | --- |
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

## WSL deployment

`deploy.py` publishes a committed source revision from the WSL checkout to the
registered native Windows runtime. It also starts that runtime, dispatches
saved-data checks, and explicitly collects a verified report revision. It does
not download market data. See [workspace commands](../docs/workspaces.md).
