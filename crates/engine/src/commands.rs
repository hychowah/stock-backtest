//! The engine's commands: each command's request, reply and handler. A
//! caller (`bt`, which turns arguments into a request and prints the reply
//! as JSON) reads strategy files itself and passes [`Strategy`]s, and
//! chooses where results go. A handler checks its request once, at the
//! start; an [`Error`] stops it. Commands that read result files read their
//! rows alone: they never open market data.

use crate::results::{self, ResultFile};
use crate::statistics::{self, Statistics};
use crate::names;
use crate::run::Screened;
use crate::names::Field;
use crate::strategy::{self, Source, Step, Test};
use crate::formula;
use crate::views::{self, Exploration, ExploredTrial, Explored, Selection, Window};
use crate::{Error, Plan, Schedule, Strategy};
use rayon::prelude::*;
use market_data::commands::Home;
use market_data::{Day, Market, MarketData};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Instant;
use tables::Cell;

/// One strategy of a run. The caller names it and chooses where its result
/// file goes: `bt` uses the strategy file's path and `DIR/<file stem>.sqlite`.
pub struct Target {
    /// Repeated in the reply; the place of the strategy's errors starts with
    /// it.
    pub name: String,
    pub strategy: Strategy,
    /// The result file to write; its folder is created when missing. The
    /// targets of a run name distinct files: anything else is the caller's
    /// mistake, and no check catches it.
    pub result: PathBuf,
}

/// Every target on the same trade dates, as one batch.
pub struct RunRequest {
    pub market: Market,
    /// A missing seed of random dates is drawn ([`Schedule::drawn`]).
    pub schedule: Schedule,
    /// At least one, all run on the same plan.
    pub runs: Vec<Target>,
}

#[derive(Debug, Serialize)]
pub struct RunReply {
    pub market: Market,
    /// The schedule run, with its seed.
    pub schedule: Schedule,
    /// The prepared generation the batch read, and its as-of time.
    pub generation: u64,
    pub as_of: String,
    /// The wall time of the whole batch.
    pub seconds: f64,
    /// One run per target, in the order given.
    pub runs: Vec<RunResult>,
}

#[derive(Debug, Serialize)]
pub struct RunResult {
    /// The target's name; `bt` names a target by its strategy file.
    pub file: String,
    /// The result file's path.
    pub result: String,
    pub identity: String,
    #[serde(flatten)]
    pub headline: Headline,
}

/// The numbers of one run that a list of runs shows.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Headline {
    /// Each trial's CAGR, in trial order.
    pub cagr: Vec<f64>,
    /// The median, lowest and highest CAGR over the trials, and the median
    /// SPY CAGR, as the run's statistics give them.
    pub median: f64,
    pub worst: f64,
    pub best: f64,
    pub spy_median: f64,
    /// The trials whose CAGR is above SPY's.
    pub beat_spy: usize,
    /// The fewest holdings of any period.
    pub min_holdings: usize,
}

/// Runs every target's strategy on the same plan as one batch and writes
/// each one's result file. The schedule is [drawn](Schedule::drawn) first,
/// so the reply and every result file hold the seed that was run. The
/// inputs are checked against the market's data as [`check_run`] checks
/// them: every target's texts, then the schedule once; then the first
/// run-stopping error (by target, trial and period) stops the batch
/// before any result file is written, its place starting with the target's
/// name. A failure while writing can leave the files written before it; a
/// result file is whole or absent.
///
/// `stop` lets another thread end the run: it is read at the start of each
/// entry day's work and once before writing. Once it is set, the run
/// returns an error and writes no result file.
pub fn run(home: &Home, request: &RunRequest, stop: &AtomicBool) -> Result<RunReply, Error> {
    let started = Instant::now();
    let schedule = request.schedule.drawn();
    if request.runs.is_empty() {
        return Err(Error::new("give at least one strategy", "runs"));
    }
    let data = MarketData::open(home, request.market)?;
    for target in &request.runs {
        check_texts(&data, &target.name, &target.strategy)?;
    }
    let plan = Plan::new(&data, &schedule)?;
    let strategies: Vec<&Strategy> = request.runs.iter().map(|t| &t.strategy).collect();
    let runs = crate::run::run(&data, &plan, &strategies, stop).map_err(|(at, e)| e.in_file(&request.runs[at].name))?;
    let runs = runs.filter(|_| !stop.load(Ordering::Relaxed)).ok_or_else(|| Error::new("the run was stopped", "stop"))?;
    for folder in request.runs.iter().filter_map(|t| t.result.parent()) {
        std::fs::create_dir_all(folder).map_err(|e| Error::new(format!("cannot create the result folder: {e}"), folder.display()))?;
    }
    // Each file is written alone, so writing them in parallel changes no byte.
    let written: Vec<Result<(), Error>> =
        request.runs.par_iter().zip(&runs).map(|(target, run)| results::write(&target.result, &schedule, run)).collect();
    written.into_iter().collect::<Result<Vec<()>, Error>>()?;
    let replies = request
        .runs
        .iter()
        .zip(&runs)
        .map(|(target, run)| RunResult {
            file: target.name.clone(),
            result: target.result.display().to_string(),
            identity: run.identity.clone(),
            headline: headline(run),
        })
        .collect();
    let manifest = data.manifest();
    Ok(RunReply {
        market: request.market,
        schedule,
        generation: manifest.generation,
        as_of: manifest.as_of.clone(),
        seconds: started.elapsed().as_secs_f64(),
        runs: replies,
    })
}

fn headline(run: &crate::run::Run) -> Headline {
    let summaries: Vec<_> = run.trials.iter().map(|t| t.summary.clone()).collect();
    let statistics = statistics::statistics(&summaries);
    Headline {
        cagr: summaries.iter().map(|s| s.cagr).collect(),
        median: statistics.cagr.median,
        worst: statistics.cagr.min,
        best: statistics.cagr.max,
        spy_median: statistics.spy_cagr.median,
        beat_spy: statistics.beat_spy,
        min_holdings: run.trials.iter().flat_map(|t| &t.periods).map(|p| p.holdings.len()).min().unwrap_or(0),
    }
}

/// Checks a run's inputs against the market's data: the strategy's `is`
/// texts, then the schedule ([`Plan::new`]). A text's error place starts
/// with `name`, the strategy's; a schedule's names its key. A schedule with
/// trials must be [drawn](Schedule::drawn) first, or it is refused.
pub fn check_run(data: &MarketData, name: &str, strategy: &Strategy, schedule: &Schedule) -> Result<Plan, Error> {
    check_texts(data, name, strategy)?;
    Plan::new(data, schedule)
}

/// `bt export tables RESULT... --out DIR` and `bt export holdings RESULT...
/// --out DIR`.
pub struct ExportResultsRequest {
    /// Result files; no two with the same stem.
    pub results: Vec<PathBuf>,
    /// The export folder: new or empty.
    pub out: PathBuf,
}

#[derive(Debug, Serialize)]
pub struct ExportResultsReply {
    /// The rows written per table.
    pub tables: BTreeMap<String, u64>,
}

/// Writes the result files as keyed tables (`tables` crate format) into
/// `out`: the stored rows `trials`, `statistics`, `periods`, `holdings`,
/// `steps` and `curve`, and the views `growth`, `band`, `sectors` and
/// `contributions`, as `proof/l3.py` defines them. Every key starts with
/// `case`, the result file's stem.
pub fn export_tables(request: &ExportResultsRequest) -> Result<ExportResultsReply, Error> {
    let (files, mut writer) = start_export(request)?;
    let fail = |message: String| Error::new(message, request.out.display());
    let mut tables = BTreeMap::new();
    let day = |d: Day| d.to_string();

    let mut table = writer.table("trials", &["case", "trial"]).map_err(fail)?;
    for (case, file) in &files {
        for s in file.trials()? {
            let dates = s.dates.iter().map(|d| d.to_string()).collect::<Vec<_>>().join(" ");
            let (start, end, first_trade) = (day(s.start), day(s.end), s.first_trade.map(day));
            table
                .row(&[
                    ("case", Cell::Text(case)),
                    ("trial", Cell::Int(s.trial.into())),
                    ("dates", Cell::Text(&dates)),
                    ("start", Cell::Text(&start)),
                    ("first_trade", first_trade.as_deref().map_or(Cell::Null, Cell::Text)),
                    ("end", Cell::Text(&end)),
                    ("cash_days", s.cash_days.map_or(Cell::Null, |d| Cell::Int(d.into()))),
                    ("periods", Cell::Int(s.periods.into())),
                    ("cagr", Cell::Number(s.cagr)),
                    ("spy_cagr", Cell::Number(s.spy_cagr)),
                    ("excess_cagr", Cell::Number(s.excess_cagr())),
                    ("total_return", Cell::Number(s.total_return())),
                    ("growth", Cell::Number(s.growth)),
                    ("spy_growth", Cell::Number(s.spy_growth)),
                    ("empty_periods", Cell::Int(s.empty_periods.into())),
                    ("short_periods", Cell::Int(s.short_periods.into())),
                ])
                .map_err(fail)?;
        }
    }
    tables.insert("trials".to_string(), table.finish().map_err(fail)?);

    let mut table = writer.table("statistics", &["case", "statistic"]).map_err(fail)?;
    for (case, file) in &files {
        for (name, value) in named_statistics(&statistics::statistics(&file.trials()?)) {
            let value = match value {
                Statistic::Count(n) => Cell::Int(n as i64),
                Statistic::Value(x) => Cell::Number(x),
            };
            table.row(&[("case", Cell::Text(case)), ("statistic", Cell::Text(&name)), ("value", value)]).map_err(fail)?;
        }
    }
    tables.insert("statistics".to_string(), table.finish().map_err(fail)?);

    let mut table = writer.table("periods", &["case", "trial", "period"]).map_err(fail)?;
    for (case, file) in &files {
        for p in file.periods()? {
            let (entry, exit) = (day(p.entry), day(p.exit));
            table
                .row(&[
                    ("case", Cell::Text(case)),
                    ("trial", Cell::Int(p.trial.into())),
                    ("period", Cell::Int(p.period.into())),
                    ("entry", Cell::Text(&entry)),
                    ("exit", Cell::Text(&exit)),
                    ("names", Cell::Int(p.names.into())),
                    ("portfolio", Cell::Number(p.portfolio)),
                    ("spy", Cell::Number(p.spy)),
                ])
                .map_err(fail)?;
        }
    }
    tables.insert("periods".to_string(), table.finish().map_err(fail)?);

    let mut table = writer.table("holdings", &["case", "trial", "period", "rank"]).map_err(fail)?;
    for (case, file) in &files {
        for h in views::holdings(file)?.1 {
            let dates = [day(h.row.fiscal), day(h.row.entry), day(h.row.exit)];
            table.row(&holding_cells(case, &h, &dates)).map_err(fail)?;
        }
    }
    tables.insert("holdings".to_string(), table.finish().map_err(fail)?);

    let mut table = writer.table("steps", &["case", "trial", "period", "rank", "sleeve", "step"]).map_err(fail)?;
    for (case, file) in &files {
        for s in file.steps()? {
            table
                .row(&[
                    ("case", Cell::Text(case)),
                    ("trial", Cell::Int(s.trial.into())),
                    ("period", Cell::Int(s.period.into())),
                    ("rank", Cell::Int(s.rank.into())),
                    ("sleeve", Cell::Int(s.sleeve.into())),
                    ("step", Cell::Int(s.step.into())),
                    ("value", s.value.map_or(Cell::Null, Cell::Number)),
                    ("step_rank", s.step_rank.map_or(Cell::Null, |r| Cell::Int(r.into()))),
                ])
                .map_err(fail)?;
        }
    }
    tables.insert("steps".to_string(), table.finish().map_err(fail)?);

    let mut table = writer.table("curve", &["case", "trial", "period", "day"]).map_err(fail)?;
    for (case, file) in &files {
        for c in file.curve()? {
            let d = day(c.point.day);
            table
                .row(&[
                    ("case", Cell::Text(case)),
                    ("trial", Cell::Int(c.trial.into())),
                    ("period", Cell::Int(c.period.into())),
                    ("day", Cell::Text(&d)),
                    ("portfolio", Cell::Number(c.point.portfolio)),
                    ("spy", Cell::Number(c.point.spy)),
                ])
                .map_err(fail)?;
        }
    }
    tables.insert("curve".to_string(), table.finish().map_err(fail)?);

    let mut growth = writer.table("growth", &["case", "trial", "day"]).map_err(fail)?;
    let mut band = writer.table("band", &["case", "day"]).map_err(fail)?;
    for (case, file) in &files {
        let curves = views::growth(file)?;
        for (c, trial) in curves.iter().zip(1i64..) {
            for ((&d, &strategy), &spy) in c.days.iter().zip(&c.strategy).zip(&c.spy) {
                let d = day(d);
                growth
                    .row(&[
                        ("case", Cell::Text(case)),
                        ("trial", Cell::Int(trial)),
                        ("day", Cell::Text(&d)),
                        ("strategy", Cell::Number(strategy)),
                        ("spy", Cell::Number(spy)),
                    ])
                    .map_err(fail)?;
            }
        }
        let b = views::band(&curves);
        for (i, &d) in b.days.iter().enumerate() {
            let d = day(d);
            band.row(&[
                ("case", Cell::Text(case)),
                ("day", Cell::Text(&d)),
                ("median", Cell::Number(b.median[i])),
                ("lowest", Cell::Number(b.lowest[i])),
                ("highest", Cell::Number(b.highest[i])),
                ("spy", Cell::Number(b.spy[i])),
            ])
            .map_err(fail)?;
        }
    }
    tables.insert("growth".to_string(), growth.finish().map_err(fail)?);
    tables.insert("band".to_string(), band.finish().map_err(fail)?);

    let mut table = writer.table("sectors", &["case", "trial", "sector"]).map_err(fail)?;
    for (case, file) in &files {
        let trials = views::sectors(file)?;
        for (sectors, trial) in trials.iter().zip(1i64..) {
            for s in sectors {
                table
                    .row(&[
                        ("case", Cell::Text(case)),
                        ("trial", Cell::Int(trial)),
                        ("sector", Cell::Text(&s.name)),
                        ("mean", Cell::Number(s.mean)),
                        ("minimum", Cell::Number(s.minimum)),
                        ("maximum", Cell::Number(s.maximum)),
                        ("present", Cell::Int(s.present.into())),
                    ])
                    .map_err(fail)?;
            }
        }
        for s in views::sector_spread(&trials) {
            table
                .row(&[
                    ("case", Cell::Text(case)),
                    ("trial", Cell::Text("all")),
                    ("sector", Cell::Text(&s.name)),
                    ("mean", Cell::Number(s.mean)),
                    ("minimum", Cell::Number(s.minimum)),
                    ("maximum", Cell::Number(s.maximum)),
                    ("leading", Cell::Int(s.leading.into())),
                ])
                .map_err(fail)?;
        }
    }
    tables.insert("sectors".to_string(), table.finish().map_err(fail)?);

    let mut table = writer.table("contributions", &["case", "trial", "period"]).map_err(fail)?;
    for (case, file) in &files {
        for (trial, period, c) in views::contributions(file)? {
            let top = c.top.join(" ");
            table
                .row(&[
                    ("case", Cell::Text(case)),
                    ("trial", Cell::Int(trial.into())),
                    ("period", Cell::Int(period.into())),
                    ("count", Cell::Int(c.count as i64)),
                    ("gains", Cell::Number(c.gains)),
                    ("losses", Cell::Number(c.losses)),
                    ("net", Cell::Number(c.net)),
                    ("top_total", Cell::Number(c.top_total)),
                    ("other_total", Cell::Number(c.other_total)),
                    ("top", Cell::Text(&top)),
                ])
                .map_err(fail)?;
        }
    }
    tables.insert("contributions".to_string(), table.finish().map_err(fail)?);

    writer.finish().map_err(fail)?;
    Ok(ExportResultsReply { tables })
}

/// Writes one table, `holdings` (case, trial, period, rank), of every holding
/// of the result files: the fields of the `holdings` table of
/// [`export_tables`], and one column for each numeric source of the
/// strategy's steps, named `source:` and the source as the canonical form
/// writes it (so it is unique and never a fixed field), with the value that
/// the holding's step trail read (null when no picking sleeve reads it).
pub fn export_holdings(request: &ExportResultsRequest) -> Result<ExportResultsReply, Error> {
    let (files, mut writer) = start_export(request)?;
    let fail = |message: String| Error::new(message, request.out.display());
    let mut table = writer.table("holdings", &["case", "trial", "period", "rank"]).map_err(fail)?;
    for (case, file) in &files {
        let (sources, holdings) = views::holdings(file)?;
        for h in &holdings {
            let dates = [h.row.fiscal.to_string(), h.row.entry.to_string(), h.row.exit.to_string()];
            let mut cells = holding_cells(case, h, &dates);
            cells.extend(sources.iter().zip(&h.values).map(|(s, v)| (s.as_str(), v.map_or(Cell::Null, Cell::Number))));
            table.row(&cells).map_err(fail)?;
        }
    }
    let rows = table.finish().map_err(fail)?;
    writer.finish().map_err(fail)?;
    Ok(ExportResultsReply { tables: BTreeMap::from([("holdings".to_string(), rows)]) })
}

/// The `holdings` fields of one holding; `dates` are its fiscal, entry and
/// exit days as text.
fn holding_cells<'a>(case: &'a str, h: &'a views::Joined, dates: &'a [String; 3]) -> Vec<(&'a str, Cell<'a>)> {
    let r = &h.row;
    vec![
        ("case", Cell::Text(case)),
        ("trial", Cell::Int(r.trial.into())),
        ("period", Cell::Int(r.period.into())),
        ("rank", Cell::Int(r.rank.into())),
        ("symbol", Cell::Text(&r.symbol)),
        ("name", Cell::Text(&r.name)),
        ("sector", Cell::Text(&r.sector)),
        ("exchange", Cell::Text(&r.exchange)),
        ("candidate_rank", r.candidate_rank.map_or(Cell::Null, |n| Cell::Int(n.into()))),
        ("fiscal", Cell::Text(&dates[0])),
        ("entry", Cell::Text(&dates[1])),
        ("exit", Cell::Text(&dates[2])),
        ("market_cap", Cell::Number(r.market_cap)),
        ("enterprise_value", Cell::Number(r.enterprise_value)),
        ("ebitda", Cell::Number(r.ebitda)),
        ("ebitda_yield", Cell::Number(r.ebitda_yield)),
        ("ev_ebitda", Cell::Number(r.ev_ebitda)),
        ("spread", Cell::Number(r.spread)),
        ("return", Cell::Number(r.return_value)),
        ("status", Cell::Text(&r.status)),
        ("ranking_value", Cell::Number(r.ranking_value)),
        ("sleeve", Cell::Int(r.sleeve.into())),
        ("weight", Cell::Number(h.weight)),
        ("contribution", Cell::Number(h.contribution)),
    ]
}

/// `bt explore RESULT --trial N|all --periods A-B --ranks A-B`.
pub struct ExploreRequest {
    pub result: PathBuf,
    pub selection: Selection,
}

/// One trial's exploration, or all trials': the window, the statistics by
/// `<value>.<statistic>` and the counts, as the `statistics` table names
/// them, and each trial.
#[derive(Debug, Serialize)]
#[serde(untagged)]
pub enum ExploreReply {
    Trial(Exploration),
    All {
        #[serde(flatten)]
        window: Window,
        statistics: BTreeMap<String, Statistic>,
        trials: Vec<ExploredTrial>,
    },
}

/// Explores one result file (`result_exploration`) from its rows alone.
/// The periods and the ranks are each `A-B` with 1 ≤ A ≤ B.
pub fn explore(request: &ExploreRequest) -> Result<ExploreReply, Error> {
    let s = &request.selection;
    for (place, (from, to)) in [("periods", s.periods), ("ranks", s.ranks)] {
        if !(1 <= from && from <= to) {
            return Err(Error::new(format!("{from}-{to} is not a range: use A-B with 1 ≤ A ≤ B, such as 2-5"), place));
        }
    }
    let file = ResultFile::open(&request.result)?;
    Ok(match views::explore(&file, s)? {
        Explored::Trial(trial) => ExploreReply::Trial(trial),
        Explored::All(batch) => ExploreReply::All {
            window: batch.window,
            statistics: named_statistics(&batch.statistics).into_iter().collect(),
            trials: batch.trials,
        },
    })
}

/// `bt screen FILE --market M`.
pub struct ScreenRequest {
    /// The place of the strategy's errors starts with its name.
    pub name: String,
    pub strategy: Strategy,
    pub market: Market,
}

#[derive(Debug, Serialize)]
pub struct ScreenReply {
    pub market: Market,
    /// The market's last session, whose latest screen was read.
    #[serde(serialize_with = "views::iso")]
    pub day: Day,
    /// The prepared generation read, and its as-of time.
    pub generation: u64,
    pub as_of: String,
    pub identity: String,
    /// In rank order.
    pub picks: Vec<Screened>,
}

/// The strategy's picks of the market's latest session, with each step's
/// value. The strategy's `is` texts are checked against the market's
/// companies first. An error's place starts with the strategy's name, as a
/// run's does.
pub fn screen(home: &Home, request: &ScreenRequest) -> Result<ScreenReply, Error> {
    let (name, strategy) = (&request.name, &request.strategy);
    let data = MarketData::open(home, request.market)?;
    check_texts(&data, name, strategy)?;
    let (day, picks) = crate::run::screen(&data, strategy).map_err(|e| e.in_file(name))?;
    let manifest = data.manifest();
    Ok(ScreenReply {
        market: request.market,
        day,
        generation: manifest.generation,
        as_of: manifest.as_of.clone(),
        identity: strategy.identity(),
        picks,
    })
}

/// `bt check FILE...`.
#[derive(Debug, Serialize)]
pub struct CheckReply {
    /// In the order given.
    pub files: Vec<Checked>,
}

/// One strategy file as the program reads it.
#[derive(Debug, Serialize)]
pub struct Checked {
    pub file: String,
    pub canonical: String,
    pub identity: String,
    /// In file order.
    pub variables: Vec<CheckedVariable>,
    pub sleeves: Vec<CheckedSleeve>,
}

#[derive(Debug, Serialize)]
pub struct CheckedVariable {
    pub name: String,
    /// The canonical formula text.
    pub formula: String,
    pub unit: &'static str,
    pub display: &'static str,
}

#[derive(Debug, Serialize)]
pub struct CheckedSleeve {
    pub name: Option<String>,
    pub steps: Vec<CheckedStep>,
}

/// One step, `filter` or `rank`; its comparison and ranks are in the
/// canonical form. A number filter's threshold is also given in the
/// source's stored units.
#[derive(Debug, Serialize)]
pub struct CheckedStep {
    pub step: &'static str,
    pub source: CheckedSource,
    pub unit: &'static str,
    pub display: &'static str,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub stored: Option<f64>,
}

/// What a step reads ([`Source::kind`]), and the source as the canonical
/// form writes it.
#[derive(Debug, Serialize)]
pub struct CheckedSource {
    pub kind: &'static str,
    pub name: String,
}

/// One strategy file as the program reads it, with no market data.
pub fn check(file: &str, strategy: &Strategy) -> Checked {
    let variables = strategy
        .variables()
        .iter()
        .map(|v| CheckedVariable {
            name: v.name().expect("a variable has a name").to_string(),
            formula: v.text().to_string(),
            unit: v.unit().id(),
            display: v.display(),
        })
        .collect();
    let step = |step: &Step| {
        let source = step.source();
        let (step, stored) = match step {
            Step::Filter { test: Test::Number(_, threshold), .. } => ("filter", Some(threshold.stored)),
            Step::Filter { .. } => ("filter", None),
            Step::Rank { .. } => ("rank", None),
        };
        CheckedStep {
            step,
            source: CheckedSource { kind: source.kind(), name: strategy.written(source) },
            unit: source.unit(),
            display: source.display(),
            stored,
        }
    };
    let sleeves = strategy
        .sleeves()
        .iter()
        .map(|sleeve| CheckedSleeve { name: sleeve.name.clone(), steps: sleeve.steps.iter().map(step).collect() })
        .collect();
    Checked { file: file.to_string(), canonical: strategy.canonical().to_string(), identity: strategy.identity(), variables, sleeves }
}

/// `bt catalog --market M`.
pub struct CatalogRequest {
    pub market: Market,
}

/// What a strategy file can write, and the market's text values.
#[derive(Debug, Serialize)]
pub struct CatalogReply {
    pub market: Market,
    /// The source names, in the list's order.
    pub names: Vec<CatalogName>,
    /// How each function and operator of a formula is written, with one
    /// line on what it means.
    pub functions: Vec<Form>,
    pub operators: Vec<Form>,
    /// The displays a threshold of each formula unit can be written in, and
    /// the default one.
    pub units: Vec<CatalogUnit>,
    pub limits: Limits,
    /// The distinct sectors and exchanges of the market's companies, in
    /// name order.
    pub sectors: Vec<String>,
    pub exchanges: Vec<String>,
}

#[derive(Debug, Serialize)]
pub struct CatalogName {
    pub name: &'static str,
    /// `built-in`, `input`, `measure` or `field`.
    pub kind: &'static str,
    pub unit: &'static str,
    pub display: &'static str,
    /// Only a whole step can use the name, not a formula.
    pub step_only: bool,
}

#[derive(Debug, Serialize)]
pub struct Form {
    pub form: String,
    pub meaning: String,
}

#[derive(Debug, Serialize)]
pub struct CatalogUnit {
    pub unit: &'static str,
    pub displays: &'static [&'static str],
    pub default: &'static str,
}

/// The limits of a strategy file and of a formula.
#[derive(Debug, Serialize)]
pub struct Limits {
    /// Characters of a threshold or a formula constant.
    pub literal: usize,
    /// Levels of a formula, alone or with what it uses.
    pub formula_levels: usize,
    /// Levels of references among the variables and measures a formula
    /// uses.
    pub formula_dependency: usize,
    /// Months `ago` goes back, and yearly values a statistic reads.
    pub ago_months: u64,
    pub yearly_values: u64,
}

/// The catalog of what a strategy file can write, with the market's
/// sectors and exchanges from its prepared data.
pub fn catalog(home: &Home, request: &CatalogRequest) -> Result<CatalogReply, Error> {
    let data = MarketData::open(home, request.market)?;
    let (sectors, exchanges) = (texts(&data, Field::Sector), texts(&data, Field::Exchange));
    let forms = |lines: Vec<(String, String)>| lines.into_iter().map(|(form, meaning)| Form { form, meaning }).collect();
    Ok(CatalogReply {
        market: request.market,
        names: names::NAMES
            .iter()
            .map(|n| CatalogName {
                name: n.name,
                kind: n.kind.id(),
                unit: n.unit(),
                display: n.display(),
                step_only: n.step_only(),
            })
            .collect(),
        functions: forms(formula::functions()),
        operators: forms(formula::operators()),
        units: formula::UNITS
            .iter()
            .map(|&u| CatalogUnit { unit: u.id(), displays: u.displays(), default: u.default_display() })
            .collect(),
        limits: Limits {
            literal: strategy::MAX_LITERAL,
            formula_levels: formula::MAX_DEPTH,
            formula_dependency: formula::MAX_DEPENDENCY,
            ago_months: formula::MAX_MONTHS,
            yearly_values: formula::MAX_YEARLY,
        },
        sectors: sectors.into_iter().map(str::to_string).collect(),
        exchanges: exchanges.into_iter().map(str::to_string).collect(),
    })
}

/// One statistic: a count, or a value of a distribution.
#[derive(Debug, Serialize)]
#[serde(untagged)]
pub enum Statistic {
    Count(usize),
    Value(f64),
}

/// The statistics of one result by name, in name order: `<value>.<statistic>`
/// of each distribution, and the counts.
fn named_statistics(s: &Statistics) -> Vec<(String, Statistic)> {
    // Every trial has a CAGR (see `Statistics`): all are valid.
    let counts = [
        ("completed", s.completed),
        ("valid", s.completed),
        ("incomplete", 0),
        ("beat_spy", s.beat_spy),
        ("unique_schedules", s.unique_schedules),
    ];
    let mut rows: Vec<(String, Statistic)> = counts.into_iter().map(|(name, n)| (name.to_string(), Statistic::Count(n))).collect();
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
        rows.push((format!("{field}.n"), Statistic::Count(d.n)));
        rows.extend(values.into_iter().map(|(statistic, value)| (format!("{field}.{statistic}"), Statistic::Value(value))));
    }
    rows.sort_by(|a, b| a.0.cmp(&b.0));
    rows
}

/// The distinct sectors or exchanges of the market's companies, in order.
fn texts(data: &MarketData, field: Field) -> BTreeSet<&str> {
    let companies = data.companies();
    companies
        .ids()
        .map(|c| match field {
            Field::Sector => companies.sector(c),
            Field::Exchange => companies.exchange(c),
            Field::MarketCap | Field::EnterpriseValue => panic!("{field:?} is a number"),
        })
        .collect()
}

/// Refuses an `is` step whose text no company of the market has, before
/// anything runs: its sleeve would hold nothing, most likely from a typing
/// slip. `is not` takes any text, since a file may run on several markets.
/// The error's place starts with `name`, the strategy's.
fn check_texts(data: &MarketData, name: &str, strategy: &Strategy) -> Result<(), Error> {
    for (s, sleeve) in strategy.sleeves().iter().enumerate() {
        for (n, step) in sleeve.steps.iter().enumerate() {
            if let Step::Filter { source: Source::Field(field), test: Test::Is(text) } = step
                && !texts(data, *field).contains(text.as_str())
            {
                let (market, field) = (data.manifest().market.id(), names::of_field(*field).name.to_lowercase());
                let message = format!("no company of {market} has the {field} {text:?}: `bt catalog --market {market}` lists them");
                return Err(Error::new(message, format!("{name}: sleeves[{}].steps[{}]", s + 1, n + 1)));
            }
        }
    }
    Ok(())
}

/// The result files of an export by case (their stems; two of one stem
/// would share one case), and the export's writer.
fn start_export(request: &ExportResultsRequest) -> Result<(BTreeMap<String, ResultFile>, tables::Writer), Error> {
    let mut files = BTreeMap::new();
    for path in &request.results {
        let file = ResultFile::open(path)?;
        if files.insert(stem(path), file).is_some() {
            return Err(Error::new("another result file has the same name; their rows would share one case", path.display()));
        }
    }
    let settings = serde_json::json!({ "cases": files.keys().collect::<Vec<_>>() });
    let writer = tables::Writer::create(&request.out, market_data::PROGRAM, settings)
        .map_err(|message| Error::new(message, request.out.display()))?;
    Ok((files, writer))
}

/// A file's name without its extension.
fn stem(path: &Path) -> String {
    path.file_stem().map(|s| s.to_string_lossy().into_owned()).unwrap_or_default()
}
