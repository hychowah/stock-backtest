# FMP-backed valuation inputs

Checked: 2026-11-02.

Current Phase 11 source exposes owner descriptions for all 52 direct inputs,
existing-policy adapters and 33 exact named measures through the shared editor.
Categories, search, units and supported history choices use the same semantic
owners as execution. The [phase record](phases/phase-11/README.md) owns final
verification and audited completion evidence. Catalog recognition, implemented
observations, backend qualification, installed readiness and observed coverage
remain separate.

Qualified captured programs run through Original and bounded numerical execution
in Latest, January, fixed and random modes. The fixed backend inventory contains
77 IDs. A capture retains the 32-definition ceiling. Numerical sample preview and
eager scalar execution remain unsupported. Inspection evaluates complete recorded
January/latest scopes with their generation, denominator and unavailable reasons.
These source capabilities establish no installed readiness or live-cache coverage.

This inventory maps documented fields from existing FMP routes. Include an input
only when an existing route supplies it or an explicit calculation uses supplied
inputs. Preserve the [versioned field contract](phases/phase-08/parameter-contract.md),
source meanings, original immutable definitions and financial policy. Phase READMEs
and git history retain earlier implementation states and exact verification.

## Source check and its limits

The tables map 52 direct inputs to FMP's documented response fields. Public FMP
documentation was checked against the project's current download routes. No
authenticated request, native-cache inspection or market-data download was made.
This establishes the documented source path. It does not establish nonmissing
coverage for every company or historical date, or test account-specific limits.

The existing Full annual financial data action requests `income-statement`,
`balance-sheet-statement` and `cash-flow-statement` with annual periods. It also
requests `key-metrics` and `ratios`. See
[`website/server/data_manager.py`](../../../website/server/data_manager.py).
[`backtest/inputs/financial_inputs.py`](../../../backtest/inputs/financial_inputs.py)
saves full statement responses, including fields not currently prepared. At the original source check, its
validated projection included only:

- Income: `revenue`, `operatingIncome`, `netIncome`, `epsDiluted`, `ebit`,
  `interestExpense`.
- Balance: `totalStockholdersEquity`, `totalCurrentAssets`,
  `totalCurrentLiabilities`, `totalDebt`.
- Cash flow: `freeCashFlow`.

Phases 8–11 add validation, conflict resolution, prepared evidence and qualified
execution for the remaining mapped fields. A raw field
must not become usable merely because the downloader retained it. Reuse valid
saved responses first. Missing data stays unavailable. Downloads remain an
explicit data-panel action.

The existing price route is `historical-price-eod/dividend-adjusted`. The existing
rate route is `treasury-rates`. Both retain complete rows. New observations such
as volume still need validation and preparation. This inventory requires no new
FMP endpoint or as-reported filing parser.

## Direct statement inputs

Unless stated otherwise, statement amounts use USD from eligible annual reports.
Shares use a share count. Every field must be finite and unambiguous for its
endpoint and fiscal date. A documented zero in one provider example does not
prove zero coverage for other companies. Null is not zero.

### Income statement

Source: [FMP Income Statement API](https://site.financialmodelingprep.com/developer/docs/stable/income-statement).
All rows use `income-statement`.

| Input | FMP field |
|---|---|
| Revenue | `revenue` |
| Cost of revenue | `costOfRevenue` |
| Selling, general and administrative expense | `sellingGeneralAndAdministrativeExpenses` |
| Research and development expense | `researchAndDevelopmentExpenses` |
| Operating income | `operatingIncome` |
| Interest income | `interestIncome` |
| Interest expense | `interestExpense` |
| Pretax income | `incomeBeforeTax` |
| Income tax expense | `incomeTaxExpense` |
| Net income under the existing FMP definition | `netIncome` |
| Weighted-average basic shares; shares | `weightedAverageShsOut` |
| Weighted-average diluted shares; shares | `weightedAverageShsOutDil` |

Weighted-average shares describe an annual period. They are not an exact share
count at the screen date. Preserve the existing `annual.net_income` meaning.
Do not relabel it as a separately verified consolidated or common-only figure.

### Balance sheet

Source: [FMP Balance Sheet Statement API](https://site.financialmodelingprep.com/developer/docs/stable/balance-sheet-statement).
All rows use `balance-sheet-statement`.

| Input | FMP field |
|---|---|
| Cash and cash equivalents | `cashAndCashEquivalents` |
| Short-term investments | `shortTermInvestments` |
| Long-term investments | `longTermInvestments` |
| Net receivables | `netReceivables` |
| Accounts receivable | `accountsReceivables` |
| Inventory | `inventory` |
| Prepaid expenses | `prepaids` |
| Total current assets | `totalCurrentAssets` |
| Net property, plant and equipment | `propertyPlantEquipmentNet` |
| Goodwill | `goodwill` |
| Intangible assets excluding goodwill | `intangibleAssets` |
| Total assets | `totalAssets` |
| Accounts payable | `accountPayables` |
| Accrued expenses | `accruedExpenses` |
| Current deferred revenue | `deferredRevenue` |
| Noncurrent deferred revenue | `deferredRevenueNonCurrent` |
| Total current liabilities | `totalCurrentLiabilities` |
| Total liabilities | `totalLiabilities` |
| FMP short-term debt | `shortTermDebt` |
| FMP long-term debt | `longTermDebt` |
| FMP lease obligations | `capitalLeaseObligations` |
| Book shareholders' equity | `totalStockholdersEquity` |
| Book preferred stock | `preferredStock` |
| Noncontrolling interests | `minorityInterest` |

Keep net receivables distinct from accounts receivable. Keep shareholders' equity
distinct from common-only equity and from equity including noncontrolling
interests. Preferred stock here is a book amount, not its market value.
The lease field does not establish separate operating and finance lease values.
Debt and lease categories can overlap. Reuse existing total-debt and EV policy;
do not sum these fields into a replacement for either calculation.

### Cash-flow statement

Source: [FMP Cash Flow Statement API](https://site.financialmodelingprep.com/developer/docs/stable/cashflow-statement).
All rows use `cash-flow-statement`.

| Input | FMP field |
|---|---|
| Combined depreciation and amortization | `depreciationAndAmortization` |
| Stock-based compensation | `stockBasedCompensation` |
| Operating cash flow | `operatingCashFlow` |
| Capital-expenditure cash flow; retain the FMP sign | `capitalExpenditure` |
| Net acquisition cash flow; retain the FMP sign | `acquisitionsNet` |
| Cash income taxes paid | `incomeTaxesPaid` |
| Cash interest paid | `interestPaid` |
| Net debt issuance | `netDebtIssuance` |
| Common dividends paid | `commonDividendsPaid` |
| Preferred dividends paid | `preferredDividendsPaid` |
| Common-share repurchase cash flow | `commonStockRepurchased` |
| Common-share issuance cash flow | `commonStockIssuance` |

Retain source signs in raw assets. Specify sign conversion per field before
exposing a positive spending amount. Never apply absolute value to all cash-flow
fields. Net acquisition cash flow is not gross acquisition spending. Net debt
issuance cannot reveal separate gross borrowing and repayment.

Use the cash-flow endpoint as the source of the combined depreciation and
amortization input. The same key in the income endpoint is a distinct source;
do not silently switch between them to fill a missing value.

## Direct market and rate inputs

Sources: [FMP Historical Market Data](https://site.financialmodelingprep.com/datasets/market-data-historic)
and [FMP Treasury Rates API](https://site.financialmodelingprep.com/developer/docs/stable/treasury-rates).

| Input | Existing route | Field | Canonical unit |
|---|---|---|---|
| Dividend-adjusted close | `historical-price-eod/dividend-adjusted` | `adjClose` | USD/share |
| Trading volume | `historical-price-eod/dividend-adjusted` | `volume` | Shares per session |
| US 3-month Treasury yield | `treasury-rates` | `month3` | Fraction; divide provider percent by 100 |
| US 10-year Treasury yield | `treasury-rates` | `year10` | Fraction; divide provider percent by 100 |

Use explicit dates and the existing availability and lookup rules. Historical
volume requires a saved value for the relevant session; an old price does not
provide missing volume. Dividend-adjusted prices must not be presented as
unadjusted transaction prices or multiplied by annual average shares to replace
the existing market-cap calculation.

## Calculated measures and existing adapters

These are reusable built-in variables or compatibility adapters. They are not
additional raw ingredients. Every calculation needs its own named definition,
required inputs and missing-data rules. Built-in ratios retain their declared
positive-denominator rules. General division keeps the Phase 1 signed-arithmetic
rules and rejects zero denominators. Existing built-ins retain their exact
arithmetic and stored rounding.

| Measure | Supported source path or proposed calculation |
|---|---|
| Gross profit | `revenue - costOfRevenue` |
| Gross margin | Gross profit / positive `revenue` |
| Operating and net margins | `operatingIncome` or `netIncome` / positive `revenue`; preserve existing net-margin policy |
| EBIT | Existing validated `income-statement.ebit`; do not equate it with operating income |
| EBITDA | The proposed `annual.ebitda` adapter keeps the existing report EV / report EV-to-EBITDA series for eligible reports. FMP also documents `income-statement.ebitda`; any separately named statement-EBITDA variable needs its own admission. Do not replace or fill the existing series with it. |
| Free cash flow | Preserve existing `cash-flow-statement.freeCashFlow`. A separately named CFO-plus-signed-CapEx formula can use `operatingCashFlow + capitalExpenditure`; require all inputs and do not silently substitute it for the stored value. |
| Total debt | Existing validated `balance-sheet-statement.totalDebt`; preserve its provider definition |
| Net debt, cash-only definition | `totalDebt - cashAndCashEquivalents`; define investment treatment separately |
| Working capital | `totalCurrentAssets - totalCurrentLiabilities` |
| Tangible book equity | `totalStockholdersEquity - goodwill - intangibleAssets`; no common-only claim |
| Market cap and enterprise value | Existing dated financial adapters and report bindings in `backtest/financial/books.py`; no share-count shortcut or new EV formula |
| Basic and diluted EPS | Documented `income-statement.eps` and existing validated `epsDiluted`; expose as built-ins with provider definitions |
| P/S and debt/assets | Existing dated market cap / positive `revenue`; existing `totalDebt` / positive `totalAssets` |
| Existing ratios, yields and operating spread | Reuse `backtest/financial/metrics.py`, the Phase 1 compatibility map and their existing input/denominator policies |
| Historical growth and averages | Apply supported date/history operators to one underlying input; require the requested history and explicit growth rules |

P/S and debt/assets have documented inputs. They still require future formula
and preparation work. Do not advertise them as current website capabilities.
Growth, averaging and calendar lookbacks are operations on an input. They do not
create extra raw parameters. Quarterly and TTM remain outside the first release.

## Items excluded from the target inventory

The earlier suggested list included finer splits that the existing routes do
not establish. Exclude the following from the admitted list:

| Excluded item | Reason |
|---|---|
| Separate depreciation and separate amortization | The checked standardized responses provide their combined amount. Do not infer either component. |
| Separate impairment charges, restructuring charges and asset-sale gains/losses | No distinct verified field in the checked responses. `otherNonCashItems` and other aggregates cannot isolate them. |
| Restricted cash and investments in associates as separate inputs | No distinct verified standardized field. Broader cash/investment totals are insufficient. |
| Separate current portion of long-term debt | `shortTermDebt` does not isolate this component. |
| Separate operating and finance lease liabilities | The verified lease fields do not establish this split. |
| Separate gross borrowing and gross debt repayment | The checked cash-flow schema supplies net issuance. Changes in balance-sheet debt do not reconstruct the gross flows. |
| Gross acquisition spending and asset-sale proceeds | Net acquisitions and aggregated investing flows cannot establish these amounts. |
| Exact shares outstanding at a screening date | Annual weighted-average shares are not an exact dated share count. No current profile/quote substitution is allowed in historical tests. |
| Book value or dividends per exact current share | No verified exact dated share count or separate per-share dividend source in these routes. Do not approximate it with annual weighted-average shares. |
| Unadjusted historical transaction price | The verified existing dividend-adjusted route does not supply this observation. |
| Separately defined consolidated and common-only net income | Keep the existing `netIncome` meaning. The check did not establish these attribution splits. |

These exclusions mean "not admitted by this check." They do not claim that FMP
can never supply an item through another endpoint or company-specific filing.
A later addition needs a separate verified source path and scope agreement.

## Admission in later increments

Keep the first provider limited to revenue, operating income, operating margin
and EV. The current Phase 2 execution plan assigns that scope to
`feature/custom-variables`. The broader inventory is a target for explicitly
verified later increments, not a claim that Phase 2 already supports it.

For each increment, map the chosen field to validation, prepared evidence,
freshness and backend capabilities. Test missing values, currencies, conflicts,
signs, fiscal dates and unavailable histories. Reuse complete saved responses;
do not redownload them just to expose an additional retained field. Measure
company/date coverage before the picker marks an input usable.

Apply the existing 90-day lag, strict availability-before-date rule and 800-day
anchor age limit. Bind all inputs to their admitted generation. No later report
may fill a missing selected-report field. This record adds no filing-vintage
accuracy claim or numerical-engine support.
