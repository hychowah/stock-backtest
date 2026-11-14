//! A run: every strategy of a batch on one plan, calculated day-major.

use crate::portfolio;
use crate::schedule::{Period, Plan};
use crate::selection::{Trail, select};
use crate::statistics::Summary;
use crate::strategy::{Step, Strategy};
use crate::values::DayValues;
use crate::Error;
use market_data::{CompanyId, Day, Market, MarketData, Screen};
use rayon::prelude::*;
use serde::Serialize;
use std::sync::Arc;

/// This program and its version, as result files and exports record it.
pub(crate) const PROGRAM: &str = concat!("bt ", env!("CARGO_PKG_VERSION"));

/// One strategy's finished run.
#[derive(Debug)]
pub(crate) struct Run {
    /// The strategy's canonical form and identity.
    pub strategy: String,
    pub identity: String,
    pub market: Market,
    /// The prepared generation the run read, its as-of time, and this program.
    pub generation: u64,
    pub as_of: String,
    pub program: String,
    /// The window's first session and the final mark; whether the last
    /// period of each trial ends on a mark to date ([`Plan::final_mark`]).
    pub window: (Day, Day),
    pub final_mark: bool,
    /// In the order of their numbers.
    pub trials: Vec<TrialRun>,
}

#[derive(Debug)]
pub(crate) struct TrialRun {
    pub summary: Summary,
    /// Trials that trade on the same entry and exit share the period.
    pub periods: Vec<Arc<PeriodRun>>,
}

/// One period of a trial.
#[derive(Debug)]
pub(crate) struct PeriodRun {
    pub entry: Day,
    pub exit: Day,
    /// The equally weighted return of the holdings, 0 without one.
    pub portfolio: f64,
    /// SPY's return over the period.
    pub spy: f64,
    /// In rank order.
    pub holdings: Vec<Holding>,
    /// One row for each session after the entry through the exit.
    pub curve: Vec<Point>,
}

/// A held company: its candidate row on the entry day, its exit and its
/// place in the selection.
#[derive(Debug)]
pub(crate) struct Holding {
    pub(crate) company: CompanyId,
    pub symbol: String,
    pub name: String,
    pub sector: String,
    pub exchange: String,
    pub candidate_rank: Option<u32>,
    pub fiscal: Day,
    /// The day of the entry close, and that close in US dollars.
    pub entry: Day,
    pub(crate) price: f64,
    /// The day of the exit close.
    pub exit: Day,
    pub market_cap: f64,
    pub enterprise_value: f64,
    pub ebitda: f64,
    pub ebitda_yield: f64,
    pub ev_ebitda: f64,
    pub spread: f64,
    /// The exit close / the entry close − 1, in US dollars.
    pub return_value: f64,
    pub status: Status,
    pub rank: u32,
    pub ranking_value: f64,
    /// Each picking sleeve's step trail, in sleeve order.
    pub sleeves: Vec<Trail>,
}

/// How a holding exited.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum Status {
    /// At the last close on or before the exit day, at most 10 days earlier.
    Scheduled,
    /// No close in those 10 days: at the last earlier one.
    LastAvailable,
    /// A scheduled exit of the last period, when the plan ends on a mark.
    Marked,
}

impl Status {
    /// The oracle's text.
    pub(crate) fn text(self) -> &'static str {
        match self {
            Status::Scheduled => "Scheduled exit",
            Status::LastAvailable => "Last available price",
            Status::Marked => "Marked to date",
        }
    }
}

/// One day of a period's curve: returns to date.
#[derive(Clone, Copy, Debug, PartialEq)]
pub(crate) struct Point {
    pub day: Day,
    pub portfolio: f64,
    pub spy: f64,
}

/// Every strategy on one plan, in order. Each entry day's candidates are
/// calculated once, in parallel over days, used for every trial and every
/// strategy that trades on that day, and dropped when that day's periods are
/// selected and valued; results do not depend on the order of the threads.
///
/// A run stops at the oracle's run-stopping errors: a selected company
/// without a valid exit, and SPY without a close at a period's entry or exit.
/// The error is the first one taken by strategy, then trial, then period; it
/// comes with the strategy's position, and its place names the market,
/// trial, entry day and, for a company, the symbol.
pub(crate) fn run(data: &MarketData, plan: &Plan, strategies: &[Strategy]) -> Result<Vec<Run>, (usize, Error)> {
    let sessions = data.sessions();
    let (start, end) = plan.window();
    let marked = |exit: Day| plan.final_mark() && exit == end;
    let days = plan.exits_by_entry();
    // valued[day][strategy][exit]
    let valued: Vec<Vec<Vec<Result<Arc<PeriodRun>, Error>>>> = days
        .par_iter()
        .map(|(entry, exits)| {
            let values = DayValues::new(data, *entry, Screen::Dated);
            strategies
                .iter()
                .map(|strategy| {
                    exits
                        .iter()
                        .map(|&exit| {
                            let picks = select(strategy, &values, Some(exit))?;
                            let period = Period { entry: *entry, exit };
                            portfolio::value(data, sessions, picks, period, marked(exit)).map(Arc::new)
                        })
                        .collect()
                })
                .collect()
        })
        .collect();
    let manifest = data.manifest();
    let mut runs = Vec::with_capacity(strategies.len());
    for (s, strategy) in strategies.iter().enumerate() {
        let (from, to) = rank_range(strategy);
        let requested = (to - from + 1) as usize;
        let mut trials = Vec::with_capacity(plan.trials().len());
        for (trial, number) in plan.trials().iter().zip(1..) {
            let mut periods = Vec::with_capacity(trial.periods.len());
            for period in &trial.periods {
                let at = days.partition_point(|(d, _)| *d < period.entry);
                let exit = days[at].1.binary_search(&period.exit).expect("a planned exit");
                let found = valued[at][s][exit].as_ref().map_err(|e| {
                    let mut place = format!("{}, trial {number}, {}", manifest.market.id(), period.entry);
                    if !e.place.is_empty() {
                        place = format!("{place}, {}", e.place);
                    }
                    (s, Error::new(e.message.clone(), place))
                })?;
                periods.push(Arc::clone(found));
            }
            let [growth, spy_growth, cagr, spy_cagr] = portfolio::compound(periods.iter().map(|p| (p.portfolio, p.spy)), start, end);
            let count = |short: &dyn Fn(usize) -> bool| periods.iter().filter(|p| short(p.holdings.len())).count() as u32;
            let summary = Summary {
                trial: number,
                dates: periods.iter().map(|p| p.entry).collect(),
                start,
                first_trade: trial.first_trade,
                end,
                cash_days: trial.cash_days,
                periods: periods.len() as u32,
                growth,
                spy_growth,
                cagr,
                spy_cagr,
                empty_periods: count(&|names| names == 0),
                short_periods: count(&|names| names < requested),
            };
            trials.push(TrialRun { summary, periods });
        }
        runs.push(Run {
            strategy: strategy.canonical().to_string(),
            identity: strategy.identity(),
            market: manifest.market,
            generation: manifest.generation,
            as_of: manifest.as_of.clone(),
            program: PROGRAM.to_string(),
            window: (start, end),
            final_mark: plan.final_mark(),
            trials,
        });
    }
    Ok(runs)
}

/// The ranks a period's holdings can have (`selection.rank_range`): one
/// sleeve, its last Rank step's; several, 1 to the sum of the sizes of their
/// last Rank steps.
pub(crate) fn rank_range(strategy: &Strategy) -> (u32, u32) {
    let last = |steps: &[Step]| match steps.iter().rev().find(|s| matches!(s, Step::Rank { .. })) {
        Some(&Step::Rank { from, to, .. }) => (from, to),
        _ => panic!("a sleeve has a Rank step"),
    };
    match strategy.sleeves() {
        [one] => last(&one.steps),
        several => (1, several.iter().map(|s| last(&s.steps)).map(|(from, to)| to - from + 1).sum()),
    }
}

/// One pick of the latest screen.
#[derive(Debug, Serialize)]
pub struct Screened {
    pub rank: u32,
    pub symbol: String,
    pub name: String,
    pub sector: String,
    /// The value of the first picking sleeve's last Rank step.
    pub ranking_value: f64,
    /// Each picking sleeve's step trail, in sleeve order; written as the
    /// `steps` rows of a result: sleeve and step from 1, value, step_rank.
    #[serde(rename = "steps", serialize_with = "trail_rows")]
    pub sleeves: Vec<Trail>,
}

fn trail_rows<S: serde::Serializer>(sleeves: &[Trail], s: S) -> Result<S::Ok, S::Error> {
    #[derive(Serialize)]
    struct Row {
        sleeve: u32,
        step: u32,
        value: Option<f64>,
        step_rank: Option<u32>,
    }
    s.collect_seq(sleeves.iter().flat_map(|trail| {
        (1..).zip(&trail.steps).map(|(step, o)| Row { sleeve: trail.sleeve as u32 + 1, step, value: o.value, step_rank: o.rank })
    }))
}

/// The strategy's picks on the market's last session, as the oracle's
/// latest screen: listed companies entering at that session's close, with no
/// exit. Gives the session and the picks in rank order. An error's place
/// names the market and the session.
pub(crate) fn screen(data: &MarketData, strategy: &Strategy) -> Result<(Day, Vec<Screened>), Error> {
    let market = data.manifest().market;
    let &day = data.sessions().last().ok_or_else(|| Error::new("the market has no session", market.id()))?;
    let values = DayValues::new(data, day, Screen::Latest);
    let picks = select(strategy, &values, None).map_err(|e| {
        let place = format!("{}, latest {day}", market.id());
        Error::new(e.message, if e.place.is_empty() { place } else { format!("{place}, {}", e.place) })
    })?;
    let companies = data.companies();
    let picks = picks
        .into_iter()
        .map(|pick| Screened {
            rank: pick.rank,
            symbol: companies.symbol(pick.candidate.company).to_string(),
            name: companies.name(pick.candidate.company).to_string(),
            sector: companies.sector(pick.candidate.company).to_string(),
            ranking_value: pick.value,
            sleeves: pick.sleeves,
        })
        .collect();
    Ok((day, picks))
}
