//! The worker: one thread inside the server that runs the queue, one run at
//! a time.
//!
//! - **Claim.** When the queue is not paused, the worker takes the first
//!   waiting run by position (one guarded update) and runs it with
//!   [`engine::commands::run`]: one target, `data/runs/<id>.sqlite`, and a
//!   stop flag of its own. A handler wakes it after a change that can give
//!   it work (add, release, move, resume); a finished run makes it look
//!   again at once.
//! - **Finish.** One update guarded by `state='running'` stores the outcome
//!   (the headline, the generation, the as-of time, the program and the
//!   seconds) or the error `{message, place}`; a panic inside the run is
//!   caught and stored as an error. When no row matches, the run was
//!   stopped or deleted meanwhile, and a result file it wrote is removed.
//!   A finish that fails (the database stays busy) is tried again until it
//!   succeeds or shutdown begins, and no run is claimed meanwhile, so only
//!   one run is ever running. A claim that fails is tried again after a
//!   second.
//! - **Stop.** Stop and delete write their state first, then set the flag
//!   of the run if it is the running one. The engine reads the flag at the
//!   start of each entry day's work and once before it writes. The claim
//!   and the record of the running run's flag happen under one lock, so a
//!   stop that comes right after a claim still finds the flag.
//! - **Shutdown.** The server sets the running run's flag, wakes the worker
//!   and joins it. A run that returns during shutdown is not recorded: its
//!   result file (if any) is removed, and once the worker has ended the
//!   server puts the run back to waiting, so the next start continues the
//!   queue.
//! - **Crash, abort and out-of-memory kill.** These end the whole process,
//!   so the run stays `running`. The next start holds it, in its place: the
//!   rest of the queue goes on, and the user releases or deletes it. A run
//!   that always ends the server therefore cannot end it again by itself.

use crate::store::{Claimed, Outcome, Store, remove};
use engine::Strategy;
use engine::commands::{RunRequest, Target};
use market_data::Error;
use market_data::commands::Home;
use std::panic::{AssertUnwindSafe, catch_unwind};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Condvar, Mutex};
use std::thread::JoinHandle;
use std::time::Duration;

/// How long the worker waits before it tries a failed database write again.
const RETRY: Duration = Duration::from_secs(1);

/// The handle that handlers and the server use to reach the worker.
#[derive(Clone, Debug, Default)]
pub(crate) struct Worker(Arc<Shared>);

#[derive(Debug, Default)]
struct Shared {
    control: Mutex<Control>,
    woken: Condvar,
}

#[derive(Debug, Default)]
struct Control {
    /// A change since the worker last looked at the queue.
    pending: bool,
    shutdown: bool,
    /// The running run and its stop flag.
    current: Option<(i64, Arc<AtomicBool>)>,
}

impl Worker {
    /// Starts the worker thread.
    pub(crate) fn start(home: Home, store: Store) -> (Worker, JoinHandle<()>) {
        let worker = Worker::default();
        let thread = {
            let worker = worker.clone();
            std::thread::Builder::new().name("worker".into()).spawn(move || worker.work(&home, &store)).expect("a worker thread")
        };
        (worker, thread)
    }

    /// Tells the worker to look at the queue.
    pub(crate) fn wake(&self) {
        self.control().pending = true;
        self.0.woken.notify_one();
    }

    /// Stops the engine if it is running run `id`.
    pub(crate) fn stop(&self, id: i64) {
        if let Some((_, flag)) = self.control().current.as_ref().filter(|(running, _)| *running == id) {
            flag.store(true, Ordering::Relaxed);
        }
    }

    /// Stops the running run and ends the thread, which the caller joins.
    pub(crate) fn shutdown(&self) {
        let mut control = self.control();
        control.shutdown = true;
        if let Some((_, flag)) = &control.current {
            flag.store(true, Ordering::Relaxed);
        }
        drop(control);
        self.0.woken.notify_one();
    }

    fn control(&self) -> std::sync::MutexGuard<'_, Control> {
        self.0.control.lock().expect("the worker's lock")
    }

    fn work(&self, home: &Home, store: &Store) {
        loop {
            let mut control = self.control();
            control.pending = false;
            if control.shutdown {
                return;
            }
            let run = match store.claim() {
                Ok(Some(run)) => run,
                Ok(None) => {
                    let _waited = self.0.woken.wait_while(control, |c| !c.pending && !c.shutdown).expect("the worker's lock");
                    continue;
                }
                Err(failure) => {
                    eprintln!("the worker cannot read the queue: {}", failure.error);
                    let _waited = self.0.woken.wait_timeout_while(control, RETRY, |c| !c.pending && !c.shutdown).expect("the worker's lock");
                    continue;
                }
            };
            let flag = Arc::new(AtomicBool::new(false));
            control.current = Some((run.id, flag.clone()));
            drop(control);
            let id = run.id;
            let ended = execute(home, store, run, &flag);
            self.control().current = None;
            loop {
                let control = self.control();
                if control.shutdown {
                    remove(&store.file(id));
                    return;
                }
                match store.finish(id, ended.as_ref()) {
                    Ok(true) => {
                        if let Err(error) = &ended {
                            eprintln!("run {id} failed: {error}");
                        }
                    }
                    Ok(false) => remove(&store.file(id)),
                    Err(failure) => {
                        eprintln!("the worker cannot record run {id}: {}", failure.error);
                        let _waited = self.0.woken.wait_timeout_while(control, RETRY, |c| !c.shutdown).expect("the worker's lock");
                        continue;
                    }
                }
                break;
            }
        }
    }
}

/// Runs one claimed run; a panic inside it becomes its error.
fn execute(home: &Home, store: &Store, run: Claimed, stop: &AtomicBool) -> Result<Outcome, Error> {
    let result = store.file(run.id);
    catch_unwind(AssertUnwindSafe(|| {
        let strategy = Strategy::parse(&run.strategy).map_err(|e| e.in_file("strategy"))?;
        let target = Target { name: "strategy".into(), strategy, result };
        let reply = engine::commands::run(home, &RunRequest { market: run.market, schedule: run.schedule, runs: vec![target] }, stop)?;
        let headline = reply.runs.into_iter().next().expect("one target").headline;
        let program = market_data::PROGRAM.to_string();
        Ok(Outcome { headline, generation: reply.generation, as_of: reply.as_of, program, seconds: Some(reply.seconds) })
    }))
    .unwrap_or_else(|panic| {
        let text = panic.downcast_ref::<&str>().map(|s| s.to_string()).or_else(|| panic.downcast_ref::<String>().cloned());
        Err(Error::new(format!("the run stopped on an internal error: {}", text.unwrap_or_default()), "run"))
    })
}
