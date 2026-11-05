# EBITDA/EV January book

A standalone US stock backtest and interactive results website. Each January, buy the 50 stocks with the highest EBITDA/enterprise value, equally weighted, and compare their dividend-adjusted returns with SPY. The saved test covers 1996 through 20 October 2026.

## Open the website

Source development lives in WSL at `<wsl-checkout>`.
The native Windows runtime is `<windows-runtime>`. Edit and commit in WSL.
Start the native runtime with `python3 tools/deploy.py --start`, or run the
installed `backtest-web.cmd` from Windows Terminal. Startup deploys the latest
committed `main` and checks that branch every two seconds. A new commit causes
verified deployment and a server restart. A pending publication resumes its
recorded revision before a newer revision can be selected.

Use `python3 tools/deploy.py --revision <commit> --start` to fix one launch to
that revision. Standalone publication without `--start` retains the installed
revision. A fresh standalone runtime requires an explicit revision. See
[workspace commands and ownership](docs/workspaces.md) for recovery and the
source-only explicit-argument forwarding limit.

On Windows, run **`backtest-web.cmd`** from the runtime folder, or double-click **`start.cmd`**. It prepares stale local caches in order,
rebuilds the website when needed, starts the local service, and opens your browser.
A standalone installation on another system can run `python3 website/serve.py` in the foreground with its own cache. In this split workspace, use the native Windows runtime. No API key or market-data
download is needed; unchanged caches are reused. The first refresh can take a
few minutes. The Windows command keeps the server attached to the terminal on `0.0.0.0:3000`. Open `http://127.0.0.1:3000` on this computer. The installed `backtest-web.cmd` command also works from other Windows Terminal folders. Keep the terminal open to see server logs. Press Ctrl+C to stop it. Repeating the command stops this project’s identified server and starts the latest committed main revision in the new terminal and watches it for updates. This also replaces any older background instance. Replacement waits for active requests to finish before it prepares data. If ownership is still held after 30 seconds, the command asks you to wait or stop the old terminal, then retry.

The server also saves development logs in `data/logs/website-<namespace>-<pid>.log`. The terminal and data panel show the current file. Logs keep error types, stack locations, file error codes, safe download context and operation times. Run `python3 -m tools.ops.log_summary` to summarize the times. They omit API keys, provider URLs, response bodies and arbitrary exception text. Each process keeps one active log and two rotated backups, up to about 5 MiB each. Startup removes logs with no write for 14 days, then the oldest stopped-process logs of this namespace beyond 50 files or 100 MiB. Active and uncertain logs are kept. Legacy and foreign-namespace logs are removed by age only. Protected files and growth between startups can exceed the targets. Cleanup errors do not stop startup.

The website opens with Latest stock picks. Switch to Historical backtest for
January books or custom trade dates with monthly, quarterly, half-yearly or
yearly rebalancing. `python3 website/build.py --snapshot` writes an untracked
portable export to `website/dist/`. Open its `index.html` directly for the saved
latest and January views; custom schedules use the local service.

Custom and random-date backtests run on the server. Locking your phone,
refreshing, or closing the page does not stop them. Reopen the same address in
the same browser to recover progress or the result. Use **Stop backtest** to
cancel. Keep the server computer awake and its terminal open. Temporary results
last 24 hours, up to four recent runs, until the server exits. Use **Save displayed
backtest** to keep a completed result in the library.

Select **Add to queue** beside **Run backtest** for overnight fixed or random-date
tests. From latest or January mode, the first click opens custom-date settings
and turns off Auto-run without starting a test. Set your parameters, then select
**Add to queue** again. Use **View queue** to see the list below the strategy
controls. Change parameters and add another test. Edit, hold, reorder
or delete waiting tests. Pause the queue to let the active test finish without
starting another. Stop cancels only the selected active test. Auto-run is
suspended while the queue has waiting or running work. Adding, copying or
editing a queue item also turns Auto-run off for continued batch setup.
Saved backtests offer 100 slots, stable IDs, rename and performance sorting.
Expand **All parameters** on a saved row to inspect its settings and filters.
Choose two saved tests and select **Compare** for recorded performance and
highlighted parameter differences. Comparison leaves the main result unchanged.
The queue, saved list and comparison tables scroll inside their sections.

Completed queue results move to Saved backtests automatically. Open them there
without calculating again. A full library or failed save keeps the complete
result in the queue while the server retries. No result is evicted.
Save or cancel an active edit before opening or copying another result. This
keeps the held test's draft parameters intact.
Reordering does not invalidate an edit. If a response is lost, the queue checks
the saved edit receipt or offers a retry of the same request. If another browser
ends the hold, your form becomes available and keeps its current settings.

The queue holds up to 100 visible records. Archived completions free queue space.
It persists in `data/backtest-queue.sqlite`. Keep this durable file and the saved
library during rebuilds and deployment. The queue is separate
from temporary manual runs and the 100-slot saved library. Server restart resumes
interrupted work with its recorded random dates; held edits stay held. Keep the
server computer awake and its terminal open overnight.

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

The website runs only the **Original** engine. The experimental (Numba) engine
is frozen in source: the website does not offer it, and the server refuses a
request that names it. Saved results from the experimental engine stay readable
with their producer label. The [frozen engine notes](docs/candidate-startup.md)
and the [faster engine summary](docs/plans/compiled-backtest/master-plan.md)
record its decisions and measured speeds. Historical timings are not a
current-source speed guarantee.

Custom ranking and filtering variables are part of `main`. Formulas combine
financial parameters with point-in-time measures and run with Original. Sample
preview uses Original reference execution. Eager scalar execution is unsupported.
See the [custom-variable summary](docs/plans/custom-variables/master-plan.md).

Records follow the [records policy](docs/records-policy.md).


## Run from the saved data

Python 3.10 or newer is required. Python scripts use only the standard library.
Run the saved-data commands below in the Windows runtime with native Python.
The WSL checkout runs source and synthetic checks; `python3 tools/deploy.py --check`
dispatches the full saved-data checks to Windows.

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

Commands above run from the runtime folder. Python scripts resolve data paths from their own location, so they also work when invoked by absolute path from another directory. Keep `raw/` with the Windows runtime. Subsequent screens and website builds query compact prepared records. The independent `backtest/engines/reference/revalue.py` reference run still reads raw prices.

## Project layout

```text
scripts/             Data preparation, screening, backtest, exit analysis, and paths
data/                Prepared local SQLite database (generated; ignored by Git)
website/             Website source, builder, hosting identity, and built output
  local/             Ignored local server output
  dist/              Ignored portable export from build.py --snapshot
results/
  summary-exits.txt  Current backtest result
  stops/             Early trading-stop analysis and filing classifications
  legacy/            Earlier results using the old exit rule
raw/                 Reusable universe, financial metrics, prices, SPY, Treasury data
  px/                One price-history file per stock
  archive/           Unused bulk downloads and exploratory responses
tools/              Deployment, operations, retained API probes and comparison runner
tests/              Calculation and path checks
docs/               Methodology, assumptions, and limitations
```

The [source map](docs/plans/project-structure/source-map.md) lists the owners of financial, input, engine, application, website and tool code. Browser assets live in `website/browser/`, static builds in `website/rendering/` and HTTP adapters in `website/server/`.

See [fast screening and backtesting](docs/research-workflow.md) for parameter examples, coverage limits, and the preparation/query separation.

## Current result

The current report is [results/summary-exits.txt](results/summary-exits.txt). From January 1996 to January 2026 it reports 18.01% annualized for the strategy versus 10.22% for SPY. These are historical backtest results, with no commissions.

[Methodology and limitations](docs/methodology.md) explain the universe, report lag, valuation adjustments, data issues, and exit treatment. The earlier `results/legacy/` reports are retained for reference and are not the current result.

## Cache and downloads

Normal backtest and website runs are offline and reuse `raw/`. No API key is required for those operations. See [raw/README.md](raw/README.md) for cache contents.

`backtest/engines/reference/legacy.py` may fetch missing data and writes the **legacy** reports. Use it only when the cache needs additional data; its exit rule still differs from the current `backtest/engines/reference/revalue.py`. API credentials remain outside this project at `~/.grok/secrets/fmp_api_key` and are read only when the main downloader makes a request. [tools/README.md](tools/README.md) describes the exploratory scripts; do not run them as part of normal analysis.

The local website is ready to use. Hosted publication has not completed because the current environment cannot reach the Sites source server. Preserve `website/.openai/hosting.json` when retrying publication.

## Version control in this environment

The authoritative WSL checkout has a `.git` pointer to the preserved `.git-local/`
history. Ordinary `git status`, `git diff` and `git commit` work there. The Windows
runtime is a deployment, with its exact source commit in `data/deployment.json`.
It has no second repository. The following explicit form also works in the WSL
checkout and is required for the retained original folder's read-only `.git/` mount:

```bash
git --git-dir=.git-local --work-tree=. status
git --git-dir=.git-local --work-tree=. log --oneline
```

Use the same options for diff, add and commit. If the default Git wrapper fails with a WSL socket error, use `/usr/bin/git` with these options. Do not initialize a new repository over the saved history.

Source and reviewed reports are versioned. The portable export in `website/dist/` is ignored. Downloaded data in `raw/` stays local to Windows and is excluded, apart from its README files. Back up the cache separately. Collect a changed verified runtime report with `python3 tools/deploy.py --collect-report` before reviewing and committing it. The unused, uncommitted website Git metadata is preserved in `.git-local/website-repository-backup/`.

## Local builds and portable snapshots

Builds write ignored `website/local/`. `python3 website/build.py --snapshot` writes the untracked export in `website/dist/`. See [website/README.md](website/README.md#local-builds-and-portable-snapshots).
