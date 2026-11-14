//! The valuation sums: per company and priced day, the running sums of the
//! daily E/P, S/P and B/P yields and their day counts, folded at preparation
//! (`facts.refold` over `books.valuation_days`); and the 3- and 5-year
//! valuation averages read from them (`metrics.filter_values`). The sums stay
//! private to this module.
//!
//! The fold takes each valid close in day order. A day counts when a book on
//! it selects a report ([`Reports::report_at`]), the report has a fiscal
//! price ([`fiscal_price`]) and the cap rescaled to the day's close
//! ([`rescaled_cap`]) is positive and finite. Its yields are the net income,
//! revenue and equity that the book reads ([`Annual::legacy`]) over that cap,
//! each when present and finite; a day without any yield is left out. Each
//! sum starts at +0.0 and adds its yields plainly, in day order, and each
//! count counts them.
//!
//! Columns: `valuation.offsets` (`u64`, one more than companies), and per
//! row `valuation.day`, `valuation.earnings`, `.sales`, `.equity` (`f64`) and
//! `valuation.earnings_days`, `.sales_days`, `.equity_days` (`u32`).

use crate::annual::{Annual, LegacyField};
use crate::companies::{Companies, CompanyId};
use crate::prices::Prices;
use crate::reports::{Reports, fiscal_price, rescaled_cap};
use crate::series::Series;
use crate::store::{Generation, GenerationWriter};
use crate::{Day, Error};
use tables::Cell;

/// The yields' fields in sum order (`rules.VALUATIONS`): E/P, S/P, B/P.
const FIELDS: [LegacyField; 3] = [LegacyField::NetIncome, LegacyField::Revenue, LegacyField::Equity];
/// The sums' names, in that order.
const NAMES: [&str; 3] = ["earnings", "sales", "equity"];

/// One company's valuation sums, in memory.
#[derive(Default)]
pub(crate) struct SumRows {
    day: Vec<Day>,
    sums: [Vec<f64>; 3],
    counts: [Vec<u32>; 3],
}

/// Folds one company's sums from its prices, reports and statements.
pub(crate) fn fold(prices: &Prices<'_>, reports: &Reports<'_>, annual: &Annual<'_>, series: &Series<'_>) -> SumRows {
    let mut out = SumRows::default();
    let (mut total, mut count) = ([0.0f64; 3], [0u32; 3]);
    // The fiscal price of the last report read: reports change rarely.
    let mut fiscal = None;
    for (day, close) in prices.closes(None) {
        let Some(report) = reports.report_at(day, series) else { continue };
        if fiscal.is_none_or(|(f, _)| f != report.fiscal) {
            fiscal = Some((report.fiscal, fiscal_price(&report, prices)));
        }
        let Some((_, Some(fiscal_px))) = fiscal else { continue };
        let cap = rescaled_cap(&report, fiscal_px, (day, close));
        if !(cap > 0.0 && cap.is_finite()) {
            continue;
        }
        let values = annual.legacy(report.fiscal, day, series);
        let yields = FIELDS.map(|field| values.get(field).map(|v| v / cap).filter(|y| y.is_finite()));
        if yields.iter().all(Option::is_none) {
            continue;
        }
        for (k, value) in yields.into_iter().enumerate() {
            if let Some(value) = value {
                total[k] += value;
                count[k] += 1;
            }
            out.sums[k].push(total[k]);
            out.counts[k].push(count[k]);
        }
        out.day.push(day);
    }
    out
}

/// Writes the valuation columns of every company, in company order.
pub(crate) fn write(out: &mut GenerationWriter<'_>, companies: &[&SumRows]) -> Result<(), Error> {
    let mut offsets = vec![0u64];
    offsets.extend(companies.iter().scan(0u64, |end, r| {
        *end += r.day.len() as u64;
        Some(*end)
    }));
    out.column("valuation.offsets", &offsets)?;
    out.column("valuation.day", &companies.iter().flat_map(|r| r.day.iter().copied()).collect::<Vec<_>>())?;
    for k in 0..3 {
        out.column(&format!("valuation.{}", NAMES[k]), &companies.iter().flat_map(|r| r.sums[k].iter().copied()).collect::<Vec<_>>())?;
        let counts: Vec<u32> = companies.iter().flat_map(|r| r.counts[k].iter().copied()).collect();
        out.column(&format!("valuation.{}_days", NAMES[k]), &counts)?;
    }
    Ok(())
}

/// One valuation average and the current multiple relative to it.
#[derive(Clone, Copy, Debug, PartialEq)]
pub(crate) struct Average {
    /// 1 / the mean daily yield (the P/E, P/S or P/B average).
    pub(crate) average: f64,
    /// The current multiple / the average, when there is a current multiple
    /// and the ratio is finite.
    pub(crate) relative: Option<f64>,
}

/// The valuation columns of a published generation.
pub(crate) struct ValuationColumns<'a> {
    offsets: &'a [u64],
    day: &'a [Day],
    sums: [&'a [f64]; 3],
    counts: [&'a [u32]; 3],
}

impl<'a> ValuationColumns<'a> {
    pub(crate) fn open(generation: &'a Generation) -> ValuationColumns<'a> {
        ValuationColumns {
            offsets: generation.column("valuation.offsets"),
            day: generation.column("valuation.day"),
            sums: NAMES.map(|name| generation.column(&format!("valuation.{name}"))),
            counts: NAMES.map(|name| generation.column(&format!("valuation.{name}_days"))),
        }
    }

    /// The sums and counts of company `c` at its last row on or before
    /// `day`, or zeros.
    fn sums(&self, c: CompanyId, day: Day) -> ([f64; 3], [u32; 3]) {
        let (start, end) = (self.offsets[c.index()] as usize, self.offsets[c.index() + 1] as usize);
        let at = start + self.day[start..end].partition_point(|&d| d <= day);
        if at == start {
            return ([0.0; 3], [0; 3]);
        }
        (self.sums.map(|s| s[at - 1]), self.counts.map(|n| n[at - 1]))
    }

    /// The 3- and 5-year valuation averages of company `c` on `day`
    /// (`metrics.filter_values`), indexed `[years: 3, 5][P/E, P/S, P/B]`.
    /// Over the window from the day `years` earlier ([`Day::anniversary`])
    /// to `day`, the mean daily yield is the difference of the sums over the
    /// difference of the counts. An average is 1 / mean; it is `None` when
    /// there is no counted day on or before the window's start, no counted
    /// day in the window, the mean is not positive or 1 / mean is not finite.
    /// `current` holds the current P/E, P/S and P/B, whose ratio to the
    /// average is `relative`.
    #[expect(dead_code, reason = "the built-ins are its first caller")]
    pub(crate) fn averages(&self, c: CompanyId, day: Day, current: [Option<f64>; 3]) -> [[Option<Average>; 3]; 2] {
        let (now, now_counts) = self.sums(c, day);
        [3, 5].map(|years| {
            let (before, before_counts) = self.sums(c, day.anniversary(years));
            std::array::from_fn(|k| {
                let count = now_counts[k] - before_counts[k];
                if before_counts[k] == 0 || count == 0 {
                    return None;
                }
                let mean = (now[k] - before[k]) / f64::from(count);
                if mean <= 0.0 || !(1.0 / mean).is_finite() {
                    return None;
                }
                let average = 1.0 / mean;
                Some(Average { average, relative: current[k].map(|v| v / average).filter(|r| r.is_finite()) })
            })
        })
    }

    /// Writes the `valuation_sums` table (key `symbol`, `day`).
    pub(crate) fn export(&self, companies: &Companies<'_>, out: &mut tables::Writer) -> Result<u64, String> {
        let mut table = out.table("valuation_sums", &["symbol", "day"])?;
        for c in companies.ids() {
            for i in self.offsets[c.index()] as usize..self.offsets[c.index() + 1] as usize {
                table.row(&[
                    ("symbol", Cell::Text(companies.symbol(c))),
                    ("day", Cell::Text(&self.day[i].to_string())),
                    ("earnings", Cell::Number(self.sums[0][i])),
                    ("sales", Cell::Number(self.sums[1][i])),
                    ("equity", Cell::Number(self.sums[2][i])),
                    ("earnings_days", Cell::Int(self.counts[0][i].into())),
                    ("sales_days", Cell::Int(self.counts[1][i].into())),
                    ("equity_days", Cell::Int(self.counts[2][i].into())),
                ])?;
            }
        }
        table.finish()
    }
}
