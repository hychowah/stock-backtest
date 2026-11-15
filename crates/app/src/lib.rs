//! This crate is not built yet: this comment is the behavior it will have.
//!
//! The runs service behind `bt serve`: one list of runs that is both the
//! queue and the saved results, a worker that runs the queue, and the
//! variable library.
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
//!   position (waiting and held runs only), whether it is locked, and the
//!   times it was created, started and finished. A complete run also holds
//!   its outcome: the [`engine::commands::Headline`], the prepared
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
//! other saved mark.
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
//! | running | the server starts | waiting |
//! | any | rename, lock | the same state |
//! | not locked | delete (a running run is stopped first) | removed |
//! | (none) | `bt save` | complete |
//!
//! Each change is one update whose condition names the states it starts
//! from, so a change that loses a race with the worker changes nothing and
//! is refused. Stop and delete write their state before they set the run's
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
//! the same home is refused. At start, with the lock held, every running run
//! goes back to waiting: this one rule covers both a crash and a shutdown.
