//! The formula parameters ([`PARAMETERS`], the oracle's catalog
//! `financial-parameters/4`) and their observations
//! ([`MarketData::observe`](crate::MarketData::observe), the oracle's
//! `columns.Formulas._observation` over `fact_view.View`). Each reading
//! calls the module that owns its rule; this module only chooses the
//! context's anchor report and valuation.

use crate::annual::{BALANCE, CASH_FLOW, Field, INCOME, field, is_share_count};
use crate::builtins::{self, BUILTINS};
use crate::screen::{self, Candidate, Columns, ENTRY_SLACK};
use crate::reports::convert;
use crate::{CompanyId, Day};

/// One formula parameter: a quantity a formula reads at a context.
#[derive(Clone, Copy, Debug)]
pub struct Parameter {
    /// The oracle's id: `annual.<field>`, `market.<name>`, `treasury.<name>`
    /// or `owner.<lane>`.
    pub id: &'static str,
    /// `USD`, `USD/share`, `share` or `scalar`.
    pub unit: &'static str,
    /// Whether it has one value per fiscal year, so that a formula can read
    /// up to 10 years of it; every other parameter has one value.
    pub yearly: bool,
    source: Source,
}

/// Where a parameter's values come from.
#[derive(Clone, Copy, Debug)]
enum Source {
    /// A statement field on the income fiscal spine.
    Annual(Field),
    /// Operating income / positive revenue on the spine.
    OperatingMargin,
    /// The selected reports' EBITDA by fiscal year.
    ReportEbitda,
    /// The dividend-adjusted close of the session, in USD.
    Close,
    Volume,
    /// The Treasury yield, by its place in [`Series::treasury_rates`](crate::series::Series::treasury_rates).
    Treasury(usize),
    EnterpriseValue,
    MarketCap,
    /// A built-in lane, by its place in [`BUILTINS`]; a percent lane
    /// (storage scale -2) is read divided by 100.
    Owner { lane: usize },
}

const fn annual(id: &'static str, statement: usize, name: &str) -> Parameter {
    let field = field(statement, name);
    let unit = if is_share_count(field) { "share" } else { "USD" };
    Parameter { id, unit, yearly: true, source: Source::Annual(field) }
}

const fn per_share(id: &'static str, name: &str) -> Parameter {
    Parameter { unit: "USD/share", ..annual(id, INCOME, name) }
}

const fn single(id: &'static str, unit: &'static str, source: Source) -> Parameter {
    Parameter { id, unit, yearly: false, source }
}

const fn owner(id: &'static str, builtin: &str) -> Parameter {
    single(id, "scalar", Source::Owner { lane: builtins::at(builtin) })
}

/// The parameters in the catalog's order.
pub const PARAMETERS: [Parameter; 77] = [
    annual("annual.revenue", INCOME, "revenue"),
    annual("annual.cost_of_revenue", INCOME, "costOfRevenue"),
    annual("annual.selling_general_administrative_expense", INCOME, "sellingGeneralAndAdministrativeExpenses"),
    annual("annual.research_development_expense", INCOME, "researchAndDevelopmentExpenses"),
    annual("annual.operating_income", INCOME, "operatingIncome"),
    annual("annual.interest_income", INCOME, "interestIncome"),
    annual("annual.interest_expense", INCOME, "interestExpense"),
    annual("annual.pretax_income", INCOME, "incomeBeforeTax"),
    annual("annual.income_tax_expense", INCOME, "incomeTaxExpense"),
    annual("annual.net_income", INCOME, "netIncome"),
    annual("annual.weighted_average_basic_shares", INCOME, "weightedAverageShsOut"),
    annual("annual.weighted_average_diluted_shares", INCOME, "weightedAverageShsOutDil"),
    annual("annual.cash_and_equivalents", BALANCE, "cashAndCashEquivalents"),
    annual("annual.short_term_investments", BALANCE, "shortTermInvestments"),
    annual("annual.long_term_investments", BALANCE, "longTermInvestments"),
    annual("annual.net_receivables", BALANCE, "netReceivables"),
    annual("annual.accounts_receivable", BALANCE, "accountsReceivables"),
    annual("annual.inventory", BALANCE, "inventory"),
    annual("annual.prepaid_expenses", BALANCE, "prepaids"),
    annual("annual.current_assets", BALANCE, "totalCurrentAssets"),
    annual("annual.property_plant_equipment_net", BALANCE, "propertyPlantEquipmentNet"),
    annual("annual.goodwill", BALANCE, "goodwill"),
    annual("annual.intangible_assets", BALANCE, "intangibleAssets"),
    annual("annual.total_assets", BALANCE, "totalAssets"),
    annual("annual.accounts_payable", BALANCE, "accountPayables"),
    annual("annual.accrued_expenses", BALANCE, "accruedExpenses"),
    annual("annual.current_deferred_revenue", BALANCE, "deferredRevenue"),
    annual("annual.noncurrent_deferred_revenue", BALANCE, "deferredRevenueNonCurrent"),
    annual("annual.current_liabilities", BALANCE, "totalCurrentLiabilities"),
    annual("annual.total_liabilities", BALANCE, "totalLiabilities"),
    annual("annual.short_term_debt", BALANCE, "shortTermDebt"),
    annual("annual.long_term_debt", BALANCE, "longTermDebt"),
    annual("annual.lease_obligations", BALANCE, "capitalLeaseObligations"),
    annual("annual.equity", BALANCE, "totalStockholdersEquity"),
    annual("annual.preferred_stock", BALANCE, "preferredStock"),
    annual("annual.noncontrolling_interests", BALANCE, "minorityInterest"),
    annual("annual.depreciation_amortization", CASH_FLOW, "depreciationAndAmortization"),
    annual("annual.stock_based_compensation", CASH_FLOW, "stockBasedCompensation"),
    annual("annual.operating_cash_flow", CASH_FLOW, "operatingCashFlow"),
    annual("annual.capital_expenditure", CASH_FLOW, "capitalExpenditure"),
    annual("annual.net_acquisitions", CASH_FLOW, "acquisitionsNet"),
    annual("annual.income_taxes_paid", CASH_FLOW, "incomeTaxesPaid"),
    annual("annual.interest_paid", CASH_FLOW, "interestPaid"),
    annual("annual.net_debt_issuance", CASH_FLOW, "netDebtIssuance"),
    annual("annual.common_dividends_paid", CASH_FLOW, "commonDividendsPaid"),
    annual("annual.preferred_dividends_paid", CASH_FLOW, "preferredDividendsPaid"),
    annual("annual.common_stock_repurchased", CASH_FLOW, "commonStockRepurchased"),
    annual("annual.common_stock_issuance", CASH_FLOW, "commonStockIssuance"),
    single("market.adjusted_price", "USD/share", Source::Close),
    single("market.volume", "share", Source::Volume),
    single("treasury.us_3m", "scalar", Source::Treasury(0)),
    single("treasury.us_10y", "scalar", Source::Treasury(1)),
    Parameter { id: "annual.operating_margin", unit: "scalar", yearly: true, source: Source::OperatingMargin },
    single("market.enterprise_value", "USD", Source::EnterpriseValue),
    annual("annual.ebit", INCOME, "ebit"),
    per_share("annual.basic_eps", "eps"),
    per_share("annual.diluted_eps", "epsDiluted"),
    annual("annual.total_debt", BALANCE, "totalDebt"),
    annual("annual.free_cash_flow", CASH_FLOW, "freeCashFlow"),
    Parameter { id: "annual.report_ebitda", unit: "USD", yearly: true, source: Source::ReportEbitda },
    single("owner.market_cap", "USD", Source::MarketCap),
    owner("owner.profit_margin", "filter:profit_margin"),
    owner("owner.pe", "filter:pe"),
    owner("owner.pb", "filter:pb"),
    owner("owner.fcf_yield", "filter:fcf_yield"),
    owner("owner.price_fcf", "filter:price_fcf"),
    owner("owner.peg", "filter:peg"),
    owner("owner.roe", "filter:roe"),
    owner("owner.current_ratio", "filter:current_ratio"),
    owner("owner.interest_coverage", "filter:interest_coverage"),
    owner("owner.debt_equity", "filter:debt_equity"),
    owner("owner.return_1y", "filter:return_1y"),
    owner("owner.return_3y", "filter:return_3y"),
    owner("owner.ev_ebitda", "metric:ev_ebitda:multiple"),
    owner("owner.ev_ebitda_3y", "metric:ev_ebitda_3y:multiple"),
    owner("owner.ebitda_yield", "metric:ev_ebitda:yield"),
    owner("owner.operating_yield_spread_3y", "filter:operating_yield_spread_3y"),
];

const OPERATING_INCOME: Field = field(INCOME, "operatingIncome");
const REVENUE: Field = field(INCOME, "revenue");

/// The context of an observation.
#[derive(Clone, Copy, Debug)]
pub enum At<'a> {
    /// A formula's root: a candidate of the screen of the day. Its owner
    /// values and enterprise value are the candidate's.
    Root(&'a Candidate, Day),
    /// A context the formula moved to (`at` a date, or a lookback): the
    /// company valued afresh on any calendar day.
    Dated(CompanyId, Day),
}

/// See [`MarketData::observe`](crate::MarketData::observe).
pub(crate) fn observe(columns: &Columns<'_>, at: At<'_>, p: Parameter, count: usize) -> Option<Vec<f64>> {
    assert!(count == 1 || p.yearly, "{} has one value", p.id);
    let (c, day, root) = match at {
        At::Root(candidate, day) => (candidate.company, day, Some(candidate)),
        At::Dated(c, day) => (c, day, None),
    };
    let facts = columns.facts(c);
    let series = facts.series;
    let one = |value: Option<f64>| value.map(|v| vec![v]);
    let values = match (p.source, root) {
        (Source::Close, _) => {
            let session = series.session(day)?;
            one(convert(series, facts.prices.saved(session).0?, facts.quote, session))
        }
        (Source::Volume, _) => one(facts.prices.saved(series.session(day)?).1),
        (Source::Treasury(rate), _) => one(series.treasury_rates(day)[rate]),
        (Source::EnterpriseValue, Some(candidate)) => one(Some(candidate.enterprise_value)),
        (Source::MarketCap, Some(candidate)) => one(Some(candidate.market_cap)),
        (Source::Owner { lane }, Some(candidate)) => one(owner_lane(candidate.values[lane], lane)),
        (source, _) => {
            let anchor = facts.reports.report_at(day, series)?;
            let members = |read: &dyn Fn(Day) -> Option<f64>| {
                facts.annual.spine(anchor.fiscal, day, count).into_iter().map(|fiscal| fiscal.and_then(read)).collect()
            };
            match source {
                Source::Annual(field) => members(&|fiscal| facts.annual.formula_value(field, fiscal, day, series)),
                Source::OperatingMargin => members(&|fiscal| {
                    let income = facts.annual.formula_value(OPERATING_INCOME, fiscal, day, series)?;
                    builtins::operating_margin(income, facts.annual.formula_value(REVENUE, fiscal, day, series)?)
                }),
                Source::ReportEbitda => facts.reports.yearly_ebitda(anchor.fiscal, day, series, count).into_iter().collect(),
                _ => {
                    // The oracle also leaves out every owner lane when the yield or multiple is not
                    // finite; reports have positive EBITDA, market cap and EV, so that cannot arise.
                    let (valuation, _) = screen::admit(&anchor, &facts.prices, day, ENTRY_SLACK).ok()?;
                    one(match source {
                        Source::EnterpriseValue => Some(valuation.enterprise_value),
                        Source::MarketCap => Some(valuation.market_cap),
                        Source::Owner { lane } => owner_lane(builtins::values(&facts, day, &valuation)[lane], lane),
                        _ => unreachable!("every other source is read above"),
                    })
                }
            }
        }
    };
    values.filter(|values: &Vec<f64>| values.iter().all(|v| v.is_finite()))
}

/// An owner value from its built-in lane (`measure_observations.lane`).
fn owner_lane(stored: Option<f64>, lane: usize) -> Option<f64> {
    stored.map(|v| if BUILTINS[lane].scale == -2 { v / 100.0 } else { v })
}

