# US EBITDA/EV book, 1996–2026

This document describes the original 30-year January study and its frozen result. The app runs it as a 12-month dated schedule from 1 January. The folder does not depend on `tmp/`. Move the whole folder, including `raw/`. Scripts resolve the project root from their own location and read the shared `raw/` cache.

The FMP key is read from `~/.grok/secrets/fmp_api_key` only for API requests. Cache-only backtests and website builds require no key.

## The test

At the first trading day of each year, buy the 50 US common stocks with the highest EBITDA/EV. Sell them at the first trading day of the next year, and repeat. The last book was bought in January 2026 and marked on 2026-10-20.

Each stock gets the same weight. The comparison is SPY with dividends. There are no commissions.

EBITDA/EV is the earnings yield on enterprise value. A high number means the company looks cheap on that measure. The 3-month Treasury yield is subtracted, as requested. On a given day that yield is the same for every stock, so it does not change which 50 are bought.

## The frozen result

`results/summary-exits.txt` is the frozen record of the study. Nothing regenerates it.

From 2 January 1996 to 2 January 2026, $1 in the book grew to $143.88. The same dollar in SPY grew to $18.51. That is 18.0% a year against 10.2% a year.

Through 20 October 2026, the book grew to $178.28 and SPY grew to $21.00. That is 18.3% a year against 10.4% a year.

`results/legacy/summary.txt` and `results/legacy/picks.csv` are an earlier pass. That pass left out stocks whose trading stopped before the January sale. Do not use those two files as the latest numbers.

## Who gets bought

The universe is common stocks on the NYSE, Nasdaq, and NYSE American. It includes stocks that have since been delisted. It leaves out ETFs and funds. About 11,054 names were listed, and 6,358 had a usable annual figure.

A report is used only after 90 days from the fiscal year-end, and only if that year-end is less than 800 days before the buy date. Enterprise value is then updated to the buy-date share price. Debt and cash stay at the last report. The price series includes dividends, so a dividend between the fiscal year-end and the buy date moves the value a little.

The buy is skipped unless market cap is at least $100 million and enterprise value is at least $50 million, in dollars of that date. The currency is USD. A stock with no entry price is left out.

## When trading stops

Thirty-seven holdings stopped trading more than 10 days before the January sale. They stay in the book.

If another company bought them, or a note was called, or a SPAC returned cash, the exit is the last trade. Examples are Orbital ATK, FairPoint, Callon Petroleum, American Equity, and Civitas. Two warrants, Mudrick and HighPeak, finished at about −99% on the last trade.

A bankruptcy is a total loss. None of those 37 stops was a bankruptcy, so none was entered as −100%. The list of forced total losses is `BANKRUPT` in `backtest/financial/rules.py`. It is empty.

A stock that still trades on the January sale date keeps that price. Being delisted in a later year does not change the year already finished. A crash that still has a January price stays at that price. Spanish Broadcasting in 2008 stays at about −95%, not −100%.

## What is in the folder

| Path | Role |
|---|---|
| `scripts/check.py` | The development check ([research workflow](research-workflow.md#development-check)). |
| `backtest/engines/reference/revalue.py` | Independently calculates the study from saved files. It never publishes or downloads. |
| `backtest/engines/reference/legacy.py` | Owns the study constants and the independent original arithmetic. |
| `results/summary-exits.txt` | The frozen year-by-year result. |
| `results/legacy/summary.txt`, `results/legacy/picks.csv` | Older pass. The holdings file matches this pass, not `results/summary-exits.txt`. |
| `results/stops/stops.json` | The 37 names that stopped trading early. |
| `results/stops/stops-class.json` | SEC form types for those 37 names. |
| `raw/universe.json` | The US name list. |
| `raw/metrics.jsonl` | Annual market cap, enterprise value, and EV/EBITDA. |
| `raw/px/` | Dividend-adjusted price history used for the screen and the returns. |
| `raw/spy-div.json` | SPY with dividends, from 1995. |
| `raw/treasury.json` | Daily Treasury yields from 1995. `month3` is the 3-month yield, in percent. |

`tools/probe.py`, `tools/fetch_bulk.py` and the CSV files under `raw/archive/` were steps used to learn the API. The backtest does not read those CSV files.

## Limits

The screen can still pick a broken ratio. A few names show an EBITDA yield above 100%, and a few show one above 1,000%, because the old market cap and the later price do not fit. Taking those names out of the old holdings file did not remove the gap versus SPY. The 30-year figure stayed near 18% a year.

About two-thirds of the names changed each year in the old holdings file. Trading costs are not charged.

Delisted names are included: about 5,068 of the 11,054. The delisted list has no sector, no delisting date and no reason. A name on that list may have been bought years before it left the exchange.

Financial companies are included. EBITDA/EV is a weak description of a bank or an insurer.

## Continue

Run the study as a custom schedule every 12 months from 1 January 1996 on the website or in the queue. It uses the saved data and does not call FMP. On a real-data copy, `python3 scripts/check.py` confirms that this run equals the independent reference engine ([development check](research-workflow.md#development-check)).

To count a bankruptcy as a total loss, add the ticker and the day of the loss to `BANKRUPT` in `backtest/financial/rules.py` and rebuild the prepared data. A holding returns −100% only in a book whose window contains that day: after the entry day, through the exit day.
