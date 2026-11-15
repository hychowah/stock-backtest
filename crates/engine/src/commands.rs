//! The engine's commands: each command's request, reply and handler. A
//! caller (`bt`, which turns arguments into a request and prints the reply
//! as JSON) reads strategy files itself and passes [`Strategy`]s, and
//! chooses where results go. A handler checks its request once, at the
//! start; an [`Error`] stops it. Commands that read result files read their
//! rows alone: they never open market data.

use crate::results::{self, ResultFile};
use crate::statistics;
use crate::names;
use crate::run::Screened;
use crate::names::Field;
use crate::strategy::{self, Source, Step, Test};
use crate::formula;
use crate::views::{self, Exploration, ExploredTrial, Explored, JoinedHolding, Selection, SourceValues, StatisticRow, Window};
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
use ts_rs::TS;

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
#[derive(Clone, Debug, Serialize, Deserialize, TS)]
#[ts(export)]
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
    numbers(&summaries, run.trials.iter().flat_map(|t| &t.periods).map(|p| p.holdings.len()))
}

/// The headline of the trials' summaries and every period's count of
/// holdings.
fn numbers(summaries: &[statistics::Summary], holdings: impl Iterator<Item = usize>) -> Headline {
    let statistics = statistics::statistics(summaries);
    Headline {
        cagr: summaries.iter().map(|s| s.cagr).collect(),
        median: statistics.cagr.median,
        worst: statistics.cagr.min,
        best: statistics.cagr.max,
        spy_median: statistics.spy_cagr.median,
        beat_spy: statistics.beat_spy,
        min_holdings: holdings.min().unwrap_or(0),
    }
}

/// What a list of runs keeps of a result file, read from the file alone.
pub struct Saved {
    pub market: Market,
    pub schedule: Schedule,
    pub strategy: Strategy,
    /// The prepared generation the run read, its as-of time, and the
    /// program that ran it.
    pub generation: u64,
    pub as_of: String,
    pub program: String,
    /// The same numbers as the run's reply gave.
    pub headline: Headline,
}

/// Reads a result file's run row and headline.
pub fn saved(result: &Path) -> Result<Saved, Error> {
    let file = ResultFile::open(result)?;
    let (strategy, schedule) = file.run()?;
    let (market, generation, as_of, program) = file.origin()?;
    let holdings = file.periods()?.into_iter().map(|p| p.names as usize);
    let headline = numbers(&file.summaries()?, holdings);
    Ok(Saved { market: market.parse()?, schedule, strategy, generation, as_of, program, headline })
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
/// `contributions`, as `proof/l3.py` defines them. Each table's rows are its
/// row type's, led by `case`, the result file's stem, which starts every key.
pub fn export_tables(request: &ExportResultsRequest) -> Result<ExportResultsReply, Error> {
    let mut export = Export::start(request)?;
    export.table("trials", &["trial"], ResultFile::trials)?;
    export.table("statistics", &["statistic"], views::statistics)?;
    export.table("periods", &["trial", "period"], ResultFile::periods)?;
    // The `holdings` table leaves out the source values, which differ by strategy.
    export.table("holdings", &["trial", "period", "rank"], |file| {
        Ok(views::holdings(file)?.1.into_iter().map(|h| JoinedHolding { sources: SourceValues::default(), ..h }).collect())
    })?;
    export.table("steps", &["trial", "period", "rank", "sleeve", "step"], ResultFile::steps)?;
    export.table("curve", &["trial", "period", "day"], ResultFile::curve)?;
    export.table("growth", &["trial", "day"], |file| Ok(views::growth(file)?.concat()))?;
    export.table("band", &["day"], |file| Ok(views::band(&views::growth(file)?)))?;
    // Each trial's sectors, then the spread over all trials as trial `all`.
    let mut table = export.writer.table("sectors", &["case", "trial", "sector"]).map_err(|e| export.fail(e))?;
    for (case, file) in &export.files {
        let trials = views::sectors(file)?;
        for share in trials.iter().flatten() {
            table.record(&[("case", Cell::Text(case))], share).map_err(|e| export.fail(e))?;
        }
        for spread in views::sector_spread(&trials) {
            table.record(&[("case", Cell::Text(case)), ("trial", Cell::Text("all"))], &spread).map_err(|e| export.fail(e))?;
        }
    }
    let rows = table.finish().map_err(|e| export.fail(e))?;
    export.tables.insert("sectors".to_string(), rows);
    export.table("contributions", &["trial", "period"], views::contributions)?;
    export.finish()
}

/// Writes one table, `holdings` (case, trial, period, rank), of every holding
/// of the result files: the fields of the `holdings` table of
/// [`export_tables`], and one column for each numeric source of the
/// strategy's steps, named `source:` and the source as the canonical form
/// writes it (so it is unique and never a fixed field), with the value that
/// the holding's step trail read (null when no picking sleeve reads it).
pub fn export_holdings(request: &ExportResultsRequest) -> Result<ExportResultsReply, Error> {
    let mut export = Export::start(request)?;
    export.table("holdings", &["trial", "period", "rank"], |file| Ok(views::holdings(file)?.1))?;
    export.finish()
}

/// An export of result files in progress, and the rows written per table.
struct Export<'r> {
    /// The result files by case (their stems; two of one stem would share
    /// one case).
    files: BTreeMap<String, ResultFile>,
    writer: tables::Writer,
    out: &'r Path,
    tables: BTreeMap<String, u64>,
}

impl Export<'_> {
    fn start(request: &ExportResultsRequest) -> Result<Export<'_>, Error> {
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
        Ok(Export { files, writer, out: &request.out, tables: BTreeMap::new() })
    }

    /// Writes table `name` of each file's `rows`, keyed by `case` and `keys`.
    fn table<R: Serialize>(&mut self, name: &str, keys: &[&str], rows: impl Fn(&ResultFile) -> Result<Vec<R>, Error>) -> Result<(), Error> {
        let keys: Vec<&str> = ["case"].into_iter().chain(keys.iter().copied()).collect();
        let mut table = self.writer.table(name, &keys).map_err(|e| self.fail(e))?;
        for (case, file) in &self.files {
            for row in rows(file)? {
                table.record(&[("case", Cell::Text(case))], &row).map_err(|e| self.fail(e))?;
            }
        }
        let rows = table.finish().map_err(|e| self.fail(e))?;
        self.tables.insert(name.to_string(), rows);
        Ok(())
    }

    fn finish(self) -> Result<ExportResultsReply, Error> {
        let out = self.out;
        self.writer.finish().map_err(|message| Error::new(message, out.display()))?;
        Ok(ExportResultsReply { tables: self.tables })
    }

    fn fail(&self, message: String) -> Error {
        Error::new(message, self.out.display())
    }
}

/// `bt explore RESULT --trial N|all --periods A-B --ranks A-B`.
pub struct ExploreRequest {
    pub result: PathBuf,
    pub selection: Selection,
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
        Explored::All(batch) => ExploreReply::All { window: batch.window, statistics: batch.statistics, trials: batch.trials },
    })
}

/// `bt screen FILE --market M`.
pub struct ScreenRequest {
    /// The place of the strategy's errors starts with its name.
    pub name: String,
    pub strategy: Strategy,
    pub market: Market,
}

#[derive(Debug, Serialize, TS)]
#[ts(export)]
pub struct ScreenReply {
    pub market: Market,
    /// The market's last session, whose latest screen was read.
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
#[derive(Debug, Serialize, TS)]
#[ts(export)]
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

#[derive(Debug, Serialize, TS)]
#[ts(export)]
pub struct CatalogName {
    pub name: &'static str,
    /// `built-in`, `input`, `measure` or `field`.
    pub kind: &'static str,
    pub unit: &'static str,
    pub display: &'static str,
    /// Only a whole step can use the name, not a formula.
    pub step_only: bool,
}

#[derive(Debug, Serialize, TS)]
#[ts(export)]
pub struct Form {
    pub form: String,
    pub meaning: String,
}

#[derive(Debug, Serialize, TS)]
#[ts(export)]
pub struct CatalogUnit {
    pub unit: &'static str,
    pub displays: &'static [&'static str],
    pub default: &'static str,
}

/// The limits of a strategy file and of a formula.
#[derive(Debug, Serialize, TS)]
#[ts(export)]
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

/// A file's name without its extension.
fn stem(path: &Path) -> String {
    path.file_stem().map(|s| s.to_string_lossy().into_owned()).unwrap_or_default()
}
