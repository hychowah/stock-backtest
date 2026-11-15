//! The routes that start and stop the data update, which is the command `bt
//! data update` (see `market_data::updates` for its files). The server does
//! not track the update: it starts it as the terminal would, and the lock
//! and the record in `data/` tell every reader what runs.

use crate::http::{App, Failure, blocking};
use axum::extract::State;
use axum::routing::post;
use axum::{Json, Router};
use market_data::Error;
use market_data::commands::Home;
use market_data::updates::{UpdateRecord, UpdateState, UpdateStatus, lock_held, request_stop, status};
use std::fs::{self, OpenOptions};
use std::os::unix::process::CommandExt;
use std::process::{Command, Stdio};
use std::time::Duration;

pub(crate) fn routes() -> Router<App> {
    Router::new().route("/api/data/update", post(start)).route("/api/data/stop", post(stop))
}

/// Whether the update's state says that an update runs.
fn busy(state: UpdateState) -> bool {
    matches!(state, UpdateState::Running | UpdateState::Stopping)
}

async fn start(State(app): State<App>) -> Result<Json<UpdateStatus>, Failure> {
    blocking(move || start_update(&app.home)).await.map(Json)
}

/// Starts `bt data update` from this program: its own process group (so the
/// server's Ctrl+C does not reach it), the server's environment, and its
/// output appended to `logs/update.log`. Returns the status once the record
/// names the new process. A process that ends without that is an error, its
/// output stays in the log, unless an update runs after all (it lost the race
/// for the lock): that is the 409.
fn start_update(home: &Home) -> Result<UpdateStatus, Failure> {
    if busy(status(home).state) {
        return Err(Failure::conflict(Error::new("an update is already running", "data/update.lock")));
    }
    let logs = home.root().join("logs");
    let log = logs.join("update.log");
    let log_error = |e: std::io::Error| Failure::io(Error::new(format!("cannot open the update log: {e}"), "logs/update.log"));
    let spawn_error = |e: std::io::Error| Failure::io(Error::new(format!("cannot start the update: {e}"), "server"));
    fs::create_dir_all(&logs).map_err(log_error)?;
    let output = OpenOptions::new().create(true).append(true).open(&log).map_err(log_error)?;
    let program = std::env::current_exe().map_err(spawn_error)?;
    let mut child = Command::new(program)
        .args(["data", "update", "--home"])
        .arg(home.root())
        .stdin(Stdio::null())
        .stdout(output.try_clone().map_err(log_error)?)
        .stderr(output)
        .process_group(0)
        .spawn()
        .map_err(spawn_error)?;
    let pid = child.id();
    loop {
        // The process is read first: a record written just before it ended is seen below.
        let ended = child.try_wait().map_err(spawn_error)?;
        if matches!(UpdateRecord::read(home), Ok(Some(record)) if record.progress.as_ref().is_some_and(|p| p.pid == pid)) {
            // The update goes on after this reply: something must collect its exit.
            std::thread::spawn(move || drop(child.wait()));
            return Ok(status(home));
        }
        if let Some(exit) = ended {
            // Another start, or a terminal's update that has not written its record yet, took the lock first
            // (an update writes its record only after it takes the lock, so the status may still say idle).
            if busy(status(home).state) || lock_held(home) {
                return Err(Failure::conflict(Error::new("an update is already running", "data/update.lock")));
            }
            let message = format!("the update ended ({exit}) before it started; see logs/update.log");
            return Err(Failure::io(Error::new(message, "logs/update.log")));
        }
        std::thread::sleep(Duration::from_millis(20));
    }
}

async fn stop(State(app): State<App>) -> Result<Json<UpdateStatus>, Failure> {
    blocking(move || {
        request_stop(&app.home).map_err(|error| if busy(status(&app.home).state) { Failure::io(error) } else { Failure::conflict(error) })?;
        Ok(status(&app.home))
    })
    .await
    .map(Json)
}
