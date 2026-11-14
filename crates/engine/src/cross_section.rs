//! `bt export cross-section`: every candidate of a schedule's entry days,
//! with its built-in values, the strategy file's variables and its return to
//! each exit, as one keyed table that a script reads to study a variable
//! against the next period's returns.

use crate::strategy::Source;
use crate::{DayValues, Error, Plan, Schedule, Strategy};
use market_data::builtins::BUILTINS;
use market_data::commands::Home;
use market_data::{Market, MarketData, Screen};
use rayon::prelude::*;
use serde::Serialize;
use std::path::PathBuf;
use tables::Cell;

/// `bt export cross-section FILE --market M <schedule> --out DIR`.
pub struct CrossSectionRequest {
    pub file: PathBuf,
    pub market: Market,
    /// The seed of random dates is chosen by the caller.
    pub schedule: Schedule,
    /// The export folder: new or empty.
    pub out: PathBuf,
}

#[derive(Debug, Serialize)]
pub struct CrossSectionReply {
    pub market: Market,
    pub schedule: Schedule,
    pub seed: Option<u32>,
    /// The prepared generation read, and its as-of time.
    pub generation: u64,
    pub as_of: String,
    /// The rows written.
    pub rows: u64,
}

/// Days evaluated at a time: enough to keep the threads busy, few enough
/// that a long schedule's rows are not all held at once.
const CHUNK: usize = 64;

/// Writes table `cross_section`, keyed by (`day`, `exit`, `symbol`): one row
/// for every candidate of the dated screen of each distinct period's entry
/// day (`day`), whether or not a run would hold it, for each exit of that
/// day. Its fields: the candidate's name, sector, exchange, candidate_rank,
/// fiscal, entry (the entry close's day), market_cap, enterprise_value,
/// ebitda, ebitda_yield, ev_ebitda and spread, as a holding has them;
/// `return`, its return to the exit as a holding's, null when it enters on or
/// after the exit or has no valid exit; each built-in by its id, in canonical
/// units, null when missing; and each file variable as `variable:<name>`, in
/// its unit, null when missing. A variable's FUTURE_DATE stops the export,
/// as it stops a run; its place starts with the file, the market and the day.
/// Such an error, or a failure while writing, can leave a partial export.
/// The file's `is` texts are checked against the market as `bt run` checks
/// them.
pub fn cross_section(home: &Home, request: &CrossSectionRequest) -> Result<CrossSectionReply, Error> {
    let strategy = Strategy::read(&request.file)?;
    let out = &request.out;
    tables::new_or_empty(out).map_err(|message| Error::new(message, out.display()))?;
    let data = MarketData::open(home, request.market)?;
    crate::commands::check_texts(&strategy, &request.file, &data)?;
    let plan = Plan::new(&data, &request.schedule)?;
    let days = plan.exits_by_entry();
    let variables: Vec<Source> = strategy.variables().iter().map(|v| Source::Formula(v.clone())).collect();
    let file = request.file.display();
    let manifest = data.manifest();
    let settings = serde_json::json!({
        "file": file.to_string(), "market": request.market, "schedule": request.schedule,
        "generation": manifest.generation, "as_of": manifest.as_of,
    });
    let fail = |message: String| Error::new(message, out.display());
    let mut writer = tables::Writer::create(out, market_data::PROGRAM, settings).map_err(fail)?;
    let mut table = writer.table("cross_section", &["day", "exit", "symbol"]).map_err(fail)?;
    let columns: Vec<String> = strategy.variables().iter().map(|v| format!("variable:{}", v.name().expect("a named variable"))).collect();
    let companies = data.companies();
    for chunk in days.chunks(CHUNK) {
        let evaluated: Vec<Result<(DayValues, Vec<Vec<Option<f64>>>), Error>> = chunk
            .par_iter()
            .map(|&(day, _)| {
                let values = DayValues::new(&data, day, Screen::Dated);
                let found = (0..values.candidates().len())
                    .map(|i| variables.iter().map(|v| values.of(v, i)).collect::<Result<Vec<_>, Error>>())
                    .collect::<Result<Vec<_>, Error>>()
                    .map_err(|e| e.within(format!("{}, {day}", request.market.id())).in_file(&file))?;
                Ok((values, found))
            })
            .collect();
        for ((day, day_exits), evaluated) in chunk.iter().zip(evaluated) {
            let (values, found) = evaluated?;
            let day_text = day.to_string();
            for &exit in day_exits {
                let exit_text = exit.to_string();
                for (c, variables) in values.candidates().iter().zip(&found) {
                    let returned = (c.entry < exit)
                        .then(|| data.exit(c.company, (c.entry, c.price), exit).ok())
                        .flatten()
                        .map(|e| e.return_value);
                    let (fiscal, entry) = (c.fiscal.to_string(), c.entry.to_string());
                    let number = |v: Option<f64>| v.map_or(Cell::Null, Cell::Number);
                    let mut row = vec![
                        ("day", Cell::Text(&day_text)),
                        ("exit", Cell::Text(&exit_text)),
                        ("symbol", Cell::Text(companies.symbol(c.company))),
                        ("name", Cell::Text(companies.name(c.company))),
                        ("sector", Cell::Text(companies.sector(c.company))),
                        ("exchange", Cell::Text(companies.exchange(c.company))),
                        ("candidate_rank", c.rank.map_or(Cell::Null, |r| Cell::Int(r.into()))),
                        ("fiscal", Cell::Text(&fiscal)),
                        ("entry", Cell::Text(&entry)),
                        ("market_cap", Cell::Number(c.market_cap)),
                        ("enterprise_value", Cell::Number(c.enterprise_value)),
                        ("ebitda", Cell::Number(c.ebitda)),
                        ("ebitda_yield", Cell::Number(c.ebitda_yield)),
                        ("ev_ebitda", Cell::Number(c.ev_ebitda)),
                        ("spread", Cell::Number(c.spread)),
                        ("return", number(returned)),
                    ];
                    for (builtin, value) in BUILTINS.iter().zip(c.values) {
                        row.push((builtin.id, number(value.and_then(|v| numbers::canonical(v, builtin.scale)))));
                    }
                    for (column, &value) in columns.iter().zip(variables) {
                        row.push((column, number(value)));
                    }
                    table.row(&row).map_err(fail)?;
                }
            }
        }
    }
    let rows = table.finish().map_err(fail)?;
    writer.finish().map_err(fail)?;
    Ok(CrossSectionReply {
        market: request.market,
        schedule: request.schedule.clone(),
        seed: request.schedule.seed(),
        generation: manifest.generation,
        as_of: manifest.as_of.clone(),
        rows,
    })
}
