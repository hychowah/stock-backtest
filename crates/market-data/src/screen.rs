//! A day's screen (`books.Screen` and `books.book` of the cached pool): the
//! report each company selects, the US tie rank, the admission gates and the
//! entry valuation of each candidate; and the L2 tables `candidates` and
//! `screens`.
//!
//! - A dated screen admits every company and enters at the first valid close
//!   on or after the day, at most [`ENTRY_SLACK`] days later; the latest
//!   screen admits listed companies only and enters at the day's own close.
//! - Report choice: [`Reports::report_at`]. The US tie rank is the position,
//!   up to [`BUFFER`], of a company's legacy-pool report ([`Reports::legacy_report_at`])
//!   by report yield, highest first; equal yields keep the first-appearance
//!   order ([`Companies::order`]). The latest screen ranks listed companies
//!   only. Hong Kong and Tokyo have no rank.
//! - The gates, in order: not listed (latest), no eligible report, no saved
//!   prices, a missing fiscal price ([`fiscal_price`]) or entry price, a cap
//!   ([`rescaled_cap`]) or EV (cap + report EV − report cap) that is not
//!   positive, a cap, EV or EBITDA (report yield × report EV) that is not
//!   finite, and, outside the US, an entry close without FX at its day.
//! - A candidate's price is the entry close in USD; its spread is its EBITDA
//!   yield − the 3-month Treasury rate of the day (0 without one); its values
//!   are the built-ins ([`builtins::values`]); its numbers are normalized as
//!   [`Candidate`] says.

use crate::annual::AnnualColumns;
use crate::builtins::{self, BUILTINS, Facts, Valuation, Values};
use crate::companies::{Companies, CompanyId};
use crate::prices::{Direction, PriceColumns, Prices};
use crate::reports::{Report, ReportColumns, convert, fiscal_price, rescaled_cap};
use crate::series::Series;
use crate::store::Generation;
use crate::valuation::ValuationColumns;
use crate::{Day, Market, MarketData};
use rayon::prelude::*;
use serde::Serialize;
use tables::Cell;

/// How many legacy-pool companies the US tie rank ranks (`rules.BUFFER`).
const BUFFER: usize = 250;
/// How many days after a dated screen's day its entry may be.
const ENTRY_SLACK: i32 = 4;

/// Which screen a day's candidates come from.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Screen {
    /// Every company, entering at the first close on or after the day, a few
    /// days later at most.
    Dated,
    /// Listed companies only, at the exact session.
    Latest,
}

/// One admitted company of a day: the oracle's sheet row. Its numbers are
/// those the oracle's REAL columns stored ([`numbers::stored_real`]: `-0.0` is
/// `0.0`); only a candidate normalizes them, the built-ins and reports do not.
#[derive(Clone, Debug, PartialEq)]
pub struct Candidate {
    pub company: CompanyId,
    /// US: the tie rank, from 1, when the company is among the highest
    /// legacy-pool report yields of the day.
    pub rank: Option<u32>,
    /// The selected report's fiscal and known dates.
    pub fiscal: Day,
    pub known: Day,
    /// The entry close's day.
    pub entry: Day,
    /// The entry close in USD.
    pub price: f64,
    pub market_cap: f64,
    pub enterprise_value: f64,
    /// The report's yield × the report's EV (`books.admit`).
    pub ebitda: f64,
    pub ebitda_yield: f64,
    pub ev_ebitda: f64,
    pub spread: f64,
    /// The built-ins, indexed as [`BUILTINS`].
    pub values: Values,
}

/// Why a company is not a candidate of a day: the gate that refused it.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum Denial {
    NotListed,
    NoEligibleReport,
    MissingCachedPrices,
    MissingPrice,
    NonpositiveValuation,
    NonfiniteResult,
}

impl Denial {
    /// Every cause the gate covers.
    pub fn message(self) -> &'static str {
        match self {
            Denial::NotListed => "the latest screen admits listed companies only",
            Denial::NoEligibleReport => {
                "no report is known before the day, recent enough to select and, in Hong Kong and Tokyo, has a fiscal \
                 market cap and converts at the day's FX to a positive, finite market cap, EV and EBITDA"
            }
            Denial::MissingCachedPrices => "the company has no saved prices",
            Denial::MissingPrice => {
                "no close shortly before the report's fiscal date, no entry close within the screen's entry slack, \
                 or, in Hong Kong and Tokyo, no FX for the entry close"
            }
            Denial::NonpositiveValuation => "the market cap or EV at entry is not positive",
            Denial::NonfiniteResult => "the market cap, EV or EBITDA at entry is not finite",
        }
    }
}

/// The prepared columns a screen reads.
pub(crate) struct Columns<'a> {
    market: Market,
    companies: Companies<'a>,
    series: Series<'a>,
    prices: PriceColumns<'a>,
    reports: ReportColumns<'a>,
    annual: AnnualColumns<'a>,
    valuation: ValuationColumns<'a>,
}

impl<'a> Columns<'a> {
    pub(crate) fn open(generation: &'a Generation) -> Columns<'a> {
        Columns {
            market: generation.manifest().market,
            companies: Companies::open(generation),
            series: Series::open(generation),
            prices: PriceColumns::open(generation),
            reports: ReportColumns::open(generation),
            annual: AnnualColumns::open(generation),
            valuation: ValuationColumns::open(generation),
        }
    }
}

/// The screen of one day: each company's selected report and tie rank.
pub(crate) struct DayScreen<'c, 'a> {
    columns: &'c Columns<'a>,
    day: Day,
    screen: Screen,
    /// By company; `None` also for an unlisted company of the latest screen.
    selected: Vec<Option<Report>>,
    ranks: Vec<Option<u32>>,
}

impl<'c, 'a> DayScreen<'c, 'a> {
    /// The screen of `day`, a session from 1996-01-01.
    pub(crate) fn new(columns: &'c Columns<'a>, day: Day, screen: Screen) -> DayScreen<'c, 'a> {
        let companies = &columns.companies;
        let mut selected = Vec::with_capacity(companies.len());
        let mut legacy = Vec::new();
        for c in companies.ids() {
            if screen == Screen::Latest && !companies.listed(c) {
                selected.push(None);
                continue;
            }
            let reports = columns.reports.company(c);
            selected.push(reports.report_at(day, &columns.series));
            if let Some(report) = reports.legacy_report_at(day) {
                legacy.push((companies.order(c).expect("a reported US company has an order"), c, report.ebitda_yield));
            }
        }
        legacy.sort_by_key(|&(order, ..)| order);
        let mut ranks = vec![None; companies.len()];
        for (c, rank) in tie_ranks(&legacy.into_iter().map(|(_, c, y)| (c, y)).collect::<Vec<_>>()) {
            ranks[c.index()] = Some(rank);
        }
        DayScreen { columns, day, screen, selected, ranks }
    }

    /// The number of companies with a selected report.
    pub(crate) fn reported(&self) -> usize {
        self.selected.iter().flatten().count()
    }

    /// The report company `c` selects.
    pub(crate) fn report(&self, c: CompanyId) -> Option<Report> {
        self.selected[c.index()]
    }

    /// The fiscal and entry closes of company `c`'s selected report.
    pub(crate) fn closes(&self, c: CompanyId) -> (Option<(Day, f64)>, Option<(Day, f64)>) {
        let Some(report) = self.report(c) else { return (None, None) };
        let prices = self.columns.prices.company(c);
        (fiscal_price(&report, &prices), self.entry_close(&prices))
    }

    fn entry_close(&self, prices: &Prices<'_>) -> Option<(Day, f64)> {
        let slack = if self.screen == Screen::Latest { 0 } else { ENTRY_SLACK };
        prices.price(self.day, Direction::OnOrAfter, Some(slack))
    }

    /// The candidates, in company order.
    pub(crate) fn candidates(&self) -> Vec<Candidate> {
        self.columns.companies.ids().filter_map(|c| self.decide(c).ok()).collect()
    }

    /// Company `c`'s candidate row, or the first gate that refuses it.
    pub(crate) fn decide(&self, c: CompanyId) -> Result<Candidate, Denial> {
        let columns = self.columns;
        if self.screen == Screen::Latest && !columns.companies.listed(c) {
            return Err(Denial::NotListed);
        }
        let report = self.selected[c.index()].ok_or(Denial::NoEligibleReport)?;
        if !columns.companies.priced(c) {
            return Err(Denial::MissingCachedPrices);
        }
        let prices = columns.prices.company(c);
        let (Some(fiscal_close), Some(entry)) = (fiscal_price(&report, &prices), self.entry_close(&prices)) else {
            return Err(Denial::MissingPrice);
        };
        let cap = rescaled_cap(&report, fiscal_close, entry);
        let ev = cap + (report.enterprise_value - report.market_cap);
        if ev <= 0.0 || cap <= 0.0 {
            return Err(Denial::NonpositiveValuation);
        }
        let ebitda = report.ebitda_yield * report.enterprise_value;
        if ![cap, ev, ebitda].iter().all(|v| v.is_finite()) {
            return Err(Denial::NonfiniteResult);
        }
        let quote = columns.companies.quote(columns.market, c);
        let price = convert(&columns.series, entry.1, quote, entry.0).ok_or(Denial::MissingPrice)?;
        let facts = Facts {
            company: c,
            quote,
            prices,
            reports: columns.reports.company(c),
            annual: columns.annual.company(c),
            series: &columns.series,
            valuation: &columns.valuation,
        };
        let valuation = Valuation { fiscal: report.fiscal, market_cap: cap, enterprise_value: ev, ebitda };
        let values = builtins::values(&facts, self.day, &valuation);
        let (ebitda_yield, ev_ebitda) = builtins::yield_and_multiple(ebitda, ev);
        let spread = ebitda_yield - columns.series.treasury(self.day).unwrap_or(0.0);
        let real = |x: f64| numbers::stored_real(x).expect("a valuation is a number");
        Ok(Candidate {
            company: c,
            rank: self.ranks[c.index()],
            fiscal: report.fiscal,
            known: report.known,
            entry: entry.0,
            price: real(price),
            market_cap: real(cap),
            enterprise_value: real(ev),
            ebitda: real(ebitda),
            ebitda_yield: real(ebitda_yield),
            ev_ebitda: real(ev_ebitda),
            spread: real(spread),
            values: values.map(|v| v.and_then(numbers::stored_real)),
        })
    }
}

/// The tie rank (`books.candidates`): `pool` holds each company's report
/// yield in first-appearance order; the [`BUFFER`] highest yields get ranks from 1,
/// and equal yields keep their pool order.
fn tie_ranks<K: Copy>(pool: &[(K, f64)]) -> Vec<(K, u32)> {
    let mut sorted = pool.to_vec();
    sorted.sort_by(|a, b| b.1.partial_cmp(&a.1).expect("report yields are numbers"));
    sorted.into_iter().take(BUFFER).zip(1..).map(|((k, _), rank)| (k, rank)).collect()
}

/// Writes the L2 tables: `candidates` (key `screen`, `day`, `symbol`; the
/// oracle's book-row fields) and `screens` (key `screen`, `day`; `reported`
/// and `admitted`), for the dated screens of `days` (ascending) and the
/// latest screen of `latest`. Days are calculated in parallel. Returns the
/// rows of each table.
pub(crate) fn export(data: &MarketData, days: &[Day], latest: Day, out: &mut tables::Writer) -> Result<(u64, u64), String> {
    let companies = data.companies();
    let lanes: Vec<String> = BUILTINS
        .iter()
        .map(|b| match b.id.strip_prefix("metric:") {
            Some(metric) => format!("m_{}", metric.replace(':', "_")),
            None => format!("f_{}", b.id.strip_prefix("filter:").expect("a filter id")),
        })
        .collect();
    let mut rows = out.table("candidates", &["screen", "day", "symbol"])?;
    let mut screens = out.table("screens", &["screen", "day"])?;
    let work: Vec<(Screen, Day)> = days.iter().map(|&d| (Screen::Dated, d)).chain([(Screen::Latest, latest)]).collect();
    for chunk in work.chunks(4 * rayon::current_num_threads()) {
        let results: Vec<(usize, Vec<Candidate>)> = chunk
            .par_iter()
            .map(|&(screen, day)| data.screen(day, screen))
            .collect();
        for (&(screen, day), (reported, candidates)) in chunk.iter().zip(results) {
            let (screen, day) = (if screen == Screen::Dated { "dated" } else { "latest" }, day.to_string());
            for row in &candidates {
                let (fiscal, known, entry) = (row.fiscal.to_string(), row.known.to_string(), row.entry.to_string());
                let mut fields = vec![
                    ("screen", Cell::Text(screen)),
                    ("day", Cell::Text(&day)),
                    ("symbol", Cell::Text(companies.symbol(row.company))),
                    ("candidate_rank", row.rank.map_or(Cell::Null, |r| Cell::Int(r.into()))),
                    ("fiscal", Cell::Text(&fiscal)),
                    ("known", Cell::Text(&known)),
                    ("entry", Cell::Text(&entry)),
                    ("price", Cell::Number(row.price)),
                    ("market_cap", Cell::Number(row.market_cap)),
                    ("enterprise_value", Cell::Number(row.enterprise_value)),
                    ("ebitda", Cell::Number(row.ebitda)),
                    ("ebitda_yield", Cell::Number(row.ebitda_yield)),
                    ("ev_ebitda", Cell::Number(row.ev_ebitda)),
                    ("spread", Cell::Number(row.spread)),
                ];
                fields.extend(lanes.iter().zip(row.values).map(|(lane, v)| (lane.as_str(), v.map_or(Cell::Null, Cell::Number))));
                rows.row(&fields)?;
            }
            screens.row(&[
                ("screen", Cell::Text(screen)),
                ("day", Cell::Text(&day)),
                ("reported", Cell::Int(reported as i64)),
                ("admitted", Cell::Int(candidates.len() as i64)),
            ])?;
        }
    }
    Ok((rows.finish()?, screens.finish()?))
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde::Deserialize;

    /// A case of `fixtures/numbers/legacy_rank.json`.
    #[derive(Deserialize)]
    struct RankCase {
        /// Each company's report yield, as `[symbol, yield]`, in first-appearance order.
        statements: Vec<(String, f64)>,
        /// The ranked companies, as `[symbol, rank]`, in rank order.
        ranks: Vec<(String, u32)>,
    }

    #[test]
    fn legacy_rank_vectors() {
        let path = concat!(env!("CARGO_MANIFEST_DIR"), "/../../fixtures/numbers/legacy_rank.json");
        #[derive(Deserialize)]
        struct File {
            cases: Vec<RankCase>,
        }
        let file: File = serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap();
        assert!(!file.cases.is_empty());
        for case in file.cases {
            let pool: Vec<(&str, f64)> = case.statements.iter().map(|(s, y)| (s.as_str(), *y)).collect();
            let ranks: Vec<(String, u32)> = tie_ranks(&pool).into_iter().map(|(s, r)| (s.to_string(), r)).collect();
            assert_eq!(ranks, case.ranks);
        }
    }
}
