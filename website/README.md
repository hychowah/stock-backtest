# Stock Backtest website

Double-click `../start.cmd` on Windows, or run `python3 website/serve.py` from the project root. The launcher refreshes stale caches, rebuilds the website if needed, starts the service and opens the browser. Unchanged caches are reused; no API key or market-data downloads are needed. A portable export built with `python3 website/build.py --snapshot` opens directly from `dist/index.html` and supports the saved latest view.

## Markets and USD

Each run uses one local market calendar. Hong Kong includes common stocks on the Main Board and GEM. Japan uses Tokyo listings. Date controls show that market’s saved session bounds, from 1996 at the earliest. Missing market data is prepared through the data panel.

Prices, valuation thresholds, returns and CAGR use USD. Foreign returns include exchange-rate changes without hedging. SPY is always the S&P 500 total-return proxy. Asian dates use the previous completed US close. Date-only FX uses the previous completed daily fixing. Cash earns 0% USD. Yield references remain US Treasury yields.

Foreign fiscal market cap uses annual basic weighted-average shares and the native unadjusted fiscal close. Entry rescaling uses adjusted prices. Report amounts use context-date FX for every report year; holding prices use their own observation-date FX. This is an annual-share approximation. FMP can have missing or zero-heavy fields, later revisions, incomplete listing coverage and dividend-adjustment defects. Missing required inputs stay unavailable.

New formulas use catalog `financial-parameters/4` and policy `market-annual/1`, with definition version 3. Opened older formulas retain their catalog and need **Use expanded inputs** before foreign execution. Upgrade rebinds named measures. Upgrade and save user-defined references separately, then choose their new revisions. Market survives held edits, queueing, copying, comparisons, exports and saved opening.

## Automatic updates

The registered Windows `backtest-web.cmd` serves the installed revision and
updates committed main and refreshes FMP data daily at 07:00 Hong Kong time.
It refreshes data even when main has no new commit. The same cycle refreshes markets with saved inventories. **Update data** in the panel targets the selected market; **Continue update** retains the recorded scope. A missed schedule waits
until the next day; launch and resume do not catch up. `--latest` updates
source at launch. Maintenance restarts the native server in the same terminal. Uncommitted saves
and other branches do not trigger updates. Remote history is not fetched or pulled.
Refresh the browser page after the server reports it is ready. Subsequent
restarts do not open another tab.

The archive is staged before shutdown. Server cleanup finishes before source
replacement. A latest screen in progress stops; interrupted queued work returns to
waiting with its recorded dates. Saved backtests and raw data are preserved.
Unavailable Git keeps the installed source revision; data refresh still runs.
A failed source publication retries automatically.
Use `python3 tools/deploy.py --revision <commit> --start` from WSL for a fixed
revision without watching. Ctrl+C stops the watcher and its server.

## Basic workflow

1. Choose **US**, **Hong Kong** or **Japan · Tokyo**, then **Latest stock picks** or **Historical backtest**. New strategies use the broad cached-price pool. It is not the full market. Restored US work retains its recorded original candidate pool.
2. Build the strategy as ordered steps under the stock universe. A new strategy has three steps: **Market cap** at least $100 million, **Enterprise value** at least $50 million, then a **Rank** by EBITDA/EV yield, highest first, ranks 1–50.
3. Use **+ Add filter** or **+ Add rank**. Type in the new row to search one list: size and listing fields, EV/EBITDA metrics, built-in values, saved variables, measures and financial parameters. A Filter takes a comparison (more than, less than, at least, at most) and a value in the shown unit; sector and exchange filters take one choice. A Rank takes **Highest first** or **Lowest first** and an inclusive rank range. A new filter goes before the last Rank. Use a step's **↑**, **↓** and **✕** buttons (Move up, Move down and Remove) to change the order. Built-in sources work offline; saved variables, measures and parameters need the local service. A stock with a missing value fails a filter and is left out of a Rank. Enter 10 for a 10% trailing return. Choose **Manage backtest data → Update data** to get financial-ratio inputs.
4. Steps run in order. Each Rank keeps its range from the stocks that reach it. The last Rank sets the final order and ranks; filters after it keep original ranks and add no replacements. Survivors receive equal weight. Filters → Rank is the old filter-first order; Rank → filters is the old rank-first order. If 20 stocks pass after a top-50 Rank, each receives 5% weight.
5. In latest mode, click **Screen latest**. In **Historical backtest**, select **Add to queue**: every dated test runs from the queue, and its result is saved in **Runs & saved**. Latest picks run offline for filters it supports and one highest EV/EBITDA-yield Rank, first or last. **Screen latest** runs every other chain on the local service. Auto-run belongs to latest mode and works for the offline shape only. Each selected stock's **Details** shows its step trail: each step's value and its rank or pass. Reset strategy restores the broad pool and the three default steps while preserving the chosen dates.

In latest mode, a notice under the builder tells you when the displayed picks do not match the current settings; **How this works** in each section contains the longer explanations.

The menu has **Build strategy**, **Runs & saved** and **Result review**. To run several variants, select **Add to queue** for each one. You can type a test name in the box beside that button; an empty name describes the strategy. [Runs & saved](#save-and-reopen-completed-backtests) shows the waiting and running tests and the saved backtests in one table.

**Tune** on a queued test or a saved backtest, and **Tune this strategy** in Result review, copy the settings of that record to the builder. The strategy returns as steps: filter-first records become filters → Rank, rank-first records become Rank → filters. Ranges such as 20–40, thresholds, units, labels and exact formula revisions are kept. Opening a result never changes the steps. A held queue edit that is saved unchanged keeps its original request; other submissions record the steps.

Backtests rebalance on the selected fixed or random schedule; a January study is a 12-month schedule from 1 January. There is no separate January view. A saved January result opens in the dated view without calculation: its book years become periods, labelled by book year where no period dates were stored. Charts, returns, CAGR, growth of $1 and stock tables update together. CSV download links export the **original completed result**. Exploration selections do not change an export. Sector and exchange are cached company metadata, not historical classifications.

If fewer stocks match than requested, the available picks receive equal weights and short periods are counted. A complete period with no matches holds cash at 0% until the next rebalance. SPY keeps its period return. CAGR includes the full elapsed window.

## Read a completed result

A completed backtest opens in **Result review**. The headline below the title
shows the original result on every tab: CAGR against SPY for a fixed schedule,
or the trial statistics for random dates. A value that the result did not
store shows **Unavailable**.

**Overview** shows the main chart and its table: returns by holding period for
a fixed schedule, or the return distribution, the statistics of complete trials
and the trial table for random dates. **Explore** and **Recorded coverage and
notes** follow them. **Returns** shows the period returns and the stocks of
each rebalance; for random dates, it shows one trial.

**Value of $1 day by day** starts Overview. It shows the strategy and SPY on
every market day, so the rallies and falls inside each holding period show.
For random dates it shows the median trial with a band from the lowest to the
highest trial, and Returns shows the selected trial. Point at the chart to read
one day. The vertical scale is logarithmic: equal heights are equal percentage
moves. A result saved before this chart existed has no chart.

## Explore a completed result

Open **Explore this result** in **Result review**. Choose **From entry**,
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

Random-date results show **Explore all trials** below the trial table.
One selection updates every trial, the combined statistics and distribution
chart. The panel shows the mean and median strategy CAGR and the mean paired
SPY CAGR of the selection. While the chart and tables show a selection, a
notice above the chart gives its window and ranks. The headline does not change.
Choose saved entry and exit blocks. Each trial keeps its own trade dates.
The summary shows the shared window, with cash before each first selected trade
and after each last selected exit for both strategy and SPY.

**Reset to original** restores the recorded summary. Holding details, downloads
and comparisons use the original completed result.

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

The updater keeps each market's reporting policy, saved US fiscal-date values
and annual conflict rules. Foreign downloads use the three statement endpoints;
unused key-metrics and ratios responses are not required. It retains full
provider fields and variants. New
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
three views. Its data come from the full annual statement assets and the saved
Treasury curves. See the [formula and data rules](../docs/research-workflow.md#sales-based-operating-yield-spread).

## Rebuild from saved data

```bash
python3 scripts/schedules.py prepare
python3 website/build.py
```

Preparation is only needed after changing data or calculation code; the daily-cache command prepares research first. The builder reads the latest book of the book store in `data/schedules.sqlite` (which attaches `data/research.sqlite`), exports each prepared market’s latest screen and available date bounds as compact tuples, and embeds them in HTML. `website/build.py` alone needs a prepared daily cache. Changing latest screen parameters runs locally in JavaScript without reparsing prices.

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

Contribution equals stock holding return divided by the actual number of selected stocks, expressed in percentage points of portfolio return. Contributions sum to the period's strategy return. Top 10 means the ten stocks with the highest signed contributions, regardless of portfolio size. If fewer than ten stocks are selected, all of them are shown. Equal contributions are ordered by symbol. In an all-loss book, these are the smallest losses. This is historical attribution, not a new picking rule.

Gains and losses use separate pie charts so no negative slice is implied. Each pie is normalized to that side's total; it is not a percentage of the net portfolio return. Named slices are the top contributors; remaining gainers and losers are grouped separately. Zero-return stocks have no slice.

```bash
node tests/check-contributions.cjs
```

This covers signed contributions, the top-10 stock limit, positive/negative/zero/empty books, deterministic ties, input preservation and the pies.

## Latest stock picks

The website opens in **Latest stock picks** mode. Historical backtest remains available in the view switch. The same universe and steps apply in either mode. The latest view shows a current selection, with no holding returns or attribution charts because those outcomes do not exist yet.

The displayed date comes from the selected market's latest completed cached session. Read the date above the latest stock table. Only companies marked currently listed in the cached universe, with a dividend-adjusted price on that exact session, are included. Earlier last-trade prices are not carried forward. The annual figure must be available under its market's reporting policy and no more than 800 days old. Market cap and EV are revalued at the latest price using report net debt and the same adjusted-price method as the historical model.

Latest mode has market-bound prepared records. The original US 250-candidate pool remains available for restored work; new forms use all eligible cached-price companies. Both remain incomplete representations of the full market. The coverage line below the picks table shows how many active names have financials and how many can be valued from current cached prices. US available-from dates assume 90 days after fiscal year-end. Hong Kong and Japan use reliable publication dates where available, otherwise four and three calendar months. Listing status, sector and exchange are cached metadata.

Click **Screen latest**. Download latest picks exports the currently selected stocks, including valuation date, adjusted price, estimated market cap/EV, ratios, fiscal date, and assumed availability date. `dist/latest-picks.csv` is the default-settings fallback export generated at build time; browser downloads reflect the current filters. The latest table is also embedded as a no-JavaScript fallback.

Updating source caches does not update an already-open standalone HTML file. Run `python3 scripts/schedules.py prepare` and `python3 website/build.py` for the local server, then reload the page. To refresh the untracked standalone export in `dist/`, use `python3 website/build.py --snapshot` explicitly. These commands never download data.

## Ranking metrics

A Rank or Filter step can use **EV / EBITDA** (current-date valuation) or **EV / 3-year average EBITDA**
(current EV divided by mean EBITDA from three consecutive annual reports), as a yield or a multiple. A highest-yield Rank puts lower multiples first;
the yield is the reciprocal of the multiple. A missing annual
report excludes the stock from the three-year metric. Latest screens and dated
books use only reports eligible at their screening date. Selected stock tables
and CSV exports show the chosen signal. For a broader comparison, use all stocks
with cached prices: the original candidate set retains its single-year pre-screen.
See `../docs/research-workflow.md` for calculation and extension details.

Built-in values also include **P/S** and the **P/E, P/S and P/B 3-year and 5-year averages**: 1 ÷ the mean daily yield (net income, revenue or equity ÷ market cap) over the trailing years. **P/E vs its 3-year average** and the other relatives divide the current multiple by its average: below 1 means cheaper than usual. A stock has no average when it has no daily yield on or before the start of the window, or when its mean yield is not positive.

## Custom trade dates and frequency

Double-click `../start.cmd`, or run `python3 website/serve.py`. The dependency
chain is automatic; no separate preparation commands are needed. The browser
opens at the successfully bound local address. The default listener is `0.0.0.0:3000`. The browser uses `http://127.0.0.1:3000` on this computer. `--host` and `--port` select another listener. If an unknown process owns the port, the service uses an available port. Use the browser tab opened by the launcher or its printed address. Under **Historical backtest**, choose **One fixed schedule**, then set the first trade date, end/mark date, and the rebalance interval (monthly, quarterly,
half-yearly, yearly, every 2 years, or a custom interval in weeks or months), then select **Add to queue**.

Rebalances stay anchored to the starting day, clamp invalid month ends, and roll
to the next cached session of the selected market. The final mark rolls back to an available session;
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

While a queued test runs, its row in **Runs & saved** and the status bar show
its progress. You can edit the draft, add more tests or close the page.
**Stop test** in the Details of the row stops it.

You can close the server during a backtest: unfinished cache writes roll back,
while previously committed books and original price/financial data remain
intact. After a restart the queue runs the interrupted test again. Shutdown coverage in `tests/test_schedules.py` includes
both a `KeyboardInterrupt` and killing a subprocess with an uncommitted SQLite
period, followed by integrity checks and a successful retry.

## Random-date sensitivity

In Historical backtest mode, **Date testing** starts at **Random date at every
rebalance**. **Random trials** and **Advanced** appear only for this choice. Choose **Random trials**
(1–100, default 24). Each run draws fresh random dates by default.
Under **Advanced**, optionally enable **Repeat the same dates** to use a fixed
date-set number (seed), or enter a number from earlier results. Every trial draws
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
in order. The running row counts completed trials and new books. A test whose
books are all saved starts no workers. Results include each trial's actual
trade dates in the CSV. Select a trial and click **Show stocks and period returns**
to inspect its usual stock tables and contribution charts. The trial opens in
**Returns** below the title **Trial N of M**. Completed trial books
survive an interrupted batch; the queue retries the test with the same date set.

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

**Tune** on a random-date result ticks **Repeat the same dates** with the
date-set number of that result, so a new test uses its dates with the same
window and frequency. Untick it to draw fresh dates.

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

**Runs & saved** shows every test in one table with two groups. **In progress** shows
the queue: the running test first, then the waiting tests in queue order, then
failed tests, stopped tests and completed tests that are not moved yet.
**Saved backtests** shows the saved library, newest first; a test that finishes
is saved there automatically. A row is one line: name,
status, test type and trials, date window, CAGR and the time when the test was
added or saved. CAGR is the mean trial CAGR for random dates. A running row
shows its progress with its status, and a failed row shows the reason there.
**Refresh** reads both groups again. The page has no other save. A saved record
keeps the submitted settings, all traded stocks, and all stock and period returns.

Select the name of a saved backtest to reopen it. Opening restores its
settings, charts, stock tables and downloads without rerunning a calculation.
Records stay available after browser and server restarts. They are stored on the
server computer in `data/saved-backtests.sqlite`, outside the rebuildable caches.
The library is shared by browser sessions using that runtime. A saved HTML file
needs the local service to use the library.

Select **Details** at the end of a row to read the settings of that test in
plain wording, such as `Market cap ≥ $100M`, and to find its other actions. A
closed **Exact recorded values** lists every recorded row with its exact text.
Renaming changes no settings or stored results.

Select the **Name**, **CAGR** or **Saved** heading to sort the saved backtests;
select it again to reverse the order. Test types and date windows can differ.
A missing CAGR stays last.

The server saves a complete independent result before it removes a completed
test from the queue. This also
runs while the execution queue is paused or its engine is unavailable. A full
library shows **Completed — waiting for saved slot** in the queue. Other save
failures retain the result and show a retry notice. Free a saved slot to let the
server retry without recalculation. Failed and stopped tests stay in the queue.
Deletion during an active transfer asks you to refresh and retry. A transferred
record appears once, even after interruption. Later rename or deletion is kept
when transfer recovery retries. Original queued submission receipts remain valid
but never restart or redisplay archived tests. Active result readers keep their
original bytes when duplicate queue evidence is released.

Tick saved backtests to compare them without opening a result or changing the
form. A panel above the Saved backtests rows shows one column for each ticked
test, in list order: first the requested settings that differ, or **Same
settings**, then the headline rows. A closed disclosure contains every setting
and, for random-date tests, six more measures; in that list, an amber row that
also says **Different** marks a setting that differs. When two tests differ in
a setting that reads the same in plain wording, that row shows the exact text.
A measure that a test does not have shows a dash. **Clear** removes every tick.
The page reads a stored result one time, when you tick its row or open its
Details; a failed read shows its reason above the rows.

Comparison reads saved results without recalculation. Legacy/current calendars
and documented defaults compare consistently. Reordered AND conditions and
repeated identical conditions mean the same thing. Strict operators, unknown
setting fields and original labels stay visible. A difference uses the exact
recorded value. Performance shows 2 decimals; a value below 0.01 shows 2
significant digits. Requested engine
and recorded producer are separate. Older results without producer evidence are
unidentified. Random comparisons show requested date policy, recorded seed and
stored trial statistics. Mean trial CAGR is not one portfolio return.
Different test types or requested/recorded windows receive a one-line notice.

The maximum is 100 records, and every finished test takes one. When full,
delete a chosen record: the next finished test then moves in. Deletion asks for confirmation and removes only that record. It does
not remove the result currently displayed in the page.

Check with `python3 tests/test_saved_backtests.py`,
`node tests/check-saved-backtests.cjs`, `python3 tests/test_queue_transfer.py`,
`node tests/check-backtest-comparison.cjs`, `node tests/check-saved-comparison.cjs`,
and the ordinary queue and range controls checks.
Run the persistence checks with native Windows Python too.

Random-date saves include every trial's exact trade dates, stock rows and period
returns, plus the seed and distribution summary. Trial inspection uses these
stored rows. It does not recalculate the book. The
[submission and reader contract](../docs/evidence-views.md#dated-submissions)
describes request formats, limits and legacy queue edits.

### Completed-result ownership and saved-record compatibility

`result-artifacts.js` owns one immutable completed artifact per view. Its submitted
settings, result, catalog and semantic presentation context travel together.
A latest screen and saved-record opening use the same publication and rendering
path. Renderers, downloads, the stale-setting notice of latest picks and the
library read this artifact. The library owns record operations and the shared record list.

Version-2 saved snapshots store coverage text, warning severity, range notes and
period labels without page selectors or CSS classes. The browser decodes
version-1 records into this format when opening them. Stored version-1 records
are not rewritten. Saved labels take precedence while displaying saved results.
New calculations use the current catalog. Random trial inspection reads the
selected trial from the same completed artifact.

An acknowledged rename or deletion updates the visible list immediately. A
background refresh reconciles other sessions' records. A refresh failure reports
that the action succeeded and the list could not be refreshed. Older list
responses cannot replace a newer acknowledged change.

Check `node tests/check-result-artifacts.cjs` alongside the saved-library and range
checks. The library checks include failed refreshes and out-of-order responses.


### Calculation engine

The website runs only Original. A new draft shows no engine choice. Queued
tests and latest screens on the local service use Original.
The latest screen keeps its shared prepared path. Normal startup and
rebuild need no numerical packages.

The experimental (Numba) engine was deleted from source. The server refuses a
request that names it with `UNSUPPORTED_CAPABILITY` at `/engine`. A restored
test that names it keeps that engine and shows the engine choice, so the user
can choose Original. A waiting queued test that names it stays waiting until
the user edits or deletes it. `options.engine` is `original` or `experimental`.
Jobs, queue receipts, held edits and recovery keep the recorded value;
it is never rewritten to Original. Manage backtest
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
