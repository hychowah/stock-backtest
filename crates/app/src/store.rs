//! `data/app.sqlite` and `data/runs/`: the rows of the run list, read and
//! changed by single statements (see the crate comment for the states).

use crate::http::Failure;
use engine::commands::{Description, Outcome};
use engine::{Schedule, Strategy, StrategyFile};
use market_data::{Error, Market};
use rusqlite::{Connection, OptionalExtension, Row};
use serde::de::IntoDeserializer;
use serde::{Deserialize, Serialize};
use serde_json::value::RawValue;
use std::path::{Path, PathBuf};
use std::time::Duration;
use ts_rs::TS;

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

/// The current UTC time, as the rows store it.
const NOW: &str = "strftime('%Y-%m-%dT%H:%M:%SZ', 'now')";

/// The application database of one home. Each use opens its own
/// connection, so any thread can use it.
#[derive(Clone, Debug)]
pub(crate) struct Store {
    database: PathBuf,
    runs: PathBuf,
}

/// Where a run is in its life (the crate comment's state table).
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize, TS)]
#[serde(rename_all = "lowercase")]
#[ts(export)]
pub enum State {
    Waiting,
    Held,
    Running,
    Complete,
    Failed,
    Stopped,
}

/// One run of the list.
#[derive(Debug, Serialize, TS)]
#[ts(export)]
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
    #[ts(optional)]
    pub started: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    #[ts(optional)]
    pub finished: Option<String>,
    /// A complete run's numbers.
    #[serde(skip_serializing_if = "Option::is_none")]
    #[ts(optional)]
    pub outcome: Option<Outcome>,
    /// Why a failed run failed.
    #[serde(skip_serializing_if = "Option::is_none")]
    #[ts(optional)]
    pub error: Option<Error>,
    /// The canonical strategy file and what each of its steps reads: in a
    /// reply about one run, not in the list.
    #[serde(skip_serializing_if = "Option::is_none")]
    #[ts(as = "Option<StrategyFile<'static>>", optional)]
    pub strategy: Option<Box<RawValue>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    #[ts(optional)]
    pub description: Option<Description>,
}

/// `GET /api/runs`: the queue's pause and every run, the queue first
/// (running, then waiting and held in queue order), then the others, newest
/// first.
#[derive(Debug, Serialize, TS)]
#[ts(export)]
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
    pub(crate) fn connect(&self) -> Result<Connection, Failure> {
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
    pub(crate) fn result(&self, id: i64) -> Result<PathBuf, Failure> {
        let state = self.state(&self.connect()?, id)?;
        if state != "complete" {
            return Err(Failure::conflict(Error::new(format!("run {id} has no result: it is {state}"), "id")));
        }
        Ok(self.file(id))
    }

    /// The state of run `id` as stored, or 404.
    fn state(&self, db: &Connection, id: i64) -> Result<String, Failure> {
        let state = db.query_row("SELECT state FROM runs WHERE id=?", [id], |row| row.get(0)).optional()?;
        state.ok_or_else(|| missing("run", id))
    }

    pub(crate) fn list(&self) -> Result<RunsReply, Failure> {
        let db = self.connect()?;
        let paused = db.query_row("SELECT paused FROM queue", [], |row| row.get(0))?;
        let sql = format!("SELECT {COLUMNS} FROM runs ORDER BY position IS NULL, state != 'running', position, id DESC");
        let mut statement = db.prepare(&sql)?;
        let runs = statement.query_map([], run_row)?.collect::<rusqlite::Result<Vec<_>>>()?;
        Ok(RunsReply { paused, runs })
    }
}

/// A run the worker took from the queue.
pub(crate) struct Claimed {
    pub id: i64,
    pub market: Market,
    pub schedule: Schedule,
    pub strategy: String,
}

/// The change of a `PATCH`: each field that is given. Settings are checked
/// by the caller, together.
pub(crate) struct Edit {
    pub name: Option<String>,
    pub locked: Option<bool>,
    pub settings: Option<(Market, Schedule, String)>,
}

impl Store {
    /// Run `id` with its strategy and its description, or 404.
    pub(crate) fn get(&self, id: i64) -> Result<RunRow, Failure> {
        let db = self.connect()?;
        let sql = format!("SELECT {COLUMNS}, strategy FROM runs WHERE id=?");
        let row = db.query_row(&sql, [id], |row| Ok((run_row(row)?, row.get::<_, String>("strategy")?))).optional()?;
        let (mut run, text) = row.ok_or_else(|| missing("run", id))?;
        let strategy = Strategy::parse(&text).map_err(|e| Failure::io(e.in_file("data/app.sqlite: runs.strategy")))?;
        run.description = Some(engine::commands::describe(&strategy));
        run.strategy = Some(RawValue::from_string(text).expect("a canonical strategy is JSON"));
        Ok(run)
    }

    /// Adds a waiting run at the end of the queue. The schedule's seed is
    /// drawn already.
    pub(crate) fn add(&self, name: &str, market: Market, schedule: &Schedule, strategy: &str) -> Result<RunRow, Failure> {
        let db = self.connect()?;
        let sql = format!(
            "INSERT INTO runs(name, market, schedule, strategy, state, position, created)
             VALUES(?, ?, ?, ?, 'waiting', (SELECT coalesce(max(position), 0) + 1 FROM runs), {NOW}) RETURNING id"
        );
        let id = db.query_row(&sql, (name, market.id(), json(schedule), strategy), |row| row.get(0))?;
        self.get(id)
    }

    /// Renames, locks or unlocks run `id` in any state, and changes the
    /// settings of a waiting or held run.
    pub(crate) fn edit(&self, id: i64, edit: &Edit) -> Result<RunRow, Failure> {
        let db = self.connect()?;
        let (market, schedule, strategy) = match &edit.settings {
            Some((market, schedule, strategy)) => (Some(market.id()), Some(json(schedule)), Some(strategy.as_str())),
            None => (None, None, None),
        };
        let changed = db.execute(
            "UPDATE runs SET name=coalesce(?1, name), locked=coalesce(?2, locked), market=coalesce(?3, market),
                 schedule=coalesce(?4, schedule), strategy=coalesce(?5, strategy)
             WHERE id=?6 AND (?3 IS NULL OR state IN ('waiting', 'held'))",
            (&edit.name, edit.locked, market, schedule, strategy, id),
        )?;
        self.changed(&db, id, changed, "only a waiting or held run's settings can change")
    }

    /// Holds a waiting run.
    pub(crate) fn hold(&self, id: i64) -> Result<RunRow, Failure> {
        self.change(id, "state='held'", "state='waiting'", "only a waiting run can be held")
    }

    /// Releases a held run: it waits in the same place.
    pub(crate) fn release(&self, id: i64) -> Result<RunRow, Failure> {
        self.change(id, "state='waiting'", "state='held'", "only a held run can be released")
    }

    /// Marks a waiting, held or running run stopped; the caller then stops
    /// the engine.
    pub(crate) fn stop(&self, id: i64) -> Result<RunRow, Failure> {
        let set = format!("state='stopped', position=NULL, finished={NOW}");
        self.change(id, &set, "state IN ('waiting', 'held', 'running')", "only a waiting, held or running run can be stopped")
    }

    /// Deletes a run that is not locked, and its result file; the caller
    /// then stops the engine.
    pub(crate) fn delete(&self, id: i64) -> Result<(), Failure> {
        let db = self.connect()?;
        if db.execute("DELETE FROM runs WHERE id=? AND NOT locked", [id])? == 0 {
            self.state(&db, id)?;
            return Err(Failure::conflict(Error::new(format!("run {id} is locked: unlock it to delete it"), "id")));
        }
        remove(&self.file(id));
        Ok(())
    }

    /// Moves a waiting or held run to place `to` of the queue (1 is the
    /// first; a place past the end is the end). The queue's runs keep the
    /// positions they had among them.
    pub(crate) fn move_to(&self, id: i64, to: u32) -> Result<RunRow, Failure> {
        let mut db = self.connect()?;
        let tx = db.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
        let queue: Vec<(i64, i64)> = tx
            .prepare("SELECT id, position FROM runs WHERE state IN ('waiting', 'held') ORDER BY position")?
            .query_map([], |row| Ok((row.get(0)?, row.get(1)?)))?
            .collect::<rusqlite::Result<_>>()?;
        let Some(from) = queue.iter().position(|&(run, _)| run == id) else {
            drop(tx);
            return self.changed(&db, id, 0, "only a waiting or held run can move");
        };
        let mut order: Vec<i64> = queue.iter().map(|&(run, _)| run).collect();
        order.remove(from);
        order.insert((to.max(1) as usize - 1).min(order.len()), id);
        for (run, &(_, position)) in order.iter().zip(&queue) {
            tx.execute("UPDATE runs SET position=? WHERE id=?", [position, *run])?;
        }
        tx.commit()?;
        self.get(id)
    }

    /// Pauses or resumes the queue.
    pub(crate) fn pause(&self, paused: bool) -> Result<(), Failure> {
        self.connect()?.execute("UPDATE queue SET paused=?", [paused])?;
        Ok(())
    }

    /// The run left running, in its place: back to waiting after a clean
    /// shutdown; held at start, when the server died while running it.
    pub(crate) fn interrupted(&self, to: &str) -> Result<(), Failure> {
        self.connect()?.execute("UPDATE runs SET state=?, started=NULL WHERE state='running'", [to])?;
        Ok(())
    }

    /// Takes the first waiting run by position, unless the queue is paused.
    pub(crate) fn claim(&self) -> Result<Option<Claimed>, Failure> {
        let sql = format!(
            "UPDATE runs SET state='running', started={NOW}
             WHERE id=(SELECT id FROM runs WHERE state='waiting' ORDER BY position LIMIT 1) AND NOT (SELECT paused FROM queue)
             RETURNING id, market, schedule, strategy"
        );
        let claimed = self.connect()?.query_row(&sql, [], |row| {
            Ok(Claimed {
                id: row.get(0)?,
                market: row.get::<_, String>(1)?.parse().expect("a stored market"),
                schedule: serde_json::from_str(&row.get::<_, String>(2)?).expect("a stored schedule"),
                strategy: row.get(3)?,
            })
        });
        Ok(claimed.optional()?)
    }

    /// Records the end of run `id` while it is still running: its outcome,
    /// or its error. Gives whether the run was still running.
    pub(crate) fn finish(&self, id: i64, end: Result<&Outcome, &Error>) -> Result<bool, Failure> {
        let (state, outcome, error) = match end {
            Ok(outcome) => ("complete", Some(json(outcome)), None),
            Err(error) => ("failed", None, Some(json(error))),
        };
        let sql = format!("UPDATE runs SET state=?, outcome=?, error=?, position=NULL, finished={NOW} WHERE id=? AND state='running'");
        Ok(self.connect()?.execute(&sql, (state, outcome, error, id))? == 1)
    }

    /// `bt save`: adds the result file `result` as a complete run. The file
    /// is copied under a temporary name, the row added, the copy renamed and
    /// only then the row committed, so a complete row always has its file.
    pub(crate) fn save(&self, name: &str, saved: &engine::commands::Saved, result: &Path) -> Result<RunRow, Failure> {
        let temporary = self.runs.join(format!(".save-{}.tmp", std::process::id()));
        std::fs::copy(result, &temporary).map_err(|e| Failure::io(Error::new(format!("cannot copy the result file: {e}"), temporary.display())))?;
        let added = (|| -> Result<i64, Failure> {
            let mut db = self.connect()?;
            let tx = db.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
            let sql = format!(
                "INSERT INTO runs(name, market, schedule, strategy, state, created, finished, outcome)
                 VALUES(?, ?, ?, ?, 'complete', {NOW}, {NOW}, ?) RETURNING id"
            );
            let values = (name, saved.market.id(), json(&saved.schedule), saved.strategy.canonical(), json(&saved.outcome));
            let id: i64 = tx.query_row(&sql, values, |row| row.get(0))?;
            let file = self.file(id);
            std::fs::rename(&temporary, &file).map_err(|e| Failure::io(Error::new(format!("cannot add the result file: {e}"), file.display())))?;
            tx.commit().inspect_err(|_| remove(&file))?;
            Ok(id)
        })();
        remove(&temporary);
        self.get(added?)
    }

    /// Changes run `id` with one update guarded by the states it starts
    /// from.
    fn change(&self, id: i64, set: &str, from: &str, refusal: &str) -> Result<RunRow, Failure> {
        let db = self.connect()?;
        let changed = db.execute(&format!("UPDATE runs SET {set} WHERE id=? AND {from}"), [id])?;
        self.changed(&db, id, changed, refusal)
    }

    /// The row after a guarded update; when the update changed nothing, 404
    /// for an unknown run, else 409 with `refusal` and the run's state.
    fn changed(&self, db: &Connection, id: i64, changed: usize, refusal: &str) -> Result<RunRow, Failure> {
        if changed == 0 {
            let state = self.state(db, id)?;
            return Err(Failure::conflict(Error::new(format!("{refusal}: run {id} is {state}"), "id")));
        }
        self.get(id)
    }
}

/// 404 for an unknown `what` (a run or a variable).
pub(crate) fn missing(what: &str, id: i64) -> Failure {
    Failure::unknown(Error::new(format!("there is no {what} {id}"), "id"))
}

fn json(value: &impl Serialize) -> String {
    serde_json::to_string(value).expect("a value serializes")
}

/// Removes a file that may not exist.
pub(crate) fn remove(path: &Path) {
    let _ = std::fs::remove_file(path);
}

/// A run row from the columns [`COLUMNS`], without its strategy.
fn run_row(row: &Row<'_>) -> rusqlite::Result<RunRow> {
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
        state: State::deserialize(IntoDeserializer::<serde::de::value::Error>::into_deserializer(row.get::<_, String>("state")?))
            .expect("a stored state"),
        locked: row.get("locked")?,
        created: row.get("created")?,
        started: row.get("started")?,
        finished: row.get("finished")?,
        outcome: json("outcome")?.map(|text| serde_json::from_str(&text).expect("a stored outcome")),
        error: json("error")?.map(|text| {
            let stored: Stored = serde_json::from_str(&text).expect("a stored error");
            Error::new(stored.message, stored.place)
        }),
        strategy: None,
        description: None,
    })
}
