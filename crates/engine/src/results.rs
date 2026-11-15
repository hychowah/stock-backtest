//! The result file of a run: one SQLite file, written once and never changed,
//! and [`ResultFile`], which reads it back as rows.
//!
//! One row type per table ([`TrialRow`], [`PeriodRow`], [`HoldingRow`],
//! [`StepRow`], [`CurveRow`]), shared by the export, the HTTP replies and the
//! website's types (the curve rows reach the website only as growth): a row
//! serializes to its table's fields in their order, days as ISO text.
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
//! The schedule is stored in the flat form of [`Schedule`].
//!
//! The file's `user_version` is [`VERSION`]. A file of another version is
//! refused with "run it again", never read with this layout.

use crate::Error;
use crate::run::{Run, Status};
use crate::schedule::Schedule;
use crate::statistics::Summary;
use crate::strategy::Strategy;
use market_data::Day;
use rusqlite::types::{FromSql, FromSqlError, FromSqlResult, ToSql, ToSqlOutput, ValueRef};
use rusqlite::{Connection, OpenFlags, Params, Row, params};
use serde::Serialize;
use std::path::Path;
use ts_rs::TS;

/// The layout written and read.
const VERSION: i32 = 1;

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
    tx.pragma_update(None, "user_version", VERSION)?;
    tx.execute(
        "INSERT INTO run VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        params![
            run.strategy,
            run.identity,
            run.market.id(),
            serde_json::to_string(schedule).expect("a schedule is JSON"),
            schedule.seed,
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
pub struct ResultFile {
    db: Connection,
    /// The first and last trial the readers read: all, or one ([`only`](Self::only)).
    trials: (u32, u32),
}

/// A trial's summary (`trials`), with its derived excess CAGR and total
/// return.
#[derive(Clone, Debug, PartialEq, Serialize, TS)]
#[ts(export)]
pub struct TrialRow {
    pub trial: u32,
    /// The entries of the trial's periods, as ISO days joined by spaces.
    pub dates: String,
    pub start: Day,
    pub first_trade: Option<Day>,
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
}

impl TrialRow {
    pub(crate) fn new(s: &Summary) -> TrialRow {
        TrialRow {
            trial: s.trial,
            dates: s.dates.iter().map(Day::to_string).collect::<Vec<_>>().join(" "),
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
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, TS)]
#[ts(export)]
pub struct PeriodRow {
    pub trial: u32,
    pub period: u32,
    pub entry: Day,
    pub exit: Day,
    pub names: u32,
    pub portfolio: f64,
    pub spy: f64,
}

#[derive(Clone, Debug, PartialEq, Serialize, TS)]
#[ts(export)]
pub struct HoldingRow {
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
    #[serde(rename = "return")]
    pub return_value: f64,
    pub status: Status,
    pub ranking_value: f64,
    /// The first picking sleeve, from 1.
    pub sleeve: u32,
}

#[derive(Clone, Debug, PartialEq, Serialize, TS)]
#[ts(export)]
pub struct StepRow {
    pub trial: u32,
    pub period: u32,
    pub rank: u32,
    pub sleeve: u32,
    pub step: u32,
    pub value: Option<f64>,
    pub step_rank: Option<u32>,
}

#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct CurveRow {
    pub trial: u32,
    pub period: u32,
    pub day: Day,
    pub portfolio: f64,
    pub spy: f64,
}

impl ResultFile {
    /// Opens a result file for reading. Fails, naming the path, when it is
    /// not one.
    pub fn open(path: &Path) -> Result<ResultFile, Error> {
        let fail = |e: rusqlite::Error| Error::new(format!("not a result file: {e}"), path.display());
        let db = Connection::open_with_flags(path, OpenFlags::SQLITE_OPEN_READ_ONLY).map_err(fail)?;
        db.query_row("SELECT count(*) FROM run", [], |_| Ok(())).map_err(fail)?;
        if db.query_row("PRAGMA user_version", [], |row| row.get::<_, i32>(0)).map_err(fail)? != VERSION {
            return Err(Error::new("this result file was written by another version of the program: run it again", path.display()));
        }
        Ok(ResultFile { db, trials: (1, u32::MAX) })
    }

    /// The same file with its readers limited to trial `trial`, so a reply
    /// about one trial reads only its rows. Refused, with the place `trial`,
    /// when the result has no such trial.
    pub fn only(self, trial: u32) -> Result<ResultFile, Error> {
        let count = self.rows("SELECT count(*) FROM trials", [], |row| row.get::<_, u32>(0))?[0];
        if !(1..=count).contains(&trial) {
            return Err(Error::new(format!("the result has {count} trials"), "trial"));
        }
        Ok(ResultFile { trials: (trial, trial), ..self })
    }

    /// The run's strategy, read back from its canonical form, and its
    /// schedule.
    pub(crate) fn run(&self) -> Result<(Strategy, Schedule), Error> {
        let rows = self.rows("SELECT strategy, schedule FROM run", [], |row| Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?)))?;
        let (strategy, schedule) = rows.into_iter().next().expect("a result file has one run row");
        let place = format!("{}: run.strategy", self.db.path().unwrap_or_default());
        Ok((Strategy::parse(&strategy).map_err(|e| e.in_file(place))?, serde_json::from_str(&schedule).expect("a stored schedule is JSON")))
    }

    /// The run row's market, prepared generation, as-of time and program.
    pub(crate) fn origin(&self) -> Result<(String, u64, String, String), Error> {
        let rows = self.rows("SELECT market, generation, as_of, program FROM run", [], |row| {
            Ok((row.get(0)?, row.get::<_, i64>(1)? as u64, row.get(2)?, row.get(3)?))
        })?;
        Ok(rows.into_iter().next().expect("a result file has one run row"))
    }

    pub fn trials(&self) -> Result<Vec<TrialRow>, Error> {
        Ok(self.summaries()?.iter().map(TrialRow::new).collect())
    }

    /// Each trial's summary, with the entries of its periods as its dates.
    pub(crate) fn summaries(&self) -> Result<Vec<Summary>, Error> {
        let mut trials = self.rows("SELECT * FROM trials WHERE trial BETWEEN ? AND ? ORDER BY trial", self.range(), |row| {
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
            trials[(period.trial - self.trials.0) as usize].dates.push(period.entry);
        }
        Ok(trials)
    }

    pub fn periods(&self) -> Result<Vec<PeriodRow>, Error> {
        self.rows("SELECT * FROM periods WHERE trial BETWEEN ? AND ? ORDER BY trial, period", self.range(), |row| {
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
        self.rows("SELECT * FROM holdings WHERE trial BETWEEN ? AND ? ORDER BY trial, period, rank", self.range(), |row| {
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

    pub fn steps(&self) -> Result<Vec<StepRow>, Error> {
        self.rows("SELECT * FROM steps WHERE trial BETWEEN ? AND ? ORDER BY trial, period, rank, sleeve, step", self.range(), |row| {
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
        self.rows("SELECT * FROM curve WHERE trial BETWEEN ? AND ? ORDER BY trial, period, day", self.range(), |row| {
            Ok(CurveRow {
                trial: row.get("trial")?,
                period: row.get("period")?,
                day: row.get::<_, IsoDay>("day")?.0,
                portfolio: row.get("portfolio")?,
                spy: row.get("spy")?,
            })
        })
    }

    /// The parameters of a reader's `trial BETWEEN ? AND ?`.
    fn range(&self) -> [u32; 2] {
        [self.trials.0, self.trials.1]
    }

    fn rows<T>(&self, sql: &str, params: impl Params, read: impl FnMut(&Row<'_>) -> rusqlite::Result<T>) -> Result<Vec<T>, Error> {
        let fail = |e: rusqlite::Error| Error::new(format!("cannot read the result file: {e}"), self.db.path().unwrap_or_default());
        let mut statement = self.db.prepare(sql).map_err(fail)?;
        let rows = statement.query_map(params, read).map_err(fail)?;
        rows.collect::<rusqlite::Result<Vec<T>>>().map_err(fail)
    }
}

impl FromSql for Status {
    fn column_result(value: ValueRef<'_>) -> FromSqlResult<Self> {
        let text = value.as_str()?;
        Status::ALL.into_iter().find(|s| s.text() == text).ok_or(FromSqlError::InvalidType)
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
