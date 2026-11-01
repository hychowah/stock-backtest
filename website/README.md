# January strategy screener

Double-click `../start.cmd` on Windows, or run `python3 website/serve.py` from the project root. The launcher refreshes stale caches, rebuilds the website if needed, starts the service and opens the browser. Unchanged caches are reused; no API key or market-data downloads are needed. Opening `dist/index.html` directly still supports the saved latest and January views.

## Automatic updates

The registered Windows `backtest-web.cmd` starts the latest committed main and
checks for new main commits every two seconds. A new commit automatically
deploys and restarts the native server in the same terminal. Uncommitted saves
and the engine branch do not trigger updates. Git is not fetched or pulled.
Refresh the browser page after the server reports it is ready. Subsequent
restarts do not open another tab.

The archive is staged before shutdown. Server cleanup finishes before source
replacement. An active manual run stops; interrupted queued work returns to
waiting with its recorded dates. Saved backtests and raw data are preserved.
Unavailable Git keeps the current server; a failed update retries automatically.
Use `python3 tools/deploy.py --revision <commit> --start` from WSL for a fixed
revision without watching. Ctrl+C stops the watcher and its server.

## Basic workflow

1. Choose **Latest stock picks** or **Historical backtest**, then choose **Original candidate set** to retain the original 250-name pre-price screen, or **All stocks with cached prices** for broader filters. The broader set is not the full universe.
2. Choose a ranking metric (EV/EBITDA is the default). Enter market-cap bounds and minimum enterprise value in **millions of USD**, minimum selected metric yield in **percent**, and optionally a maximum selected multiple, sector or exchange.
3. Use **Additional filters → + Add filter** to combine metric, **Less than** or **More than**, and value conditions. All conditions must pass at your chosen selection stage. Two conditions on one metric create a range. Comparisons are strict. A stock with a missing value fails the condition that needs it. Values use each label’s units: millions of USD, percent or multiples. Enter 10 for a 10% trailing return. Available filters include 1-year and 3-year trailing returns, size and EBITDA multiples/yield. Financial filters include P/E, P/B, FCF amount/yield, price/FCF, net profit margin, historical PEG, ROE, current ratio, interest coverage and debt/equity. Download Full annual financial data and rebuild to supply their inputs.
4. Choose inclusive ranks in either mode, and book years in historical mode. Choose **Selection order**: **Filter first, then rank** (default), or **Rank first, then filter**. The second option filters only the requested shortlist, keeps original ranks and adds no replacements. Rank 1 has the lowest selected valuation multiple in the ranking scope. Top 50 and Top 100 are shortcuts; ranks 10–20 select up to 11 stocks each year.
5. Click **Screen latest** or **Run backtest** for the chosen mode. Year and rank changes also update the current filters. Reset strategy restores original filters and ranks 1–50 while preserving the chosen years.

The order choice applies to all user filters, including size, sector and additional conditions. Both options start from the same prepared stock pool. If 20 stocks pass after selecting the top 50, each receives 5% weight. Saved results and queued tests retain the submitted order. Older saved results restore filter-first. Changing the order reuses prepared books.

The saved January view reselects and equally weights stocks every January. Custom calendars rebalance on the selected fixed or random schedule. Charts, returns, CAGR, growth of $1, median market cap, and stock tables update together. CSV download links export the **current selection**. Sector and exchange are cached company metadata, not historical classifications.

If fewer stocks match than requested, the available picks receive equal weights and short years are listed. A year with no matches displays no strategy return; CAGR and cumulative strategy growth are unavailable for a period containing an empty book. SPY continues to show the full selected period. This is distinct from the CLI's explicitly labelled populated-book compounding. Early stops outside the original top-50 review are flagged when selected.

## Manage backtest data

Choose **Manage backtest data** from the strategy builder. Select a stock group,
optional symbols, price-history dates and data types. **Check data** reports
actual date spans, missing financial symbols, empty histories and prepared-data
freshness. Export the full check as JSON when needed.

Use **Download missing data**, then **Rebuild prepared data + website**, then
open the strategy builder. Downloads use the local FMP key file and preserve
valid cached records. Checks and rebuilds are offline. No download starts when
the panel opens. Downloads run up to 32 requests in parallel. A shared cap permits
45 request starts per second (2,700/minute) for this account's stated 3,000/minute
allowance. Connections are reused. Gzip responses reduce transferred bytes and
are decoded before validation; plain responses also work. A 429 response pauses
all workers and reduces the start rate. One writer saves each result. Cancel keeps completed windows, stops new requests and interrupts retry waits. A retry also fills unfinished managed windows inside an expanded date span.
Completion evidence belongs to the exact saved file; loss or corruption cannot
leave missing data falsely complete. Short histories may reflect IPOs or stops.
The downloader does not refresh existing reports/profiles or repair internal
price gaps. Full annual financial data downloads income, balance-sheet, cash-flow, key-metrics and ratios responses for the chosen group. It retains every returned field, null, currency and filing metadata in the raw cache. New key-metric records also keep full responses. Older trimmed key metrics can be backfilled separately. Prepared calculations use eligible USD inputs; future metrics can reuse the other saved fields.

If essential source files are missing or invalid, startup opens this panel for
recovery. The page is served from current source at `/data.html`; opening the
built HTML directly provides local-service instructions. See the detailed
[data workflow](../docs/research-workflow.md#data-control-panel).

The **Sales × 3-year avg operating margin / EV − US 10Y (pp)** filter uses
the selected annual revenue multiplied by the simple average of three annual
operating margins, divided by screen-date EV. An annual operating margin is
operating income divided by revenue. The three fiscal years must be consecutive
and end at the selected report. Subtract the latest saved US 10-year Treasury
yield on or before the screen date. Enter 5 for a spread of 5 percentage points.
Missing history or Treasury values fail this condition. Negative margins and
spreads remain valid. This filter follows the chosen selection order in both pools and all
four views. Installing this change requires an offline rebuild of research,
daily data and the website. It reuses full annual statement assets and saved
Treasury curves. See the [formula and data rules](../docs/research-workflow.md#sales-based-operating-yield-spread).

## Rebuild from saved data

```bash
python3 scripts/research.py prepare
python3 website/build.py
```

Preparation is only needed after changing data or calculation code. The builder queries the compact SQLite database, exports both pools as compact tuples, and embeds them in HTML. Changing screen parameters runs locally in JavaScript without reparsing prices. Stock tables are rendered when a year is opened to avoid creating thousands of hidden rows for large portfolios.

The original top-50 result and tables remain embedded as a fallback for previews that block JavaScript. Interactive screening requires JavaScript. `dist/returns.csv`, `dist/holdings.csv`, and `dist/valuations.json` retain the baseline exports; browser-generated CSV downloads contain the selected strategy. The original canonical report remains `../results/summary-exits.txt` and is never overwritten by screening.

The 2026 book is partial through 20 October 2026. Other book years are January-to-January, not calendar-year returns. Strategy and SPY returns in the interactive screener use full-precision prepared values.

## Checks

```bash
node tests/check-range.cjs
python3 tests/check_screener.py
python3 tests/test_data_manager.py
python3 tests/test_fmp_download.py
python3 tests/test_cache_access.py
node tests/check-data-panel.cjs
```

The first checks controls and rendering using a simulated DOM. The second compares browser selection directly with SQLite across historical and latest configurations, including combined conditions, short and empty years. It requires the current prepared database. These checks do not replace a real-browser appearance check.

A private Sites project is registered in `.openai/hosting.json`. Hosted publication remains blocked by source-host access from this environment. Preserve the project ID when retrying.

## Per-year return contributions

The latest selected year opens automatically in Explore the selected stocks. Choose another year or expand its entry to see gain/loss contribution pies, the top 10 contributors, and the full stock table. These views update with the current screen and rank range.

Contribution equals stock holding return divided by the actual number of selected stocks, expressed in percentage points of portfolio return. Contributions sum to the year's strategy return. Top 10 means the ten stocks with the highest signed contributions, regardless of portfolio size. If fewer than ten stocks are selected, all of them are shown. In an all-loss book, these are the smallest losses. This is historical attribution, not a new picking rule.

Gains and losses use separate pie charts so no negative slice is implied. Each pie is normalized to that side's total; it is not a percentage of the net portfolio return. Named slices are the top contributors; remaining gainers and losers are grouped separately. Zero-return stocks have no slice. The facts above the charts reconcile top contributors and other stocks to net return.

The full table includes a contribution column. Browser holdings CSV exports add fractional initial weight and `contribution_pp`. Static original-book pies and top-contributor tables are included for previews without JavaScript; baseline CSV files retain their original columns. Attribution is calculated when a year's stock table opens.

```bash
node tests/check-contributions.cjs
python3 tests/test_attribution.py
```

These cover signed contributions, the top-10 stock limit, positive/negative/zero/empty books, deterministic ties, input preservation, and the static fallback. Existing range/control tests also check year switching and attribution updates.

## Latest stock picks

The website opens in **Latest stock picks** mode. Historical backtest remains available in the view switch. The same size, valuation, sector, exchange, universe and rank controls apply in either mode. The latest view shows a current selection, with no holding returns or attribution charts because those outcomes do not exist yet.

The displayed date comes from the latest cached SPY session. Read the date above the latest stock table. Only companies marked currently listed in the cached universe, with a dividend-adjusted price on that exact session, are included. Earlier last-trade prices are not carried forward. The annual figure must be available under the existing strict 90-day lag and no more than 800 days old. Market cap and EV are revalued at the latest price using report net debt and the same adjusted-price method as the historical model.

Latest mode has separate prepared records for the original 250-candidate pool and all eligible cached-price companies. Both remain incomplete representations of the full market. The coverage line shows how many active names have financials and how many can be valued from current cached prices. Available-from dates are assumptions based on fiscal year-end, not verified filing dates. Listing status, sector and exchange are cached metadata.

Click **Screen latest**, **Top 50**, or **Top 100**. Download latest picks exports the currently selected stocks, including valuation date, adjusted price, estimated market cap/EV, ratios, fiscal date, and assumed availability date. `dist/latest-picks.csv` is the default-settings fallback export generated at build time; browser downloads reflect the current filters. The latest table is also embedded as a no-JavaScript fallback.

Updating source caches does not update an already-open standalone HTML file. Run `python3 scripts/research.py prepare` and `python3 website/build.py` for the local server, then reload the page. To refresh a standalone file in `dist/`, use `python3 website/build.py --snapshot` explicitly. These commands never download data. Future latest sessions are prepared independently of the canonical backtest's saved Through date, so new current prices do not silently extend the old report.

## Ranking metrics

Choose **EV / EBITDA** (current-date valuation) or **EV / 3-year average EBITDA**
(current EV divided by mean EBITDA from three consecutive annual reports). Lower multiples rank first;
minimum selected yield is the reciprocal of the multiple. A missing annual
report excludes the stock from the three-year metric. Both latest and historical
modes use only reports eligible at their screening date. Selected stock tables
and CSV exports show the chosen signal. For a broader comparison, use all stocks
with cached prices: the original candidate set retains its single-year pre-screen.
See `../docs/research-workflow.md` for calculation and extension details.

## Custom trade dates and frequency

Double-click `../start.cmd`, or run `python3 website/serve.py`. The dependency
chain is automatic; no separate preparation commands are needed. The browser
opens at the successfully bound local address. The default listener is `0.0.0.0:3000`. The browser uses `http://127.0.0.1:3000` on this computer. `--host` and `--port` select another listener. If an unknown process owns the port, the service uses an available port. Use the browser tab opened by the launcher or its printed address. Under **Historical backtest**, choose **Custom trade date
and frequency**. Set the first trade date, end/mark date, and monthly, quarterly,
half-yearly or yearly rebalance interval, then click **Run backtest**.

Rebalances stay anchored to the starting day, clamp invalid month ends, and roll
to the next cached SPY session. The final mark rolls back to an available session;
the last period can be partial. The chart and stock explorer use dated holding
periods, with contribution pies and CSV downloads for the current schedule.
Prices, financial availability, filters and valuation calculations use the saved
cache. Dated books are persisted, so changing filters does not reparse prices.
Each run prepares only its selected stock universe. Switching universes can take
longer the first time because it prepares the other pool; later runs reuse it.
The launcher retains existing completed books when upgrading the daily cache.

Custom schedules require the local service; opening the HTML directly continues
to support January backtests and latest picks. Daily preparation can take longer
than January preparation and adds a local SQLite index; it never downloads data.
See `../docs/research-workflow.md` for timing and calculation semantics.

While a custom backtest runs, the page shows a spinner, elapsed time and the
requested date range. Strategy controls are temporarily disabled to prevent
repeat submissions. Existing results are explicitly labelled as previous results
until the new run completes. Success, server errors and connection failures clear
the loading state and restore the controls.

You can close the server during a backtest. Restart the launcher and run the
schedule again: unfinished cache writes roll back, while previously committed
books and original price/financial data remain intact. The unfinished request is
not resumed automatically. Shutdown coverage in `tests/test_schedules.py` includes
both a `KeyboardInterrupt` and killing a subprocess with an uncommitted SQLite
period, followed by integrity checks and a successful retry.

## Random-date sensitivity

In custom historical mode, select **Random date at every rebalance**. Choose
**Random trials** (1–100, default 24). Each run draws fresh random dates by default.
Under **Advanced**, optionally enable **Repeat the same dates** to use a fixed
date-set number (seed), or replay a number from earlier results. Every trial draws
one trading session independently from each frequency-sized block, including
the last partial block. Yearly means blocks of 12 months; **Every 2 years** uses
24-month blocks. Holding intervals therefore vary around the nominal frequency.
In repeat mode, the same date-set number, window and frequency reproduce the
same trade dates when comparing metrics or filters.

All trials use a common start/end window. Strategy and paired SPY hold zero-return
cash until that trial's first sampled trade. The screen reports mean and median
CAGR, paired SPY, percentiles, range, population standard deviation, total-return
and ending-value distributions. Incomplete trials remain visible and are excluded
from both paired summary distributions. These overlapping historical scenarios
are not independent observations or confidence intervals; mean CAGR describes
trial CAGRs, not one investment portfolio.

The batch plans shared missing books upfront. Worker processes calculate books
in parallel from read-only SQLite connections. One parent saves complete trials
in order. The progress bar counts completed trials; a separate book count and
worker count show preparation ahead of those saves. Cached replays start no
workers. Results include each trial's actual
trade dates in the CSV. Select a trial and click **Show stocks and period returns**
to inspect its usual stock tables and contribution charts. Completed trial books
survive an interrupted batch; restart the launcher and rerun the same seed.

On Windows, `backtest-web.cmd` and `start.cmd` use managed startup. A new launch
stops this project’s identified server and starts current code in the invoking
terminal. Replacement waits up to 30 seconds for the previous listener and
request threads to release ownership. If they remain active, wait or stop the
old terminal, then retry. An unknown port owner stays running; the new instance
uses an available port. Direct `python3 website/serve.py` starts a foreground
server without replacing an existing server. Add `--managed` to request replacement.
Use the opened browser tab; refreshing an old tab does not reload Python server
code. Unsupported API routes display a relaunch instruction rather than only
“Unknown endpoint”.

After a random batch completes, Advanced remembers its date-set number. Checking
**Repeat the same dates** then replays that batch's dates with the same window
and frequency. Leaving it unchecked draws fresh dates, without needing a number.

## Development diagnostics

Each server process saves `data/logs/website-<namespace>-<pid>.log`. Startup and the data panel show the current path. The files record startup, job completion or failure, provider status and retries, saved windows, and file publication retries. Error chains include exception types, OS codes and stack locations. Messages, source lines, locals, API keys, provider URLs and response bodies are omitted. Logs use UTC timestamps. Each process keeps a 5 MiB active file and two rotated backups. Startup removes stopped-process logs older than 14 days, then removes the oldest stopped-process logs to target 100 MiB total. Running or inaccessible process logs are kept. Namespace-qualified names separate Windows machines and Linux boot/PID namespaces. Legacy logs, foreign namespaces and unknown ownership are kept and count toward the size target. Deletion errors do not stop startup. Protected files and growth between starts can exceed the target. Logs stay local and are ignored by Git.

Windows file indexers can briefly lock cache files. Atomic JSON publication retries access or sharing errors up to eight times, with less than two seconds of total retry waits. Other file errors fail immediately. The existing cache owner remains held. Receipts still publish before their corresponding assets. Persistent failures keep the previous saved data and record the error location in the log.

Check with `python3 tests/test_diagnostics.py`, `python3 tests/test_data_manager.py` and `python3 tests/test_startup.py`. Run these checks on native Windows too.


Rebuilds verify the January baseline with two independent engines at the saved
Through date. Agreement permits a revised report. The previous report and priced
holdings remain in `../results/baseline-history/`. The data panel shows the last
revision after a check or rebuild. **Export baseline revision** downloads its
old/new holdings, prices and returns as JSON. First-run unknown old prices stay
null. Engine disagreement leaves the prior report, database and website intact.
An interrupted file replacement requires retrying preparation; readers reject
its unfinished publication journal. Standalone `build.py` takes cache ownership;
managed children receive `--cache-owned` from their owning parent.

## Local builds and portable snapshots

Normal builds, startup and data-panel rebuilds write ignored `website/local/`. The server uses this output. They do not change the tracked portable snapshot in `website/dist/`.

Run `python3 website/build.py --snapshot` to refresh the portable snapshot explicitly after preparing data. Review and commit that refresh deliberately. Each build writes `snapshot.json` with the historical report cutoff, latest screen date, report hash and website source hashes. An already-open page needs a reload.

Range and SQL/browser parity checks use local output by default. To check the portable snapshot, run `node tests/check-range.cjs website/dist` and `python3 tests/check_screener.py website/dist`.

## Save and reopen completed backtests

Use **Save displayed backtest** after a historical run. Give it a name if useful.
The save keeps the settings used for the displayed result, all traded stocks,
and all stock and period returns. Pending control edits are not included.
A stopped or failed run does not replace the last completed result.

Open **Manage saved backtests** to reopen a record. Opening restores its
settings, charts, stock tables and downloads without rerunning a calculation.
Records stay available after browser and server restarts. They are stored on the
server computer in `data/saved-backtests.sqlite`, outside the rebuildable caches.
The library is shared by browser sessions using that runtime. A saved HTML file
needs the local service to use the library.

Each row shows its stable UUID database ID. Select **Rename**, edit the name,
then **Save name** or **Cancel**. Renaming changes no settings or stored results.
Use **Sort saved backtests** for newest saved or performance in either direction.
Performance means CAGR for January/fixed tests and mean trial CAGR for random
tests. Different test types and date windows can differ. Missing values stay last.
The queue and library lists scroll inside their sections. Their controls remain
outside the scrolling list. Keyboard users can focus each list and scroll it.

Completed queue tests move into this library automatically. The server saves a
complete independent result before removing it from the visible queue. This also
runs while the execution queue is paused or its engine is unavailable. A full
library shows **Completed — waiting for saved slot** in the queue. Other save
failures retain the result and show a retry notice. Free a saved slot to let the
server retry without recalculation. Failed and stopped tests stay in the queue.
Deletion during an active transfer asks you to refresh and retry. A transferred
record appears once, even after interruption. Later rename or deletion is kept
when transfer recovery retries. Original queued submission receipts remain valid
but never restart or redisplay archived tests. Active result readers keep their
original bytes when duplicate queue evidence is released.

The maximum is 100 records. When full, delete a chosen record before saving
another. Deletion asks for confirmation and removes only that record. It does
not remove the result currently displayed in the page.

Check with `python3 tests/test_saved_backtests.py`,
`node tests/check-saved-backtests.cjs`, `python3 tests/test_queue_transfer.py`,
and the ordinary queue and range controls checks.
Run the persistence checks with native Windows Python too.

Random-date saves include every trial's exact trade dates, stock rows and period
returns, plus the seed and distribution summary. Trial inspection uses these
stored rows. It does not recalculate the book. Current background jobs and queued
random tests capture full trial holdings through `backtest_jobs.calculate`.
Existing `/api/robustness` streaming clients can opt into full trial results with
`X-Backtest-Details: holdings`. Summary-only clients keep their existing response. Save a completed new run; older summary-only
results do not contain enough evidence for a complete random backtest record.

### Completed-result ownership and saved-record compatibility

`result-artifacts.js` owns one immutable completed artifact per view. Its submitted
settings, result, catalog and semantic presentation context travel together.
Fresh calculation and saved-record opening use the same publication and rendering
path. Renderers, downloads, stale-setting notices and the library read this
artifact. The library owns record operations and the shared record list.

Version-2 saved snapshots store coverage text, warning severity, range notes and
period labels without page selectors or CSS classes. The browser decodes
version-1 records into this format when opening them. Stored version-1 records
are not rewritten. Saved labels take precedence while displaying saved results.
New calculations use the current catalog. Random trial inspection reads the
selected trial from the same completed artifact.

An acknowledged save or deletion updates the visible list immediately. A
background refresh reconciles other sessions' records. A refresh failure reports
that the action succeeded and the list could not be refreshed. Older list
responses cannot replace a newer acknowledged change.

Check `node tests/check-result-artifacts.cjs` alongside the saved-library and range
checks. The library checks include failed refreshes and out-of-order responses.


### Selectable dated engines

Current source offers Original (default) and New engine — experimental for
custom dated fixed/random runs. January and latest screens keep their paths.
Normal startup and ordinary rebuild require no numerical packages. Use the
separate Prepare experimental engine action in Manage backtest data after
installing the pinned optional stack. See [preparation and recovery](../docs/candidate-startup.md#normal-app-selectable-engines-cb-15-source).

The submitted engine stays with manual jobs, queued tests, retries and replay.
Original accepts monthly presets. Custom week/month calendars require the
experimental engine. Experimental operating yield spread fails explicitly.
New results and CSVs identify their recorded producer; older evidence remains
unidentified. Opening stored evidence does not calculate. No automatic fallback
or default replacement is provided. CB-15 source is not a deployed release.
