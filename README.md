# EBITDA/EV stock backtest

A standalone US stock backtest and interactive results website. Screen US stocks by EBITDA/enterprise value or custom variables, then test the selected stocks on fixed or random dated schedules, equally weighted, against SPY with dividends included. The original study bought the 50 highest EBITDA/EV stocks each January from 1996; its frozen result covers 1996 through 20 October 2026.

## Open the website

Source development lives in this repository's WSL checkout; edit and commit there.
The native Windows runtime is a separate deployed export of the same source.
Start the native runtime with `python3 tools/deploy.py --start`, or run the
installed `backtest-web.cmd` from Windows Terminal. Startup serves the installed
revision. At 07:00 Hong Kong time it updates committed `main`, refreshes FMP
data and prepares the website. A missed schedule waits until the next day.
Add `--latest` to update source at launch. See [workspace commands and ownership](docs/workspaces.md).

Use `python3 tools/deploy.py --revision <commit> --start` to fix one launch to
that revision. Standalone publication without `--start` retains the installed
revision. A fresh standalone runtime requires an explicit revision. See
the same document for recovery and the source-only explicit-argument
forwarding limit.

On Windows, run **`backtest-web.cmd`** from the runtime folder, or double-click **`start.cmd`**. It prepares stale local caches in order,
rebuilds the website when needed, starts the local service, and opens your browser.
A standalone installation on another system can run `python3 website/serve.py` in the foreground with its own cache. In this split workspace, use the native Windows runtime. No API key or market-data
download is needed; unchanged caches are reused. The first refresh can take a
few minutes. The Windows command keeps the server attached to the terminal on `0.0.0.0:3000`. Open `http://127.0.0.1:3000` on this computer. The installed `backtest-web.cmd` command also works from other Windows Terminal folders. Keep the terminal open to see server logs. Press Ctrl+C to stop it. Repeating the command stops this project’s identified server and starts a new one in the new terminal. This also replaces any older background instance. Replacement waits for active requests to finish before it prepares data. If ownership is still held after 30 seconds, the command asks you to wait or stop the old terminal, then retry.

The server also saves development logs in `data/logs/`. The terminal and data panel show the current file. Logs keep safe error traces and operation times, never API keys, provider URLs, response bodies or exception text. Startup removes old logs. Run `python3 -m tools.ops.log_summary` to see where the time goes. The [development log](docs/architecture-guide/dist/index.html#development-log) section of the architecture guide has the details.

The website opens with Latest stock picks. Switch to Historical backtest for
custom trade dates with monthly, quarterly, half-yearly or yearly rebalancing; a
January study is a 12-month schedule from 1 January. Saved January results open
in that dated view without calculation. `python3 website/build.py --snapshot`
writes an untracked portable export to `website/dist/`. Open its `index.html`
directly for the saved latest view; backtests use the local service.

Custom and random-date backtests run on the server. Locking your phone,
refreshing, or closing the page does not stop them. Reopen the same address in
the same browser to recover progress or the result. Use **Stop backtest** to
cancel. Keep the server computer awake and its terminal open. Temporary results
last 24 hours, up to four recent runs, until the server exits. Use **Save original
backtest** to keep a completed result in the library.

Open **Explore this result** to inspect a shorter saved time window or a smaller
rank range without another backtest. For random tests, **Explore all trials**
opens above the combined summary. For example, select 2010–2015 and ranks 20–30
within a saved 24-trial, 2000–2025, top-50 result. Apply updates each trial,
combined statistics and the distribution chart. Dates select saved rebalance
blocks; the summary shows the actual shared window. Reset restores the original
summary. Empty selections hold cash at 0% until rebalance; SPY keeps its period
return. Holding details, downloads, comparisons and saving use the original
completed result.

Select **Add to queue** beside **Run backtest** for overnight fixed or random-date
tests. From latest mode, the first click opens the dated backtest settings
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
Every research rebuild is a full build; a failure keeps the previous database. No download starts when the panel opens. If essential source files are missing,
startup opens the data panel for recovery. See [the data workflow](docs/research-workflow.md#data-control-panel).

Random-date batches plan missing books once, calculate ahead with separate Python
processes, and save complete trials through one SQLite writer. Replays reuse
saved books. Filters, metrics and stock counts share the ordinary screening rules.

For an explanation of the program, open the [plain-language architecture guide](docs/architecture-guide/dist/index.html).
It is a separate static website. It works offline and includes diagrams, setting
examples, a file map and the measured speed comparisons.

The website runs only the **Original** engine. The source has no experimental
(Numba) engine. The server refuses a request that names it. Saved results from
the experimental engine stay readable with their producer label. The
[faster engine summary](docs/plans/compiled-backtest/master-plan.md) records its
decisions and measured speeds. Historical timings are not a
current-source speed guarantee.

Custom ranking and filtering variables are part of `main`. Formulas combine
financial parameters with point-in-time measures and run with Original. Sample
preview uses Original. Eager scalar execution is unsupported.
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

# Show the database size and latest price coverage
python3 scripts/research.py status

# Rebuild ignored local output from the prepared latest screen
python3 website/build.py

# Check rank filtering and result presentation (requires Node.js)
node tests/check-range.cjs
python3 tests/check_screener.py

# Check project paths, imports, and cache-only operation
python3 tests/check_paths.py
```

Commands above run from the runtime folder. Python scripts resolve data paths from their own location, so they also work when invoked by absolute path from another directory. Keep `raw/` with the Windows runtime. Subsequent screens and website builds query compact prepared records.

After a change to book policy, run the development check, `python3 scripts/check.py`, on a real-data copy; it must find 0 differences. See [the research workflow](docs/research-workflow.md#development-check).

## Project layout

```text
scripts/             Data preparation, daily cache and the development check
data/                Prepared local SQLite databases (generated; ignored by Git)
website/             Website source, builder, and built output
  local/             Ignored local server output
  dist/              Ignored portable export from build.py --snapshot
results/             Frozen January record and cited experiment summaries
  summary-exits.txt  The January study result (frozen)
  stops/             Early trading-stop analysis and filing classifications (frozen)
  legacy/            Earlier results using the old exit rule (frozen)
raw/                 Reusable universe, financial metrics, prices, SPY, Treasury data
  px/                One price-history file per stock
  archive/           Unused bulk downloads and exploratory responses
tools/              Deployment, operations and retained API probes
tests/              Calculation and path checks
docs/               Methodology, assumptions, and limitations
```

The [source map](docs/plans/project-structure/source-map.md) lists the owners of financial, input, engine, application, website and tool code. Browser assets live in `website/browser/`, static builds in `website/rendering/` and HTTP adapters in `website/server/`.

See [fast screening and backtesting](docs/research-workflow.md) for parameter examples, coverage limits, and the preparation/query separation.

## The January record

The frozen report of the original study is [results/summary-exits.txt](results/summary-exits.txt). From January 1996 to January 2026 it reports 18.01% annualized for the strategy versus 10.22% for SPY. These are historical backtest results, with no commissions. Nothing regenerates it; run the study again as a 12-month schedule from 1 January.

[Methodology and limitations](docs/methodology.md) explain the universe, report lag, valuation adjustments, data issues, and exit treatment. The earlier `results/legacy/` reports are retained for reference and are not the study result.

## Cache and downloads

Normal backtest and website runs are offline and reuse `raw/`. No API key is required for those operations. See [raw/README.md](raw/README.md) for cache contents.

Fill missing data with **Download missing data** in the data panel. API credentials remain outside this project at `~/.grok/secrets/fmp_api_key` and are read only when that downloader makes a request. [tools/README.md](tools/README.md) describes the exploratory scripts; do not run them as part of normal analysis.

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

Source and the frozen reports are versioned. The portable export in `website/dist/` is ignored. Downloaded data in `raw/` stays local to Windows and is excluded, apart from its README files. Back up the cache separately. The unused, uncommitted website Git metadata is preserved in `.git-local/website-repository-backup/`.

## Local builds and portable snapshots

Builds write ignored `website/local/`. `python3 website/build.py --snapshot` writes the untracked export in `website/dist/`. See [website/README.md](website/README.md#local-builds-and-portable-snapshots).
