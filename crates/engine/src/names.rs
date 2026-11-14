//! The source names: one list of the names a strategy file can use as a step
//! source, as `bt catalog` prints it. It holds the rows of the oracle's
//! vocabulary (`backtest/application/vocabulary.py`), "Free cash flow" and
//! the four fields.
//!
//! - A name that links a built-in, or that only a step can use, reads the
//!   built-in's stored lane when it is a whole step source. Its unit and
//!   display come from [`BUILTINS`].
//! - A field reads the candidate's own field.
//! - An input or a measure without a built-in reads a formula of its term
//!   ([`crate::formula`]), shown in the vocabulary's display.
//! - Inside a formula, a name reads its formula term; a step-only name or a
//!   field there is an error.
//! - Matching ignores case and repeated spaces; the list's spelling is the
//!   canonical one.

use crate::formula::Measure;
use market_data::builtins::BUILTINS;
use market_data::parameters::PARAMETERS;

/// One source name.
#[derive(Debug)]
pub struct Name {
    pub name: &'static str,
    pub kind: Kind,
}

/// What a name reads.
#[derive(Debug)]
pub enum Kind {
    /// A built-in's stored lane (its id in [`BUILTINS`]). `term` is the
    /// formula input the name reads inside a formula, `None` when only a
    /// whole step can use the name.
    Builtin { id: &'static str, term: Option<&'static str> },
    /// A formula input without a built-in: a parameter of
    /// [`PARAMETERS`], which owns its unit.
    Input { parameter: &'static str, display: &'static str },
    /// A named measure without a built-in: a formula of several inputs
    /// ([`Measure`], which owns its unit).
    Measure { measure: &'static str, display: &'static str },
    /// A field of the candidate.
    Field(Field),
}

/// A candidate's own fields that a step can read.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Field {
    Sector,
    Exchange,
    /// The entry market cap in US dollars.
    MarketCap,
    /// The entry enterprise value in US dollars.
    EnterpriseValue,
}

impl Kind {
    /// `built-in`, `input`, `measure` or `field`.
    pub fn id(&self) -> &'static str {
        match self {
            Kind::Builtin { .. } => "built-in",
            Kind::Input { .. } => "input",
            Kind::Measure { .. } => "measure",
            Kind::Field(_) => "field",
        }
    }
}

impl Field {
    /// Sector and exchange are text; the two size fields are numbers.
    pub fn is_text(self) -> bool {
        matches!(self, Field::Sector | Field::Exchange)
    }
}

impl Name {
    /// `USD`, `scalar`, `USD/share`, `share`, or `text` for sector and exchange.
    pub fn unit(&self) -> &'static str {
        match self.kind {
            Kind::Builtin { .. } => BUILTINS[self.builtin().expect("a built-in name")].unit,
            Kind::Input { parameter, .. } => PARAMETERS.iter().find(|p| p.id == parameter).expect("a formula parameter").unit,
            Kind::Measure { measure, .. } => Measure::of(measure).unit().id(),
            Kind::Field(field) if field.is_text() => "text",
            Kind::Field(_) => "USD",
        }
    }

    /// The unit a threshold is written in: a built-in's display, the
    /// vocabulary's display for an input or a measure, whole US dollars
    /// (`usd`) for the size fields and `text` for sector and exchange.
    pub fn display(&self) -> &'static str {
        match self.kind {
            Kind::Builtin { .. } => BUILTINS[self.builtin().expect("a built-in name")].display,
            Kind::Input { display, .. } | Kind::Measure { display, .. } => display,
            Kind::Field(field) if field.is_text() => "text",
            Kind::Field(_) => "usd",
        }
    }

    /// Whether only a whole step can use the name: a built-in without a
    /// formula term, or a field.
    pub fn step_only(&self) -> bool {
        matches!(self.kind, Kind::Builtin { term: None, .. } | Kind::Field(_))
    }

    /// The position in [`BUILTINS`] of the lane a whole-name step reads.
    pub fn builtin(&self) -> Option<usize> {
        match self.kind {
            Kind::Builtin { id, .. } => Some(BUILTINS.iter().position(|b| b.id == id).expect("a known built-in id")),
            _ => None,
        }
    }
}

/// The name with this spelling, ignoring case and repeated spaces.
pub fn find(text: &str) -> Option<&'static Name> {
    let key = key(text);
    NAMES.iter().find(|n| self::key(n.name) == key)
}

/// The list's name of the built-in at `index` in [`BUILTINS`]. Every
/// built-in a step source resolves to has one.
pub fn of_builtin(index: usize) -> &'static Name {
    NAMES.iter().find(|n| n.builtin() == Some(index)).expect("a built-in with a name")
}

/// The list's name of a field.
pub fn of_field(field: Field) -> &'static Name {
    NAMES.iter().find(|n| matches!(n.kind, Kind::Field(f) if f == field)).expect("a field with a name")
}

/// The matching form of a name: lower case, with each run of spaces as one
/// space and none at either end.
pub fn key(text: &str) -> String {
    text.split_whitespace().collect::<Vec<_>>().join(" ").to_lowercase()
}

/// Up to three of `known` that look like `text`, closest first: those whose
/// matching forms differ in at most a third of their characters.
pub fn suggestions<'a>(text: &str, known: impl IntoIterator<Item = &'a str>) -> Vec<&'a str> {
    let wanted: Vec<char> = key(text).chars().collect();
    let mut close: Vec<(usize, &str)> = known
        .into_iter()
        .filter_map(|name| {
            let other: Vec<char> = key(name).chars().collect();
            let distance = edit_distance(&wanted, &other);
            (distance * 3 <= wanted.len().max(other.len())).then_some((distance, name))
        })
        .collect();
    close.sort_by_key(|&(distance, _)| distance);
    close.into_iter().take(3).map(|(_, name)| name).collect()
}

/// The Levenshtein distance.
fn edit_distance(a: &[char], b: &[char]) -> usize {
    let mut row: Vec<usize> = (0..=b.len()).collect();
    for (i, x) in a.iter().enumerate() {
        let mut diagonal = row[0];
        row[0] = i + 1;
        for (j, y) in b.iter().enumerate() {
            let above = row[j + 1];
            row[j + 1] = (diagonal + usize::from(x != y)).min(above + 1).min(row[j] + 1);
            diagonal = above;
        }
    }
    row[b.len()]
}

const fn input(name: &'static str, parameter: &'static str, display: &'static str) -> Name {
    Name { name, kind: Kind::Input { parameter, display } }
}

const fn usd(name: &'static str, parameter: &'static str) -> Name {
    input(name, parameter, "usd_million")
}

const fn measure(name: &'static str, measure: &'static str, display: &'static str) -> Name {
    Name { name, kind: Kind::Measure { measure, display } }
}

const fn linked(name: &'static str, term: &'static str, id: &'static str) -> Name {
    Name { name, kind: Kind::Builtin { id, term: Some(term) } }
}

const fn step_only(name: &'static str, id: &'static str) -> Name {
    Name { name, kind: Kind::Builtin { id, term: None } }
}

const fn field(name: &'static str, field: Field) -> Name {
    Name { name, kind: Kind::Field(field) }
}

/// The list, in the vocabulary's order, then "Free cash flow" and the fields.
/// A linked name reads its first linked built-in.
pub static NAMES: [Name; 106] = [
    // Income statement
    usd("Revenue", "annual.revenue"),
    usd("Cost of revenue", "annual.cost_of_revenue"),
    measure("Gross profit", "gross_profit", "usd_million"),
    usd("SG&A expense", "annual.selling_general_administrative_expense"),
    usd("R&D expense", "annual.research_development_expense"),
    usd("Operating income", "annual.operating_income"),
    usd("EBIT", "annual.ebit"),
    usd("EBITDA", "annual.report_ebitda"),
    usd("Interest income", "annual.interest_income"),
    usd("Interest expense", "annual.interest_expense"),
    usd("Pretax income", "annual.pretax_income"),
    usd("Income tax expense", "annual.income_tax_expense"),
    usd("Net income", "annual.net_income"),
    input("Basic shares", "annual.weighted_average_basic_shares", "shares"),
    input("Diluted shares", "annual.weighted_average_diluted_shares", "shares"),
    input("Basic EPS", "annual.basic_eps", "usd_per_share"),
    input("Diluted EPS", "annual.diluted_eps", "usd_per_share"),
    // Balance sheet
    usd("Cash and equivalents", "annual.cash_and_equivalents"),
    usd("Short term investments", "annual.short_term_investments"),
    usd("Long term investments", "annual.long_term_investments"),
    usd("Net receivables", "annual.net_receivables"),
    usd("Accounts receivable", "annual.accounts_receivable"),
    usd("Inventory", "annual.inventory"),
    usd("Prepaid expenses", "annual.prepaid_expenses"),
    usd("Current assets", "annual.current_assets"),
    usd("Net PP&E", "annual.property_plant_equipment_net"),
    usd("Goodwill", "annual.goodwill"),
    usd("Intangible assets", "annual.intangible_assets"),
    usd("Total assets", "annual.total_assets"),
    usd("Accounts payable", "annual.accounts_payable"),
    usd("Accrued expenses", "annual.accrued_expenses"),
    usd("Current deferred revenue", "annual.current_deferred_revenue"),
    usd("Noncurrent deferred revenue", "annual.noncurrent_deferred_revenue"),
    usd("Current liabilities", "annual.current_liabilities"),
    measure("Working capital", "working_capital", "usd_million"),
    usd("Total liabilities", "annual.total_liabilities"),
    usd("Short term debt", "annual.short_term_debt"),
    usd("Long term debt", "annual.long_term_debt"),
    usd("Lease obligations", "annual.lease_obligations"),
    usd("Total debt", "annual.total_debt"),
    measure("Net debt", "net_debt", "usd_million"),
    usd("Shareholders equity", "annual.equity"),
    measure("Tangible book equity", "tangible_book_equity", "usd_million"),
    usd("Preferred stock", "annual.preferred_stock"),
    usd("Minority interest", "annual.noncontrolling_interests"),
    // Cash flow
    usd("Operating cash flow", "annual.operating_cash_flow"),
    usd("CapEx", "annual.capital_expenditure"),
    measure("Operating cash flow plus CapEx", "operating_cash_flow_plus_capex", "usd_million"),
    usd("Reported free cash flow", "annual.free_cash_flow"),
    usd("Depreciation and amortization", "annual.depreciation_amortization"),
    usd("Stock based compensation", "annual.stock_based_compensation"),
    usd("Net acquisitions", "annual.net_acquisitions"),
    usd("Income taxes paid", "annual.income_taxes_paid"),
    usd("Interest paid", "annual.interest_paid"),
    usd("Net debt issuance", "annual.net_debt_issuance"),
    usd("Common dividends paid", "annual.common_dividends_paid"),
    usd("Preferred dividends paid", "annual.preferred_dividends_paid"),
    usd("Share buybacks", "annual.common_stock_repurchased"),
    usd("Share issuance", "annual.common_stock_issuance"),
    // Market
    input("Share price", "market.adjusted_price", "usd_per_share"),
    input("Trading volume", "market.volume", "shares"),
    linked("Market cap", "owner.market_cap", "filter:market_cap"),
    linked("Enterprise value", "market.enterprise_value", "filter:enterprise_value"),
    input("Treasury 3 month yield", "treasury.us_3m", "percent"),
    input("Treasury 10 year yield", "treasury.us_10y", "percent"),
    // Valuation
    linked("P/E", "owner.pe", "filter:pe"),
    linked("P/B", "owner.pb", "filter:pb"),
    measure("Price/sales", "price_sales", "multiple"),
    linked("Price/FCF", "owner.price_fcf", "filter:price_fcf"),
    linked("FCF yield", "owner.fcf_yield", "filter:fcf_yield"),
    linked("PEG", "owner.peg", "filter:peg"),
    linked("EV/EBITDA", "owner.ev_ebitda", "metric:ev_ebitda:multiple"),
    linked("EV/3-year average EBITDA", "owner.ev_ebitda_3y", "metric:ev_ebitda_3y:multiple"),
    linked("EBITDA yield", "owner.ebitda_yield", "metric:ev_ebitda:yield"),
    linked("Operating yield spread", "owner.operating_yield_spread_3y", "filter:operating_yield_spread_3y"),
    step_only("P/S", "filter:ps"),
    step_only("3-year average EBITDA yield", "metric:ev_ebitda_3y:yield"),
    step_only("P/E 3-year average", "filter:pe_avg_3y"),
    step_only("P/E 5-year average", "filter:pe_avg_5y"),
    step_only("P/S 3-year average", "filter:ps_avg_3y"),
    step_only("P/S 5-year average", "filter:ps_avg_5y"),
    step_only("P/B 3-year average", "filter:pb_avg_3y"),
    step_only("P/B 5-year average", "filter:pb_avg_5y"),
    step_only("P/E vs 3-year average", "filter:pe_vs_avg_3y"),
    step_only("P/E vs 5-year average", "filter:pe_vs_avg_5y"),
    step_only("P/S vs 3-year average", "filter:ps_vs_avg_3y"),
    step_only("P/S vs 5-year average", "filter:ps_vs_avg_5y"),
    step_only("P/B vs 3-year average", "filter:pb_vs_avg_3y"),
    step_only("P/B vs 5-year average", "filter:pb_vs_avg_5y"),
    step_only("Dividend yield", "filter:dividend_yield"),
    step_only("Turnover rate 1-week average", "filter:turnover_1w"),
    // Margins and returns
    input("Operating margin", "annual.operating_margin", "percent"),
    measure("Gross margin", "gross_margin", "percent"),
    linked("Net margin", "owner.profit_margin", "filter:profit_margin"),
    linked("ROE", "owner.roe", "filter:roe"),
    linked("One year return", "owner.return_1y", "filter:return_1y"),
    linked("Three year return", "owner.return_3y", "filter:return_3y"),
    // Debt and liquidity
    linked("Current ratio", "owner.current_ratio", "filter:current_ratio"),
    linked("Interest coverage", "owner.interest_coverage", "filter:interest_coverage"),
    linked("Debt/equity", "owner.debt_equity", "filter:debt_equity"),
    measure("Debt/assets", "debt_assets", "multiple"),
    // The built-in the vocabulary does not name, and the fields.
    step_only("Free cash flow", "filter:fcf"),
    field("Sector", Field::Sector),
    field("Exchange", Field::Exchange),
    field("Market cap in dollars", Field::MarketCap),
    field("Enterprise value in dollars", Field::EnterpriseValue),
];
