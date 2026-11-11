# Stock Backtest

A local research tool that screens stocks by valuation and backtests the picks against SPY.

[![Tests](https://github.com/hychowah/stock-backtest/actions/workflows/tests.yml/badge.svg)](https://github.com/hychowah/stock-backtest/actions/workflows/tests.yml)

## What it does

Stock Backtest screens US, Hong Kong and Tokyo common stocks, one market at a
time. You build a strategy from filters and rankings, then either:

- see the **latest picks** for the most recent trading session, or
- run a **historical backtest** on fixed or random rebalance dates.

A backtest buys an equal-weight portfolio of the selected stocks at each
rebalance. It reports the return in US dollars and compares it with SPY,
including dividends. Everything runs on your own computer, from a local cache of
market data.

## Highlights

- **Strategy builder.** A strategy is an ordered chain of **Filter** and
  **Rank** blocks, up to 50. A Filter keeps the stocks that pass a condition. A
  Rank orders the survivors and keeps a rank range, such as 1–50. Each selected
  stock shows its step trail: its value and outcome at every step.
- **Custom variables.** Write formulas over point-in-time annual facts: 55
  annual financial inputs, 33 named measures, and annual statistics such as mean,
  growth and CAGR. Saved variables keep every revision. Each run records the
  exact formula, so a result always reopens the same way.
- **Random-date robustness trials.** Run 1–100 seeded trials (24 by default).
  Each trial picks one random trading day in every rebalance period. The
  result shows the spread of returns against SPY, not one lucky start date.
- **Saved library and queue.** Every dated test runs from a queue. Edit, hold,
  reorder or pause waiting tests. Completed results move to a library of up to
  100 saved backtests. You can rename them, sort them and compare up to eight
  side by side. Opening a saved result never recalculates it.
- **Incremental daily updates.** A data update downloads only what is new or
  missing. Preparation then recalculates only the affected companies and
  dates. Tests check that the result matches a fresh full build.

## Screenshots

**Strategy builder:** a chain of Filter and Rank blocks.

![Strategy builder](docs/images/strategy-builder.png)

**Step trail:** how one holding passed each step.

![Step trail](docs/images/step-trail.png)

**Random-date trials:** the distribution of returns across trials.

![Random-date trials](docs/images/random-trials.png)

## How it works

```mermaid
flowchart LR
    FMP["FMP API"] -->|"Update data"| RAW["Raw cache<br/>prices, reports, FX"]
    RAW --> RES["Research database<br/>typed annual facts"]
    RES --> SHEETS["Prepared daily sheets<br/>candidates per date"]
    SHEETS --> CHAIN["Strategy chain<br/>Filter and Rank steps"]
    CHAIN --> RESULTS["Portfolio results<br/>USD returns vs SPY"]
    RESULTS --> WEB["Website"]
    WEB -->|"Add to queue"| QUEUE["Queue"]
    QUEUE --> CHAIN
    RESULTS --> LIB["Saved library"]
    LIB --> WEB
```

The data panel downloads prices, annual reports, FX rates, SPY and Treasury
yields from Financial Modeling Prep (FMP) and saves each file once. Preparation
turns them into a SQLite database of typed annual facts, then into daily sheets
of candidate stocks. On each rebalance date the strategy chain selects from
that day's sheet. Portfolio results pair each period with SPY. Strategy
calculations never download data.

## Methodology essentials

- **Point-in-time reports.** A US annual report is used only from 90 days after
  its fiscal year-end. Hong Kong and Tokyo reports use reliable publication
  dates, otherwise four (Hong Kong) or three (Tokyo) months after year-end. A
  fiscal year-end more than 800 days old is too old to use. A newer report never
  fills a missing value.
- **No look-ahead by date.** A screen uses only reports, prices and FX rates
  dated on or before the screen date. Report values are FMP's current
  versions, not the original filings.
- **Dividend-adjusted prices.** Returns use dividend-adjusted prices.
  Enterprise value at entry uses the report's debt and cash and the entry
  price.
- **USD conversion.** All money, thresholds and returns are in US dollars.
  Foreign returns include currency moves, without hedging.
- **SPY total-return benchmark.** SPY includes dividends. Hong Kong and Tokyo
  dates use the previous completed US close.
- **Equal weights, no costs.** Every selected stock gets the same weight. There
  are no commissions or transaction costs. Cash earns 0%.
- **Delisted stocks included.** The US universe includes delisted names. If
  trading stops before the exit date, the last price is the exit.

See [docs/methodology.md](docs/methodology.md) for the original study, its
exit rules and its limits.

## Project layout

| Folder | Contents |
|---|---|
| `backtest/` | Financial rules, data preparation, selection, the calculation engine and the queue and library |
| `website/` | Browser interface, page builder and local HTTP server |
| `scripts/` | Command-line preparation and the development check |
| `tools/` | Deployment, operations and FMP API probes |
| `tests/` | Python and Node.js tests and the test runner |
| `docs/` | Methodology, design notes and the architecture guide ([index](docs/README.md)) |
| `results/` | Frozen January study record and experiment summaries |
| `raw/` | Local market-data cache (not tracked) |
| `data/` | Local databases, saved backtests and the queue (not tracked) |

## Getting started

**Requirements**

- Python 3, developed and tested with 3.14. The project uses only the standard
  library, so there is nothing to install with pip.
- Node.js, for the browser checks.
- An FMP API key, only for downloads. Save it as a one-line text file at the
  path that `KEY_PATH` sets in `backtest/inputs/fmp_download.py`. Backtests on
  saved data need no key.

**Run the website**

```bash
git clone https://github.com/hychowah/stock-backtest.git
cd stock-backtest
python3 website/serve.py
```

The server listens on port 3000 (`--port` changes it) and opens your browser
at `http://127.0.0.1:3000`. Before it starts, it prepares any stale data and
rebuilds the page. With an empty cache it opens the data panel: choose
**Manage backtest data → Update data** to download market data.

Other commands:

```bash
python3 scripts/research.py prepare    # build the research database (no downloads)
python3 scripts/research.py status     # show database size and price coverage
python3 website/build.py               # rebuild the page into website/local/
python3 website/build.py --snapshot    # write a portable export to website/dist/
```

**Windows**

Run `backtest-web.cmd`, or double-click `start.cmd`. On a plain clone it runs
the same local server with native Python. Keep the terminal open; press Ctrl+C
to stop.

The author's setup develops in WSL and deploys committed source to a separate
native Windows runtime, which updates its data every day at 07:00 Hong Kong
time. See [docs/workspaces.md](docs/workspaces.md).

## Testing

```bash
python3 tests/run.py                 # fast tier (default)
python3 tests/run.py --tier heavy    # slow workloads
python3 tests/run.py --tier all      # both
```

The runner starts each `tests/test_*.py` and `tests/check-*.cjs` file in its
own process, eight at a time (`--jobs` changes this), with a private temporary
folder. It fails any test that touches the checkout's `data/` folder. Tests use
small synthetic data and need no API key. GitHub Actions runs the fast tier on
every push.

To run one file, call it directly, for example `python3 tests/test_queue.py` or
`node tests/check-queue.cjs`. After `python3 website/build.py`, also run
`node tests/check-range.cjs` and `python3 tests/check_screener.py`.

---

© 2026 hychowah. All rights reserved.
