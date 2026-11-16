# Methodology

This page gives the financial rules that a reader needs to trust a result,
then the original 30-year US January study. The research is not investment
advice. A backtest describes the past and does not predict future returns.

## Markets and universes

The program prepares three markets: US, Hong Kong and Tokyo. A test uses one
market. `bt data update` downloads US and Hong Kong data only, so Tokyo data
stays as it was saved.

- **US.** Common stocks on the NYSE, Nasdaq and NYSE American, from the
  provider's company screener and its delisted list. ETFs, funds and ETNs are
  left out. The list keeps delisted companies.
- **Hong Kong.** Listings on the Hong Kong exchange with a code of the form
  `dddd.HK`. Codes that start with 4 are left out: the provider lists bonds
  and dormant Hong Kong lines of US companies there, with months-old prices
  and the companies' worldwide share counts. Five-digit RMB counters and names
  with the word ETF, fund or ETN are also left out.
- **Tokyo.** Codes of three digits, then a digit or a capital letter, then
  `.T`, without ETFs, funds or ETNs.

A historical screen admits every company of the list, delisted ones included.
The latest screen admits only the companies that are listed now. Names,
sectors and exchanges are the provider's current values, not a history.

**Sessions.** US sessions are the days with a SPY close. Hong Kong and Tokyo
sessions are the completed sessions of the local index calendar: a day counts
after its close (16:00 Hong Kong time, 15:30 Tokyo time).

## When a report counts as known

A US report comes from the provider's annual key metrics. It is accepted when
its market cap, enterprise value and EV/EBITDA are positive and its currency
is USD or not given. Its EBITDA is enterprise value divided by EV/EBITDA. It is known 90
days after its fiscal date, whatever its publication date.

A Hong Kong or Tokyo report is built from the income statement and the
balance sheet of one fiscal date. Both must name the same currency. The
report needs positive basic weighted shares and EBITDA, and valid total debt
and cash. A statement is known on its publication date when that date is later
than the fiscal date. Otherwise it is known four months (Hong Kong) or three
months (Tokyo) after the fiscal date. The report is known on the later date of
its two statements.

On a screen day, a company uses its newest report that:

- became known before that day, and
- has a fiscal date at most 800 days before that day.

Formulas read the annual statements of the selected report's fiscal year and
of the years before it. A later report never fills a missing value. A field
with two different values for one fiscal date is missing. A US statement
value must be in USD.

Report values are the provider's current versions, not the original filings.
The fallback delays are assumptions about availability, not proof of a
point-in-time archive.

## Valuation and currency

All money, thresholds, holdings, returns and CAGR are in US dollars. Cash is
in US dollars and earns 0%.

**Entry valuation.** A report's market cap is valued at its fiscal date. It is
moved to the entry day with the ratio of the dividend-adjusted closes:

- market cap at entry = report market cap × entry close / fiscal close;
- enterprise value at entry = market cap at entry + report enterprise value −
  report market cap. Debt and cash stay as reported.

The fiscal close is the last close on or before the fiscal date, at most 7
days earlier. A historical screen enters at the first close on or after the
screen day, at most 4 days later. The latest screen enters at the close of the
day itself. A company without these closes, or with a market cap or enterprise
value that is not positive, is not a candidate.

**Hong Kong and Tokyo.** The fiscal market cap is the basic weighted shares
times the last unadjusted local close within the 7 days up to the fiscal date.
On a screen day, the market cap is converted at the quote currency's rate of
that day. EBITDA, debt and cash are converted at the report currency's rate of
that day. A holding's prices are converted at the rate of each price's own
day.

**FX rates.** A rate for a day is the last fixing before that day, at most 7
days old. A price or report value without a rate is missing.

**Spread.** A candidate's spread is its EBITDA yield minus the US 3-month
Treasury rate of the day, or minus 0 when there is no rate. All markets use US
Treasury yields.

## Prices and dividends

Every stock price is the provider's dividend-adjusted close. A close must be
positive and in the company's currency. A price series in which one close is
at least 8 times, or at most 1/8 of, both of its neighbours mixes two price
scales. The program then uses no close of that series.

### Dividends

The engine keeps no dividend cash. A holding's return is
`adjusted exit / adjusted entry − 1`. This is a total return: each dividend
counts as reinvested in the same stock on its ex-date, before tax. Hong Kong
and Tokyo prices are adjusted in the local currency, and each end is converted
to USD at its own day's rate. SPY and the trailing-return values use the same
kind of series.

This method has four known limits. They are accepted as they are.

- **Entry valuation is too high for dividend payers.** The adjusted price
  ratio that moves the market cap to the entry day includes the dividends
  paid between the two dates. Entry market cap and EV are then too high by
  about that amount, and a high-dividend stock ranks slightly lower than it
  should.
- **The provider omits some dividends.** The adjusted series then shows no
  payment, and that holding's return is too low.
- **The provider records a few adjustments that are much too large.** That
  holding's return is too high.
- **Returns are before tax.** No withholding tax and no delay between ex-date
  and payment are modeled.

The sizes were measured for Hong Kong on a copy of the owner's raw data
(prices through 6 November 2026), with the engine's price rules: the first
session of each month from August 2001 to November 2025, the top 50 by
EBITDA/EV with a market cap of at least $100 million and an EV of at least
$50 million, held 12 months.

| Item | Measured for these Hong Kong picks |
|---|---|
| Mean 12-month return | 15.8% in USD, of which dividends are 4.4 percentage points. For picks entered from 2018: 7.0%, of which 5.5 points. |
| Entry market cap too high | Median 2.2%, mean 3.4%, one pick in ten above 7.9%. From 2018: median 3.4%, one in ten above 10.8%. |
| Effect of that on picks | Moving the market cap with the unadjusted close changes about 6% of picks. The mean return moves from 15.8% to 16.2%, inside the spread between periods (standard deviation 2.6 points). |
| Omitted dividends | In about 11% of pick-years the cash-flow statement shows dividends and the adjusted price shows none (for example Sinopec, fiscal 2017 and 2020). The yield implied by prices is 3.6% against 4.7% from statements. The gap is an upper bound: statement amounts can include payments to other holders. |
| Oversized adjustments | 19 symbols show a one-year adjustment above 25% of the price (for example 3903.HK: 73% of the price on one day in 2018). With these holdings at their price-only return, the mean falls from 15.8% to 15.1%. |
| Tax | At most about 0.5 points a year if every pick had 10% withholding. This is arithmetic, not a measurement. |
| Rounding of low adjusted prices | Negligible: 0.6% of picks can be wrong by more than 1%. |

The two provider errors have opposite directions. The average Hong Kong
return is probably correct to about one percentage point a year, but the
return of one holding can be far wrong. These are observed values, not
guarantees. US and Tokyo were not measured, and the US data has no
unadjusted prices.

## The portfolio and its exits

- On each entry day, each sleeve runs its steps in order on all candidates.
  The picks of the sleeves join into one portfolio. A company that two
  sleeves pick is held once.
- When a Rank step finds equal values, it puts first the candidates without
  a tie rank (Hong Kong and Tokyo have none), then lower tie ranks,
  then symbols in alphabetical order. A US company's tie rank is its place,
  up to 250, by the yield of its newest usable report with a market cap of at
  least $100 million and an enterprise value of at least $50 million.
- Every holding gets the same weight. There are no commissions, taxes or
  slippage.
- A holding exits at its last close on or before the exit day, at most 10
  days earlier. If it has no close in those 10 days, because trading stopped,
  it exits at its last earlier close and the money stays in cash at 0% until
  the period ends. A holding with no close at all from its entry to its exit
  stops the run with an error.
- A period's return is the mean of its holdings' returns. A period without
  holdings returns 0%.
- SPY is the S&P 500 total-return benchmark. A US day uses that day's SPY
  close. A Hong Kong or Tokyo day uses the last completed US close before it,
  at most 7 days earlier.
- A test's growth is the product of its periods' growth. Its CAGR is that
  growth per year over the whole window, with years of 365.25 days.

## Schedules and random trial dates

The window runs from the first session on or after the start date to the
final mark, the last session on or before the end date. The start date is 1
January 1996 or later. The end date must not be after the market's last
prepared session.

- **Fixed interval.** Trade every N weeks (1 to 104) or N months (1 to 24).
  Each target date counts from the requested start date. A month end that
  does not exist becomes the last day of that month. A target that is not a
  session rolls forward to the next session. The last period exits at the
  final mark, so it can be shorter than the interval. Each period exits on the
  next period's entry, so periods do not overlap.
- **Random dates.** The window is cut into the same interval blocks. Each
  trial trades on one random session in every block that has a session. The
  seed sets the dates: the same seed on the same sessions gives the same
  dates. Every trial has the same window. The trial and its SPY comparison
  both hold cash at 0% from the window's first session until its first
  trade, so all trials compare over the same time.
- **Explicit dates.** One trial trades on the given sessions, in increasing
  order, from the window's first session and before the final mark.

Over the trials, the result gives the median, mean, worst and best CAGR,
percentiles by linear interpolation, the population standard deviation and
the number of trials whose CAGR is above SPY's. Percentiles describe the
sampled dates. They are not confidence limits.

A formula that reads a value with `at(X, DATE)` stops the run when `DATE` is
after the screen day.

## The January study, 1996–2026

The original study is a 30-year US test: on the first trading day of each
year, buy the 50 US common stocks with the highest EBITDA/EV. Sell them on the
first trading day of the next year, and repeat. The last book was bought in
January 2026 and marked on 2026-10-20. Each stock gets the same weight. The
comparison is SPY with dividends. There are no commissions.

EBITDA/EV is the earnings yield on enterprise value. A high number means that
the company looks cheap on that measure. The 3-month Treasury yield is
subtracted. On a given day that yield is the same for every stock, so it does
not change which 50 are bought.

### The frozen result

`results/summary-exits.txt` is the frozen record of the study. Nothing
regenerates it, and no code reads it.

From 2 January 1996 to 2 January 2026, $1 in the book grew to $143.88. The
same dollar in SPY grew to $18.51. That is 18.0% a year against 10.2% a year.

Through 20 October 2026, the book grew to $178.28 and SPY grew to $21.00. That
is 18.3% a year against 10.4% a year.

`results/legacy/summary.txt` and `results/legacy/picks.csv` are an earlier
pass. That pass left out stocks whose trading stopped before the January sale.
Do not use those two files as the latest numbers.

### Who was bought

The universe was the US list above, with delisted stocks. About 11,054 names
were listed, and 6,358 had a usable annual figure. On each buy date the study
first kept the 250 companies with the highest report yields, among reports
with a market cap of at least $100 million and an enterprise value of at least
$50 million. It then valued them at the buy date as this page describes, and
skipped a buy below the same two floors in dollars of that date. The program
has no such pre-screen: it selects from every candidate, and a floor is a
Filter step. So the program cannot run the study again exactly.

### When trading stopped

Thirty-seven holdings stopped trading more than 10 days before the January
sale. They stay in the book.

If another company bought them, or a note was called, or a SPAC returned cash,
the exit is the last trade. Examples are Orbital ATK, FairPoint, Callon
Petroleum, American Equity and Civitas. Two warrants, Mudrick and HighPeak,
finished at about −99% on the last trade.

The study counted a bankruptcy as a total loss only from a list of named
cases. None of the 37 stops was a bankruptcy, so the list was empty and none
was entered as −100%. The program has no such list.

A stock that still trades on the January sale date keeps that price. A
delisting in a later year does not change the year already finished. A crash
that still has a January price stays at that price: Spanish Broadcasting in
2008 stays at about −95%, not −100%.

`results/stops/stops.json` lists the 37 names, and
`results/stops/stops-class.json` gives their SEC form types.

### Limits of the study

The screen can still pick a broken ratio. A few names show an EBITDA yield
above 100%, and a few show one above 1,000%, because the old market cap and the
later price do not fit. Taking those names out of the old holdings file did
not remove the gap against SPY. The 30-year figure stayed near 18% a year.

About two-thirds of the names changed each year in the old holdings file.
Trading costs are not charged.

Delisted names are included: about 5,068 of the 11,054. The delisted list has
no sector, no delisting date and no reason. A name on that list may have been
bought years before it left the exchange.

Financial companies are included. EBITDA/EV is a weak description of a bank or
an insurer.
