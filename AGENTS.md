# EBITDA/EV January book

This folder is a standalone US stock backtest. It is not a a different research session. Do not open the parent harness, do not invent a fair value, and do not edit product code from here.

The folder can move. Scripts resolve paths from their own file. Keep `raw/` with the code. The FMP key stays at `~/.grok/secrets/fmp_api_key`. Never print the key or a request URL.

## Current result

`results/summary-exits.txt` is the result to continue from. It is the pass that keeps a stock when trading stops.

`results/legacy/summary.txt` and `results/legacy/picks.csv` are the earlier pass. That pass dropped a stock when its price stopped more than 10 days before the January sale. Do not quote those files as the latest result.

`scripts/revalue.py` writes `results/summary-exits.txt`. It reads the cache and does not download. `scripts/run.py` still uses the old exit rule and rewrites `results/legacy/summary.txt`.

## What the test does

Each January, from 1996 through 2026, buy the 50 US common stocks with the highest EBITDA/EV. Sell at the next January. The 2026 book is marked through the last SPY session on or before 2026-10-21. Compare with SPY, dividends included. Equal weight. No commissions.

The 3-month Treasury yield is one number for every stock that day. Subtracting it does not change the rank.

## Rules already chosen

- Exchanges: NYSE, Nasdaq, NYSE American. ETFs and funds are out. Delisted US names are in the universe.
- The annual figure is treated as known 90 days after fiscal year-end. A report older than 800 days is dropped.
- Enterprise value at the buy date uses the report's debt and cash, and the buy-date price. That price series is dividend-adjusted.
- Market cap at least $100 million. Enterprise value at least $50 million. Currency USD.
- A stock with no buy price is left out.
- If trading stops before the January sale, the exit is the last price. That covers an acquisition, a called note, and a SPAC that returns cash.
- A bankruptcy is a total loss. `BANKRUPT` in `scripts/revalue.py` is the set of `(year, symbol)` pairs that get −100%. It is empty. The 37 stops were checked. They were acquisitions, redemptions, SPAC cash, or warrants. None was marked a bankruptcy.
- A stock that still has a January price keeps that price. A later delisting does not rewrite the year.

## Cache

Do not refetch data that is already here.

- `raw/universe.json` — about 11,054 US names, including 5,068 delisted names. Delisted rows have no sector and no delisted date.
- `raw/metrics.jsonl` — annual key metrics. One JSON object per line: symbol, date, fiscal year, currency, market cap, enterprise value, EV/EBITDA.
- `raw/px/` — dividend-adjusted price history for the screened names, about 1,999 files.
- `raw/spy-div.json` — SPY total-return prices from 1995.
- `raw/treasury.json` — daily Treasury yields from 1995. The 3-month yield is `month3`, in percent.

`raw/archive/*.csv` and `raw/archive/delisted-*.json` are leftover bulk downloads. `scripts/run.py` does not read them.

## FMP limits

A 30-year price or Treasury request returns only the latest rows. Request short date windows. One stock price history is capped at about 5,000 sessions, so `scripts/run.py` asks for three windows.

Bulk statement files (`key-metrics-bulk`, `income-statement-bulk`) are refused when many run at once. Per-symbol `key-metrics` calls work at about 16 at a time. The pace gate inside `scripts/run.py` made those calls stall. `fetch_metrics` turns that gate off.

## How to continue

Recompute exits from the cache:

```
python scripts/revalue.py
```

Add a bankruptcy as a total loss by putting `(year, "SYMBOL")` in `BANKRUPT` in `scripts/revalue.py`, then run that file again.

Change the screen, the universe, or the price cache in `scripts/run.py`. Run it only when the cache is missing data. Merge any new exit rule into `scripts/revalue.py` before treating `results/legacy/summary.txt` as current.

`scripts/classify_stops.py` and `results/stops/stops-class.json` record SEC form types for the 37 stops. The merger flag in that file is broad. `scripts/revalue.py` does not read it. It uses the last price for every stop. Use the form list as a clue, and check a name before calling it a bankruptcy.

## Project layout

Backtest entry points live in `scripts/`, with shared paths in `scripts/paths.py`. API experiments and repair tools are in `tools/`. Current reports are in `results/`, older reports in `results/legacy/`, and stop analyses in `results/stops/`. Unused acquisition files are preserved in `raw/archive/`; active cache locations are unchanged.

The website source and ready-to-open output live in `website/` and `website/dist/`. Rebuild with `python3 website/build.py`. Verify path handling with `python3 tests/check_paths.py` and website calculations with `node tests/check-range.cjs`. Python uses the standard library; the JavaScript check needs Node.js. Cache-only workflows require no API key.

## Fast research workflow

`scripts/research.py prepare` creates the offline `data/research.sqlite` January data layer from the raw cache. It verifies the baseline against `results/summary-exits.txt`; repeated preparation skips parsing when inputs are current. Use `scripts/research.py screen --top 100` or other flags for experiments, rather than editing `HOLD` and reparsing daily history. The website uses the prepared database. `scripts/revalue.py` remains the independent slower reference calculation.

The `legacy` research pool preserves the original 250-candidate pre-price screen and uses the **current** exit rule. The `cached` pool broadens the screen to available cached-price companies, not the full universe. Report missing coverage and unreviewed new early stops; do not imply all expanded holdings received the earlier bankruptcy review. See `docs/research-workflow.md`. Test with `python3 tests/test_research.py`.

## Website strategy builder

`website/dataset.py` exports both prepared January pools as compact records embedded in the HTML. `website/screener.js` implements browser filtering/ranking; `website/range.js` connects controls and renders results. Each runtime shares filtering and ranking between historical and latest modes; only historical mode validates years. Browser parameters must match the SQL selection semantics in `scripts/research.py`. Check parity with `python3 tests/check_screener.py` after building; it requires a current prepared database. Keep the original static top-50 fallback and baseline CSV/JSON exports. Browser downloads reflect the current strategy. Show short/empty-year coverage explicitly; do not calculate a full-period strategy CAGR when any selected year is empty.

Yearly attribution uses `website/contributions.js` for browser calculations and `website/attribution.py` for the static fallback. Top contributors means the first `min(10, actual selected count)` stocks, ordered by signed contribution (return / actual selected count), with ties by symbol. Gain/loss pies are normalized separately; never draw negative slices or describe them as shares of net return. Check with `node tests/check-contributions.cjs`, `python3 tests/test_attribution.py`, and the existing range/control tests.

## Latest-date website screening

Schema version 2 prepares `latest_snapshots` separately from historical snapshots. Latest date means the latest cached SPY session. Require an exact-session dividend-adjusted price and cached `listed=True`; never reuse old stopped prices in the latest screen. Use the same 90-day lag, strict availability-before-date rule and 800-day report-age limit. No future return or contribution is stored for latest picks. `research.latest_screen()` and `StockScreener.latestScreen()` must agree. The website opens in latest mode; historical mode retains year controls.

Historical preparation is bounded by the canonical report's Through date and historical ASOF, while latest preparation can advance independently. The reference report participates in freshness checks. Refresh prepared data and rebuild the HTML after cache updates; the website does not fetch market data. Tests include exact-date exclusion, unavailable/stale reports, cached listing status, unchanged historical periods when latest prices advance, both SQL/browser screen modes and latest CSV output.

## Ranking metric catalog

Schema version 4 stores uniform `screening_metrics` pairs (multiple and yield)
for each mode, pool, year and symbol; `scripts/metrics.py` owns the display
catalog, calculator registry and all metric calculations. Both website modes and SQL selection accept a metric
ID, with the catalog embedded by `website/dataset.py`. Keep filtering/ranking
and rendering generic: consumers read prepared pairs without interpreting formulas
or calculator types. Three-year metric means current EV divided by mean EBITDA from three
consecutive annual reports, excluding incomplete histories; current
EV/EBITDA remains the default. Original-pool membership still comes from the
single-year buffer. Add temporal/missing-year and SQL/browser parity checks for
new metrics. Calculation/catalog changes require offline prepare and rebuild.

## Custom dated schedules

`scripts/schedules.py prepare` builds a separate ignored daily SQLite cache from
saved prices after research preparation. `website/serve.py` serves the built page
and a loopback custom-schedule API. January and latest views remain standalone;
custom dates use `website/schedule.js` and the local service. Dates are anchored
to the original starting day, clamp month ends, and roll forward to SPY sessions;
end marks roll back. Supported intervals are 1, 3, 6, 12 and 24 months. Persist dated
books independently of filters and reuse `research._select` and
`metrics.evaluate` rather than duplicating filtering or metric formulas. Custom
charts show dated period returns; don't label monthly/quarterly books as annual
returns. Keep canonical January reports untouched. Verify with
`python3 tests/test_schedules.py` and existing research/website checks.

## Automatic local launcher

`start.cmd` (Windows) and `python3 website/serve.py` own startup. The daily
preparer first ensures the research cache, then the server checks the website
build stamp and rebuilds if needed. Open the browser only after successful
preparation and binding; `--no-browser` supports headless use. Keep dependency
repair automatic rather than making users chain preparation commands. Source
fingerprints use POSIX relative keys and exclude platform-specific directory
sizes. `website/build_state.py` tracks normalized source contents and the prepared
database generation. Test with `python3 tests/test_startup.py`.

## Random-date sensitivity

`scripts/robustness.py` samples one SPY trading session independently in every
nominal frequency block for each seeded trial. Trial count is configurable
(1–100, default 24). `schedules.backtest_dates` shares the dated-book evaluator
with fixed schedules. All trial CAGRs use a common window with zero-return cash
before the first trade for both strategy and paired SPY. Keep incomplete trials
visible and exclude them from both paired distributions. Average trial CAGR is
not one portfolio return; percentiles are not confidence intervals. Stream real
completed-trial counts through `/api/robustness`; commit per trial so retrying a
seed reuses books after interruption. Inspect trials using the ordinary schedule
API with explicit dates. Check `python3 tests/test_robustness.py` and
`node tests/check-robustness.cjs` alongside existing checks.

Random date batches draw fresh dates by default; an omitted seed is generated
server-side and recorded for replay. An explicit seed remains deterministic,
exposed through an advanced repeat option rather than the main strategy controls.
If the default port is occupied, open a new loopback instance on an available
port rather than reusing a possibly outdated API process.
