//! `data/app.sqlite` and `data/runs/`: the rows of the run list, read and
//! changed by single statements (see the crate comment for the states).

use crate::http::Failure;
use engine::Schedule;
use engine::commands::Headline;
use market_data::{Error, Market};
use rusqlite::{Connection, OptionalExtension, Row};
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};
use std::time::Duration;

const SCHEMA: &str = r#"
CREATE TABLE runs(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, market TEXT NOT NULL,
    schedule TEXT NOT NULL, strategy TEXT NOT NULL, state TEXT NOT NULL, position INTEGER,
    locked INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL, started TEXT, finished TEXT,
    outcome TEXT, error TEXT);
CREATE TABLE queue(paused INTEGER NOT NULL);
INSERT INTO queue VALUES(0);
CREATE TABLE variables(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
    formula TEXT NOT NULL, display TEXT NOT NULL, favourite INTEGER NOT NULL);
"#;

/// The columns of a [`RunRow`] without the strategy.
const COLUMNS: &str = "id, name, market, schedule, state, locked, created, started, finished, outcome, error";

/// The application database of one home. Each use opens its own
/// connection, so any thread can use it.
#[derive(Clone, Debug)]
pub struct Store {
    database: PathBuf,
    runs: PathBuf,
}

/// Where a run is in its life (the crate comment's state table).
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum State {
    Waiting,
    Held,
    Running,
    Complete,
    Failed,
    Stopped,
}

/// One run of the list.
#[derive(Debug, Serialize)]
pub struct RunRow {
    pub id: i64,
    pub name: String,
    pub market: Market,
    /// With its seed, when it has trials.
    pub schedule: Schedule,
    pub state: State,
    pub locked: bool,
    /// UTC times, `YYYY-MM-DDTHH:MM:SSZ`.
    pub created: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub started: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub finished: Option<String>,
    /// A complete run's numbers.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub outcome: Option<Outcome>,
    /// Why a failed run failed.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<Error>,
    /// The canonical strategy: in the reply of one run, not in the list.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub strategy: Option<String>,
}

/// What a complete run gave, stored when it finished.
#[derive(Debug, Serialize, Deserialize)]
pub struct Outcome {
    pub headline: Headline,
    /// The prepared generation the run read, and its as-of time.
    pub generation: u64,
    pub as_of: String,
    /// The program that ran it.
    pub program: String,
    /// The run's wall time; absent for a result added by `bt save`.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub seconds: Option<f64>,
}

/// `GET /api/runs`: the queue's pause and every run, the queue first
/// (running, then waiting and held in queue order), then the others, newest
/// first.
#[derive(Debug, Serialize)]
pub struct RunsReply {
    pub paused: bool,
    pub runs: Vec<RunRow>,
}

impl Store {
    /// Opens the home's database, creating `data/`, `data/runs/` and the
    /// database when missing.
    pub(crate) fn open(root: &Path) -> Result<Store, Error> {
        let data = root.join("data");
        let store = Store { database: data.join("app.sqlite"), runs: data.join("runs") };
        std::fs::create_dir_all(&store.runs).map_err(|e| Error::new(format!("cannot create the folder: {e}"), store.runs.display()))?;
        store.create().map_err(|e| e.error)?;
        Ok(store)
    }

    /// Creates the tables once. Two processes may open a new database at the
    /// same time: the write transaction lets only the first create them.
    fn create(&self) -> Result<(), Failure> {
        let mut db = self.connect()?;
        db.pragma_update(None, "journal_mode", "WAL")?;
        let tx = db.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
        let version: i32 = tx.pragma_query_value(None, "user_version", |row| row.get(0))?;
        match version {
            0 => {
                tx.execute_batch(SCHEMA)?;
                tx.pragma_update(None, "user_version", 1)?;
            }
            1 => {}
            _ => return Err(Failure::io(Error::new("this database was written by another version of the program", self.database.display()))),
        }
        tx.commit()?;
        Ok(())
    }

    /// A new connection with the busy timeout.
    pub fn connect(&self) -> Result<Connection, Failure> {
        let db = Connection::open(&self.database)?;
        db.busy_timeout(Duration::from_secs(5))?;
        Ok(db)
    }

    /// The result file of run `id`, which holds a result once the run is
    /// complete.
    pub(crate) fn file(&self, id: i64) -> PathBuf {
        self.runs.join(format!("{id}.sqlite"))
    }

    /// The result file of run `id`: 404 for an unknown run, 409 for a run
    /// that is not complete.
    pub fn result(&self, id: i64) -> Result<PathBuf, Failure> {
        let state = self.state(&self.connect()?, id)?;
        if state != State::Complete {
            return Err(Failure::conflict(Error::new(format!("run {id} has no result: it is {}", state.word()), "id")));
        }
        Ok(self.file(id))
    }

    /// The state of run `id`, or 404.
    fn state(&self, db: &Connection, id: i64) -> Result<State, Failure> {
        let state: Option<String> = db.query_row("SELECT state FROM runs WHERE id=?", [id], |row| row.get(0)).optional()?;
        state.map(|s| State::parse(&s)).ok_or_else(|| Failure::unknown(Error::new(format!("there is no run {id}"), "id")))
    }

    pub(crate) fn list(&self) -> Result<RunsReply, Failure> {
        let db = self.connect()?;
        let paused = db.query_row("SELECT paused FROM queue", [], |row| row.get(0))?;
        let sql = format!("SELECT {COLUMNS} FROM runs ORDER BY position IS NULL, state != 'running', position, id DESC");
        let mut statement = db.prepare(&sql)?;
        let runs = statement.query_map([], |row| run_row(row, false))?.collect::<rusqlite::Result<Vec<_>>>()?;
        Ok(RunsReply { paused, runs })
    }
}

impl State {
    fn parse(text: &str) -> State {
        serde_json::from_value(serde_json::Value::String(text.to_string())).expect("a stored state")
    }

    /// The state as it is stored and replied.
    pub(crate) fn word(self) -> &'static str {
        match self {
            State::Waiting => "waiting",
            State::Held => "held",
            State::Running => "running",
            State::Complete => "complete",
            State::Failed => "failed",
            State::Stopped => "stopped",
        }
    }
}

/// A run row from the columns [`COLUMNS`], then the strategy when `strategy`.
fn run_row(row: &Row<'_>, strategy: bool) -> rusqlite::Result<RunRow> {
    #[derive(Deserialize)]
    struct Stored {
        message: String,
        place: String,
    }
    let json = |column: &str| -> rusqlite::Result<Option<String>> { row.get(column) };
    let market: String = row.get("market")?;
    Ok(RunRow {
        id: row.get("id")?,
        name: row.get("name")?,
        market: market.parse().expect("a stored market"),
        schedule: serde_json::from_str(&row.get::<_, String>("schedule")?).expect("a stored schedule"),
        state: State::parse(&row.get::<_, String>("state")?),
        locked: row.get("locked")?,
        created: row.get("created")?,
        started: row.get("started")?,
        finished: row.get("finished")?,
        outcome: json("outcome")?.map(|text| serde_json::from_str(&text).expect("a stored outcome")),
        error: json("error")?.map(|text| {
            let stored: Stored = serde_json::from_str(&text).expect("a stored error");
            Error::new(stored.message, stored.place)
        }),
        strategy: if strategy { Some(row.get("strategy")?) } else { None },
    })
}
