//! The built-ins: the two metrics (EV / EBITDA and EV / 3-year average
//! EBITDA, each as a yield and a multiple) and the filter values. Each one's
//! id, label, unit, display unit and storage scale ([`BUILTINS`], the oracle's
//! `builtin_catalog`), and their values for one company valued on one day
//! (`books.owner_values`, `metrics.evaluate`, `metrics.filter_values`,
//! `metrics.financial_values`, `metrics.operating_yield_spread`).
//!
//! Values are raw binary64 in the oracle's stored units, with its order of
//! floating-point operations: dollars in millions (scale 6), percentages and
//! percentage points times 100 (scale -2), multiples as they are (scale 0).

use crate::annual::{Annual, LegacyField, LegacyValues};
use crate::companies::CompanyId;
use crate::prices::{Direction, Prices};
use crate::reports::{Reports, convert};
use crate::series::Series;
use crate::valuation::ValuationColumns;
use crate::Day;

/// One built-in: what it measures and in which units its values are.
#[derive(Clone, Copy, Debug)]
pub struct Builtin {
    /// `metric:<metric>:<yield|multiple>` or `filter:<field>`.
    pub id: &'static str,
    pub label: &'static str,
    /// `scalar` or `USD`.
    pub unit: &'static str,
    /// `percent`, `multiple`, `usd_million` or `percentage_points`.
    pub display: &'static str,
    /// The decimal exponent from a stored value to the unit: 6 (millions),
    /// -2 (percent) or 0.
    pub scale: i32,
}

const fn metric(id: &'static str, label: &'static str, display: &'static str) -> Builtin {
    Builtin { id, label, unit: "scalar", display, scale: 0 }
}

const fn filter(id: &'static str, label: &'static str, display: &'static str) -> Builtin {
    let (unit, scale) = match display.as_bytes() {
        b"usd_million" => ("USD", 6),
        b"percent" | b"percentage_points" => ("scalar", -2),
        _ => ("scalar", 0),
    };
    Builtin { id, label, unit, display, scale }
}

/// The built-ins in the oracle's catalog order; a candidate's values follow it.
pub const BUILTINS: [Builtin; 38] = [
    metric("metric:ev_ebitda:yield", "EBITDA / EV yield", "percent"),
    metric("metric:ev_ebitda:multiple", "EV / EBITDA multiple", "multiple"),
    metric("metric:ev_ebitda_3y:yield", "3-year average EBITDA / EV yield", "percent"),
    metric("metric:ev_ebitda_3y:multiple", "EV / 3-year average EBITDA multiple", "multiple"),
    filter("filter:pb", "P/B (×)", "multiple"),
    filter("filter:pe", "P/E (×)", "multiple"),
    filter("filter:ps", "P/S (×)", "multiple"),
    filter("filter:pe_avg_3y", "P/E 3-year average (×)", "multiple"),
    filter("filter:pe_avg_5y", "P/E 5-year average (×)", "multiple"),
    filter("filter:ps_avg_3y", "P/S 3-year average (×)", "multiple"),
    filter("filter:ps_avg_5y", "P/S 5-year average (×)", "multiple"),
    filter("filter:pb_avg_3y", "P/B 3-year average (×)", "multiple"),
    filter("filter:pb_avg_5y", "P/B 5-year average (×)", "multiple"),
    filter("filter:pe_vs_avg_3y", "P/E vs its 3-year average (×)", "multiple"),
    filter("filter:pe_vs_avg_5y", "P/E vs its 5-year average (×)", "multiple"),
    filter("filter:ps_vs_avg_3y", "P/S vs its 3-year average (×)", "multiple"),
    filter("filter:ps_vs_avg_5y", "P/S vs its 5-year average (×)", "multiple"),
    filter("filter:pb_vs_avg_3y", "P/B vs its 3-year average (×)", "multiple"),
    filter("filter:pb_vs_avg_5y", "P/B vs its 5-year average (×)", "multiple"),
    filter("filter:fcf", "Free cash flow ($ million)", "usd_million"),
    filter("filter:fcf_yield", "Free cash flow yield (%)", "percent"),
    filter("filter:price_fcf", "Price / free cash flow (×)", "multiple"),
    filter("filter:dividend_yield", "Dividend yield (%)", "percent"),
    filter("filter:profit_margin", "Net profit margin (%)", "percent"),
    filter("filter:operating_yield_spread_3y", "Sales × 3-year avg operating margin / EV − US 10Y (pp)", "percentage_points"),
    filter("filter:peg", "PEG — 3-year EPS growth (×)", "multiple"),
    filter("filter:roe", "Return on average equity (%)", "percent"),
    filter("filter:current_ratio", "Current ratio (×)", "multiple"),
    filter("filter:interest_coverage", "Interest coverage — EBIT / interest (×)", "multiple"),
    filter("filter:debt_equity", "Debt / equity (×)", "multiple"),
    filter("filter:return_1y", "1-year trailing return (%)", "percent"),
    filter("filter:return_3y", "3-year trailing return (%)", "percent"),
    filter("filter:turnover_1w", "Turnover rate — 1-week average (%)", "percent"),
    filter("filter:market_cap", "Market cap ($ million)", "usd_million"),
    filter("filter:enterprise_value", "Enterprise value ($ million)", "usd_million"),
    filter("filter:ev_ebitda", "EV / EBITDA (×)", "multiple"),
    filter("filter:ev_ebitda_3y", "EV / 3-year average EBITDA (×)", "multiple"),
    filter("filter:ebitda_yield", "EBITDA / EV (%)", "percent"),
];

/// The position of built-in `id` in [`BUILTINS`].
pub(crate) const fn at(id: &str) -> usize {
    let mut i = 0;
    while i < BUILTINS.len() {
        let (a, b) = (BUILTINS[i].id.as_bytes(), id.as_bytes());
        if a.len() == b.len() {
            let mut k = 0;
            while k < a.len() && a[k] == b[k] {
                k += 1;
            }
            if k == a.len() {
                return i;
            }
        }
        i += 1;
    }
    panic!("no such built-in");
}

const EV_EBITDA_YIELD: usize = at("metric:ev_ebitda:yield");
const EV_EBITDA_MULTIPLE: usize = at("metric:ev_ebitda:multiple");
const EV_EBITDA_3Y_YIELD: usize = at("metric:ev_ebitda_3y:yield");
const EV_EBITDA_3Y_MULTIPLE: usize = at("metric:ev_ebitda_3y:multiple");
const PE: usize = at("filter:pe");
const PS: usize = at("filter:ps");
const PB: usize = at("filter:pb");
/// `[years: 3, 5][P/E, P/S, P/B]`, as [`ValuationColumns::averages`] gives them.
const AVERAGES: [[usize; 3]; 2] = [
    [at("filter:pe_avg_3y"), at("filter:ps_avg_3y"), at("filter:pb_avg_3y")],
    [at("filter:pe_avg_5y"), at("filter:ps_avg_5y"), at("filter:pb_avg_5y")],
];
const RELATIVES: [[usize; 3]; 2] = [
    [at("filter:pe_vs_avg_3y"), at("filter:ps_vs_avg_3y"), at("filter:pb_vs_avg_3y")],
    [at("filter:pe_vs_avg_5y"), at("filter:ps_vs_avg_5y"), at("filter:pb_vs_avg_5y")],
];
const FCF: usize = at("filter:fcf");
const FCF_YIELD: usize = at("filter:fcf_yield");
const PRICE_FCF: usize = at("filter:price_fcf");
const DIVIDEND_YIELD: usize = at("filter:dividend_yield");
const PROFIT_MARGIN: usize = at("filter:profit_margin");
const OPERATING_YIELD_SPREAD: usize = at("filter:operating_yield_spread_3y");
const PEG: usize = at("filter:peg");
const ROE: usize = at("filter:roe");
const CURRENT_RATIO: usize = at("filter:current_ratio");
const INTEREST_COVERAGE: usize = at("filter:interest_coverage");
const DEBT_EQUITY: usize = at("filter:debt_equity");
const RETURNS: [(i32, usize); 2] = [(1, at("filter:return_1y")), (3, at("filter:return_3y"))];
const TURNOVER: usize = at("filter:turnover_1w");
const MARKET_CAP: usize = at("filter:market_cap");
const ENTERPRISE_VALUE: usize = at("filter:enterprise_value");
const FILTER_EV_EBITDA: usize = at("filter:ev_ebitda");
const FILTER_EV_EBITDA_3Y: usize = at("filter:ev_ebitda_3y");
const FILTER_EBITDA_YIELD: usize = at("filter:ebitda_yield");

/// Built-in values, indexed as [`BUILTINS`]; `None` where the oracle leaves
/// a value out.
pub type Values = [Option<f64>; BUILTINS.len()];

/// One company's prepared data, as the built-ins read it.
pub(crate) struct Facts<'a, 's> {
    pub(crate) company: CompanyId,
    /// The quote currency.
    pub(crate) quote: &'a str,
    pub(crate) prices: Prices<'a>,
    pub(crate) reports: Reports<'a>,
    pub(crate) annual: Annual<'a>,
    pub(crate) series: &'s Series<'a>,
    pub(crate) valuation: &'s ValuationColumns<'a>,
}

/// The entry valuation a company is valued at on a day.
pub(crate) struct Valuation {
    /// The selected report's fiscal date.
    pub(crate) fiscal: Day,
    pub(crate) market_cap: f64,
    pub(crate) enterprise_value: f64,
    pub(crate) ebitda: f64,
}

/// EBITDA / EV and EV / EBITDA, each divided on its own
/// (`books.ebitda_yield_and_multiple`).
pub(crate) fn yield_and_multiple(ebitda: f64, enterprise_value: f64) -> (f64, f64) {
    (ebitda / enterprise_value, enterprise_value / ebitda)
}

/// Every built-in of the company valued at `valuation` on `day`.
pub(crate) fn values(facts: &Facts<'_, '_>, day: Day, valuation: &Valuation) -> Values {
    let Valuation { fiscal, market_cap: cap, enterprise_value: ev, ebitda } = *valuation;
    let series = facts.series;
    let mut out: Values = [None; BUILTINS.len()];
    let (ebitda_yield, multiple) = yield_and_multiple(ebitda, ev);
    out[EV_EBITDA_YIELD] = Some(ebitda_yield);
    out[EV_EBITDA_MULTIPLE] = Some(multiple);
    let ebitda_3y: Option<Vec<f64>> = facts.reports.yearly_ebitda(fiscal, day, series, 3).into_iter().collect();
    if let Some(average) = ebitda_3y.map(|values| numbers::mean(&values)).filter(|&a| a > 0.0) {
        let multiple = ev / average;
        out[EV_EBITDA_3Y_MULTIPLE] = Some(multiple);
        out[EV_EBITDA_3Y_YIELD] = Some(1.0 / multiple);
    }
    out[MARKET_CAP] = Some(cap / 1e6);
    out[ENTERPRISE_VALUE] = Some(ev / 1e6);
    out[FILTER_EBITDA_YIELD] = Some(ebitda_yield * 100.0);
    out[FILTER_EV_EBITDA] = out[EV_EBITDA_MULTIPLE];
    out[FILTER_EV_EBITDA_3Y] = out[EV_EBITDA_3Y_MULTIPLE];
    if let Some(dividends) = facts.annual.dividends(fiscal, day, series) {
        out[DIVIDEND_YIELD] = Some(-dividends / cap * 100.0);
    }
    if let Some(shares) = facts.annual.shares(fiscal, day).filter(|&s| s > 0.0) {
        let traded: Vec<f64> = facts.prices.volumes(Day(day.0 - 6), day).collect();
        if !traded.is_empty() {
            out[TURNOVER] = Some(numbers::sum(&traded) / traded.len() as f64 / shares * 100.0);
        }
    }
    let usd_close = |when: Day| {
        let (found, close) = facts.prices.price(when, Direction::OnOrBefore, Some(7))?;
        convert(series, close, facts.quote, found)
    };
    let end = usd_close(day);
    for (years, lane) in RETURNS {
        if let (Some(end), Some(start)) = (end, usd_close(day.anniversary(years)))
            && start > 0.0
        {
            out[lane] = Some((end / start - 1.0) * 100.0);
        }
    }
    let annual = facts.annual.legacy_at(day, series);
    financial_values(fiscal, cap, &annual, &mut out);
    out[OPERATING_YIELD_SPREAD] = operating_yield_spread(fiscal, ev, &annual, series.ten_year(day));
    let averages = facts.valuation.averages(facts.company, day, [out[PE], out[PS], out[PB]]);
    for (years, averages) in averages.into_iter().enumerate() {
        for (k, average) in averages.into_iter().enumerate() {
            if let Some(average) = average {
                out[AVERAGES[years][k]] = Some(average.average);
                out[RELATIVES[years][k]] = average.relative;
            }
        }
    }
    out
}

/// The legacy values of calendar year `year`: its last fiscal date on or
/// before `fiscal`, or none.
fn in_year(annual: &[(Day, LegacyValues)], fiscal: Day, year: i32) -> LegacyValues {
    annual.iter().rev().filter(|(d, _)| *d <= fiscal).find(|(d, _)| d.ymd().0 == year).map(|(_, v)| *v).unwrap_or_default()
}

/// `numerator / denominator × scale` when both are present, the denominator
/// is positive and the result finite (`financial_values.ratio`).
fn ratio(numerator: Option<f64>, denominator: Option<f64>, scale: f64) -> Option<f64> {
    let (n, d) = (numerator?, denominator?);
    (d > 0.0).then(|| n / d * scale).filter(|v| v.is_finite())
}

/// The annual ratios of fiscal date `fiscal` at market cap `cap`
/// (`metrics.financial_values`), from `annual`, the legacy values by fiscal
/// date in fiscal order.
fn financial_values(fiscal: Day, cap: f64, annual: &[(Day, LegacyValues)], out: &mut Values) {
    use LegacyField::*;
    let year = fiscal.ymd().0;
    let current = annual.iter().find(|(d, _)| *d == fiscal).map(|(_, v)| *v).unwrap_or_default();
    let previous = in_year(annual, fiscal, year - 1);
    let (income, equity, fcf) = (current.get(NetIncome), current.get(Equity), current.get(FreeCashFlow));
    out[PE] = ratio(Some(cap), income, 1.0);
    out[PS] = ratio(Some(cap), current.get(Revenue), 1.0);
    out[PB] = ratio(Some(cap), equity, 1.0);
    out[FCF_YIELD] = ratio(fcf, Some(cap), 100.0);
    out[PRICE_FCF] = ratio(Some(cap), fcf, 1.0);
    out[PROFIT_MARGIN] = ratio(income, current.get(Revenue), 100.0);
    if let (Some(equity), Some(old)) = (equity, previous.get(Equity))
        && equity > 0.0
        && old > 0.0
    {
        out[ROE] = ratio(income, Some((equity + old) / 2.0), 100.0);
    }
    out[CURRENT_RATIO] = ratio(current.get(CurrentAssets), current.get(CurrentLiabilities), 1.0);
    out[INTEREST_COVERAGE] = ratio(current.get(Ebit), current.get(InterestExpense), 1.0);
    out[DEBT_EQUITY] = ratio(current.get(TotalDebt), equity, 1.0);
    let eps: Option<Vec<f64>> = (0..4).map(|i| in_year(annual, fiscal, year - i).get(EpsDiluted).filter(|&e| e > 0.0)).collect();
    if let (Some(pe), Some(eps)) = (out[PE], eps) {
        let growth = (numbers::pow(eps[0] / eps[3], 1.0 / 3.0) - 1.0) * 100.0;
        out[PEG] = ratio(Some(pe), Some(growth), 1.0);
    }
    if let Some(fcf) = fcf {
        out[FCF] = Some(fcf / 1e6);
    }
}

/// Operating income / revenue, when the revenue is positive
/// (`metrics.operating_margin`).
pub(crate) fn operating_margin(income: f64, revenue: f64) -> Option<f64> {
    (revenue > 0.0).then(|| income / revenue)
}

/// Sales × the mean operating margin of the 3 calendar years ending at
/// `fiscal` / `ev` × 100 − `ten_year` (`metrics.operating_yield_spread`).
fn operating_yield_spread(fiscal: Day, ev: f64, annual: &[(Day, LegacyValues)], ten_year: Option<f64>) -> Option<f64> {
    use LegacyField::*;
    let ten_year = ten_year.filter(|t| t.is_finite())?;
    let current = annual.iter().find(|(d, _)| *d == fiscal).map(|(_, v)| *v).unwrap_or_default();
    let sales = current.get(Revenue).filter(|&s| s > 0.0)?;
    if ev <= 0.0 {
        return None;
    }
    let year = fiscal.ymd().0;
    let margins: Option<Vec<f64>> = (year - 2..=year)
        .map(|y| {
            let report = in_year(annual, fiscal, y);
            operating_margin(report.get(OperatingIncome)?, report.get(Revenue)?)
        })
        .collect();
    let value = sales * numbers::mean(&margins?) / ev * 100.0 - ten_year;
    value.is_finite().then_some(value)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde::Deserialize;

    /// A case of `fixtures/numbers/peg.json`: the oracle's annual ratios of a
    /// 2023-12-31 report with one diluted EPS per year.
    #[derive(Deserialize)]
    struct PegCase {
        /// The market cap the ratios divide.
        market_cap: f64,
        /// The net income of the selected year.
        net_income: f64,
        /// Diluted EPS of the selected year, then of each of the three years before it.
        eps: [f64; 4],
        /// The P/E; `null` when the oracle leaves it out.
        pe: Option<f64>,
        /// The PEG; `null` when the oracle leaves it out.
        peg: Option<f64>,
    }

    #[test]
    fn peg_vectors() {
        let path = concat!(env!("CARGO_MANIFEST_DIR"), "/../../fixtures/numbers/peg.json");
        #[derive(Deserialize)]
        struct File {
            cases: Vec<PegCase>,
        }
        let file: File = serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap();
        assert!(!file.cases.is_empty());
        for case in file.cases {
            let annual: Vec<(Day, LegacyValues)> = (0..4)
                .rev()
                .map(|i| {
                    let mut values = [None; 11];
                    values[LegacyField::EpsDiluted as usize] = Some(case.eps[i]);
                    if i == 0 {
                        values[LegacyField::NetIncome as usize] = Some(case.net_income);
                    }
                    (Day::parse(&format!("{}-12-31", 2023 - i)).unwrap(), LegacyValues(values))
                })
                .collect();
            let mut out = [None; BUILTINS.len()];
            financial_values(Day::parse("2023-12-31").unwrap(), case.market_cap, &annual, &mut out);
            let bits = |v: Option<f64>| v.map(f64::to_bits);
            assert_eq!(bits(out[PE]), bits(case.pe), "pe of {:?}", case.eps);
            assert_eq!(bits(out[PEG]), bits(case.peg), "peg of {:?}", case.eps);
        }
    }
}
