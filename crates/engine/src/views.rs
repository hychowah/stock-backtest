//! The views of a result file: what a person or a script reads from a run,
//! derived from its stored rows alone with the oracle's arithmetic. No view
//! opens market data or selects again.
//!
//! - [`growth`]: each trial's growth of 1 by day, and [`band`] over the
//!   trials (`result_curves`).
//! - [`sectors`]: each trial's sector weights, and [`sector_spread`] over the
//!   trials (`result_sectors`).
//! - [`contributions`]: each period's equal-weight attribution
//!   (`contributions.js`).
//! - [`explore`]: one trial or all trials over a window of periods and a
//!   range of ranks (`result_exploration`).
//! - [`holdings`]: each holding with its weight, contribution and the value
//!   of each numeric source of its step trail.

use crate::portfolio;
use crate::results::{CurveRow, HoldingRow, PeriodRow, ResultFile};
use crate::run::rank_range;
use crate::schedule::Dates;
use crate::statistics::{self, Statistics, Summary};
use crate::strategy::Source;
use crate::Error;
use market_data::Day;
use serde::{Serialize, Serializer};
use std::collections::BTreeMap;

/// One trial's growth of 1 on each day it records: 1 at its start (cash
/// before the first trade) and at its first entry, then each curve row
/// compounded on the value at its period's entry.
#[derive(Debug)]
pub(crate) struct Curve {
    pub days: Vec<Day>,
    pub strategy: Vec<f64>,
    pub spy: Vec<f64>,
}

/// Every trial's curve, in trial order.
pub(crate) fn growth(file: &ResultFile) -> Result<Vec<Curve>, Error> {
    let (trials, periods, curve) = (file.trials()?, file.periods()?, file.curve()?);
    let curves = by_period(&periods, &curve, |c: &CurveRow| (c.trial, c.period));
    let mut out = Vec::with_capacity(trials.len());
    let mut at = 0;
    for summary in &trials {
        let mut c = Curve { days: Vec::new(), strategy: Vec::new(), spy: Vec::new() };
        let (mut growth, mut paired) = (1.0, 1.0);
        while at < periods.len() && periods[at].trial == summary.trial {
            if c.days.is_empty() {
                c.days.push(periods[at].entry);
                c.strategy.push(1.0);
                c.spy.push(1.0);
            }
            for row in curves[at] {
                c.days.push(row.point.day);
                c.strategy.push(growth * (1.0 + row.point.portfolio));
                c.spy.push(paired * (1.0 + row.point.spy));
            }
            (growth, paired) = (*c.strategy.last().unwrap(), *c.spy.last().unwrap());
            at += 1;
        }
        if summary.start < c.days[0] {
            c.days.insert(0, summary.start);
            c.strategy.insert(0, 1.0);
            c.spy.insert(0, 1.0);
        }
        out.push(c);
    }
    Ok(out)
}

/// The spread of the trials' curves on every day any trial records.
#[derive(Debug)]
pub(crate) struct Band {
    pub days: Vec<Day>,
    /// Over the trials' strategy values: `statistics.median`, `min`, `max`.
    pub median: Vec<f64>,
    pub lowest: Vec<f64>,
    pub highest: Vec<f64>,
    /// The median of the trials' SPY values.
    pub spy: Vec<f64>,
}

/// The band of `curves` (not empty). A trial holds its last value on a day
/// it does not record, and 1 before its first.
pub(crate) fn band(curves: &[Curve]) -> Band {
    let mut days: Vec<Day> = curves.iter().flat_map(|c| c.days.iter().copied()).collect();
    days.sort_unstable();
    days.dedup();
    let on = |c: &Curve, values: &[f64]| {
        let (mut at, mut value) = (0, 1.0);
        days.iter()
            .map(|&day| {
                while at < c.days.len() && c.days[at] <= day {
                    value = values[at];
                    at += 1;
                }
                value
            })
            .collect::<Vec<f64>>()
    };
    let strategy: Vec<Vec<f64>> = curves.iter().map(|c| on(c, &c.strategy)).collect();
    let spy: Vec<Vec<f64>> = curves.iter().map(|c| on(c, &c.spy)).collect();
    let mut band = Band { days: Vec::new(), median: Vec::new(), lowest: Vec::new(), highest: Vec::new(), spy: Vec::new() };
    for i in 0..days.len() {
        let day: Vec<f64> = strategy.iter().map(|values| values[i]).collect();
        let paired: Vec<f64> = spy.iter().map(|values| values[i]).collect();
        band.median.push(numbers::median(&day));
        band.lowest.push(numbers::min(&day));
        band.highest.push(numbers::max(&day));
        band.spy.push(numbers::median(&paired));
    }
    band.days = days;
    band
}

/// One sector over one trial's periods. A period's weight of a sector is
/// its holdings in the sector / the period's holdings; an empty period
/// weighs every sector 0.
#[derive(Debug)]
pub(crate) struct SectorShare {
    pub name: String,
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
pub(crate) fn sectors(file: &ResultFile) -> Result<Vec<Vec<SectorShare>>, Error> {
    let (periods, holdings) = (file.periods()?, file.holdings()?);
    let books = by_period(&periods, &holdings, |h: &HoldingRow| (h.trial, h.period));
    let mut out = Vec::new();
    let mut at = 0;
    for trial in periods.chunk_by(|a, b| a.trial == b.trial) {
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
                    name: name.to_string(),
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
/// without it).
#[derive(Debug)]
pub(crate) struct SectorSpread {
    pub name: String,
    pub mean: f64,
    pub minimum: f64,
    pub maximum: f64,
    /// The trials in which the sector has the highest mean, above 0; ties
    /// count for each sector.
    pub leading: u32,
}

/// The sectors of all trials, in name order. Every trial has a CAGR, so
/// every trial counts.
pub(crate) fn sector_spread(trials: &[Vec<SectorShare>]) -> Vec<SectorSpread> {
    let mut names: Vec<&str> = trials.iter().flatten().map(|s| s.name.as_str()).collect();
    names.sort_unstable();
    names.dedup();
    let mean = |trial: &[SectorShare], name: &str| trial.iter().find(|s| s.name == name).map(|s| s.mean);
    let highest = |trial: &[SectorShare]| numbers::max(&trial.iter().map(|s| s.mean).collect::<Vec<_>>());
    names
        .into_iter()
        .map(|name| {
            let weights: Vec<f64> = trials.iter().map(|t| mean(t, name).unwrap_or(0.0)).collect();
            let leading = trials.iter().filter(|t| mean(t, name).is_some_and(|m| m > 0.0 && m == highest(t))).count();
            SectorSpread {
                name: name.to_string(),
                mean: numbers::sum(&weights) / weights.len() as f64,
                minimum: numbers::min(&weights),
                maximum: numbers::max(&weights),
                leading: leading as u32,
            }
        })
        .collect()
}

/// One period's equal-weight attribution (`contributions.js` `analyze`).
/// A holding's contribution is its return / the period's holdings.
#[derive(Debug)]
pub(crate) struct Contributions {
    pub count: usize,
    /// The positive contributions, the negative ones as a positive number,
    /// and all of them, each added in rank order.
    pub gains: f64,
    pub losses: f64,
    pub net: f64,
    /// The ten highest contributions (symbol order among equal ones), added
    /// in that order, and the rest, added in rank order.
    pub top_total: f64,
    pub other_total: f64,
    pub top: Vec<String>,
}

/// Each period's attribution, with its trial and period, in key order.
pub(crate) fn contributions(file: &ResultFile) -> Result<Vec<(u32, u32, Contributions)>, Error> {
    let (periods, holdings) = (file.periods()?, file.holdings()?);
    let books = by_period(&periods, &holdings, |h: &HoldingRow| (h.trial, h.period));
    Ok(periods.iter().zip(books).map(|(p, held)| (p.trial, p.period, analyze(held))).collect())
}

/// The attribution of one period's holdings, given in rank order.
fn analyze(holdings: &[HoldingRow]) -> Contributions {
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
    let mut other_total = 0.0;
    for h in holdings {
        if !top.iter().any(|t| t.1 == h.symbol) {
            other_total += h.return_value / n;
        }
    }
    Contributions {
        count: holdings.len(),
        gains,
        losses,
        net,
        top_total: top.iter().fold(0.0, |s, t| s + t.0),
        other_total,
        top: top.into_iter().map(|t| t.1.to_string()).collect(),
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
#[derive(Debug, Serialize)]
pub struct Window {
    #[serde(serialize_with = "iso")]
    pub start: Day,
    #[serde(serialize_with = "iso")]
    pub end: Day,
    pub period_from: u32,
    pub period_to: u32,
    pub rank_from: u32,
    pub rank_to: u32,
    pub periods: u32,
}

/// One trial over the selected periods and ranks (`_reduce`). A period's
/// return is the mean of its holdings' returns within the ranks (Python's
/// `sum`), or its stored return when the ranks are the strategy's; SPY keeps
/// its stored return. The periods compound over the window: from the
/// trial's start when it starts at period 1, else from the entry of its
/// first period, to the exit of its last.
#[derive(Debug, Serialize)]
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
/// latest selected exit, in cash outside its own periods.
#[derive(Debug, Serialize)]
pub struct ExploredTrial {
    pub trial: u32,
    #[serde(serialize_with = "iso")]
    pub start: Day,
    /// The entry of the trial's first selected period.
    #[serde(serialize_with = "iso_option")]
    pub first_trade: Option<Day>,
    #[serde(serialize_with = "iso")]
    pub end: Day,
    pub cash_days: Option<i32>,
    pub periods: u32,
    pub cagr: f64,
    pub spy_cagr: f64,
    pub excess_cagr: f64,
    pub total_return: f64,
    pub growth: f64,
    pub spy_growth: f64,
    pub empty_periods: u32,
    pub short_periods: u32,
    /// The entries of the selected periods.
    #[serde(serialize_with = "iso_list")]
    pub dates: Vec<Day>,
    /// The exit of the last selected period, and the days from it to the
    /// window's end; `None` when the selection is the whole run, whose
    /// stored trials are given unchanged.
    #[serde(serialize_with = "iso_option")]
    pub last_exit: Option<Day>,
    pub final_cash_days: Option<i32>,
}

/// All trials of a random run over the selected periods and ranks.
#[derive(Debug)]
pub(crate) struct BatchExploration {
    /// The shared window.
    pub window: Window,
    /// The statistics over the explored trials.
    pub statistics: Statistics,
    pub trials: Vec<ExploredTrial>,
}

#[derive(Debug)]
pub(crate) enum Explored {
    Trial(Exploration),
    All(BatchExploration),
}

/// Explores the result. Fails, naming the setting, when the trial is not in
/// the result, `all` is asked of a run without random dates, a trial has
/// fewer periods than the window's last, or the ranks are outside the
/// strategy's (one sleeve: its last Rank step's; several: 1 to the sum of
/// their last Rank steps' sizes).
pub(crate) fn explore(file: &ResultFile, selection: &Selection) -> Result<Explored, Error> {
    let (strategy, schedule) = file.run()?;
    let (trials, periods, holdings) = (file.trials()?, file.periods()?, file.holdings()?);
    match selection.trial {
        Some(n) if n < 1 || n as usize > trials.len() => {
            return Err(Error::new(format!("the result has {} trials", trials.len()), "trial"));
        }
        None if !matches!(schedule.dates, Dates::Random { .. }) => {
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
    let (lower, upper) = rank_range(&strategy);
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
                    let mean = if returns.is_empty() { 0.0 } else { numbers::sum(&returns) / returns.len() as f64 };
                    (returns.len() as u32, mean)
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
                trial: s.trial,
                start: s.start,
                first_trade: s.first_trade,
                end: s.end,
                cash_days: s.cash_days,
                periods: s.periods,
                cagr: s.cagr,
                spy_cagr: s.spy_cagr,
                excess_cagr: s.excess_cagr(),
                total_return: s.total_return(),
                growth: s.growth,
                spy_growth: s.spy_growth,
                empty_periods: s.empty_periods,
                short_periods: s.short_periods,
                dates: s.dates.clone(),
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
        return Ok(Explored::All(BatchExploration { window, statistics: statistics::statistics(&summaries), trials: explored }));
    };
    let (summary, total, chosen) = &found[0];
    let (start, end) = (if first == 1 { summary.start } else { chosen[0].0.entry }, chosen[chosen.len() - 1].0.exit);
    let ([mut growth, mut spy_growth, mut cagr, mut spy_cagr], empty, short) = reduce(chosen, start, end);
    if first == 1 && last == *total && !narrowed && empty == 0 {
        // The whole trial: its stored totals.
        [growth, spy_growth, cagr, spy_cagr] = [summary.growth, summary.spy_growth, summary.cagr, summary.spy_cagr];
    }
    Ok(Explored::Trial(Exploration {
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

/// One holding of a result with what is derived from it.
#[derive(Debug)]
pub(crate) struct Joined {
    pub row: HoldingRow,
    /// 1 / the period's holdings, and the return × the weight in percentage
    /// points (`portfolio_results._holdings`).
    pub weight: f64,
    pub contribution: f64,
    /// The value of each of [`holdings`]' sources that its step trail
    /// reads, from its first picking sleeve that reads it.
    pub values: Vec<Option<f64>>,
}

/// The numeric sources of the strategy's steps (every source but a field),
/// each once, named `source:` and the source as the canonical form writes
/// it, in the order of their first step; and every holding, in key order.
pub(crate) fn holdings(file: &ResultFile) -> Result<(Vec<String>, Vec<Joined>), Error> {
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
        out.push(Joined { weight: 1.0 / n, contribution: row.return_value / n * 100.0, values, row });
    }
    Ok((sources, out))
}

pub(crate) fn iso<S: Serializer>(day: &Day, s: S) -> Result<S::Ok, S::Error> {
    s.collect_str(day)
}

fn iso_option<S: Serializer>(day: &Option<Day>, s: S) -> Result<S::Ok, S::Error> {
    match day {
        Some(day) => s.collect_str(day),
        None => s.serialize_none(),
    }
}

fn iso_list<S: Serializer>(days: &[Day], s: S) -> Result<S::Ok, S::Error> {
    s.collect_seq(days.iter().map(|d| d.to_string()))
}
