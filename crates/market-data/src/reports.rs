//! Company reports: the annual anchors that books value a company from, and
//! the report a book selects on a day. The only reader of `metrics.jsonl`.
//!
//! US, from the annual key metrics of `metrics.jsonl`:
//! - The last record of a symbol wins, but the symbol keeps the position of
//!   its first record (`cache_assets.financial_records`).
//! - A report is accepted when its date reads, its market cap, enterprise
//!   value and EV/EBITDA are positive numbers and its `reportedCurrency` is
//!   USD or absent; it is known 90 days after its fiscal date, its EBITDA is
//!   EV / multiple and its yield 1 / multiple (`books.statements`). Of two
//!   reports with the same fiscal date, the later row wins.
//! - The reported set: the listed US companies with an accepted report. Its
//!   first-appearance order breaks the legacy ranking's ties, and it is the US
//!   price scope.
//!
//! Hong Kong and Tokyo, the foreign anchors (`facts.store_foreign_reports`):
//! one for each fiscal date with an income statement and a balance sheet
//! that name the same one currency, positive basic weighted shares and
//! EBITDA, and a valid total debt and cash ([`crate::annual`]). It is known
//! on the later of the two statements' known dates and keeps the income
//! statement's basis. Its fiscal cap is the shares times the last native
//! (unadjusted, `px-full`) close on a local session within the 7 days up to
//! the fiscal date, or none. Native closes follow the rules of a dated row
//! (positive, in the quote currency); only the fiscal cap reads them, so they
//! are not stored.
//!
//! Columns: `reports.offsets` (`u64`, one more than companies), and per
//! report in fiscal order `reports.fiscal` and `reports.known`; US
//! `reports.market_cap`, `.enterprise_value`, `.ebitda` and `.ebitda_yield`;
//! foreign `reports.currency` (text), `.shares`, `.ebitda`, `.debt`, `.cash`,
//! `.basis` (`u8`, [`Basis`] codes) and `.fiscal_cap` (`NaN` for none).

use crate::annual::{self, Annual};
use crate::companies::{Companies, Company, CompanyId};
use crate::market::Basis;
use crate::prices::{Direction, Prices};
use crate::raw::{Json, Raw, number, observe, parse_day, read_json};
use crate::series::Series;
use crate::store::{Generation, GenerationWriter, Text, Texts};
use crate::{Day, Error, Market};
use serde_json::Value;
use std::collections::HashMap;
use std::io;
use tables::Cell;

/// The oldest report a book selects: 800 days after its fiscal date.
const MAX_AGE: i32 = 800;
/// The US legacy pool's report floors (`rules.MIN_MARKET_CAP`, `MIN_EV`).
const MIN_MARKET_CAP: f64 = 100_000_000.0;
const MIN_EV: f64 = 50_000_000.0;

/// A report as a book on a day reads it, in USD: an accepted US report, or a
/// foreign anchor converted at the day.
#[derive(Clone, Copy, Debug)]
pub(crate) struct Report {
    pub(crate) fiscal: Day,
    pub(crate) known: Day,
    pub(crate) market_cap: f64,
    pub(crate) enterprise_value: f64,
    pub(crate) ebitda: f64,
    pub(crate) ebitda_yield: f64,
}

/// The US reported set: each company's accepted reports and its
/// first-appearance position, by [`CompanyId`].
pub(crate) struct Reported {
    reports: Vec<Vec<Report>>,
    order: Vec<Option<u32>>,
}

/// Reads `metrics.jsonl` for the listed `companies` (in [`CompanyId`]
/// order). A missing file gives no reports. Text that is not UTF-8, or a line
/// that is not a record with a symbol and a list of row objects, stops
/// preparation; an unreadable last line without a final newline is an
/// unfinished append and is skipped.
pub(crate) fn read_us(raw: &Raw, companies: &[Company]) -> Result<Reported, Error> {
    let path = raw.metrics();
    let bytes = match std::fs::read(&path) {
        Ok(bytes) => bytes,
        Err(e) if e.kind() == io::ErrorKind::NotFound => Vec::new(),
        Err(e) => return Err(Error::new(format!("cannot read the file: {e}"), path.display())),
    };
    let invalid = |what: String| Error::new(format!("{what}: repair annual financials from the data panel"), path.display());
    let records = records(&bytes).map_err(invalid)?;
    let mut reported = Reported { reports: vec![Vec::new(); companies.len()], order: vec![None; companies.len()] };
    let mut position = 0;
    for (symbol, rows) in records {
        let Ok(c) = companies.binary_search_by(|company| company.symbol.as_str().cmp(&symbol)) else {
            continue;
        };
        let accepted = accepted(&rows);
        if !accepted.is_empty() {
            position += 1;
            reported.reports[c] = accepted;
            reported.order[c] = Some(position);
        }
    }
    Ok(reported)
}

/// The records of `metrics.jsonl` as (symbol, rows), in first-appearance
/// order, each with its last record's rows. A line ends with `\n`, `\r\n`
/// (the raw cache's lines, written on Windows) or `\r`; blank lines are
/// skipped.
fn records(bytes: &[u8]) -> Result<Vec<(String, Vec<Value>)>, String> {
    let mut bytes = bytes;
    if bytes.last().is_some_and(|&b| b != b'\n') {
        let boundary = bytes.iter().rposition(|&b| b == b'\n').map_or(0, |i| i + 1);
        if serde_json::from_slice::<Value>(&bytes[boundary..]).is_err() {
            bytes = &bytes[..boundary];
        }
    }
    let text = std::str::from_utf8(bytes).map_err(|_| "the annual financial cache is not UTF-8 text".to_string())?;
    let mut records: Vec<(String, Vec<Value>)> = Vec::new();
    let mut positions = HashMap::new();
    for (number, line) in text.replace("\r\n", "\n").split(['\n', '\r']).enumerate() {
        if line.trim().is_empty() {
            continue;
        }
        let record = serde_json::from_str::<Value>(line).ok().and_then(|record| {
            let Value::Object(mut record) = record else { return None };
            let symbol = record.get("symbol")?.as_str().filter(|s| !s.is_empty())?.to_string();
            let Some(Value::Array(rows)) = record.remove("rows") else { return None };
            rows.iter().all(Value::is_object).then_some((symbol, rows))
        });
        let Some((symbol, rows)) = record else {
            return Err(format!("the annual financial cache has an invalid record on line {}", number + 1));
        };
        match positions.get(&symbol) {
            Some(&i) => records[i] = (symbol, rows),
            None => {
                positions.insert(symbol.clone(), records.len());
                records.push((symbol, rows));
            }
        }
    }
    Ok(records)
}

/// The accepted reports of one record's rows, in fiscal order; of equal
/// fiscal dates the later row.
fn accepted(rows: &[Value]) -> Vec<Report> {
    let mut reports: Vec<Report> = Vec::new();
    for row in rows {
        // The raw cache names the currency in capitals, or not at all.
        let usd = row.get("reportedCurrency").is_none_or(|code| code == "USD");
        let values = ["marketCap", "enterpriseValue", "evToEBITDA"].map(|key| number(row.get(key)).filter(|&v| v > 0.0));
        let (Some(fiscal), [Some(market_cap), Some(enterprise_value), Some(multiple)], true) = (parse_day(row.get("date")), values, usd)
        else {
            continue;
        };
        let report = Report {
            fiscal,
            known: Market::Us.available(fiscal, None).0,
            market_cap,
            enterprise_value,
            ebitda: enterprise_value / multiple,
            ebitda_yield: 1.0 / multiple,
        };
        // Stable: equal fiscal dates keep row order, and the later replaces.
        let at = reports.partition_point(|r| r.fiscal <= fiscal);
        if at > 0 && reports[at - 1].fiscal == fiscal {
            reports[at - 1] = report;
        } else {
            reports.insert(at, report);
        }
    }
    reports
}

impl Reported {
    /// Whether the company is in the reported set: it has an accepted report.
    pub(crate) fn is_reported(&self, c: CompanyId) -> bool {
        !self.reports[c.index()].is_empty()
    }

    /// Each company's position, from 1, in the reported set's
    /// first-appearance order; `None` when unreported.
    pub(crate) fn order(&self) -> &[Option<u32>] {
        &self.order
    }

    /// The accepted reports of a company, in fiscal order.
    pub(crate) fn reports(&self, c: CompanyId) -> &[Report] {
        &self.reports[c.index()]
    }
}

/// The FX conversion of an amount in `currency` at `day`
/// (`BookFacts.convert`): times the day's USD per unit ([`Series::fx`]);
/// `None` without a fixing or when the result is not finite.
pub(crate) fn convert(series: &Series<'_>, value: f64, currency: &str, day: Day) -> Option<f64> {
    let (_, usd) = series.fx(currency, day)?;
    Some(value * usd).filter(|v| v.is_finite())
}

/// A report's fiscal price (`books.fiscal_price`): the last valid close on
/// or before its fiscal date, at most 7 days earlier, with its day.
pub(crate) fn fiscal_price(report: &Report, prices: &Prices<'_>) -> Option<(Day, f64)> {
    prices.price(report.fiscal, Direction::OnOrBefore, Some(7))
}

/// A report's market cap rescaled from its fiscal price to `price`, a close
/// with its day (`books.rescaled_cap`): cap × (price / fiscal price). Both
/// the valuation fold and admission value a company with it.
pub(crate) fn rescaled_cap(report: &Report, fiscal_price: (Day, f64), price: (Day, f64)) -> f64 {
    report.market_cap * (price.1 / fiscal_price.1)
}

/// One company's reports, in memory.
pub(crate) struct ReportRows {
    market: Market,
    fiscal: Vec<Day>,
    known: Vec<Day>,
    market_cap: Vec<f64>,
    enterprise_value: Vec<f64>,
    ebitda: Vec<f64>,
    ebitda_yield: Vec<f64>,
    currency: Texts,
    shares: Vec<f64>,
    debt: Vec<f64>,
    cash: Vec<f64>,
    basis: Vec<u8>,
    fiscal_cap: Vec<f64>,
}

impl ReportRows {
    fn new(market: Market) -> ReportRows {
        ReportRows {
            market,
            fiscal: Vec::new(),
            known: Vec::new(),
            market_cap: Vec::new(),
            enterprise_value: Vec::new(),
            ebitda: Vec::new(),
            ebitda_yield: Vec::new(),
            currency: Texts::new(),
            shares: Vec::new(),
            debt: Vec::new(),
            cash: Vec::new(),
            basis: Vec::new(),
            fiscal_cap: Vec::new(),
        }
    }

    /// A US company's accepted reports.
    pub(crate) fn us(reports: &[Report]) -> ReportRows {
        let mut rows = ReportRows::new(Market::Us);
        for r in reports {
            rows.fiscal.push(r.fiscal);
            rows.known.push(r.known);
            rows.market_cap.push(r.market_cap);
            rows.enterprise_value.push(r.enterprise_value);
            rows.ebitda.push(r.ebitda);
            rows.ebitda_yield.push(r.ebitda_yield);
        }
        rows
    }

    /// A foreign company's anchors from its statements and its native closes
    /// on the market's `sessions`. `quote` is its quote currency. A missing,
    /// unreadable or malformed native file gives no closes.
    pub(crate) fn foreign(
        raw: &Raw,
        market: Market,
        symbol: &str,
        quote: &str,
        annual: &Annual<'_>,
        sessions: &[Day],
    ) -> Result<ReportRows, Error> {
        let mut rows = ReportRows::new(market);
        let fiscals = annual.income_fiscals();
        if fiscals.is_empty() {
            return Ok(rows);
        }
        let native: Vec<(Day, f64)> = match read_json(&raw.native(symbol))? {
            Json::Value(Value::Array(days)) => observe(&days, &["close"], Some(quote))
                .into_iter()
                .filter_map(|(day, states)| Some((day, states[0].ok()?)))
                .filter(|(day, _)| sessions.binary_search(day).is_ok())
                .collect(),
            _ => Vec::new(),
        };
        for &fiscal in fiscals {
            let (Some(income), Some(balance)) = (annual.metadata(annual::SHARES, fiscal), annual.metadata(annual::TOTAL_DEBT, fiscal)) else {
                continue;
            };
            let Some(currency) = income.currency.filter(|&c| balance.currency == Some(c)) else { continue };
            let state = |field| annual.state(field, fiscal).expect("both statements exist");
            let (Ok(shares), Ok(ebitda), Ok(debt), Ok(cash)) =
                (state(annual::SHARES), state(annual::EBITDA), state(annual::TOTAL_DEBT), state(annual::CASH))
            else {
                continue;
            };
            if !(shares > 0.0 && ebitda > 0.0) {
                continue;
            }
            let end = native.partition_point(|&(day, _)| day <= fiscal);
            let close = end.checked_sub(1).map(|i| native[i]).filter(|&(day, _)| day.0 >= fiscal.0 - 7);
            rows.fiscal.push(fiscal);
            rows.known.push(income.known.max(balance.known));
            rows.currency.push(currency);
            rows.shares.push(shares);
            rows.ebitda.push(ebitda);
            rows.debt.push(debt);
            rows.cash.push(cash);
            rows.basis.push(income.basis as u8);
            rows.fiscal_cap.push(close.map_or(f64::NAN, |(_, close)| shares * close));
        }
        Ok(rows)
    }

    /// The reading over these rows; `quote` is the company's quote currency.
    pub(crate) fn view<'a>(&'a self, quote: &'a str) -> Reports<'a> {
        let values = match self.market {
            Market::Us => Values::Us {
                market_cap: &self.market_cap,
                enterprise_value: &self.enterprise_value,
                ebitda: &self.ebitda,
                ebitda_yield: &self.ebitda_yield,
            },
            _ => Values::Foreign {
                quote,
                currency: self.currency.view(),
                ebitda: &self.ebitda,
                debt: &self.debt,
                cash: &self.cash,
                fiscal_cap: &self.fiscal_cap,
            },
        };
        Reports { fiscal: &self.fiscal, known: &self.known, values }
    }
}

/// Writes the report columns of every company of `market`, in company order.
pub(crate) fn write(out: &mut GenerationWriter<'_>, market: Market, companies: &[&ReportRows]) -> Result<(), Error> {
    let mut offsets = vec![0u64];
    offsets.extend(companies.iter().scan(0u64, |end, r| {
        *end += r.fiscal.len() as u64;
        Some(*end)
    }));
    out.column("reports.offsets", &offsets)?;
    out.column("reports.fiscal", &companies.iter().flat_map(|r| r.fiscal.iter().copied()).collect::<Vec<_>>())?;
    out.column("reports.known", &companies.iter().flat_map(|r| r.known.iter().copied()).collect::<Vec<_>>())?;
    let mut values = |name: &str, column: fn(&ReportRows) -> &Vec<f64>| {
        out.column(&format!("reports.{name}"), &companies.iter().flat_map(|r| column(r).iter().copied()).collect::<Vec<_>>())
    };
    values("ebitda", |r| &r.ebitda)?;
    if market == Market::Us {
        values("market_cap", |r| &r.market_cap)?;
        values("enterprise_value", |r| &r.enterprise_value)?;
        return values("ebitda_yield", |r| &r.ebitda_yield);
    }
    values("shares", |r| &r.shares)?;
    values("debt", |r| &r.debt)?;
    values("cash", |r| &r.cash)?;
    values("fiscal_cap", |r| &r.fiscal_cap)?;
    out.column("reports.basis", &companies.iter().flat_map(|r| r.basis.iter().copied()).collect::<Vec<_>>())?;
    let currency: Vec<&str> = companies.iter().flat_map(|r| (0..r.fiscal.len()).map(|i| r.currency.view().get(i))).collect();
    out.text("reports.currency", &currency)
}

/// One company's reports, in fiscal order, and the report a book selects.
#[derive(Clone, Copy)]
pub(crate) struct Reports<'a> {
    fiscal: &'a [Day],
    known: &'a [Day],
    values: Values<'a>,
}

#[derive(Clone, Copy)]
enum Values<'a> {
    Us { market_cap: &'a [f64], enterprise_value: &'a [f64], ebitda: &'a [f64], ebitda_yield: &'a [f64] },
    Foreign { quote: &'a str, currency: Text<'a>, ebitda: &'a [f64], debt: &'a [f64], cash: &'a [f64], fiscal_cap: &'a [f64] },
}

impl<'a> Reports<'a> {
    /// Whether report `i` is selectable on `day` (`rules.selectable`): known
    /// before `day`, with its fiscal date at most 800 days earlier.
    fn selectable(&self, i: usize, day: Day) -> bool {
        self.known[i] < day && day.0 - self.fiscal[i].0 <= MAX_AGE
    }

    /// US report `i` as stored; `None` for a foreign report.
    fn stored(&self, i: usize) -> Option<Report> {
        let Values::Us { market_cap, enterprise_value, ebitda, ebitda_yield } = self.values else { return None };
        Some(Report {
            fiscal: self.fiscal[i],
            known: self.known[i],
            market_cap: market_cap[i],
            enterprise_value: enterprise_value[i],
            ebitda: ebitda[i],
            ebitda_yield: ebitda_yield[i],
        })
    }

    /// Report `i` as a book on `day` reads it: US as stored; foreign
    /// converted at `day` (`BookFacts._report`): market cap = fiscal cap ×
    /// quote-currency FX, EBITDA × report-currency FX, EV = market cap +
    /// (debt − cash) × report-currency FX, yield = EBITDA / EV. `None` when
    /// it has no fiscal cap, an FX is missing or a value is not positive and
    /// finite.
    fn at(&self, i: usize, day: Day, series: &Series<'_>) -> Option<Report> {
        let (fiscal, known) = (self.fiscal[i], self.known[i]);
        match self.values {
            Values::Us { .. } => self.stored(i),
            Values::Foreign { quote, currency, ebitda, debt, cash, fiscal_cap } => {
                if fiscal_cap[i].is_nan() {
                    return None;
                }
                let (_, quote_fx) = series.fx(quote, day)?;
                let (_, report_fx) = series.fx(currency.get(i), day)?;
                let market_cap = fiscal_cap[i] * quote_fx;
                let ebitda = ebitda[i] * report_fx;
                let enterprise_value = market_cap + (debt[i] - cash[i]) * report_fx;
                if ![market_cap, ebitda, enterprise_value].iter().all(|v| v.is_finite() && *v > 0.0) {
                    return None;
                }
                Some(Report { fiscal, known, market_cap, enterprise_value, ebitda, ebitda_yield: ebitda / enterprise_value })
            }
        }
    }

    /// The report a book on `day` selects (`BookFacts.report_at`, the cached
    /// pool): the last report in fiscal order that is selectable on `day`
    /// and, foreign, converts at `day`. A foreign report that does not
    /// convert gives way to the one before it.
    pub(crate) fn report_at(&self, day: Day, series: &Series<'_>) -> Option<Report> {
        (0..self.fiscal.len()).rev().filter(|&i| self.selectable(i, day)).find_map(|i| self.at(i, day, series))
    }

    /// The reports the built-ins read on `day` (`books.owner_values`'
    /// history), in fiscal order: US every report; foreign those known before
    /// `day` that convert at `day`.
    pub(crate) fn history(&self, day: Day, series: &Series<'_>) -> Vec<Report> {
        let us = matches!(self.values, Values::Us { .. });
        (0..self.fiscal.len()).filter(|&i| us || self.known[i] < day).filter_map(|i| self.at(i, day, series)).collect()
    }

    /// The US legacy pool's report on `day` (`books.pools`, then
    /// `rules.latest_statement`): the last report in fiscal order with a
    /// market cap of at least $100M and an EV of at least $50M that is
    /// selectable on `day`. Hong Kong and Tokyo have no legacy pool: `None`.
    pub(crate) fn legacy_report_at(&self, day: Day) -> Option<Report> {
        let Values::Us { market_cap, enterprise_value, .. } = self.values else { return None };
        (0..self.fiscal.len())
            .rev()
            .filter(|&i| market_cap[i] >= MIN_MARKET_CAP && enterprise_value[i] >= MIN_EV)
            .find(|&i| self.selectable(i, day))
            .and_then(|i| self.stored(i))
    }
}

/// The report columns of a published generation.
pub(crate) struct ReportColumns<'a> {
    companies: Companies<'a>,
    offsets: &'a [u64],
    fiscal: &'a [Day],
    known: &'a [Day],
    market_cap: &'a [f64],
    enterprise_value: &'a [f64],
    ebitda: &'a [f64],
    ebitda_yield: &'a [f64],
    currency: Option<Text<'a>>,
    shares: &'a [f64],
    debt: &'a [f64],
    cash: &'a [f64],
    basis: &'a [u8],
    fiscal_cap: &'a [f64],
}

impl<'a> ReportColumns<'a> {
    pub(crate) fn open(generation: &'a Generation) -> ReportColumns<'a> {
        let market = generation.manifest().market;
        let us = market == Market::Us;
        let values = |name: &str, here: bool| if here { generation.column::<f64>(&format!("reports.{name}")) } else { &[][..] };
        ReportColumns {
            companies: Companies::open(generation),
            offsets: generation.column("reports.offsets"),
            fiscal: generation.column("reports.fiscal"),
            known: generation.column("reports.known"),
            market_cap: values("market_cap", us),
            enterprise_value: values("enterprise_value", us),
            ebitda: values("ebitda", true),
            ebitda_yield: values("ebitda_yield", us),
            currency: (!us).then(|| generation.text("reports.currency")),
            shares: values("shares", !us),
            debt: values("debt", !us),
            cash: values("cash", !us),
            basis: if us { &[] } else { generation.column("reports.basis") },
            fiscal_cap: values("fiscal_cap", !us),
        }
    }

    /// One company's reports.
    pub(crate) fn company(&self, c: CompanyId) -> Reports<'a> {
        let rows = self.offsets[c.index()] as usize..self.offsets[c.index() + 1] as usize;
        let values = match self.currency {
            None => Values::Us {
                market_cap: &self.market_cap[rows.clone()],
                enterprise_value: &self.enterprise_value[rows.clone()],
                ebitda: &self.ebitda[rows.clone()],
                ebitda_yield: &self.ebitda_yield[rows.clone()],
            },
            Some(currency) => Values::Foreign {
                quote: self.companies.currency(c),
                currency: currency.slice(rows.clone()),
                ebitda: &self.ebitda[rows.clone()],
                debt: &self.debt[rows.clone()],
                cash: &self.cash[rows.clone()],
                fiscal_cap: &self.fiscal_cap[rows.clone()],
            },
        };
        Reports { fiscal: &self.fiscal[rows.clone()], known: &self.known[rows], values }
    }

    /// Writes the `reports` table (key `symbol`, `fiscal`): US the accepted
    /// reports (the oracle's `statements`), foreign the anchors (its
    /// `foreign_reports`).
    pub(crate) fn export(&self, out: &mut tables::Writer) -> Result<u64, String> {
        let companies = &self.companies;
        let mut table = out.table("reports", &["symbol", "fiscal"])?;
        for c in companies.ids() {
            for i in self.offsets[c.index()] as usize..self.offsets[c.index() + 1] as usize {
                let (fiscal, known) = (self.fiscal[i].to_string(), self.known[i].to_string());
                let mut row = vec![
                    ("symbol", Cell::Text(companies.symbol(c))),
                    ("fiscal", Cell::Text(&fiscal)),
                    ("known", Cell::Text(&known)),
                ];
                match self.currency {
                    None => row.extend([
                        ("market_cap", Cell::Number(self.market_cap[i])),
                        ("enterprise_value", Cell::Number(self.enterprise_value[i])),
                        ("ebitda", Cell::Number(self.ebitda[i])),
                        ("ebitda_yield", Cell::Number(self.ebitda_yield[i])),
                    ]),
                    Some(currency) => row.extend([
                        ("currency", Cell::Text(currency.get(i))),
                        ("shares", Cell::Number(self.shares[i])),
                        ("ebitda", Cell::Number(self.ebitda[i])),
                        ("debt", Cell::Number(self.debt[i])),
                        ("cash", Cell::Number(self.cash[i])),
                        ("basis", Cell::Text(Basis::from_code(self.basis[i]).text())),
                        ("fiscal_cap", Some(self.fiscal_cap[i]).filter(|v| !v.is_nan()).map_or(Cell::Null, Cell::Number)),
                    ]),
                }
                table.row(&row)?;
            }
        }
        table.finish()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// metrics.jsonl was written on Windows: every line ends with `\r\n`.
    /// A symbol saved twice (510 in the raw cache) keeps the position of its
    /// first record and the rows of its last.
    #[test]
    fn crlf_lines_and_repeated_records_read_as_the_oracle_reads_them() {
        let text = b"{\"symbol\": \"B\", \"rows\": []}\r\n{\"symbol\": \"A\", \"rows\": [{}]}\r\n\r\n{\"symbol\": \"B\", \"rows\": [{}, {}]}\r\n{\"symbol\": \"C\"";
        let read = records(text).unwrap();
        let summary: Vec<(&str, usize)> = read.iter().map(|(s, rows)| (s.as_str(), rows.len())).collect();
        assert_eq!(summary, [("B", 2), ("A", 1)]);
        assert!(records(b"{\"symbol\": \"B\", \"rows\": [1]}\n").unwrap_err().contains("line 1"));
    }

    /// 22 records of the raw cache repeat a fiscal date: the later row wins.
    #[test]
    fn a_repeated_fiscal_date_keeps_the_later_row() {
        let rows: Vec<Value> = serde_json::from_str(
            r#"[{"date": "2020-12-31", "marketCap": 4, "enterpriseValue": 8, "evToEBITDA": 2, "reportedCurrency": "USD"},
                {"date": "2019-12-31", "marketCap": 1, "enterpriseValue": 1, "evToEBITDA": 1},
                {"date": "2020-12-31", "marketCap": 5, "enterpriseValue": 10, "evToEBITDA": 4},
                {"date": "2021-12-31", "marketCap": 5, "enterpriseValue": 10, "evToEBITDA": 4, "reportedCurrency": "CAD"}]"#,
        )
        .unwrap();
        let reports = accepted(&rows);
        let summary: Vec<(String, f64, f64)> = reports.iter().map(|r| (r.fiscal.to_string(), r.market_cap, r.ebitda)).collect();
        assert_eq!(summary, [("2019-12-31".into(), 1.0, 1.0), ("2020-12-31".into(), 5.0, 2.5)]);
        assert_eq!(reports[1].known.to_string(), "2021-03-31");
    }
}
