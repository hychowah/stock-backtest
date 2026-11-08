# Strategy screener

Double-click `../start.cmd` on Windows, or run `python3 website/serve.py` from the project root. The launcher refreshes stale caches, rebuilds the website if needed, starts the service and opens the browser. Unchanged caches are reused; no API key or market-data downloads are needed. A portable export built with `python3 website/build.py --snapshot` opens directly from `dist/index.html` and supports the saved latest view.

## Automatic updates

The registered Windows `backtest-web.cmd` serves the installed revision and
updates committed main and refreshes FMP data daily at 07:00 Hong Kong time.
It refreshes data even when main has no new commit. A missed schedule waits
until the next day; launch and resume do not catch up. `--latest` updates
source at launch. Maintenance restarts the native server in the same terminal. Uncommitted saves
and other branches do not trigger updates. Remote history is not fetched or pulled.
Refresh the browser page after the server reports it is ready. Subsequent
restarts do not open another tab.

The archive is staged before shutdown. Server cleanup finishes before source
replacement. An active manual run stops; interrupted queued work returns to
waiting with its recorded dates. Saved backtests and raw data are preserved.
Unavailable Git keeps the installed source revision; data refresh still runs.
A failed source publication retries automatically.
Use `python3 tools/deploy.py --revision <commit> --start` from WSL for a fixed
revision without watching. Ctrl+C stops the watcher and its server.

## Basic workflow

1. Choose **Latest stock picks** or **Historical backtest**, then choose **Original candidate set** to retain the original 250-name pre-price screen, or **All stocks with cached prices** for broader filters. The broader set is not the full universe.
2. Choose a ranking metric (EV/EBITDA is the default). Enter market-cap bounds and minimum enterprise value in **millions of USD**, minimum selected metric yield in **percent**, and optionally a maximum selected multiple, sector or exchange.
3. Use **Additional filters → + Add filter**. Type in the new row to search one list of built-in filters, saved variables, measures and financial parameters, then choose **More than** or **Less than** and a value. Built-in filters work offline; a variable, measure or parameter makes the strategy run on the local service, and auto-run pauses. All conditions must pass at your chosen selection stage. Two conditions on one item create a range. Comparisons are strict. A stock with a missing value fails the condition that needs it. Values use each label’s units: millions of USD, percent or multiples. Enter 10 for a 10% trailing return. Available filters include 1-year and 3-year trailing returns, size and EBITDA multiples/yield. Financial filters include P/E, P/B, FCF amount/yield, price/FCF, net profit margin, historical PEG, ROE, current ratio, interest coverage and debt/equity. Choose **Manage backtest data → Update data** to get their inputs and prepare them automatically.
4. Choose inclusive ranks in either mode. Choose **Selection order**: **Filter first, then rank** (default), or **Rank first, then filter**. The second option filters only the requested shortlist, keeps original ranks and adds no replacements. Rank 1 has the lowest selected valuation multiple in the ranking scope. Top 50 and Top 100 are shortcuts; ranks 10–20 select up to 11 stocks at each rebalance.
5. Click **Screen latest** or **Run backtest** for the chosen mode. Opening **Historical backtest** runs nothing by itself. Reset strategy restores original filters and ranks 1–50 while preserving the chosen dates.

The order choice applies to all user filters, including size, sector and additional conditions. Both options start from the same prepared stock pool. If 20 stocks pass after selecting the top 50, each receives 5% weight. Saved results and queued tests retain the submitted order. Older saved results restore filter-first. Changing the order reuses prepared books.

Backtests rebalance on the selected fixed or random schedule; a January study is a 12-month schedule from 1 January. There is no separate January view. A saved January result opens in the dated view without calculation: its book years become periods, labelled by book year where no period dates were stored. Charts, returns, CAGR, growth of $1 and stock tables update together. CSV download links export the **original completed result**. Exploration selections do not change an export. Sector and exchange are cached company metadata, not historical classifications.

If fewer stocks match than requested, the available picks receive equal weights and short periods are counted. A complete period with no matches holds cash at 0% until the next rebalance. SPY keeps its period return. CAGR includes the full elapsed window.

## Explore a completed result

Open **Explore this result** in the dated result panel. Choose **From entry**,
**Through exit / mark**, **From rank** and **Through rank**, then select **Apply**.
For example, a saved 1997–2025 top-30 test can show the periods from 2008 to
2016 and ranks 20–30. Each date comes from an original holding-period boundary.
The panel shows strategy and paired SPY total return and CAGR. It uses saved
returns and runs no new backtest.

Ranks retain their meaning at each rebalance. A smaller range gives equal
weight to the holdings that remain. Missing ranks receive no replacements.
An empty selected period holds cash at 0%; SPY keeps its saved period return.
The trial table reports empty-period counts. Older saved originals keep their
recorded totals; select Apply to derive a cash-based summary.
Older January results can have year-only boundaries; those selections have
no CAGR when exact dates were not saved.

Random-date results show **Explore all trials** above the combined summary.
One selection updates every trial, the combined statistics and distribution
chart. Choose saved entry and exit blocks. Each trial keeps its own trade dates.
The summary shows the shared window, with cash before each first selected trade
and after each last selected exit for both strategy and SPY.

**Reset to original** restores the recorded summary. Holding details, downloads,
comparisons and **Save original backtest** use the original completed result.

## Manage backtest data

Choose **Manage backtest data**, then **Update data**. The app checks for
missing inputs and newer reports, updates prices and prepares the data and
website automatically. It maintains saved stocks and new eligible listings.
Saved price receipts also identify managed stocks whose files need replacing.
Saved backtests and queue records stay unchanged.

The main card shows overall estimated completion, elapsed time and estimated
time remaining. Preparation participates in the estimate. Estimates use the last successful update with the same scope and live stage
counts. Without a matching success, they show Estimating time remaining. Per-stock messages
and logs stay under **Details**. The latest SPY date and last successful update
are separate; an empty provider response cannot invent a newer session.

Close or reload the page without stopping the update. The page reconnects and
shows the same operation. Connection loss marks estimates as Last seen. Stop
update waits for safe cleanup and keeps completed work. After a server or
computer shutdown, use **Continue update**. It verifies saved evidence and
reuses matching work. Recorded running time excludes the stopped interval.
Opening the page and ordinary startup never initiate market-data downloads.

**More options** selects stocks and price-history dates for **Update selected
stocks and history**. This action prepares its inputs automatically. The main
Update data button maintains full managed coverage independently of those
controls. **Details** contains checks, report export and offline preparation.
Those local actions require no API key.

The updater keeps the existing 90-day report policy, saved fiscal-date values
and annual conflict rules. It retains full provider fields and variants. New
managed stocks receive histories from 1995. Recent prices and yields are
rechecked. A changed adjusted price requires a consistent full replacement.
Unchanged assets retain their bytes and timestamps. Recent overlap checks do
not audit every old provider correction. Annual requests retain their
40-report limit.

The existing financial cache owner also owns `data/data-refresh.json`. This
small atomic record keeps scope, target date, stage counts, verified running
time, last success and previous successful stage durations. Continue reruns
unfinished stages. Receipts prove saved content and price coverage, not annual
refresh freshness. A foreign busy cache leaves the update status unconfirmed
until ownership is available. Readiness remains separate from update success.

A financial append is newline terminated and flushed. Only an unparseable
unfinished tail is removed before the next owned append or preparation. A
valid JSON tail without a newline is retained. Website rebuilds durably
invalidate the old marker, flush outputs and publish completion last. Cache
replacement keeps file and POSIX directory synchronization. Physical power-loss
behavior and live-provider coverage are not established by synthetic fixtures.

Downloads retain the shared cap of 45 starts per second and up to 32 parallel
tasks. Provider retries and waits remain cancellable. One asset failure can
leave a partial result while valid saved inputs are prepared. Preparation
failure cannot report readiness. Essential missing inputs open the source-served
recovery page at `/data.html`.

See the detailed [data workflow](../docs/research-workflow.md#data-control-panel).

The **Sales × 3-year avg operating margin / EV − US 10Y (pp)** filter uses
the selected annual revenue multiplied by the simple average of three annual
operating margins, divided by screen-date EV. An annual operating margin is
operating income divided by revenue. The three fiscal years must be consecutive
and end at the selected report. Subtract the latest saved US 10-year Treasury
yield on or before the screen date. Enter 5 for a spread of 5 percentage points.
Missing history or Treasury values fail this condition. Negative margins and
spreads remain valid. This filter follows the chosen selection order in both pools and all
three views. Installing this change requires an offline rebuild of research,
daily data and the website. It reuses full annual statement assets and saved
Treasury curves. See the [formula and data rules](../docs/research-workflow.md#sales-based-operating-yield-spread).

## Rebuild from saved data

```bash
python3 scripts/schedules.py prepare
python3 website/build.py
```

Preparation is only needed after changing data or calculation code; the daily-cache command prepares research first. The builder reads the latest book of the book store in `data/schedules.sqlite` (which attaches `data/research.sqlite`), exports the latest screen of both pools as compact tuples, and embeds them in HTML. `website/build.py` alone needs a prepared daily cache. Changing latest screen parameters runs locally in JavaScript without reparsing prices.

The default latest picks remain embedded as a static table for previews that block JavaScript. Interactive screening requires JavaScript. The build writes `index.html`, `latest-picks.csv`, `data.html` and `snapshot.json`; browser-generated CSV downloads contain the original completed result. The canonical report `../results/summary-exits.txt` is a frozen record that no screen reads or overwrites.

## Checks

```bash
node tests/check-range.cjs
python3 tests/check_screener.py
python3 tests/test_data_manager.py
python3 tests/test_fmp_download.py
python3 tests/test_cache_access.py
node tests/check-data-panel.cjs
```

The first checks controls and rendering using a simulated DOM, including a saved January result in the dated view. The second compares browser latest selection directly with SQLite, including combined conditions and empty screens. It requires the current prepared database. These checks do not replace a real-browser appearance check.

## Return contributions

Each dated period shows gain/loss contribution pies, the top 10 contributors and the full stock table.

Contribution equals stock holding return divided by the actual number of selected stocks, expressed in percentage points of portfolio return. Contributions sum to the period's strategy return. Top 10 means the ten stocks with the highest signed contributions, regardless of portfolio size. If fewer than ten stocks are selected, all of them are shown. In an all-loss book, these are the smallest losses. This is historical attribution, not a new picking rule.

Gains and losses use separate pie charts so no negative slice is implied. Each pie is normalized to that side's total; it is not a percentage of the net portfolio return. Named slices are the top contributors; remaining gainers and losers are grouped separately. Zero-return stocks have no slice.

```bash
node tests/check-contributions.cjs
```

This covers signed contributions, the top-10 stock limit, positive/negative/zero/empty books, deterministic ties, input preservation and the pies.

## Latest stock picks

The website opens in **Latest stock picks** mode. Historical backtest remains available in the view switch. The same size, valuation, sector, exchange, universe and rank controls apply in either mode. The latest view shows a current selection, with no holding returns or attribution charts because those outcomes do not exist yet.

The displayed date comes from the latest cached SPY session. Read the date above the latest stock table. Only companies marked currently listed in the cached universe, with a dividend-adjusted price on that exact session, are included. Earlier last-trade prices are not carried forward. The annual figure must be available under the existing strict 90-day lag and no more than 800 days old. Market cap and EV are revalued at the latest price using report net debt and the same adjusted-price method as the historical model.

Latest mode has separate prepared records for the original 250-candidate pool and all eligible cached-price companies. Both remain incomplete representations of the full market. The coverage line shows how many active names have financials and how many can be valued from current cached prices. Available-from dates are assumptions based on fiscal year-end, not verified filing dates. Listing status, sector and exchange are cached metadata.

Click **Screen latest**, **Top 50**, or **Top 100**. Download latest picks exports the currently selected stocks, including valuation date, adjusted price, estimated market cap/EV, ratios, fiscal date, and assumed availability date. `dist/latest-picks.csv` is the default-settings fallback export generated at build time; browser downloads reflect the current filters. The latest table is also embedded as a no-JavaScript fallback.

Updating source caches does not update an already-open standalone HTML file. Run `python3 scripts/schedules.py prepare` and `python3 website/build.py` for the local server, then reload the page. To refresh the untracked standalone export in `dist/`, use `python3 website/build.py --snapshot` explicitly. These commands never download data.

## Ranking metrics

Choose **EV / EBITDA** (current-date valuation) or **EV / 3-year average EBITDA**
(current EV divided by mean EBITDA from three consecutive annual reports). Lower multiples rank first;
minimum selected yield is the reciprocal of the multiple. A missing annual
report excludes the stock from the three-year metric. Latest screens and dated
books use only reports eligible at their screening date. Selected stock tables
and CSV exports show the chosen signal. For a broader comparison, use all stocks
with cached prices: the original candidate set retains its single-year pre-screen.
See `../docs/research-workflow.md` for calculation and extension details.

## Custom trade dates and frequency

Double-click `../start.cmd`, or run `python3 website/serve.py`. The dependency
chain is automatic; no separate preparation commands are needed. The browser
opens at the successfully bound local address. The default listener is `0.0.0.0:3000`. The browser uses `http://127.0.0.1:3000` on this computer. `--host` and `--port` select another listener. If an unknown process owns the port, the service uses an available port. Use the browser tab opened by the launcher or its printed address. Under **Historical backtest**, set the first trade date, end/mark date, and monthly, quarterly,
half-yearly or yearly rebalance interval, then click **Run backtest**.

Rebalances stay anchored to the starting day, clamp invalid month ends, and roll
to the next cached SPY session. The final mark rolls back to an available session;
the last period can be partial. The chart and stock explorer use dated holding
periods, with contribution pies and CSV downloads for the current schedule.
Prices, financial availability, filters and valuation calculations use the saved
cache. Dated books are persisted, so changing filters does not reparse prices.
Each run prepares only its selected stock universe. Switching universes can take
longer the first time because it prepares the other pool; later runs reuse it.
Daily preparation keeps each saved dated book that new data cannot change; the
others are calculated again when a run needs them. An older daily-cache version
or a book-code change starts with no saved dated book.

Custom schedules require the local service; opening the HTML directly continues
to support latest picks. Daily preparation writes the book store; it never
downloads data.
See `../docs/research-workflow.md` for timing and calculation semantics.

While a custom backtest runs, the page shows a spinner, elapsed time and the
requested date range. The Run button is disabled to prevent repeat submissions.
You can edit the strategy draft. Those edits do not change the submitted run or
start another run. Previous results stay visible until a new run succeeds.
A lost connection starts reconnection; the calculation continues on the server.
The Run button becomes available after completion, failure or confirmed Stop.

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

Each server process saves `data/logs/website-<namespace>-<pid>.log`. Startup and the data panel show the current path. The logs record safe error traces, operation times and progress lines for operations longer than a minute; `python3 -m tools.ops.log_summary [--days N]` lists unfinished operations and summarizes the times. Startup removes old logs. The [development log](../docs/architecture-guide/dist/index.html#development-log) section of the architecture guide lists the events, the omitted fields and the cleanup rules.

Windows file indexers can briefly lock cache files. Atomic JSON publication retries access or sharing errors up to eight times, with less than two seconds of total retry waits. Other file errors fail immediately. The existing cache owner remains held. Receipts still publish before their corresponding assets. Persistent failures keep the previous saved data and record the error location in the log.

Check with `python3 tests/test_diagnostics.py`, `python3 tests/test_data_manager.py` and `python3 tests/test_startup.py`. Run these checks on native Windows too.


Research preparation reuses a current database or builds a complete replacement.
A failed research build keeps the prior database. Website publication invalidates the old completion marker, flushes outputs and
records completion last. An interrupted website
build needs recovery before it is current. Standalone `build.py` takes cache
ownership. Server builders run in process under the existing owner.

## Local builds and portable snapshots

Normal builds, startup and data-panel rebuilds write ignored `website/local/`. The server uses this output. They do not change the untracked portable export in `website/dist/`.

Run `python3 website/build.py --snapshot` to refresh the portable snapshot explicitly after preparing data. Each build writes `snapshot.json` with the latest screen date and the website source hashes. An already-open page needs a reload.

Range and SQL/browser parity checks use local output by default. To check the portable snapshot, run `node tests/check-range.cjs website/dist` and `python3 tests/check_screener.py website/dist`.

## Save and reopen completed backtests

Use **Save original backtest** after a historical run. Give it a name if useful.
The save keeps the submitted settings of the original result, all traded stocks,
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
Performance means CAGR for saved January and fixed tests and mean trial CAGR for random
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

Each saved row has **All parameters**. Expand it to read that test's recorded
settings and selected filters without opening its results or changing the form.
The first expansion loads only that record. Sorting, renaming and refreshing keep
its expansion. A failed load shows **Retry parameters** inside the row. Temporary
evidence readers close after the parameter description is read.

Choose **First saved test** and **Second saved test**, then **Compare**. The two
IDs must differ. Recorded performance and parameter rows appear in the library.
Amber rows also say **Different**. Sort or rename records without losing the
selection. Deleting a selected record clears its comparison. **Clear comparison**
clears both selected IDs. The main results and strategy settings stay unchanged.

Comparison reads saved results without recalculation. Legacy/current calendars
and documented defaults compare consistently. Reordered AND conditions and
repeated identical conditions mean the same thing. Strict operators, exact
values, unknown setting fields and original labels stay visible. Requested engine
and recorded producer are separate. Older results without producer evidence are
unidentified. Random comparisons show requested date policy, recorded seed and
stored trial distributions. Mean trial CAGR is not one portfolio return.
Different test types or requested/recorded windows receive a notice. Temporary
version-3 readers are released after their compact descriptions are read.

The maximum is 100 records. When full, delete a chosen record before saving
another. Deletion asks for confirmation and removes only that record. It does
not remove the result currently displayed in the page.

Check with `python3 tests/test_saved_backtests.py`,
`node tests/check-saved-backtests.cjs`, `python3 tests/test_queue_transfer.py`,
`node tests/check-backtest-comparison.cjs`, `node tests/check-saved-comparison.cjs`,
and the ordinary queue and range controls checks.
Run the persistence checks with native Windows Python too.

Random-date saves include every trial's exact trade dates, stock rows and period
returns, plus the seed and distribution summary. Trial inspection uses these
stored rows. It does not recalculate the book. Current background jobs and queued
random tests use strategy captures and the calculation owner’s `calculate_into`
method. This includes built-in-only forms. Tables read bounded evidence pages.
Built-in filters still read precomputed sheet values. Latest built-in screening
stays local; latest custom variables use captured execution. Existing waiting and
held legacy queue rows keep their request format and eager execution.
Save a completed new run; older summary-only
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


### Calculation engine

The website runs only Original. A new draft shows no engine choice. Custom
dated, random and variable-strategy runs use Original on the local service.
The latest screen keeps its shared prepared path. Normal startup and
rebuild need no numerical packages.

The experimental (Numba) engine was deleted from source. The server refuses a
request that names it with `UNSUPPORTED_CAPABILITY` at `/engine`. A restored
test that names it keeps that engine and shows the engine choice, so the user
can choose Original. A waiting queued test that names it stays waiting until
the user edits or deletes it. Replay keeps the recorded engine. Manage backtest
data has no experimental preparation action. New results and CSVs identify
their recorded producer; older evidence stays unidentified. Opening stored
evidence does not calculate.

## Source owners

`website/browser/` contains the plain browser scripts, styles and HTML fragments.
Their basenames, global interfaces and execution order stay the same. The built
HTML embeds these assets. The latest view still works without a server.

`website/rendering/data.py` loads detached page data from one verified daily
connection: the latest book of the book store and the attached research
company names. It closes the connection before rendering. `page.py` builds static
markup. `assets.py` owns asset order and the source-only recovery page.
`rendering/build.py` writes the HTML, the latest picks CSV, the data panel and
the snapshot provenance. `rendering/state.py`
checks explicit nested source inventories and the latest book's identity: the
daily generation that wrote it, not the cache file's stamp, so a saved dated book
does not force a rebuild.
The executable command remains `python3 website/build.py`.

`website/server/app.py` owns HTTP transport and server lifetime. Its grouped
adapters are `backtests.py`, `results.py` and `data.py`. They call application
owners without implementing financial policy or durable storage. Data jobs and
launcher identity remain in `server/data_manager.py` and `server/launcher.py`.
`website/serve.py` acquires source ownership before importing the application.
It holds ownership until workers, requests, databases and result readers close.
