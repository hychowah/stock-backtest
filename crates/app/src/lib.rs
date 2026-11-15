//! The runs service behind `bt serve`: one list of runs that is both the
//! queue and the saved results, a worker that runs the queue, and the
//! variable library.
//!
//! The routes are listed in [`http`], the worker's rules in the `worker`
//! module and the library's in the `library` module.
//!
//! # The database
//!
//! `data/app.sqlite` in the home: WAL mode, a busy timeout of 5 s and
//! `user_version` 1. The first process that opens it creates it.
//!
//! - `runs`: one row per run. Its id is never reused, so a link to a result
//!   never shows another run. The row holds the name, the market, the
//!   schedule (the flat [`engine::Schedule`], with a seed drawn when the row
//!   is written), the strategy's canonical form, the state, the queue
//!   position (waiting, held and running runs), whether it is locked, and
//!   the times it was created, started and finished. A complete run also
//!   holds its outcome: the [`engine::commands::Headline`], the prepared
//!   generation and as-of time, the program and the seconds. A failed run
//!   holds its error. The list reads these rows and opens no result file.
//! - `queue`: one row, whether the queue is paused.
//! - `variables`: the variable library, each entry with an id, a unique
//!   name, a formula, a display and a favourite mark. The entries are read
//!   in dependency order (ties by id) as the `variables` of one strategy
//!   file. A change that would make them unreadable, such as a cycle or the
//!   removal of an entry that another uses, is refused.
//!
//! Run N's result is `data/runs/N.sqlite`. The engine writes it whole or not
//! at all, and it never changes. A complete run is a saved run: there is no
//! other saved mark. A kill can leave a temporary file in `data/runs/`
//! (`.N.sqlite.tmp` from a run, `.save-PID.tmp` from `bt save`): it is
//! harmless, never listed and never reused, and nothing sweeps it.
//!
//! # States
//!
//! | From | Action | To |
//! |---|---|---|
//! | (none) | add | waiting, at the end of the queue |
//! | waiting / held | hold / release | held / waiting, in the same place |
//! | waiting, held | edit the settings, move | the same state |
//! | waiting | the worker takes the first by position, when not paused | running |
//! | running | the engine returns | complete or failed |
//! | waiting, held, running | stop | stopped |
//! | running | the server shuts down (Ctrl+C or SIGTERM) | waiting, in the same place |
//! | running | the server starts: the last one died while running it | held, in the same place |
//! | any | rename, lock | the same state |
//! | not locked | delete (a running run is stopped first) | removed |
//! | (none) | `bt save` | complete |
//!
//! Each change is one update whose condition names the states it starts
//! from, so a change that loses a race with the worker changes nothing and
//! is refused. Move is the exception: one write transaction reads the queue
//! and renumbers it, and refuses a run that is no longer waiting or held. Stop and delete write their state before they set the run's
//! stop flag. The worker records the end of a run only while the run is
//! still running: a run stopped meanwhile stays stopped, and the result
//! file of a run deleted meanwhile is removed.
//!
//! # Who writes
//!
//! | Who | Writes | Reads |
//! |---|---|---|
//! | `bt serve` | `app.sqlite`, `data/runs/` | prepared data, result files |
//! | `bt save` | one result file, then one short `app.sqlite` transaction | the result file |
//! | `bt run`, `bt export` | only their `--out` folder | prepared data |
//! | `bt data prepare` | prepared data, under its own lock | raw data |
//!
//! `bt save` copies the result file to a temporary name in `data/runs/`,
//! adds the row, renames the file and then commits, so a complete row always
//! has its file. SQLite's write lock is held for milliseconds and the busy
//! timeout waits for it. A prepared generation stays readable while it is in
//! use, and result files never change, so neither needs a lock.
//!
//! # One server per home
//!
//! `bt serve` holds `data/serve.lock` while it runs, and a second server on
//! the same home is refused. A clean shutdown puts the run it interrupted
//! back to waiting. At start, with the lock held, a run still marked running
//! means the last server died while running it, perhaps because of that
//! run: it is held, so the rest of the queue goes on and the owner releases
//! or deletes it.

mod formula;
pub mod http;
mod library;
mod runs;
mod store;
mod worker;

pub use http::{App, Body, Failure, Id, blocking, serve};
pub use library::{NewVariable, Variable};
pub use runs::{AddRun, Deleted, EditRun, MoveRun, Queue};
pub use store::{Outcome, RunRow, RunsReply, State, Store};

use market_data::Error;
use std::path::Path;

/// `bt save RESULT --name N`: adds a result file to the run list of the
/// home at `root` as a complete run, beside a running server or without
/// one. The row holds the strategy, schedule, market and numbers the file
/// stores.
pub fn save(root: &Path, result: &Path, name: &str) -> Result<RunRow, Error> {
    let saved = engine::commands::saved(result)?;
    let store = Store::open(root)?;
    store.save(name, &saved, result).map_err(|failure| failure.error)
}
