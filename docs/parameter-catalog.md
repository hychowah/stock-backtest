# Parameter catalog

This page maps each input that a formula can read to its provider field and
unit. `bt catalog` lists every name, with its display and category
([command-line guide](command-line.md#variables-and-formulas)). The provider
is Financial Modeling Prep (FMP).

## Units and rules

- **USD:** an amount in US dollars. A Hong Kong or Tokyo value is converted
  to USD at the rate of the day that the formula reads. A step shows it in
  millions of dollars.
- **share:** a share count. It is never converted.
- **USD/share:** an amount per share, in US dollars.
- **scalar:** a ratio or a rate, read as a fraction (0.15 is 15%).

Statement inputs are yearly: a formula can read up to 10 fiscal years,
ending at the year of the selected report. Which statement values count is in
the [methodology](methodology.md#when-a-report-counts-as-known). A missing value
stays missing: null is not zero, and no other field fills it.

Weighted-average shares describe a year, not the share count on the screen
day. Cash-flow fields keep the provider's signs: spending is usually negative.

## Income statement

Endpoint: `income-statement`, annual.

| Input | Field | Unit |
|---|---|---|
| Revenue | `revenue` | USD |
| Cost of revenue | `costOfRevenue` | USD |
| SG&A expense | `sellingGeneralAndAdministrativeExpenses` | USD |
| R&D expense | `researchAndDevelopmentExpenses` | USD |
| Operating income | `operatingIncome` | USD |
| EBIT | `ebit` | USD |
| Interest income | `interestIncome` | USD |
| Interest expense | `interestExpense` | USD |
| Pretax income | `incomeBeforeTax` | USD |
| Income tax expense | `incomeTaxExpense` | USD |
| Net income | `netIncome` | USD |
| Basic shares | `weightedAverageShsOut` | share |
| Diluted shares | `weightedAverageShsOutDil` | share |
| Basic EPS | `eps` | USD/share |
| Diluted EPS | `epsDiluted` | USD/share |

## Balance sheet

Endpoint: `balance-sheet-statement`, annual.

| Input | Field | Unit |
|---|---|---|
| Cash and equivalents | `cashAndCashEquivalents` | USD |
| Short term investments | `shortTermInvestments` | USD |
| Long term investments | `longTermInvestments` | USD |
| Net receivables | `netReceivables` | USD |
| Accounts receivable | `accountsReceivables` | USD |
| Inventory | `inventory` | USD |
| Prepaid expenses | `prepaids` | USD |
| Current assets | `totalCurrentAssets` | USD |
| Net PP&E | `propertyPlantEquipmentNet` | USD |
| Goodwill | `goodwill` | USD |
| Intangible assets | `intangibleAssets` | USD |
| Total assets | `totalAssets` | USD |
| Accounts payable | `accountPayables` | USD |
| Accrued expenses | `accruedExpenses` | USD |
| Current deferred revenue | `deferredRevenue` | USD |
| Noncurrent deferred revenue | `deferredRevenueNonCurrent` | USD |
| Current liabilities | `totalCurrentLiabilities` | USD |
| Total liabilities | `totalLiabilities` | USD |
| Short term debt | `shortTermDebt` | USD |
| Long term debt | `longTermDebt` | USD |
| Lease obligations | `capitalLeaseObligations` | USD |
| Total debt | `totalDebt` | USD |
| Shareholders equity | `totalStockholdersEquity` | USD |
| Preferred stock | `preferredStock` | USD |
| Minority interest | `minorityInterest` | USD |

Net receivables and accounts receivable are different fields. Shareholders
equity leaves out minority interest. Preferred stock is a book amount. Debt and
lease fields can overlap: do not add them to replace Total debt.

## Cash-flow statement

Endpoint: `cash-flow-statement`, annual.

| Input | Field | Unit |
|---|---|---|
| Operating cash flow | `operatingCashFlow` | USD |
| CapEx | `capitalExpenditure` | USD |
| Reported free cash flow | `freeCashFlow` | USD |
| Depreciation and amortization | `depreciationAndAmortization` | USD |
| Stock based compensation | `stockBasedCompensation` | USD |
| Net acquisitions | `acquisitionsNet` | USD |
| Income taxes paid | `incomeTaxesPaid` | USD |
| Interest paid | `interestPaid` | USD |
| Net debt issuance | `netDebtIssuance` | USD |
| Common dividends paid | `commonDividendsPaid` | USD |
| Preferred dividends paid | `preferredDividendsPaid` | USD |
| Share buybacks | `commonStockRepurchased` | USD |
| Share issuance | `commonStockIssuance` | USD |

Depreciation and amortization comes from the cash-flow statement, not from the
income statement. Net acquisitions and net debt issuance are net amounts: they
do not give gross spending, borrowing or repayment.

## Market and rate inputs

| Input | Source | Unit |
|---|---|---|
| Share price | `historical-price-eod/dividend-adjusted`, `adjClose`, in USD at the day's rate | USD/share |
| Trading volume | `historical-price-eod/dividend-adjusted`, `volume` | share |
| Treasury 3 month yield | `treasury-rates`, `month3`, divided by 100 | scalar |
| Treasury 10 year yield | `treasury-rates`, `year10`, divided by 100 | scalar |

A price or volume is the one of the last session on or before the day, at
most 7 days earlier. A Treasury yield is the one of the last Treasury day on
or before the screen day (before it, for Hong Kong and Tokyo).

## Calculated inputs

| Input | How it is calculated | Unit |
|---|---|---|
| EBITDA | US: report enterprise value / EV/EBITDA, from `key-metrics`. Hong Kong and Tokyo: `income-statement` `ebitda`. One value for each fiscal year of the selected reports. | USD |
| Operating margin | Operating income / Revenue, when Revenue is above zero | scalar |

Market cap and Enterprise value are built-in values: the entry valuation of
the [methodology](methodology.md#valuation-and-currency).

## Named measures

| Measure | Formula |
|---|---|
| Gross profit | Revenue − Cost of revenue |
| Gross margin | Gross profit / positive(Revenue) |
| Working capital | Current assets − Current liabilities |
| Net debt | Total debt − Cash and equivalents |
| Tangible book equity | Shareholders equity − Goodwill − Intangible assets |
| Operating cash flow plus CapEx | Operating cash flow + CapEx |
| Price/sales | Market cap / positive(Revenue) |
| Debt/assets | Total debt / positive(Total assets) |

## Built-in values

The program calculates the built-in values from the selected report, the
prices and the entry valuation; `bt catalog` lists them all. "The year" is the
selected report's fiscal year. A value is missing when a part of it is
missing or a bottom is not above zero. The values that need a definition:

| Value | Definition |
|---|---|
| P/E, P/S, P/B, Price/FCF | Market cap ÷ the year's net income, revenue, shareholders equity or free cash flow |
| ROE | The year's net income ÷ the mean of the year's and the year before's shareholders equity, both above zero |
| PEG | P/E ÷ the yearly growth, in percent, of diluted EPS over 3 years; needs diluted EPS above zero in all 4 years |
| EV/3-year average EBITDA | Enterprise value ÷ the mean EBITDA of the 3 calendar years that end with the year; needs a report in each year. 3-year average EBITDA yield is its inverse |
| Operating yield spread | Revenue × the mean operating margin of the same 3 years ÷ enterprise value, in percent, − the US 10-year Treasury yield, in percentage points |
| One year return, Three year return | The dividend-adjusted close of the screen day ÷ the close of the same date 1 or 3 years earlier − 1, in USD. Each close is the last one on or before its date, at most 7 days earlier; 29 February becomes 28 February |
| P/E, P/S and P/B 3-year and 5-year averages | 1 ÷ the mean daily yield (net income, revenue or equity of the report selected that day ÷ that day's market cap; a loss counts) over the days after the same date 3 or 5 years earlier, through the screen day. Needs a day with a yield on or before that start, and a mean above zero |
| P/E, P/S and P/B vs 3-year or 5-year average | The current value ÷ its average: below 1 is cheaper than usual |
| Dividend yield | The year's common dividends paid, with the sign reversed (the provider shows a payment as negative), ÷ market cap. 0 when the report shows no payment |
| Turnover rate 1-week average | The mean of the saved volumes in the 7 calendar days that end on the screen day ÷ the year's basic weighted shares. The provider restates volumes and report shares to the latest split, so a split after a report was saved skews turnover until the reports are downloaded again |

## Not available

The provider's standard annual fields do not give these items, so no input
reads them: depreciation and amortization apart; impairment and restructuring
charges; restricted cash; the current part of long-term debt; operating and
finance leases apart; the share count on a given day; dividends per share;
quarterly or trailing-twelve-month values.
