# EBITDA/EV January book

A standalone US stock backtest and interactive results website. Each January, buy the 50 stocks with the highest EBITDA/enterprise value, equally weighted, and compare their dividend-adjusted returns with SPY. The saved test covers 1996 through 20 October 2026.

## Open the website

On Windows, double-click **`start.cmd`**. It prepares stale local caches in order,
rebuilds the website when needed, starts the local service, and opens your browser.
On other systems, run `python3 website/serve.py`. No API key or market-data
download is needed; unchanged caches are reused. The first refresh can take a
few minutes. Keep the launcher running while using custom dates and frequency.

The website opens with Latest stock picks. Switch to Historical backtest for
January books or custom trade dates with monthly, quarterly, half-yearly or
yearly rebalancing. You can still open [website/dist/index.html](website/dist/index.html)
directly for the saved latest/January views; custom schedules use the local service.

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

# Rebuild the website from prepared holdings
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
  dist/              Ready-to-open HTML, CSV exports, and valuation data
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

The workspace mounts `.git/` read-only. Git metadata is therefore stored in `.git-local/`. Use:

```bash
git --git-dir=.git-local --work-tree=. status
git --git-dir=.git-local --work-tree=. log --oneline
```

Source, reports and the built website are versioned. Downloaded data in `raw/` stays local and is excluded, apart from its README files. Back up the cache separately. The unused, uncommitted website Git metadata is preserved in `.git-local/website-repository-backup/`.
