//! Annual statements: each company's income statements, balance sheets and
//! cash-flow statements by fiscal date, with each field's state, the reported
//! currency and the day the statement became known; and the point-in-time
//! readings of them: the one books and the built-ins use, and the one
//! formulas use.
//!
//! Reading a company (`financial_inputs.resolve_history`):
//! - A statement file counts when it is JSON, version 2, names the company and
//!   the endpoint, and holds a list of rows; otherwise, or when it is missing,
//!   it gives no rows. Of its rows, those that are objects with a readable
//!   `date`, the company's `symbol` or none, `period` `FY` or none, and a
//!   number or null in each legacy field are kept; the others are left out
//!   (the oracle's salvage of a damaged file).
//! - Rows with the same fiscal date (the day of `date`) form one statement.
//!   Its currency is its rows' one `reportedCurrency`, in capitals, or none
//!   when they name none or several. Its publication date is the one date,
//!   later than the fiscal date, among its rows' first of `availableDate`,
//!   `filingDate` and `acceptedDate`; its known date and basis follow
//!   ([`Market::available`]).
//! - A field's state comes from the distinct values of the rows in the right
//!   currency (US: `USD`; foreign: the statement's currency). Equal values
//!   agree and a null never overrides a value; one value is valid, several
//!   are `CONFLICTING_INPUT`. A foreign statement with several currencies is
//!   also conflicting. Otherwise, without a value: `NON_USD_INPUT` (US: a
//!   value in another currency), `INVALID_INPUT` (a value that is no number)
//!   or `MISSING_INPUT`.
//! - Every catalog field is read (`STATEMENTS`); Hong Kong and Tokyo also
//!   read the income statement's `ebitda` for the foreign anchors.
//!
//! Columns, per statement kind `<s>` (`balance`, `cash_flow`, `income`):
//! `annual.<s>.offsets` (`u64`, one more than companies), and per statement
//! in fiscal order `annual.<s>.fiscal`, `.known`, `.basis` (`u8`,
//! [`Basis`] codes), `.currency` (text, empty for none), `.values` (`f64`, the
//! kind's fields in `STATEMENTS` order, row after row, `NaN` where absent)
//! and `.reasons` (`u8`, [`Reason`] codes, laid out as `.values`).

use crate::companies::Companies;
use crate::market::Basis;
use crate::raw::{Json, Raw, Reason, State, number, parse_day, read_json, state_cells};
use crate::reports::convert;
use crate::series::Series;
use crate::store::{Generation, GenerationWriter, Text, Texts};
use crate::{Day, Error, Market};
use serde_json::{Map, Value};
use std::collections::{BTreeMap, BTreeSet};
use tables::Cell;

/// One kind of annual statement: its provider endpoint, its column group and
/// its fields as (provider field, oracle column).
struct Statement {
    endpoint: &'static str,
    group: &'static str,
    fields: &'static [(&'static str, &'static str)],
}

pub(crate) const BALANCE: usize = 0;
pub(crate) const CASH_FLOW: usize = 1;
pub(crate) const INCOME: usize = 2;

/// The statement kinds, in endpoint name order (the export's order).
const STATEMENTS: [Statement; 3] = [
    Statement {
        endpoint: "balance-sheet-statement",
        group: "balance",
        fields: &[
            ("cashAndCashEquivalents", "cash_and_equivalents"),
            ("shortTermInvestments", "short_term_investments"),
            ("longTermInvestments", "long_term_investments"),
            ("netReceivables", "net_receivables"),
            ("accountsReceivables", "accounts_receivable"),
            ("inventory", "inventory"),
            ("prepaids", "prepaid_expenses"),
            ("totalCurrentAssets", "current_assets"),
            ("propertyPlantEquipmentNet", "property_plant_equipment_net"),
            ("goodwill", "goodwill"),
            ("intangibleAssets", "intangible_assets"),
            ("totalAssets", "total_assets"),
            ("accountPayables", "accounts_payable"),
            ("accruedExpenses", "accrued_expenses"),
            ("deferredRevenue", "current_deferred_revenue"),
            ("deferredRevenueNonCurrent", "noncurrent_deferred_revenue"),
            ("totalCurrentLiabilities", "current_liabilities"),
            ("totalLiabilities", "total_liabilities"),
            ("shortTermDebt", "short_term_debt"),
            ("longTermDebt", "long_term_debt"),
            ("capitalLeaseObligations", "lease_obligations"),
            ("totalStockholdersEquity", "equity"),
            ("preferredStock", "preferred_stock"),
            ("minorityInterest", "noncontrolling_interests"),
            ("totalDebt", "total_debt"),
        ],
    },
    Statement {
        endpoint: "cash-flow-statement",
        group: "cash_flow",
        fields: &[
            ("depreciationAndAmortization", "depreciation_amortization"),
            ("stockBasedCompensation", "stock_based_compensation"),
            ("operatingCashFlow", "operating_cash_flow"),
            ("capitalExpenditure", "capital_expenditure"),
            ("acquisitionsNet", "net_acquisitions"),
            ("incomeTaxesPaid", "income_taxes_paid"),
            ("interestPaid", "interest_paid"),
            ("netDebtIssuance", "net_debt_issuance"),
            ("commonDividendsPaid", "common_dividends_paid"),
            ("preferredDividendsPaid", "preferred_dividends_paid"),
            ("commonStockRepurchased", "common_stock_repurchased"),
            ("commonStockIssuance", "common_stock_issuance"),
            ("freeCashFlow", "free_cash_flow"),
        ],
    },
    Statement {
        endpoint: "income-statement",
        group: "income",
        // `ebitda` is last: only Hong Kong and Tokyo read it.
        fields: &[
            ("revenue", "revenue"),
            ("costOfRevenue", "cost_of_revenue"),
            ("sellingGeneralAndAdministrativeExpenses", "selling_general_administrative_expense"),
            ("researchAndDevelopmentExpenses", "research_development_expense"),
            ("operatingIncome", "operating_income"),
            ("interestIncome", "interest_income"),
            ("interestExpense", "interest_expense"),
            ("incomeBeforeTax", "pretax_income"),
            ("incomeTaxExpense", "income_tax_expense"),
            ("netIncome", "net_income"),
            ("weightedAverageShsOut", "weighted_average_basic_shares"),
            ("weightedAverageShsOutDil", "weighted_average_diluted_shares"),
            ("ebit", "ebit"),
            ("eps", "basic_eps"),
            ("epsDiluted", "diluted_eps"),
            ("ebitda", "income_ebitda"),
        ],
    },
];

/// The number of fields of statement kind `s` that the market reads.
fn width(s: usize, market: Market) -> usize {
    STATEMENTS[s].fields.len() - usize::from(s == INCOME && market == Market::Us)
}

/// One field of one statement kind.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct Field {
    statement: usize,
    index: usize,
}

/// The field of statement kind `statement` that the provider names `name`.
pub(crate) const fn field(statement: usize, name: &str) -> Field {
    let fields = STATEMENTS[statement].fields;
    let mut index = 0;
    while index < fields.len() {
        let (a, b) = (fields[index].0.as_bytes(), name.as_bytes());
        if a.len() == b.len() {
            let mut i = 0;
            while i < a.len() && a[i] == b[i] {
                i += 1;
            }
            if i == a.len() {
                return Field { statement, index };
            }
        }
        index += 1;
    }
    panic!("no such field");
}

/// The foreign anchor's inputs: basic weighted shares and EBITDA (income),
/// total debt and cash (balance sheet).
pub(crate) const SHARES: Field = field(INCOME, "weightedAverageShsOut");
pub(crate) const EBITDA: Field = field(INCOME, "ebitda");
pub(crate) const TOTAL_DEBT: Field = field(BALANCE, "totalDebt");
pub(crate) const CASH: Field = field(BALANCE, "cashAndCashEquivalents");
const DILUTED_SHARES: Field = field(INCOME, "weightedAverageShsOutDil");

/// Whether `field` is one of the two weighted share counts, which are never
/// converted to USD.
pub(crate) const fn is_share_count(field: Field) -> bool {
    field.statement == INCOME && (field.index == SHARES.index || field.index == DILUTED_SHARES.index)
}
const DIVIDENDS: Field = field(CASH_FLOW, "commonDividendsPaid");

/// The legacy annual fields that books read (`facts.LEGACY`).
#[derive(Clone, Copy, Debug)]
pub(crate) enum LegacyField {
    Revenue,
    OperatingIncome,
    NetIncome,
    EpsDiluted,
    Ebit,
    InterestExpense,
    Equity,
    CurrentAssets,
    CurrentLiabilities,
    TotalDebt,
    FreeCashFlow,
}

/// The field of each [`LegacyField`], indexed by it (`facts.LEGACY` order).
/// A statement row whose value of one of them is not a number or null is
/// left out.
const LEGACY: [Field; 11] = [
    field(INCOME, "revenue"),
    field(INCOME, "operatingIncome"),
    field(INCOME, "netIncome"),
    field(INCOME, "epsDiluted"),
    field(INCOME, "ebit"),
    field(INCOME, "interestExpense"),
    field(BALANCE, "totalStockholdersEquity"),
    field(BALANCE, "totalCurrentAssets"),
    field(BALANCE, "totalCurrentLiabilities"),
    field(BALANCE, "totalDebt"),
    field(CASH_FLOW, "freeCashFlow"),
];

/// The legacy values of one fiscal date at a day: each valid, readable value.
#[derive(Clone, Copy, Debug, Default)]
pub(crate) struct LegacyValues(pub(crate) [Option<f64>; 11]);

impl LegacyValues {
    pub(crate) fn get(&self, field: LegacyField) -> Option<f64> {
        self.0[field as usize]
    }

    fn is_empty(&self) -> bool {
        self.0.iter().all(Option::is_none)
    }
}

/// One statement kind of one company, in memory.
struct StatementRows {
    fiscal: Vec<Day>,
    known: Vec<Day>,
    basis: Vec<u8>,
    currency: Texts,
    values: Vec<f64>,
    reasons: Vec<u8>,
}

/// One company's statements, in memory.
pub(crate) struct AnnualRows {
    market: Market,
    statements: [StatementRows; 3],
}

/// Reads a company's statement files. Only a file that exists and cannot be
/// read stops preparation.
pub(crate) fn read(raw: &Raw, market: Market, symbol: &str) -> Result<AnnualRows, Error> {
    let mut statements = Vec::with_capacity(3);
    for (s, kind) in STATEMENTS.iter().enumerate() {
        let width = width(s, market);
        let mut out = StatementRows {
            fiscal: Vec::new(),
            known: Vec::new(),
            basis: Vec::new(),
            currency: Texts::new(),
            values: Vec::new(),
            reasons: Vec::new(),
        };
        let rows = statement_rows(raw, s, symbol)?;
        let mut statements_by_fiscal: BTreeMap<Day, Vec<&Map<String, Value>>> = BTreeMap::new();
        for row in &rows {
            statements_by_fiscal.entry(parse_day(row.get("date")).expect("kept rows have a date")).or_default().push(row);
        }
        for (fiscal, members) in statements_by_fiscal {
            let currencies: BTreeSet<String> = members
                .iter()
                .filter_map(|row| row.get("reportedCurrency").and_then(Value::as_str).filter(|code| !code.is_empty()))
                .map(str::to_uppercase)
                .collect();
            let currency = (currencies.len() == 1).then(|| currencies.first().unwrap().as_str());
            let publications: BTreeSet<Day> = members.iter().filter_map(|row| publication(row)).filter(|&day| day > fiscal).collect();
            let (known, basis) = market.available(fiscal, (publications.len() == 1).then(|| *publications.first().unwrap()));
            out.fiscal.push(fiscal);
            out.known.push(known);
            out.basis.push(basis as u8);
            out.currency.push(currency.unwrap_or(""));
            for &(name, _) in &kind.fields[..width] {
                let state = field_state(&members, name, market, currency, currencies.len());
                out.values.push(state.unwrap_or(f64::NAN));
                out.reasons.push(Reason::code(state));
            }
        }
        statements.push(out);
    }
    Ok(AnnualRows { market, statements: statements.try_into().ok().unwrap() })
}

/// The kept rows of one statement file.
fn statement_rows(raw: &Raw, s: usize, symbol: &str) -> Result<Vec<Map<String, Value>>, Error> {
    let kind = &STATEMENTS[s];
    let Json::Value(Value::Object(mut record)) = read_json(&raw.statement(kind.endpoint, symbol))? else {
        return Ok(Vec::new());
    };
    let text = |key: &str| record.get(key).and_then(Value::as_str);
    if record.get("version").and_then(Value::as_u64) != Some(2) || text("symbol") != Some(symbol) || text("endpoint") != Some(kind.endpoint) {
        return Ok(Vec::new());
    }
    let Some(Value::Array(rows)) = record.remove("rows") else { return Ok(Vec::new()) };
    let kept = |row: &Map<String, Value>| {
        parse_day(row.get("date")).is_some()
            && row.get("symbol").is_none_or(|s| s.as_str() == Some(symbol))
            && row.get("period").is_none_or(|p| p.as_str() == Some("FY"))
            && LEGACY
                .iter()
                .filter(|field| field.statement == s)
                .all(|field| matches!(row.get(kind.fields[field.index].0), None | Some(Value::Null | Value::Number(_))))
    };
    Ok(rows
        .into_iter()
        .filter_map(|row| match row {
            Value::Object(row) if kept(&row) => Some(row),
            _ => None,
        })
        .collect())
}

/// A row's publication date: the day of its first non-empty of
/// `availableDate`, `filingDate` and `acceptedDate`, when that reads.
fn publication(row: &Map<String, Value>) -> Option<Day> {
    let first = ["availableDate", "filingDate", "acceptedDate"]
        .iter()
        .find_map(|key| row.get(*key).filter(|v| !matches!(v, Value::Null) && v.as_str() != Some("")))?;
    parse_day(Some(first))
}

/// One field's state of one statement (see the module comment).
fn field_state(members: &[&Map<String, Value>], name: &str, market: Market, currency: Option<&str>, currencies: usize) -> State {
    let us = market == Market::Us;
    fn code(row: &Map<String, Value>) -> Option<&str> {
        row.get("reportedCurrency").and_then(Value::as_str)
    }
    let mut numbers: Vec<f64> = Vec::new();
    for row in members {
        let accepted = if us { code(row) == Some("USD") } else { currency.is_some() && code(row) == currency };
        if let Some(value) = number(row.get(name))
            && accepted
            && !numbers.contains(&value)
        {
            numbers.push(value);
        }
    }
    match numbers[..] {
        [value] => Ok(value),
        _ if numbers.len() > 1 || (!us && currencies > 1) => Err(Reason::Conflicting),
        _ if us
            && members.iter().any(|row| code(row).is_some_and(|c| !c.is_empty() && c != "USD") && number(row.get(name)).is_some()) =>
        {
            Err(Reason::NonUsd)
        }
        _ if members.iter().any(|row| !matches!(row.get(name), None | Some(Value::Null)) && number(row.get(name)).is_none()) => {
            Err(Reason::Invalid)
        }
        _ => Err(Reason::Missing),
    }
}

impl AnnualRows {
    /// The reading over these rows.
    pub(crate) fn view(&self) -> Annual<'_> {
        Annual {
            market: self.market,
            statements: [0, 1, 2].map(|s| {
                let rows = &self.statements[s];
                Statements {
                    width: width(s, self.market),
                    fiscal: &rows.fiscal,
                    known: &rows.known,
                    basis: &rows.basis,
                    currency: rows.currency.view(),
                    values: &rows.values,
                    reasons: &rows.reasons,
                }
            }),
        }
    }
}

/// Writes the annual columns of every company, in company order; `None` for a
/// company without statements (an unreported US company).
pub(crate) fn write(out: &mut GenerationWriter<'_>, companies: &[Option<&AnnualRows>]) -> Result<(), Error> {
    for (s, kind) in STATEMENTS.iter().enumerate() {
        let parts: Vec<&StatementRows> = companies.iter().flatten().map(|a| &a.statements[s]).collect();
        let name = |column: &str| format!("annual.{}.{column}", kind.group);
        let mut offsets = vec![0u64];
        offsets.extend(companies.iter().scan(0u64, |end, a| {
            *end += a.map_or(0, |a| a.statements[s].fiscal.len() as u64);
            Some(*end)
        }));
        out.column(&name("offsets"), &offsets)?;
        out.column(&name("fiscal"), &parts.iter().flat_map(|p| p.fiscal.iter().copied()).collect::<Vec<_>>())?;
        out.column(&name("known"), &parts.iter().flat_map(|p| p.known.iter().copied()).collect::<Vec<_>>())?;
        out.column(&name("basis"), &parts.iter().flat_map(|p| p.basis.iter().copied()).collect::<Vec<_>>())?;
        let currency: Vec<&str> = parts.iter().flat_map(|p| (0..p.fiscal.len()).map(|i| p.currency.view().get(i))).collect();
        out.text(&name("currency"), &currency)?;
        out.column(&name("values"), &parts.iter().flat_map(|p| p.values.iter().copied()).collect::<Vec<_>>())?;
        out.column(&name("reasons"), &parts.iter().flat_map(|p| p.reasons.iter().copied()).collect::<Vec<_>>())?;
    }
    Ok(())
}

/// One statement kind of one company: rows in fiscal order.
#[derive(Clone, Copy)]
struct Statements<'a> {
    /// Fields per row.
    width: usize,
    fiscal: &'a [Day],
    known: &'a [Day],
    basis: &'a [u8],
    currency: Text<'a>,
    values: &'a [f64],
    reasons: &'a [u8],
}

impl<'a> Statements<'a> {
    fn row(&self, fiscal: Day) -> Option<usize> {
        self.fiscal.binary_search(&fiscal).ok()
    }

    fn state(&self, row: usize, index: usize) -> State {
        let at = row * self.width + index;
        match self.reasons[at] {
            0 => Ok(self.values[at]),
            code => Err(Reason::from_code(code)),
        }
    }

    fn currency(&self, row: usize) -> Option<&'a str> {
        Some(self.currency.get(row)).filter(|c| !c.is_empty())
    }
}

/// One company's statements: the stored states and the point-in-time
/// reading of books and built-ins.
#[derive(Clone, Copy)]
pub(crate) struct Annual<'a> {
    market: Market,
    /// By [`STATEMENTS`] index.
    statements: [Statements<'a>; 3],
}

/// A statement's record: its currency, known date and basis.
pub(crate) struct Metadata<'a> {
    pub(crate) currency: Option<&'a str>,
    pub(crate) known: Day,
    pub(crate) basis: Basis,
}

impl<'a> Annual<'a> {
    /// The fiscal dates of the income statements, ascending.
    pub(crate) fn income_fiscals(&self) -> &'a [Day] {
        self.statements[INCOME].fiscal
    }

    /// The record of the statement of `field`'s kind at `fiscal`, or `None`
    /// when there is none.
    pub(crate) fn metadata(&self, field: Field, fiscal: Day) -> Option<Metadata<'a>> {
        let s = &self.statements[field.statement];
        let row = s.row(fiscal)?;
        Some(Metadata { currency: s.currency(row), known: s.known[row], basis: Basis::from_code(s.basis[row]) })
    }

    /// The stored state of `field` at `fiscal`, or `None` when the company
    /// has no such statement.
    pub(crate) fn state(&self, field: Field, fiscal: Day) -> Option<State> {
        let s = &self.statements[field.statement];
        Some(s.state(s.row(fiscal)?, field.index))
    }

    /// The valid value of `field` at `fiscal` as a book on `day` reads it,
    /// with its currency: US whatever the day, foreign only when its
    /// statement is known before `day` (`BookFacts._annual_value`).
    fn readable(&self, field: Field, fiscal: Day, day: Day) -> Option<(f64, &'a str)> {
        let s = &self.statements[field.statement];
        let row = s.row(fiscal)?;
        let value = s.state(row, field.index).ok()?;
        match self.market {
            Market::Us => Some((value, "USD")),
            _ => (s.known[row] < day).then(|| (value, s.currency(row).expect("a valid foreign value has a currency"))),
        }
    }

    /// The legacy values of fiscal date `fiscal` that a book on `day` reads
    /// (`BookFacts.report_at`'s values): US as stored; foreign only those
    /// known before `day`, converted to USD at `day`, and left out when the
    /// FX is missing or the result is not finite.
    pub(crate) fn legacy(&self, fiscal: Day, day: Day, series: &Series<'_>) -> LegacyValues {
        LegacyValues(LEGACY.map(|field| self.readable(field, fiscal, day).and_then(|(v, c)| convert(series, v, c, day))))
    }

    /// The legacy values of every fiscal date at `day`, in fiscal order,
    /// leaving out dates without any (`BookFacts.legacy_annual(symbol,
    /// day)`): what the built-ins read for the selected report and the years
    /// before it.
    pub(crate) fn legacy_at(&self, day: Day, series: &Series<'_>) -> Vec<(Day, LegacyValues)> {
        let fiscals: BTreeSet<Day> = [BALANCE, CASH_FLOW, INCOME].iter().flat_map(|&s| self.statements[s].fiscal.iter().copied()).collect();
        fiscals.into_iter().map(|fiscal| (fiscal, self.legacy(fiscal, day, series))).filter(|(_, v)| !v.is_empty()).collect()
    }

    /// The common dividends paid of fiscal date `fiscal` in USD at `day`,
    /// signed as reported (`BookFacts.dividends`): read as a legacy value is,
    /// and converted at `day` (US: times 1).
    pub(crate) fn dividends(&self, fiscal: Day, day: Day, series: &Series<'_>) -> Option<f64> {
        let (value, currency) = self.readable(DIVIDENDS, fiscal, day)?;
        convert(series, value, currency, day)
    }

    /// The annual weighted-average basic shares of fiscal date `fiscal`
    /// (`BookFacts.shares`): read as a legacy value is, and never converted.
    pub(crate) fn shares(&self, fiscal: Day, day: Day) -> Option<f64> {
        self.readable(SHARES, fiscal, day).map(|(value, _)| value)
    }

    /// The fiscal dates of the `count` calendar years ending at the year of
    /// `anchor` (the selected report's fiscal date), oldest first, that a
    /// formula on `day` reads (`columns._periods`, the income fiscal spine):
    /// the anchor itself, and for each earlier year the last income statement
    /// of that year on or before `anchor` known before `day`; `None` for a
    /// year without one. (The oracle reads no US metadata and takes the
    /// fiscal date + 90 days, which is the US known date.) The built-ins
    /// choose a year's statement among every statement kind instead, from
    /// those with a legacy value.
    pub(crate) fn spine(&self, anchor: Day, day: Day, count: usize) -> Vec<Option<Day>> {
        let income = &self.statements[INCOME];
        let year = anchor.ymd().0;
        let earlier = |y: i32| {
            let found = (0..income.fiscal.len()).rev().find(|&i| income.fiscal[i].ymd().0 == y && income.fiscal[i] <= anchor && income.known[i] < day);
            found.map(|i| income.fiscal[i])
        };
        (year + 1 - count as i32..=year).map(|y| if y == year { Some(anchor) } else { earlier(y) }).collect()
    }

    /// The value of `field` at `fiscal` as a formula on `day` reads it
    /// (`fact_view.View.company`): as [`legacy`](Self::legacy) reads a value,
    /// except that the two weighted share counts are never converted.
    pub(crate) fn formula_value(&self, field: Field, fiscal: Day, day: Day, series: &Series<'_>) -> Option<f64> {
        let (value, currency) = self.readable(field, fiscal, day)?;
        if is_share_count(field) { Some(value) } else { convert(series, value, currency, day) }
    }
}

/// The annual columns of a published generation.
pub(crate) struct AnnualColumns<'a> {
    market: Market,
    statements: [(&'a [u64], Statements<'a>); 3],
}

impl<'a> AnnualColumns<'a> {
    pub(crate) fn open(generation: &'a Generation) -> AnnualColumns<'a> {
        let market = generation.manifest().market;
        let statements = [0, 1, 2].map(|s| {
            let name = |column: &str| format!("annual.{}.{column}", STATEMENTS[s].group);
            let columns = Statements {
                width: width(s, market),
                fiscal: generation.column(&name("fiscal")),
                known: generation.column(&name("known")),
                basis: generation.column(&name("basis")),
                currency: generation.text(&name("currency")),
                values: generation.column(&name("values")),
                reasons: generation.column(&name("reasons")),
            };
            (generation.column::<u64>(&name("offsets")), columns)
        });
        AnnualColumns { market, statements }
    }

    /// One company's statements.
    pub(crate) fn company(&self, c: crate::CompanyId) -> Annual<'a> {
        Annual {
            market: self.market,
            statements: [0, 1, 2].map(|s| {
                let (offsets, all) = self.statements[s];
                let rows = offsets[c.index()] as usize..offsets[c.index() + 1] as usize;
                let cells = rows.start * all.width..rows.end * all.width;
                Statements {
                    width: all.width,
                    fiscal: &all.fiscal[rows.clone()],
                    known: &all.known[rows.clone()],
                    basis: &all.basis[rows.clone()],
                    currency: all.currency.slice(rows),
                    values: &all.values[cells.clone()],
                    reasons: &all.reasons[cells],
                }
            }),
        }
    }

    /// Writes the `annual_facts` table (key `symbol`, `endpoint`, `fiscal`,
    /// `column`): one row for each field of each statement.
    pub(crate) fn export_facts(&self, companies: &Companies<'_>, out: &mut tables::Writer) -> Result<u64, String> {
        let mut table = out.table("annual_facts", &["symbol", "endpoint", "fiscal", "column"])?;
        let orders = [0, 1, 2].map(|s| {
            let fields = &STATEMENTS[s].fields[..width(s, self.market)];
            let mut order: Vec<usize> = (0..fields.len()).collect();
            order.sort_by_key(|&i| fields[i].1);
            order
        });
        for c in companies.ids() {
            let annual = self.company(c);
            for (s, kind) in STATEMENTS.iter().enumerate() {
                let rows = &annual.statements[s];
                for row in 0..rows.fiscal.len() {
                    let fiscal = rows.fiscal[row].to_string();
                    for &i in &orders[s] {
                        let at = row * rows.width + i;
                        let (value, reason) = state_cells(rows.values[at], rows.reasons[at]);
                        table.row(&[
                            ("symbol", Cell::Text(companies.symbol(c))),
                            ("endpoint", Cell::Text(kind.endpoint)),
                            ("fiscal", Cell::Text(&fiscal)),
                            ("column", Cell::Text(kind.fields[i].1)),
                            ("value", value),
                            ("reason", reason),
                        ])?;
                    }
                }
            }
        }
        table.finish()
    }

    /// Writes the `annual_metadata` table (key `symbol`, `endpoint`, `fiscal`).
    pub(crate) fn export_metadata(&self, companies: &Companies<'_>, out: &mut tables::Writer) -> Result<u64, String> {
        let mut table = out.table("annual_metadata", &["symbol", "endpoint", "fiscal"])?;
        for c in companies.ids() {
            let annual = self.company(c);
            for (s, kind) in STATEMENTS.iter().enumerate() {
                let rows = &annual.statements[s];
                for row in 0..rows.fiscal.len() {
                    table.row(&[
                        ("symbol", Cell::Text(companies.symbol(c))),
                        ("endpoint", Cell::Text(kind.endpoint)),
                        ("fiscal", Cell::Text(&rows.fiscal[row].to_string())),
                        ("currency", rows.currency(row).map_or(Cell::Null, Cell::Text)),
                        ("known", Cell::Text(&rows.known[row].to_string())),
                        ("basis", Cell::Text(Basis::from_code(rows.basis[row]).text())),
                    ])?;
                }
            }
        }
        table.finish()
    }
}
