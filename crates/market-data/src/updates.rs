//! The home's update files. `data/update.json` holds `memory` (what the next
//! update needs) and `progress` (this update), replaced whole. The update
//! holds `update.lock` from start to end, so a record that says running or
//! stopping while the lock is free belongs to an update that crashed:
//! `status` reads it as interrupted. `request_stop` writes `update.stop`,
//! which the running update checks about ten times a second, whether or not
//! a request ends.
//!
//! All four files are in `data/`: `update.json` ([`UpdateRecord`]),
//! `update.lock` ([`UpdateLock`]), `update.stop` ([`request_stop`],
//! [`stop_requested`]) and `update.done`, the journal of the items an
//! update has saved ([`Journal`]).

use crate::commands::Home;
use crate::raw::replace;
use crate::{Day, Error, Market};
use serde::{Deserialize, Serialize};
use std::collections::HashSet;
use std::fs::{self, File, TryLockError};
use std::io::{self, Write};
use std::path::PathBuf;
use std::time::{Duration, Instant};
use ts_rs::TS;

fn path(home: &Home, name: &str) -> PathBuf {
    home.root().join("data").join(name)
}

/// `data/update.json`. Without the file, no update has run and no report
/// check was made.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct UpdateRecord {
    #[serde(default)]
    pub memory: UpdateMemory,
    /// The last update's progress; `None` before the first update (a record
    /// may hold only `memory`).
    #[serde(default)]
    pub progress: Option<UpdateProgress>,
}

/// What an update needs from the earlier ones. Saved before any raw file
/// whose change it records.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct UpdateMemory {
    /// The Hong Kong date of the last complete report check.
    #[serde(default)]
    pub last_report_check: Option<Day>,
    /// The Hong Kong date of the last report check that also asked for the
    /// delisted companies.
    #[serde(default)]
    pub last_full_sweep: Option<Day>,
    /// Each market's new companies still waiting for their price file and
    /// statements.
    #[serde(default)]
    pub pending: Pending,
    /// The finish time of the last complete update, RFC 3339.
    #[serde(default)]
    pub last_success: Option<String>,
}

/// New companies by market, each list in symbol order.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct Pending {
    #[serde(default)]
    pub us: Vec<String>,
    #[serde(default)]
    pub hk: Vec<String>,
}

/// An update's state.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, TS)]
#[serde(rename_all = "snake_case")]
#[ts(export)]
pub enum UpdateState {
    /// No update has run. Only read, never written.
    Idle,
    /// An update holds the lock.
    Running,
    /// A stop was asked; the update is ending.
    Stopping,
    /// Ended by a stop.
    Stopped,
    /// The record says running or stopping but nothing holds the lock.
    /// Only read, never written.
    Interrupted,
    /// Downloads ended on an error, preparation failed, or the record is
    /// unreadable.
    Failed,
    /// Finished with failed items.
    Partial,
    /// Finished with no failed item.
    Complete,
}

/// The step an update is on.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, TS)]
#[serde(rename_all = "snake_case")]
#[ts(export)]
pub enum UpdateStage {
    Companies,
    Reports,
    Prices,
    Preparing,
}

/// Whether an update checks reports, and the delisted companies too.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, TS)]
#[serde(rename_all = "snake_case")]
#[ts(export)]
pub enum ReportCheck {
    NotDue,
    Due,
    Sweep,
}

/// One update's run. The next update replaces it.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, TS)]
#[ts(export)]
pub struct UpdateProgress {
    pub state: UpdateState,
    /// The process id of the update.
    pub pid: u32,
    /// The stage running or last run; none before the first.
    pub stage: Option<UpdateStage>,
    /// The market the stage works on; none for a stage of both.
    pub market: Option<Market>,
    /// The stage's items done so far.
    pub done: u64,
    /// The stage's items in all.
    pub total: u64,
    /// The update's failed items.
    pub failed: u64,
    /// The failed items, what happened and the raw file of each: the update
    /// keeps the first 20.
    pub failures: Vec<Error>,
    /// The start time, RFC 3339.
    pub started: String,
    /// The finish time, RFC 3339; none while running.
    pub finished: Option<String>,
    /// The last price day the update asks for.
    pub end: Day,
    pub reports: ReportCheck,
    /// What went wrong in the update, if anything.
    pub error: Option<Error>,
}

impl UpdateRecord {
    /// Reads `data/update.json`; `None` when there is none. Fails, naming the
    /// file, when it cannot be read.
    pub fn read(home: &Home) -> Result<Option<UpdateRecord>, Error> {
        let path = path(home, "update.json");
        let text = match fs::read_to_string(&path) {
            Ok(text) => text,
            Err(e) if e.kind() == io::ErrorKind::NotFound => return Ok(None),
            Err(e) => return Err(Error::new(format!("cannot read the update record: {e}"), path.display())),
        };
        serde_json::from_str(&text).map(Some).map_err(|e| Error::new(format!("unreadable update record: {e}"), path.display()))
    }

    /// Replaces `data/update.json` with this record.
    pub fn write(&self, home: &Home) -> Result<(), Error> {
        let text = serde_json::to_string_pretty(self).expect("a record is JSON") + "\n";
        replace(&path(home, "update.json"), text.as_bytes())
    }
}

/// `data/update.lock`, held by the running update. The operating system
/// releases it when the value is dropped or the process ends, so a crash
/// leaves no stale lock.
pub struct UpdateLock {
    _file: File,
}

impl UpdateLock {
    /// Takes the lock, waiting up to 2 s, then deletes a stale
    /// `update.stop`. Fails with "an update is already running" when another
    /// update holds it. The wait lets a status read probe the lock without
    /// making a starting update fail.
    pub fn take(home: &Home) -> Result<UpdateLock, Error> {
        let path = path(home, "update.lock");
        let file = (|| {
            fs::create_dir_all(path.parent().unwrap())?;
            File::options().create(true).truncate(false).write(true).open(&path)
        })()
        .map_err(|e| Error::new(format!("cannot open the update lock: {e}"), path.display()))?;
        let started = Instant::now();
        loop {
            match file.try_lock() {
                Ok(()) => break,
                Err(TryLockError::WouldBlock) if started.elapsed() < Duration::from_secs(2) => {
                    std::thread::sleep(Duration::from_millis(50))
                }
                Err(TryLockError::WouldBlock) => return Err(Error::new("an update is already running", path.display())),
                Err(TryLockError::Error(e)) => return Err(Error::new(format!("cannot take the update lock: {e}"), path.display())),
            }
        }
        let stop = path.with_file_name("update.stop");
        match fs::remove_file(&stop) {
            Err(e) if e.kind() != io::ErrorKind::NotFound => {
                return Err(Error::new(format!("cannot delete the stop request: {e}"), stop.display()));
            }
            _ => {}
        }
        Ok(UpdateLock { _file: file })
    }
}

/// Whether an update holds the lock of this home. Takes it shared for an
/// instant when it is free and never waits, so probes never conflict with each
/// other, and a starting update waits for the instant to pass.
pub fn lock_held(home: &Home) -> bool {
    let Ok(file) = File::open(path(home, "update.lock")) else { return false };
    matches!(file.try_lock_shared(), Err(TryLockError::WouldBlock))
}

/// Asks the running update to stop: writes `data/update.stop`. Fails when
/// no update runs.
pub fn request_stop(home: &Home) -> Result<(), Error> {
    let stop = path(home, "update.stop");
    if !lock_held(home) {
        return Err(Error::new("no update is running", stop.display()));
    }
    File::create(&stop).map(drop).map_err(|e| Error::new(format!("cannot write the stop request: {e}"), stop.display()))
}

/// Whether a stop was asked since the running update took the lock.
pub fn stop_requested(home: &Home) -> bool {
    path(home, "update.stop").exists()
}

/// The `update` field of the data status.
#[derive(Debug, Clone, Serialize, TS)]
#[ts(export)]
pub struct UpdateStatus {
    /// The last update's state; `interrupted` when its record says running
    /// or stopping but no update holds the lock; `idle` when no update has
    /// run; `failed` when the record cannot be read.
    pub state: UpdateState,
    /// The last update's progress, with `state` as above.
    pub progress: Option<UpdateProgress>,
    /// The finish time of the last complete update, RFC 3339.
    pub last_success: Option<String>,
}

/// Reads the update's state. It probes the lock only when the record says
/// running or stopping. When the lock is free it reads the record again, as
/// the update may have written its last record and ended in between. Does
/// not fail.
pub fn status(home: &Home) -> UpdateStatus {
    let failed = UpdateStatus { state: UpdateState::Failed, progress: None, last_success: None };
    let unfinished = |record: &UpdateRecord| {
        record.progress.as_ref().is_some_and(|p| matches!(p.state, UpdateState::Running | UpdateState::Stopping))
    };
    let Ok(record) = UpdateRecord::read(home) else { return failed };
    let mut record = record.unwrap_or_default();
    if unfinished(&record) && !lock_held(home) {
        let Ok(again) = UpdateRecord::read(home) else { return failed };
        record = again.unwrap_or_default();
        if unfinished(&record) {
            record.progress.as_mut().unwrap().state = UpdateState::Interrupted;
        }
    }
    let progress = record.progress;
    UpdateStatus {
        state: progress.as_ref().map_or(UpdateState::Idle, |p| p.state),
        progress,
        last_success: record.memory.last_success,
    }
}

/// `data/update.done`: the items one update has saved, so that a continued
/// update does not ask for them again. Its first line is the update's last
/// price day; then one item per line.
pub struct Journal {
    file: File,
    path: PathBuf,
    items: HashSet<String>,
}

impl Journal {
    /// Opens the journal of the update whose last price day is `end`. With
    /// `resume`, a journal of the same day keeps its items (an unfinished
    /// last line, cut by a crash, is removed); otherwise a new, empty
    /// journal replaces it. A journal that cannot be read counts as empty:
    /// it only saves requests.
    pub fn open(home: &Home, end: Day, resume: bool) -> Result<Journal, Error> {
        let path = path(home, "update.done");
        let fail = |e: io::Error| Error::new(format!("cannot open the update journal: {e}"), path.display());
        let mut items = HashSet::new();
        let text = if resume { fs::read_to_string(&path).unwrap_or_default() } else { String::new() };
        let complete = text.rfind('\n').map_or("", |i| &text[..i]);
        let mut lines = complete.lines();
        if resume && lines.next() == Some(end.to_string().as_str()) {
            items.extend(lines.map(str::to_string));
            if !text.ends_with('\n') {
                // Later items must not be appended to a cut line.
                replace(&path, format!("{complete}\n").as_bytes())?;
            }
        } else {
            replace(&path, format!("{end}\n").as_bytes())?;
        }
        let file = File::options().append(true).open(&path).map_err(fail)?;
        Ok(Journal { file, path, items })
    }

    /// Whether `item` was saved in this update.
    pub fn contains(&self, item: &str) -> bool {
        self.items.contains(item)
    }

    /// Records `item` (a text without line breaks) as saved: call it after
    /// its file is saved. The line is not synced: a line lost in a crash
    /// only asks for its item again.
    pub fn record(&mut self, item: &str) -> Result<(), Error> {
        assert!(!item.contains(['\n', '\r']), "a journal item is one line");
        self.file
            .write_all(format!("{item}\n").as_bytes())
            .map_err(|e| Error::new(format!("cannot write the update journal: {e}"), self.path.display()))?;
        self.items.insert(item.to_string());
        Ok(())
    }
}
