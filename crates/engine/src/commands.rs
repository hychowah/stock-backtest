//! The engine's commands: each command's request, reply and handler. `bt`
//! turns arguments into a request, calls the handler and prints the reply as
//! JSON. A handler checks its request once, at the start; an [`Error`]
//! stops it.

use crate::results::{self, ResultFile};
use crate::statistics::{self, Statistics};
use crate::{Error, Plan, Schedule, Strategy};
use rayon::prelude::*;
use market_data::commands::Home;
use market_data::{Day, Market, MarketData};
use serde::Serialize;
use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};
use std::time::Instant;
use tables::Cell;

/// `bt run FILE... --market M <schedule> --out DIR`.
pub struct RunRequest {
    /// Strategy files; no two with the same stem.
    pub files: Vec<PathBuf>,
    pub market: Market,
    /// The seed of random dates is chosen by the caller.
    pub schedule: Schedule,
    /// The result folder: new or empty.
    pub out: PathBuf,
}

#[derive(Debug, Serialize)]
pub struct RunReply {
    pub market: Market,
    pub schedule: Schedule,
    /// The seed of random dates, shared by the batch.
    pub seed: Option<u32>,
    /// The prepared generation the batch read, and its as-of time.
    pub generation: u64,
    pub as_of: String,
    /// The wall time of the whole batch.
    pub seconds: f64,
    /// One run per strategy file, in the order given.
    pub runs: Vec<RunResult>,
}

#[derive(Debug, Serialize)]
pub struct RunResult {
    pub file: String,
    /// The result file: `DIR/<strategy stem>.sqlite`.
    pub result: String,
    pub identity: String,
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

/// Runs every strategy file on the same plan as one batch and writes one
/// result file for each. Every file is read and checked before any market
/// data; then the schedule is checked against the data. The first
/// run-stopping error (by file, trial and period) stops the batch before any
/// result file is written; its place starts with the strategy file. A
/// failure while writing can leave the files written before it.
pub fn run(home: &Home, request: &RunRequest) -> Result<RunReply, Error> {
    let started = Instant::now();
    let strategies = request.files.iter().map(|file| Strategy::read(file)).collect::<Result<Vec<_>, _>>()?;
    let mut stems = BTreeSet::new();
    for file in &request.files {
        if !stems.insert(stem(file)) {
            return Err(Error::new("another strategy file has the same name; their results would share one file", file.display()));
        }
    }
    let out = &request.out;
    if std::fs::read_dir(out).is_ok_and(|mut entries| entries.next().is_some()) || (out.exists() && !out.is_dir()) {
        return Err(Error::new("the result folder must be new or empty", out.display()));
    }
    let data = MarketData::open(home, request.market)?;
    let plan = Plan::new(&data, &request.schedule)?;
    let runs = crate::run::run(&data, &plan, &strategies)
        .map_err(|(at, e)| Error::new(e.message, format!("{}: {}", request.files[at].display(), e.place)))?;
    std::fs::create_dir_all(out).map_err(|e| Error::new(format!("cannot create the result folder: {e}"), out.display()))?;
    // Each file is written alone, so writing them in parallel changes no byte.
    let paths: Vec<PathBuf> = request.files.iter().map(|file| out.join(format!("{}.sqlite", stem(file)))).collect();
    let written: Vec<Result<(), Error>> =
        paths.par_iter().zip(&runs).map(|(path, run)| results::write(path, &request.schedule, run)).collect();
    written.into_iter().collect::<Result<Vec<()>, Error>>()?;
    let mut replies = Vec::with_capacity(runs.len());
    for ((file, path), run) in request.files.iter().zip(&paths).zip(&runs) {
        let summaries: Vec<_> = run.trials.iter().map(|t| t.summary.clone()).collect();
        let statistics = statistics::statistics(&summaries);
        replies.push(RunResult {
            file: file.display().to_string(),
            result: path.display().to_string(),
            identity: run.identity.clone(),
            cagr: summaries.iter().map(|s| s.cagr).collect(),
            median: statistics.cagr.median,
            worst: statistics.cagr.min,
            best: statistics.cagr.max,
            spy_median: statistics.spy_cagr.median,
            beat_spy: statistics.beat_spy,
            min_holdings: run.trials.iter().flat_map(|t| &t.periods).map(|p| p.holdings.len()).min().unwrap_or(0),
        });
    }
    let manifest = data.manifest();
    Ok(RunReply {
        market: request.market,
        schedule: request.schedule.clone(),
        seed: request.schedule.seed(),
        generation: manifest.generation,
        as_of: manifest.as_of.clone(),
        seconds: started.elapsed().as_secs_f64(),
        runs: replies,
    })
}

/// `bt export tables RESULT... --out DIR`.
pub struct ExportTablesRequest {
    /// Result files; no two with the same stem.
    pub results: Vec<PathBuf>,
    /// The export folder: new or empty.
    pub out: PathBuf,
}

#[derive(Debug, Serialize)]
pub struct ExportTablesReply {
    /// The rows written per table.
    pub tables: BTreeMap<String, u64>,
}

/// Writes the result files as keyed tables (`tables` crate format) into
/// `out`: `trials`, `statistics`, `periods`, `holdings`, `steps` and `curve`,
/// as `proof/l3.py` defines them. Every key starts with `case`, the result
/// file's stem. The entry dates of a trial, its excess CAGR and total return,
/// the statistics, and a holding's weight and contribution are derived here.
pub fn export_tables(request: &ExportTablesRequest) -> Result<ExportTablesReply, Error> {
    let mut files = BTreeMap::new();
    for path in &request.results {
        let file = ResultFile::open(path)?;
        if files.insert(stem(path), file).is_some() {
            return Err(Error::new("another result file has the same name; their rows would share one case", path.display()));
        }
    }
    let out = &request.out;
    let fail = |message: String| Error::new(message, out.display());
    let settings = serde_json::json!({ "cases": files.keys().collect::<Vec<_>>() });
    let mut writer = tables::Writer::create(out, crate::run::PROGRAM, settings).map_err(fail)?;
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
        let rows = statistic_rows(&statistics::statistics(&file.trials()?));
        for (name, value) in &rows {
            table.row(&[("case", Cell::Text(case)), ("statistic", Cell::Text(name)), ("value", *value)]).map_err(fail)?;
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
        let names: BTreeMap<(u32, u32), f64> = file.periods()?.iter().map(|p| ((p.trial, p.period), f64::from(p.names))).collect();
        for h in file.holdings()? {
            // Equal weights (portfolio_results._holdings).
            let n = names[&(h.trial, h.period)];
            let (fiscal, entry, exit) = (day(h.fiscal), day(h.entry), day(h.exit));
            table
                .row(&[
                    ("case", Cell::Text(case)),
                    ("trial", Cell::Int(h.trial.into())),
                    ("period", Cell::Int(h.period.into())),
                    ("rank", Cell::Int(h.rank.into())),
                    ("symbol", Cell::Text(&h.symbol)),
                    ("name", Cell::Text(&h.name)),
                    ("sector", Cell::Text(&h.sector)),
                    ("exchange", Cell::Text(&h.exchange)),
                    ("candidate_rank", h.candidate_rank.map_or(Cell::Null, |r| Cell::Int(r.into()))),
                    ("fiscal", Cell::Text(&fiscal)),
                    ("entry", Cell::Text(&entry)),
                    ("exit", Cell::Text(&exit)),
                    ("market_cap", Cell::Number(h.market_cap)),
                    ("enterprise_value", Cell::Number(h.enterprise_value)),
                    ("ebitda", Cell::Number(h.ebitda)),
                    ("ebitda_yield", Cell::Number(h.ebitda_yield)),
                    ("ev_ebitda", Cell::Number(h.ev_ebitda)),
                    ("spread", Cell::Number(h.spread)),
                    ("return", Cell::Number(h.return_value)),
                    ("status", Cell::Text(&h.status)),
                    ("ranking_value", Cell::Number(h.ranking_value)),
                    ("sleeve", Cell::Int(h.sleeve.into())),
                    ("weight", Cell::Number(1.0 / n)),
                    ("contribution", Cell::Number(h.return_value / n * 100.0)),
                ])
                .map_err(fail)?;
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

    writer.finish().map_err(fail)?;
    Ok(ExportTablesReply { tables })
}

/// The `statistics` rows of one result, in name order: `<value>.<statistic>`
/// of each distribution, and the counts.
fn statistic_rows(s: &Statistics) -> Vec<(String, Cell<'static>)> {
    let count = |n: usize| Cell::Int(n as i64);
    // Every trial has a CAGR (see `Statistics`): all are valid.
    let counts = [
        ("completed", s.completed),
        ("valid", s.completed),
        ("incomplete", 0),
        ("beat_spy", s.beat_spy),
        ("unique_schedules", s.unique_schedules),
    ];
    let mut rows: Vec<(String, Cell<'static>)> = counts.into_iter().map(|(name, n)| (name.to_string(), count(n))).collect();
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
        rows.push((format!("{field}.n"), count(d.n)));
        rows.extend(values.into_iter().map(|(statistic, value)| (format!("{field}.{statistic}"), Cell::Number(value))));
    }
    rows.sort_by(|a, b| a.0.cmp(&b.0));
    rows
}

/// A file's name without its extension.
fn stem(path: &Path) -> String {
    path.file_stem().map(|s| s.to_string_lossy().into_owned()).unwrap_or_default()
}
