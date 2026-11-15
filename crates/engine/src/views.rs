//! The views of a result file: what a person or a script reads from a run,
//! derived from its stored rows alone with the oracle's arithmetic. No view
//! opens market data or selects again. Each view has one row type, shared,
//! like the stored rows of [`results`](crate::results), by the export, the
//! HTTP replies and the website's types; only the attribution's exported
//! row differs from the one the website reads.
//!
//! - [`statistics`]: the statistics over the trials, one row each.
//! - [`growth`]: each trial's growth of 1 by day, and [`band`] over the
//!   trials (`result_curves`).
//! - [`sectors`]: each trial's sector weights, and [`sector_spread`] over the
//!   trials (`result_sectors`).
//! - [`contributions`]: each period's equal-weight attribution
//!   (`contributions.js`): the top holdings with their contributions, which
//!   the exported [`ContributionRow`] joins into a text of symbols.
//! - [`explore`]: one trial or all trials over a window of periods and a
//!   range of ranks (`result_exploration`).
//! - [`holdings`]: each holding with its weight, contribution and the value
//!   of each numeric source of its step trail.

use crate::portfolio;
use crate::results::{CurveRow, HoldingRow, PeriodRow, ResultFile, TrialRow};
use crate::statistics::{self, Statistics, Summary};
use crate::strategy::Source;
use crate::Error;
use market_data::Day;
use serde::{Serialize, Serializer};
use std::collections::BTreeMap;
use ts_rs::TS;

/// One statistic over a run's trials (`statistics`).
#[derive(Clone, Debug, PartialEq, Serialize, TS)]
#[ts(export)]
pub struct StatisticRow {
    /// `<value>.<statistic>` of each distribution, such as `cagr.median`,
    /// or a count, such as `beat_spy`.
    pub statistic: String,
    pub value: Statistic,
}

/// A count, or a value of a distribution.
#[derive(Clone, Debug, PartialEq, Serialize, TS)]
#[serde(untagged)]
#[ts(export)]
pub enum Statistic {
    Count(usize),
    Value(f64),
}

/// The statistics over the result's trials, in name order.
pub fn statistics(file: &ResultFile) -> Result<Vec<StatisticRow>, Error> {
    Ok(named(&statistics::statistics(&file.summaries()?)))
}

/// The statistics by name, in name order: the counts, and `<value>.n` and
/// `<value>.<statistic>` of each distribution.
fn named(s: &Statistics) -> Vec<StatisticRow> {
    // Every trial has a CAGR (see `Statistics`): all are valid.
    let counts = [
        ("completed", s.completed),
        ("valid", s.completed),
        ("incomplete", 0),
        ("beat_spy", s.beat_spy),
        ("unique_schedules", s.unique_schedules),
    ];
    let row = |statistic: String, value| StatisticRow { statistic, value };
    let mut rows: Vec<StatisticRow> = counts.into_iter().map(|(name, n)| row(name.to_string(), Statistic::Count(n))).collect();
    let distributions =
        [("cagr", &s.cagr), ("spy_cagr", &s.spy_cagr), ("excess_cagr", &s.excess_cagr), ("total_return", &s.total_return), ("growth", &s.growth)];
    for (field, d) in distributions {
        let values = [
            ("mean", d.mean),
            ("median", d.median),
            ("p10", d.p10),
            ("p25", d.p25),
            ("p75", d.p75),
            ("p90", d.p90),
            ("min", d.min),
            ("max", d.max),
            ("stddev", d.stddev),
        ];
        rows.push(row(format!("{field}.n"), Statistic::Count(d.n)));
        rows.extend(values.into_iter().map(|(statistic, value)| row(format!("{field}.{statistic}"), Statistic::Value(value))));
    }
    rows.sort_by(|a, b| a.statistic.cmp(&b.statistic));
    rows
}

/// One day of one trial's growth of 1 (`growth`).
#[derive(Clone, Debug, PartialEq, Serialize, TS)]
#[ts(export)]
pub struct GrowthRow {
    pub trial: u32,
    pub day: Day,
    pub strategy: f64,
    pub spy: f64,
}

/// Every trial's curve, in trial order: 1 at its start (cash before the
/// first trade) and at its first entry, then each curve row compounded on
/// the value at its period's entry.
pub fn growth(file: &ResultFile) -> Result<Vec<Vec<GrowthRow>>, Error> {
    let (trials, periods, curve) = (file.summaries()?, file.periods()?, file.curve()?);
    let curves = by_period(&periods, &curve, |c: &CurveRow| (c.trial, c.period));
    let mut out = Vec::with_capacity(trials.len());
    let mut at = 0;
    for summary in &trials {
        let trial = summary.trial;
        let mut c: Vec<GrowthRow> = Vec::new();
        let (mut growth, mut paired) = (1.0, 1.0);
        while at < periods.len() && periods[at].trial == trial {
            if c.is_empty() {
                c.push(GrowthRow { trial, day: periods[at].entry, strategy: 1.0, spy: 1.0 });
            }
            for row in curves[at] {
                c.push(GrowthRow { trial, day: row.day, strategy: growth * (1.0 + row.portfolio), spy: paired * (1.0 + row.spy) });
            }
            let last = c.last().unwrap();
            (growth, paired) = (last.strategy, last.spy);
            at += 1;
        }
        if summary.start < c[0].day {
            c.insert(0, GrowthRow { trial, day: summary.start, strategy: 1.0, spy: 1.0 });
        }
        out.push(c);
    }
    Ok(out)
}

/// The spread of the trials' curves on one day any trial records (`band`).
#[derive(Clone, Debug, PartialEq, Serialize, TS)]
#[ts(export)]
pub struct BandRow {
    pub day: Day,
    /// The median, lowest and highest of the trials' strategy values.
    pub median: f64,
    pub lowest: f64,
    pub highest: f64,
    /// The median of the trials' SPY values.
    pub spy: f64,
}

/// The band of `curves` (not empty), by day. A trial holds its last value on
/// a day it does not record, and 1 before its first.
pub fn band(curves: &[Vec<GrowthRow>]) -> Vec<BandRow> {
    let mut days: Vec<Day> = curves.iter().flatten().map(|row| row.day).collect();
    days.sort_unstable();
    days.dedup();
    let on = |c: &[GrowthRow], value: fn(&GrowthRow) -> f64| {
        let (mut at, mut last) = (0, 1.0);
        days.iter()
            .map(|&day| {
                while at < c.len() && c[at].day <= day {
                    last = value(&c[at]);
                    at += 1;
                }
                last
            })
            .collect::<Vec<f64>>()
    };
    let strategy: Vec<Vec<f64>> = curves.iter().map(|c| on(c, |row| row.strategy)).collect();
    let spy: Vec<Vec<f64>> = curves.iter().map(|c| on(c, |row| row.spy)).collect();
    days.iter()
        .enumerate()
        .map(|(i, &day)| {
            let values: Vec<f64> = strategy.iter().map(|values| values[i]).collect();
            let paired: Vec<f64> = spy.iter().map(|values| values[i]).collect();
            BandRow {
                day,
                median: numbers::median(&values),
                lowest: numbers::min(&values),
                highest: numbers::max(&values),
                spy: numbers::median(&paired),
            }
        })
        .collect()
}

/// One sector over one trial's periods (`sectors`). A period's weight of a
/// sector is its holdings in the sector / the period's holdings; an empty
/// period weighs every sector 0.
#[derive(Clone, Debug, PartialEq, Serialize, TS)]
#[ts(export)]
pub struct SectorShare {
    pub trial: u32,
    pub sector: String,
    /// The mean weight over all the trial's periods.
    pub mean: f64,
    /// The lowest and highest weight, counting 0 for the periods before the
    /// sector's first one.
    pub minimum: f64,
    pub maximum: f64,
    /// The periods that hold the sector.
    pub present: u32,
}

/// Each trial's sectors, in trial order; a trial's in name order.
pub fn sectors(file: &ResultFile) -> Result<Vec<Vec<SectorShare>>, Error> {
    let (periods, holdings) = (file.periods()?, file.holdings()?);
    let books = by_period(&periods, &holdings, |h: &HoldingRow| (h.trial, h.period));
    let mut out = Vec::new();
    let mut at = 0;
    for trial in periods.chunk_by(|a, b| a.trial == b.trial) {
        let number = trial[0].trial;
        // name → (total, minimum, maximum, present)
        let mut found: BTreeMap<&str, (f64, f64, f64, u32)> = BTreeMap::new();
        for (count, period) in trial.iter().enumerate() {
            let mut counts: BTreeMap<&str, u32> = BTreeMap::new();
            for h in books[at] {
                *counts.entry(&h.sector).or_default() += 1;
            }
            at += 1;
            for name in counts.keys() {
                // A sector first held now starts at 0 when an earlier period lacked it.
                found.entry(name).or_insert((0.0, if count > 0 { 0.0 } else { f64::INFINITY }, 0.0, 0));
            }
            for (name, (total, minimum, maximum, present)) in &mut found {
                let weight = counts.get(name).map_or(0.0, |&n| f64::from(n) / f64::from(period.names));
                // Python's min and max keep the first of equal values.
                *minimum = if weight < *minimum { weight } else { *minimum };
                *maximum = if weight > *maximum { weight } else { *maximum };
                *total += weight;
                *present += u32::from(weight > 0.0);
            }
        }
        let count = trial.len() as f64;
        out.push(
            found
                .into_iter()
                .map(|(name, (total, minimum, maximum, present))| SectorShare {
                    trial: number,
                    sector: name.to_string(),
                    mean: total / count,
                    minimum,
                    maximum,
                    present,
                })
                .collect(),
        );
    }
    Ok(out)
}

/// One sector over all trials, from each trial's mean weight (0 in a trial
/// without it): the `sectors` rows of trial `all`.
#[derive(Clone, Debug, PartialEq, Serialize, TS)]
#[ts(export)]
pub struct SectorSpread {
    pub sector: String,
    pub mean: f64,
    pub minimum: f64,
    pub maximum: f64,
    /// The trials in which the sector has the highest mean, above 0; ties
    /// count for each sector.
    pub leading: u32,
}

/// The sectors of all trials, in name order. Every trial has a CAGR, so
/// every trial counts.
pub fn sector_spread(trials: &[Vec<SectorShare>]) -> Vec<SectorSpread> {
    let mut names: Vec<&str> = trials.iter().flatten().map(|s| s.sector.as_str()).collect();
    names.sort_unstable();
    names.dedup();
    let mean = |trial: &[SectorShare], name: &str| trial.iter().find(|s| s.sector == name).map(|s| s.mean);
    let highest = |trial: &[SectorShare]| numbers::max(&trial.iter().map(|s| s.mean).collect::<Vec<_>>());
    names
        .into_iter()
        .map(|name| {
            let weights: Vec<f64> = trials.iter().map(|t| mean(t, name).unwrap_or(0.0)).collect();
            let leading = trials.iter().filter(|t| mean(t, name).is_some_and(|m| m > 0.0 && m == highest(t))).count();
            SectorSpread {
                sector: name.to_string(),
                mean: numbers::sum(&weights) / weights.len() as f64,
                minimum: numbers::min(&weights),
                maximum: numbers::max(&weights),
                leading: leading as u32,
            }
        })
        .collect()
}

/// One period's gains and losses split among its top ten holdings and the
/// rest, as fractions of the portfolio. A holding's contribution is its
/// return / the period's holdings, all holdings weighing the same.
#[derive(Clone, Debug, PartialEq, Serialize, TS)]
#[ts(export)]
pub struct Attribution {
    pub trial: u32,
    pub period: u32,
    pub count: usize,
    /// The positive contributions, the negative ones as a positive number,
    /// and all of them, each added in rank order.
    pub gains: f64,
    pub losses: f64,
    pub net: f64,
    /// The ten highest contributions (symbol order among equal ones), and
    /// their sum, added in that order.
    pub top: Vec<Contributor>,
    pub top_total: f64,
    /// The other holdings' contributions, added in rank order: all of them,
    /// the positive ones, and the negative ones as a positive number.
    pub other_total: f64,
    pub other_gains: f64,
    pub other_losses: f64,
}

#[derive(Clone, Debug, PartialEq, Serialize, TS)]
pub struct Contributor {
    pub symbol: String,
    /// A fraction of the portfolio; times 100 it is the holdings'
    /// percentage points.
    pub contribution: f64,
}

/// An [`Attribution`] as the exported table `contributions` has it: the top
/// holdings' symbols joined by spaces, without the other gains and losses.
#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct ContributionRow {
    pub trial: u32,
    pub period: u32,
    pub count: usize,
    pub gains: f64,
    pub losses: f64,
    pub net: f64,
    pub top_total: f64,
    pub other_total: f64,
    pub top: String,
}

impl From<Attribution> for ContributionRow {
    fn from(a: Attribution) -> ContributionRow {
        let top = a.top.iter().map(|c| c.symbol.as_str()).collect::<Vec<_>>().join(" ");
        let (trial, period, count, gains, losses, net) = (a.trial, a.period, a.count, a.gains, a.losses, a.net);
        ContributionRow { trial, period, count, gains, losses, net, top_total: a.top_total, other_total: a.other_total, top }
    }
}

/// Each period's attribution, in key order.
pub fn contributions(file: &ResultFile) -> Result<Vec<Attribution>, Error> {
    let (periods, holdings) = (file.periods()?, file.holdings()?);
    let books = by_period(&periods, &holdings, |h: &HoldingRow| (h.trial, h.period));
    Ok(periods.iter().zip(books).map(|(p, held)| analyze(p, held)).collect())
}

/// The attribution of one period's holdings, given in rank order.
fn analyze(period: &PeriodRow, holdings: &[HoldingRow]) -> Attribution {
    let n = holdings.len() as f64;
    // Math.max(0, x) is +0 for any x that is not above 0.
    let positive = |x: f64| if x > 0.0 { x } else { 0.0 };
    let (mut gains, mut losses, mut net) = (0.0, 0.0, 0.0);
    let mut top: Vec<(f64, &str)> = Vec::new();
    for h in holdings {
        let c = h.return_value / n;
        gains += positive(c);
        losses += positive(-c);
        net += c;
        top.push((c, &h.symbol));
    }
    // `b.contribution - a.contribution || symbol order`: a total order, so
    // keeping the first ten of each sorted prefix keeps the first ten of all.
    top.sort_by(|a, b| b.0.partial_cmp(&a.0).expect("finite contributions").then(a.1.cmp(b.1)));
    top.truncate(10);
    let (mut other_total, mut other_gains, mut other_losses) = (0.0, 0.0, 0.0);
    for h in holdings {
        if !top.iter().any(|t| t.1 == h.symbol) {
            let c = h.return_value / n;
            other_total += c;
            other_gains += positive(c);
            other_losses += positive(-c);
        }
    }
    Attribution {
        trial: period.trial,
        period: period.period,
        count: holdings.len(),
        gains,
        losses,
        net,
        top_total: top.iter().fold(0.0, |s, t| s + t.0),
        top: top.iter().map(|&(contribution, symbol)| Contributor { symbol: symbol.to_string(), contribution }).collect(),
        other_total,
        other_gains,
        other_losses,
    }
}

/// The rows of each period, in period order, from rows in the same
/// (trial, period) order.
fn by_period<'r, R>(periods: &[PeriodRow], rows: &'r [R], key: impl Fn(&R) -> (u32, u32)) -> Vec<&'r [R]> {
    let mut at = 0;
    periods
        .iter()
        .map(|p| {
            let start = at;
            while at < rows.len() && key(&rows[at]) == (p.trial, p.period) {
                at += 1;
            }
            &rows[start..at]
        })
        .collect()
}

/// What to explore: one trial (`None`: all trials of a random run), the
/// periods `from`–`to` of each trial and the ranks `from`–`to`, counted
/// from 1.
#[derive(Debug)]
pub struct Selection {
    pub trial: Option<u32>,
    pub periods: (u32, u32),
    pub ranks: (u32, u32),
}

/// The days an exploration covers and what it selects.
#[derive(Debug, Serialize, TS)]
pub struct Window {
    pub start: Day,
    pub end: Day,
    pub period_from: u32,
    pub period_to: u32,
    pub rank_from: u32,
    pub rank_to: u32,
    pub periods: u32,
}

/// One trial over the selected periods and ranks. A period's return is the
/// mean of its holdings' returns within the ranks, or its stored return when
/// the ranks are the strategy's; SPY keeps its stored return. The periods compound over the window: from the
/// trial's start when it starts at period 1, else from the entry of its
/// first period, to the exit of its last.
#[derive(Debug, Serialize, TS)]
#[ts(export)]
pub struct Exploration {
    #[serde(flatten)]
    pub window: Window,
    /// Periods without a holding in the ranks, and with fewer than the
    /// ranks hold.
    pub empty: u32,
    pub short: u32,
    /// The trial's cash days when the window starts at period 1, else 0.
    pub cash_days: i32,
    pub total_return: f64,
    pub spy_total_return: f64,
    pub growth: f64,
    pub spy_growth: f64,
    pub cagr: f64,
    pub spy_cagr: f64,
}

/// One trial of a random run over the selected periods and ranks, on the
/// window shared by all trials: from the earliest selected entry to the
/// latest selected exit, in cash outside its own periods: a trial row whose
/// dates are the entries of the selected periods and whose first trade is
/// the first of them.
#[derive(Debug, Serialize, TS)]
#[ts(export)]
pub struct ExploredTrial {
    #[serde(flatten)]
    pub row: TrialRow,
    /// The exit of the last selected period, and the days from it to the
    /// window's end; `None` when the selection is the whole run, whose
    /// stored trials are given unchanged.
    pub last_exit: Option<Day>,
    pub final_cash_days: Option<i32>,
}

/// One trial's exploration, or all trials': the window, the statistics as
/// the `statistics` table has them, and each trial.
#[derive(Debug, Serialize, TS)]
#[serde(untagged)]
#[ts(export)]
pub enum ExploreReply {
    Trial(Exploration),
    All {
        #[serde(flatten)]
        window: Window,
        statistics: Vec<StatisticRow>,
        trials: Vec<ExploredTrial>,
    },
}

/// Explores the result (`result_exploration`). Fails, naming the setting,
/// when the periods or the ranks are not `A-B` with 1 ≤ A ≤ B, the trial is
/// not in the result, `all` is asked of a run without random dates, a trial
/// has fewer periods than the window's last, or the ranks are outside the
/// strategy's (one sleeve: its last Rank step's; several: 1 to the sum of
/// their last Rank steps' sizes).
pub fn explore(file: &ResultFile, selection: &Selection) -> Result<ExploreReply, Error> {
    for (place, (from, to)) in [("periods", selection.periods), ("ranks", selection.ranks)] {
        if !(1 <= from && from <= to) {
            return Err(Error::new(format!("{from}-{to} is not a range: use A-B with 1 ≤ A ≤ B, such as 2-5"), place));
        }
    }
    let (strategy, schedule) = file.run()?;
    let (trials, periods, holdings) = (file.summaries()?, file.periods()?, file.holdings()?);
    match selection.trial {
        Some(n) if n < 1 || n as usize > trials.len() => {
            return Err(Error::new(format!("the result has {} trials", trials.len()), "trial"));
        }
        None if schedule.trials.is_none() => {
            return Err(Error::new("all trials are explored only in a run of random dates", "trial"));
        }
        _ => {}
    }
    let books = by_period(&periods, &holdings, |h: &HoldingRow| (h.trial, h.period));
    let (first, last) = selection.periods;
    // Each explored trial with its selected periods and their holdings.
    let mut found = Vec::new();
    let mut at = 0;
    for summary in &trials {
        let begin = at;
        while at < periods.len() && periods[at].trial == summary.trial {
            at += 1;
        }
        if selection.trial.is_some_and(|n| n != summary.trial) {
            continue;
        }
        let total = (at - begin) as u32;
        if last > total {
            return Err(Error::new(format!("trial {} has {total} periods", summary.trial), "periods"));
        }
        let chosen: Vec<(&PeriodRow, &[HoldingRow])> =
            (begin + first as usize - 1..begin + last as usize).map(|i| (&periods[i], books[i])).collect();
        found.push((summary, total, chosen));
    }
    let (lower, upper) = strategy.ranks();
    if !(lower <= selection.ranks.0 && selection.ranks.1 <= upper) {
        return Err(Error::new(format!("the strategy's ranks are {lower}-{upper}"), "ranks"));
    }
    let narrowed = selection.ranks != (lower, upper);
    let reduce = |chosen: &[(&PeriodRow, &[HoldingRow])], start: Day, end: Day| {
        let (mut empty, mut short) = (0, 0);
        let returns: Vec<(f64, f64)> = chosen
            .iter()
            .map(|(period, held)| {
                let (count, portfolio) = if narrowed {
                    let returns: Vec<f64> = held
                        .iter()
                        .filter(|h| (selection.ranks.0..=selection.ranks.1).contains(&h.rank))
                        .map(|h| h.return_value)
                        .collect();
                    (returns.len() as u32, numbers::mean_return(&returns))
                } else {
                    (period.names, period.portfolio)
                };
                empty += u32::from(count == 0);
                short += u32::from(count < selection.ranks.1 - selection.ranks.0 + 1);
                (portfolio, period.spy)
            })
            .collect();
        (portfolio::compound(returns.into_iter(), start, end), empty, short)
    };
    if selection.trial.is_none() {
        let start = found.iter().map(|(s, _, chosen)| if first == 1 { s.start } else { chosen[0].0.entry }).min().unwrap();
        let end = found.iter().map(|(_, _, chosen)| chosen[chosen.len() - 1].0.exit).max().unwrap();
        let whole = found.iter().all(|(_, total, _)| first == 1 && last == *total) && !narrowed;
        let (mut summaries, mut explored) = (Vec::new(), Vec::new());
        for (summary, _, chosen) in &found {
            let (entry, exit) = (chosen[0].0.entry, chosen[chosen.len() - 1].0.exit);
            let s = if whole {
                (*summary).clone()
            } else {
                let ([growth, spy_growth, cagr, spy_cagr], empty, short) = reduce(chosen, start, end);
                Summary {
                    trial: summary.trial,
                    dates: chosen.iter().map(|(p, _)| p.entry).collect(),
                    start,
                    first_trade: Some(entry),
                    end,
                    cash_days: Some(entry.0 - start.0),
                    periods: last - first + 1,
                    growth,
                    spy_growth,
                    cagr,
                    spy_cagr,
                    empty_periods: empty,
                    short_periods: short,
                }
            };
            explored.push(ExploredTrial {
                row: TrialRow::new(&s),
                last_exit: (!whole).then_some(exit),
                final_cash_days: (!whole).then_some(end.0 - exit.0),
            });
            summaries.push(s);
        }
        let window = Window {
            start,
            end,
            period_from: first,
            period_to: last,
            rank_from: selection.ranks.0,
            rank_to: selection.ranks.1,
            periods: last - first + 1,
        };
        return Ok(ExploreReply::All { window, statistics: named(&statistics::statistics(&summaries)), trials: explored });
    };
    let (summary, total, chosen) = &found[0];
    let (start, end) = (if first == 1 { summary.start } else { chosen[0].0.entry }, chosen[chosen.len() - 1].0.exit);
    let ([mut growth, mut spy_growth, mut cagr, mut spy_cagr], empty, short) = reduce(chosen, start, end);
    if first == 1 && last == *total && !narrowed && empty == 0 {
        // The whole trial: its stored totals.
        [growth, spy_growth, cagr, spy_cagr] = [summary.growth, summary.spy_growth, summary.cagr, summary.spy_cagr];
    }
    Ok(ExploreReply::Trial(Exploration {
        window: Window {
            start,
            end,
            period_from: first,
            period_to: last,
            rank_from: selection.ranks.0,
            rank_to: selection.ranks.1,
            periods: last - first + 1,
        },
        empty,
        short,
        cash_days: if first == 1 { summary.cash_days.unwrap_or(0) } else { 0 },
        total_return: growth - 1.0,
        spy_total_return: spy_growth - 1.0,
        growth,
        spy_growth,
        cagr,
        spy_cagr,
    }))
}

/// One holding with what is derived from it (`holdings`): its stored row,
/// its weight and contribution, and the value of each numeric source of its
/// step trail as a field `source:<source>`. Its TypeScript type is written
/// here because those field names depend on the strategy.
#[derive(Clone, Debug, PartialEq, Serialize, TS)]
#[ts(
    export,
    type = "import(\"./HoldingRow.ts\").HoldingRow & { weight: number; /** Percentage points. */ contribution: number; [source: `source:${string}`]: number | null }"
)]
pub struct JoinedHolding {
    #[serde(flatten)]
    pub row: HoldingRow,
    /// 1 / the period's holdings.
    pub weight: f64,
    /// The return × the weight, in percentage points.
    pub contribution: f64,
    #[serde(flatten)]
    pub sources: SourceValues,
}

/// The value of each of [`holdings`]' sources that a holding's step trail
/// reads, from its first picking sleeve that reads it, by source name in
/// the sources' order.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct SourceValues(pub Vec<(String, Option<f64>)>);

impl Serialize for SourceValues {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.collect_map(self.0.iter().map(|(name, value)| (name, value)))
    }
}

/// The numeric sources of the strategy's steps (every source but a field),
/// each once, named `source:` and the source as the canonical form writes
/// it, in the order of their first step; and every holding, in key order.
pub fn holdings(file: &ResultFile) -> Result<(Vec<String>, Vec<JoinedHolding>), Error> {
    let (strategy, _) = file.run()?;
    let mut sources: Vec<String> = Vec::new();
    // column[sleeve][step]: the source's position in `sources`.
    let column: Vec<Vec<Option<usize>>> = strategy
        .sleeves()
        .iter()
        .map(|sleeve| {
            sleeve
                .steps
                .iter()
                .map(|step| {
                    let source = step.source();
                    if matches!(source, Source::Field(_)) {
                        return None;
                    }
                    let name = format!("source:{}", strategy.written(source));
                    Some(sources.iter().position(|s| *s == name).unwrap_or_else(|| {
                        sources.push(name);
                        sources.len() - 1
                    }))
                })
                .collect()
        })
        .collect();
    let (periods, rows, steps) = (file.periods()?, file.holdings()?, file.steps()?);
    let names: BTreeMap<(u32, u32), f64> = periods.iter().map(|p| ((p.trial, p.period), f64::from(p.names))).collect();
    let mut out = Vec::with_capacity(rows.len());
    let mut at = 0;
    for row in rows {
        let mut values = vec![None; sources.len()];
        while at < steps.len() && (steps[at].trial, steps[at].period, steps[at].rank) == (row.trial, row.period, row.rank) {
            let s = &steps[at];
            if let Some(i) = column[s.sleeve as usize - 1][s.step as usize - 1] {
                values[i] = values[i].or(s.value);
            }
            at += 1;
        }
        let n = names[&(row.trial, row.period)];
        let sources = SourceValues(sources.iter().cloned().zip(values).collect());
        out.push(JoinedHolding { weight: 1.0 / n, contribution: row.return_value / n * 100.0, sources, row });
    }
    Ok((sources, out))
}
