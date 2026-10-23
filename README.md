# EBITDA/EV January book

A standalone US stock backtest and interactive results website. Each January, buy the 50 stocks with the highest EBITDA/enterprise value, equally weighted, and compare their dividend-adjusted returns with SPY. The saved test covers 1996 through 20 October 2026.

## Open the website

On Windows, run **`backtest-web.cmd`** from the project folder, or double-click **`start.cmd`**. It prepares stale local caches in order,
rebuilds the website when needed, starts the local service, and opens your browser.
On other systems, run `python3 website/serve.py` in the foreground. No API key or market-data
download is needed; unchanged caches are reused. The first refresh can take a
few minutes. The Windows command keeps the server attached to the terminal on `0.0.0.0:3000`. Open `http://127.0.0.1:3000` on this computer. The installed `backtest-web.cmd` command also works from other Windows Terminal folders. Keep the terminal open to see server logs. Press Ctrl+C to stop it. Repeating the command stops this project’s identified server and starts current code in the new terminal. This also replaces any older background instance. Replacement waits for active requests to finish before it prepares data. If ownership is still held after 30 seconds, the command asks you to wait or stop the old terminal, then retry.

The server also saves development logs in `data/logs/website-<namespace>-<pid>.log`. The terminal and data panel show the current file. Logs keep error types, stack locations, file error codes and safe download context. They omit API keys, provider URLs, response bodies and arbitrary exception text. Each process keeps one active log and two rotated backups, up to about 5 MiB each. Startup removes stopped-process logs older than 14 days, then the oldest eligible logs toward a 100 MiB total target. Active, legacy, foreign-namespace and uncertain logs are kept. Protected files and growth between startups can exceed the target. Cleanup errors do not stop startup.

The website opens with Latest stock picks. Switch to Historical backtest for
January books or custom trade dates with monthly, quarterly, half-yearly or
yearly rebalancing. You can still open [website/dist/index.html](website/dist/index.html)
directly for the saved latest/January views; custom schedules use the local service.

Choose **Manage backtest data** to inspect saved files and date coverage.
Choose a stock group or enter symbols. **Download missing data** fills missing
financial symbols and price ranges with your local FMP key. **Rebuild prepared
data + website** applies saved changes offline. Existing records are kept.
A rebuild compares SQL results with the independent reference engine at the saved historical cutoff. When they agree, it updates the report and preserves revision evidence in `results/baseline-history/`. Engine disagreement stops publication. Use **Export baseline revision** in the data panel to inspect changed holdings and prices. No download starts when the panel opens. If essential source files are missing,
startup opens the data panel for recovery. See [the data workflow](docs/research-workflow.md#data-control-panel).

Random-date batches plan missing books once, calculate ahead with separate Python
processes, and save complete trials through one SQLite writer. Replays reuse
saved books. Filters, metrics and stock counts share the ordinary screening rules.

For an explanation of the program, open the [plain-language architecture guide](docs/architecture-guide/dist/index.html).
It is a separate static website. It works offline and includes diagrams, setting
examples, a file map and the measured speed comparisons.


## Run from the saved data

Python 3.10 or newer is required. Python scripts use only the standard library.

```bash
# Prepare the local database once (no downloads)
python3 scripts/research.py prepare

# Run a fast screen; change --top, years, or filters freely
python3 scripts/research.py screen --top 100

# Rebuild ignored local output from prepared holdings
python3 website/build.py

# Check year/rank filtering and performance calculations (requires Node.js)
node tests/check-range.cjs
python3 tests/check_screener.py

# Check project paths, imports, and cache-only operation
python3 tests/check_paths.py
```

Commands above run from the project folder. Python scripts resolve data paths from their own location, so they also work when invoked by absolute path from another directory. Keep `raw/` with the project when moving it. Initial database preparation reads roughly 1.2 GB of cached price files. Subsequent screens and website builds query compact prepared records. The independent `scripts/revalue.py` reference run still reads raw prices.

## Project layout

```text
scripts/             Data preparation, screening, backtest, exit analysis, and paths
data/                Prepared local SQLite database (generated; ignored by Git)
website/             Website source, builder, hosting identity, and built output
  local/             Ignored local server output
  dist/              Tracked portable snapshot; refresh explicitly
results/
  summary-exits.txt  Current backtest result
  stops/             Early trading-stop analysis and filing classifications
  legacy/            Earlier results using the old exit rule
raw/                 Reusable universe, financial metrics, prices, SPY, Treasury data
  px/                One price-history file per stock
  archive/           Unused bulk downloads and exploratory responses
tools/              API probes, download experiments, and market-data repair
tests/              Calculation and path checks
docs/               Methodology, assumptions, and limitations
```

See [fast screening and backtesting](docs/research-workflow.md) for parameter examples, coverage limits, and the preparation/query separation.

## Current result

The current report is [results/summary-exits.txt](results/summary-exits.txt). From January 1996 to January 2026 it reports 18.01% annualized for the strategy versus 10.22% for SPY. These are historical backtest results, with no commissions.

[Methodology and limitations](docs/methodology.md) explain the universe, report lag, valuation adjustments, data issues, and exit treatment. The earlier `results/legacy/` reports are retained for reference and are not the current result.

## Cache and downloads

Normal backtest and website runs are offline and reuse `raw/`. No API key is required for those operations. See [raw/README.md](raw/README.md) for cache contents.

`scripts/run.py` may fetch missing data and writes the **legacy** reports. Use it only when the cache needs additional data; its exit rule still differs from the current `scripts/revalue.py`. API credentials remain outside this project at `~/.grok/secrets/fmp_api_key` and are read only when the main downloader makes a request. [tools/README.md](tools/README.md) describes the exploratory scripts; do not run them as part of normal analysis.

The local website is ready to use. Hosted publication has not completed because the current environment cannot reach the Sites source server. Preserve `website/.openai/hosting.json` when retrying publication.

## Version control in this environment

The workspace mounts an empty `.git/` folder read-only. The repository history is stored in `.git-local/`. Ordinary Git commands and apps may not detect it automatically. From the project folder, use:

```bash
git --git-dir=.git-local --work-tree=. status
git --git-dir=.git-local --work-tree=. log --oneline
```

Use the same options for diff, add and commit. If the default Git wrapper fails with a WSL socket error, use `/usr/bin/git` with these options. Do not initialize a new repository over the saved history.

Source, reports and the built website are versioned. Downloaded data in `raw/` stays local and is excluded, apart from its README files. Back up the cache separately. The unused, uncommitted website Git metadata is preserved in `.git-local/website-repository-backup/`.

## Local builds and portable snapshots

Normal builds, startup and data-panel rebuilds write ignored `website/local/`. The server uses this output. They do not change the tracked portable snapshot in `website/dist/`.

Run `python3 website/build.py --snapshot` to refresh the portable snapshot explicitly after preparing data. Review and commit that refresh deliberately. Each build writes `snapshot.json` with the historical report cutoff, latest screen date, report hash and website source hashes. An already-open page needs a reload.

Range and SQL/browser parity checks use local output by default. To check the portable snapshot, run `node tests/check-range.cjs website/dist` and `python3 tests/check_screener.py website/dist`.
