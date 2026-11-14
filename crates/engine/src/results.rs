//! The result file of a run: one SQLite file, written once and never changed.
//!
//! Tables, keyed by the columns in brackets; every count starts at 1:
//! - `run`, one row: strategy (canonical form), identity, market, schedule
//!   (JSON), seed, window_start, window_end, final_mark, program, generation,
//!   as_of;
//! - `trials` (trial): start, first_trade, end, cash_days, periods, growth,
//!   spy_growth, cagr, spy_cagr, empty_periods, short_periods;
//! - `periods` (trial, period): entry, exit, names, portfolio, spy;
//! - `holdings` (trial, period, rank): symbol, name, sector, exchange,
//!   candidate_rank, fiscal, entry, exit, market_cap, enterprise_value,
//!   ebitda, ebitda_yield, ev_ebitda, spread, return, status, ranking_value,
//!   sleeve (the first picking sleeve);
//! - `steps` (trial, period, rank, sleeve, step): value, step_rank; picking
//!   sleeves only, a passed Filter without step_rank, a field without value;
//! - `curve` (trial, period, day): portfolio, spy, returns to date.
//!
//! Days are ISO text. Number columns have no declared type, so SQLite keeps
//! each value as written, `-0.0` included. Whatever can be derived (excess
//! CAGR, total return, entry dates, weights, contributions) is not stored.

use crate::Error;
use crate::run::{Point, Run};
use crate::schedule::Schedule;
use crate::statistics::Summary;
use market_data::Day;
use rusqlite::types::{FromSql, FromSqlError, FromSqlResult, ToSql, ToSqlOutput, ValueRef};
use rusqlite::{Connection, OpenFlags, Row, params};
use std::path::Path;

const SCHEMA: &str = r#"
CREATE TABLE run(strategy TEXT NOT NULL, identity TEXT NOT NULL, market TEXT NOT NULL, schedule TEXT NOT NULL,
    seed INTEGER, window_start TEXT NOT NULL, window_end TEXT NOT NULL, final_mark INTEGER NOT NULL,
    program TEXT NOT NULL, generation INTEGER NOT NULL, as_of TEXT NOT NULL);
CREATE TABLE trials(trial INTEGER PRIMARY KEY, start TEXT NOT NULL, first_trade TEXT, "end" TEXT NOT NULL,
    cash_days INTEGER, periods INTEGER NOT NULL, growth, spy_growth, cagr, spy_cagr,
    empty_periods INTEGER NOT NULL, short_periods INTEGER NOT NULL);
CREATE TABLE periods(trial INTEGER, period INTEGER, entry TEXT NOT NULL, exit TEXT NOT NULL,
    names INTEGER NOT NULL, portfolio, spy, PRIMARY KEY(trial, period)) WITHOUT ROWID;
CREATE TABLE holdings(trial INTEGER, period INTEGER, rank INTEGER, symbol TEXT NOT NULL, name TEXT NOT NULL,
    sector TEXT NOT NULL, exchange TEXT NOT NULL, candidate_rank INTEGER, fiscal TEXT NOT NULL,
    entry TEXT NOT NULL, exit TEXT NOT NULL, market_cap, enterprise_value, ebitda, ebitda_yield, ev_ebitda,
    spread, "return", status TEXT NOT NULL, ranking_value, sleeve INTEGER NOT NULL,
    PRIMARY KEY(trial, period, rank)) WITHOUT ROWID;
CREATE TABLE steps(trial INTEGER, period INTEGER, rank INTEGER, sleeve INTEGER, step INTEGER, value,
    step_rank INTEGER, PRIMARY KEY(trial, period, rank, sleeve, step)) WITHOUT ROWID;
CREATE TABLE curve(trial INTEGER, period INTEGER, day TEXT, portfolio, spy,
    PRIMARY KEY(trial, period, day)) WITHOUT ROWID;
"#;

/// Writes `run`, made on `schedule`, to a new file at `path`: first under a
/// temporary name in the same folder, then renamed, so `path` holds a whole
/// result or nothing.
pub(crate) fn write(path: &Path, schedule: &Schedule, run: &Run) -> Result<(), Error> {
    let name = path.file_name().expect("a result file name").to_string_lossy();
    let temporary = path.with_file_name(format!(".{name}.tmp"));
    let written = fill(&temporary, schedule, run).map_err(|e| e.to_string()).and_then(|()| {
        std::fs::rename(&temporary, path).map_err(|e| e.to_string())
    });
    if written.is_err() {
        let _ = std::fs::remove_file(&temporary);
    }
    written.map_err(|e| Error::new(format!("cannot write the result file: {e}"), path.display()))
}

fn fill(path: &Path, schedule: &Schedule, run: &Run) -> rusqlite::Result<()> {
    let _ = std::fs::remove_file(path);
    let mut db = Connection::open(path)?;
    // The file is not a result until it is renamed, so a crash may lose it:
    // no rollback journal and no sync. Neither changes the file's bytes.
    db.execute_batch("PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;")?;
    let tx = db.transaction()?;
    tx.execute_batch(SCHEMA)?;
    tx.execute(
        "INSERT INTO run VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        params![
            run.strategy,
            run.identity,
            run.market.id(),
            serde_json::to_string(schedule).expect("a schedule is JSON"),
            schedule.seed(),
            IsoDay(run.window.0),
            IsoDay(run.window.1),
            run.final_mark,
            run.program,
            run.generation as i64,
            run.as_of
        ],
    )?;
    {
        let mut trials = tx.prepare("INSERT INTO trials VALUES(?,?,?,?,?,?,?,?,?,?,?,?)")?;
        let mut periods = tx.prepare("INSERT INTO periods VALUES(?,?,?,?,?,?,?)")?;
        let mut holdings = tx.prepare("INSERT INTO holdings VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)")?;
        let mut steps = tx.prepare("INSERT INTO steps VALUES(?,?,?,?,?,?,?)")?;
        let mut curve = tx.prepare("INSERT INTO curve VALUES(?,?,?,?,?)")?;
        for trial in &run.trials {
            let s = &trial.summary;
            trials.execute(params![
                s.trial,
                IsoDay(s.start),
                s.first_trade.map(IsoDay),
                IsoDay(s.end),
                s.cash_days,
                s.periods,
                s.growth,
                s.spy_growth,
                s.cagr,
                s.spy_cagr,
                s.empty_periods,
                s.short_periods
            ])?;
            for (period, number) in trial.periods.iter().zip(1u32..) {
                let key = (s.trial, number);
                periods.execute(params![
                    key.0,
                    key.1,
                    IsoDay(period.entry),
                    IsoDay(period.exit),
                    period.holdings.len() as u32,
                    period.portfolio,
                    period.spy
                ])?;
                for h in &period.holdings {
                    holdings.execute(params![
                        key.0,
                        key.1,
                        h.rank,
                        h.symbol,
                        h.name,
                        h.sector,
                        h.exchange,
                        h.candidate_rank,
                        IsoDay(h.fiscal),
                        IsoDay(h.entry),
                        IsoDay(h.exit),
                        h.market_cap,
                        h.enterprise_value,
                        h.ebitda,
                        h.ebitda_yield,
                        h.ev_ebitda,
                        h.spread,
                        h.return_value,
                        h.status.text(),
                        h.ranking_value,
                        h.sleeves[0].sleeve as u32 + 1
                    ])?;
                    for trail in &h.sleeves {
                        for (outcome, step) in trail.steps.iter().zip(1u32..) {
                            steps.execute(params![key.0, key.1, h.rank, trail.sleeve as u32 + 1, step, outcome.value, outcome.rank])?;
                        }
                    }
                }
                for point in &period.curve {
                    curve.execute(params![key.0, key.1, IsoDay(point.day), point.portfolio, point.spy])?;
                }
            }
        }
    }
    tx.commit()?;
    db.close().map_err(|(_, e)| e)
}

/// A finished result file, open for reading. Rows come in key order.
pub(crate) struct ResultFile {
    db: Connection,
}

#[derive(Clone, Debug, PartialEq)]
pub(crate) struct PeriodRow {
    pub trial: u32,
    pub period: u32,
    pub entry: Day,
    pub exit: Day,
    pub names: u32,
    pub portfolio: f64,
    pub spy: f64,
}

#[derive(Clone, Debug, PartialEq)]
pub(crate) struct HoldingRow {
    pub trial: u32,
    pub period: u32,
    pub rank: u32,
    pub symbol: String,
    pub name: String,
    pub sector: String,
    pub exchange: String,
    pub candidate_rank: Option<u32>,
    pub fiscal: Day,
    pub entry: Day,
    pub exit: Day,
    pub market_cap: f64,
    pub enterprise_value: f64,
    pub ebitda: f64,
    pub ebitda_yield: f64,
    pub ev_ebitda: f64,
    pub spread: f64,
    pub return_value: f64,
    /// The oracle's status text.
    pub status: String,
    pub ranking_value: f64,
    /// The first picking sleeve, from 1.
    pub sleeve: u32,
}

#[derive(Clone, Debug, PartialEq)]
pub(crate) struct StepRow {
    pub trial: u32,
    pub period: u32,
    pub rank: u32,
    pub sleeve: u32,
    pub step: u32,
    pub value: Option<f64>,
    pub step_rank: Option<u32>,
}

#[derive(Clone, Debug, PartialEq)]
pub(crate) struct CurveRow {
    pub trial: u32,
    pub period: u32,
    pub point: Point,
}

impl ResultFile {
    /// Opens a result file for reading. Fails, naming the path, when it is
    /// not one.
    pub(crate) fn open(path: &Path) -> Result<ResultFile, Error> {
        let fail = |e: rusqlite::Error| Error::new(format!("not a result file: {e}"), path.display());
        let db = Connection::open_with_flags(path, OpenFlags::SQLITE_OPEN_READ_ONLY).map_err(fail)?;
        db.query_row("SELECT count(*) FROM run", [], |_| Ok(())).map_err(fail)?;
        Ok(ResultFile { db })
    }

    /// Each trial's summary, with the entries of its periods as its dates.
    pub(crate) fn trials(&self) -> Result<Vec<Summary>, Error> {
        let mut trials = self.rows("SELECT * FROM trials ORDER BY trial", |row| {
            Ok(Summary {
                trial: row.get("trial")?,
                dates: Vec::new(),
                start: row.get::<_, IsoDay>("start")?.0,
                first_trade: row.get::<_, Option<IsoDay>>("first_trade")?.map(|d| d.0),
                end: row.get::<_, IsoDay>("end")?.0,
                cash_days: row.get("cash_days")?,
                periods: row.get("periods")?,
                growth: row.get("growth")?,
                spy_growth: row.get("spy_growth")?,
                cagr: row.get("cagr")?,
                spy_cagr: row.get("spy_cagr")?,
                empty_periods: row.get("empty_periods")?,
                short_periods: row.get("short_periods")?,
            })
        })?;
        for period in self.periods()? {
            trials[period.trial as usize - 1].dates.push(period.entry);
        }
        Ok(trials)
    }

    pub(crate) fn periods(&self) -> Result<Vec<PeriodRow>, Error> {
        self.rows("SELECT * FROM periods ORDER BY trial, period", |row| {
            Ok(PeriodRow {
                trial: row.get("trial")?,
                period: row.get("period")?,
                entry: row.get::<_, IsoDay>("entry")?.0,
                exit: row.get::<_, IsoDay>("exit")?.0,
                names: row.get("names")?,
                portfolio: row.get("portfolio")?,
                spy: row.get("spy")?,
            })
        })
    }

    pub(crate) fn holdings(&self) -> Result<Vec<HoldingRow>, Error> {
        self.rows("SELECT * FROM holdings ORDER BY trial, period, rank", |row| {
            Ok(HoldingRow {
                trial: row.get("trial")?,
                period: row.get("period")?,
                rank: row.get("rank")?,
                symbol: row.get("symbol")?,
                name: row.get("name")?,
                sector: row.get("sector")?,
                exchange: row.get("exchange")?,
                candidate_rank: row.get("candidate_rank")?,
                fiscal: row.get::<_, IsoDay>("fiscal")?.0,
                entry: row.get::<_, IsoDay>("entry")?.0,
                exit: row.get::<_, IsoDay>("exit")?.0,
                market_cap: row.get("market_cap")?,
                enterprise_value: row.get("enterprise_value")?,
                ebitda: row.get("ebitda")?,
                ebitda_yield: row.get("ebitda_yield")?,
                ev_ebitda: row.get("ev_ebitda")?,
                spread: row.get("spread")?,
                return_value: row.get("return")?,
                status: row.get("status")?,
                ranking_value: row.get("ranking_value")?,
                sleeve: row.get("sleeve")?,
            })
        })
    }

    pub(crate) fn steps(&self) -> Result<Vec<StepRow>, Error> {
        self.rows("SELECT * FROM steps ORDER BY trial, period, rank, sleeve, step", |row| {
            Ok(StepRow {
                trial: row.get("trial")?,
                period: row.get("period")?,
                rank: row.get("rank")?,
                sleeve: row.get("sleeve")?,
                step: row.get("step")?,
                value: row.get("value")?,
                step_rank: row.get("step_rank")?,
            })
        })
    }

    pub(crate) fn curve(&self) -> Result<Vec<CurveRow>, Error> {
        self.rows("SELECT * FROM curve ORDER BY trial, period, day", |row| {
            Ok(CurveRow {
                trial: row.get("trial")?,
                period: row.get("period")?,
                point: Point { day: row.get::<_, IsoDay>("day")?.0, portfolio: row.get("portfolio")?, spy: row.get("spy")? },
            })
        })
    }

    fn rows<T>(&self, sql: &str, read: impl FnMut(&Row<'_>) -> rusqlite::Result<T>) -> Result<Vec<T>, Error> {
        let fail = |e: rusqlite::Error| Error::new(format!("cannot read the result file: {e}"), self.db.path().unwrap_or_default());
        let mut statement = self.db.prepare(sql).map_err(fail)?;
        let rows = statement.query_map([], read).map_err(fail)?;
        rows.collect::<rusqlite::Result<Vec<T>>>().map_err(fail)
    }
}

/// A day stored as ISO text.
struct IsoDay(Day);

impl ToSql for IsoDay {
    fn to_sql(&self) -> rusqlite::Result<ToSqlOutput<'_>> {
        Ok(ToSqlOutput::from(self.0.to_string()))
    }
}

impl FromSql for IsoDay {
    fn column_result(value: ValueRef<'_>) -> FromSqlResult<Self> {
        Day::parse(value.as_str()?).map(IsoDay).ok_or(FromSqlError::InvalidType)
    }
}
