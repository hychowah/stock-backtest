//! The home's update files: the record, the lock, the stop request, the
//! journal and the status read.

use market_data::commands::Home;
use market_data::updates::{
    self, Journal, Pending, ReportCheck, UpdateLock, UpdateMemory, UpdateProgress, UpdateRecord, UpdateStage, UpdateState,
};
use market_data::{Day, Error, Market};
use std::time::{Duration, Instant};

fn day(text: &str) -> Day {
    Day::parse(text).unwrap()
}

fn running() -> UpdateProgress {
    UpdateProgress {
        state: UpdateState::Running,
        pid: 1,
        stage: Some(UpdateStage::Prices),
        market: Some(Market::Hk),
        done: 3,
        total: 10,
        failed: 1,
        failures: vec![Error::new("the provider returned invalid dated values", "raw/px/A.json")],
        started: "2026-11-14T23:00:00+00:00".to_string(),
        finished: None,
        end: day("2026-11-14"),
        reports: ReportCheck::Sweep,
        error: None,
    }
}

#[test]
fn a_running_record_reads_as_running_only_while_the_lock_is_held() {
    let dir = tempfile::tempdir().unwrap();
    let home = Home::new(dir.path());
    let status = updates::status(&home);
    assert_eq!((status.state, status.progress, status.last_success), (UpdateState::Idle, None, None));

    let memory = UpdateMemory {
        last_report_check: Some(day("2026-11-14")),
        last_full_sweep: None,
        pending: Pending { us: vec!["NEW".to_string()], hk: Vec::new() },
        last_success: Some("2026-11-13T23:20:00+00:00".to_string()),
    };
    let record = UpdateRecord { memory, progress: Some(running()) };
    record.write(&home).unwrap();
    assert_eq!(UpdateRecord::read(&home).unwrap(), Some(record.clone()));

    let status = updates::status(&home);
    assert_eq!(status.state, UpdateState::Interrupted);
    assert_eq!(status.progress.unwrap().state, UpdateState::Interrupted);
    assert_eq!(status.last_success.as_deref(), Some("2026-11-13T23:20:00+00:00"));

    let lock = UpdateLock::take(&home).unwrap();
    assert_eq!(updates::status(&home).state, UpdateState::Running);
    // The status probe leaves the lock with its holder.
    assert_eq!(updates::status(&home).state, UpdateState::Running);
    drop(lock);
    assert_eq!(updates::status(&home).state, UpdateState::Interrupted);
}

#[test]
fn a_record_of_memory_alone_reads_as_idle() {
    let dir = tempfile::tempdir().unwrap();
    let home = Home::new(dir.path());
    std::fs::create_dir_all(dir.path().join("data")).unwrap();
    let seed = r#"{"memory": {"last_report_check": "2026-11-07", "last_full_sweep": "2026-09-05", "pending": {"us": ["NEW"]}}}"#;
    std::fs::write(dir.path().join("data/update.json"), seed).unwrap();
    let record = UpdateRecord::read(&home).unwrap().unwrap();
    assert_eq!(record.memory.last_full_sweep, Some(day("2026-09-05")));
    assert_eq!(record.memory.pending.us, ["NEW"]);
    assert!(record.memory.pending.hk.is_empty() && record.progress.is_none());
    assert_eq!(updates::status(&home).state, UpdateState::Idle);
}

#[test]
fn one_update_at_a_time_and_a_stop_only_while_one_runs() {
    let dir = tempfile::tempdir().unwrap();
    let home = Home::new(dir.path());
    assert!(updates::request_stop(&home).is_err());
    let lock = UpdateLock::take(&home).unwrap();
    assert!(!updates::stop_requested(&home));
    updates::request_stop(&home).unwrap();
    assert!(updates::stop_requested(&home));

    let started = Instant::now();
    let second = UpdateLock::take(&home).err().unwrap();
    assert_eq!(second.message, "an update is already running");
    assert!(started.elapsed() >= Duration::from_secs(2));

    // A stop request left by an ended update is deleted by the next one.
    drop(lock);
    assert!(updates::stop_requested(&home));
    let _lock = UpdateLock::take(&home).unwrap();
    assert!(!updates::stop_requested(&home));
}

#[test]
fn a_journal_continues_only_the_same_last_day() {
    let dir = tempfile::tempdir().unwrap();
    let home = Home::new(dir.path());
    let mut journal = Journal::open(&home, day("2026-11-13"), true).unwrap();
    journal.record("px/A.json").unwrap();
    journal.record("px/B.json").unwrap();
    drop(journal);
    // A line cut short by a crash is not an item.
    let path = dir.path().join("data/update.done");
    std::fs::write(&path, std::fs::read_to_string(&path).unwrap() + "px/C.js").unwrap();

    let mut journal = Journal::open(&home, day("2026-11-13"), true).unwrap();
    assert!(journal.contains("px/A.json") && journal.contains("px/B.json") && !journal.contains("px/C.js"));
    journal.record("px/D.json").unwrap();
    assert!(Journal::open(&home, day("2026-11-13"), true).unwrap().contains("px/D.json"));
    let journal = Journal::open(&home, day("2026-11-13"), false).unwrap();
    assert!(!journal.contains("px/A.json"));
    let mut journal = Journal::open(&home, day("2026-11-13"), true).unwrap();
    journal.record("px/A.json").unwrap();
    let journal = Journal::open(&home, day("2026-11-14"), true).unwrap();
    assert!(!journal.contains("px/A.json"));
    // A journal that cannot be read blocks no update.
    std::fs::write(&path, b"\xff\xfe").unwrap();
    assert!(!Journal::open(&home, day("2026-11-15"), false).unwrap().contains("px/A.json"));
    std::fs::write(&path, b"2026-11-15\npx/A.json\n\xff\n").unwrap();
    let mut journal = Journal::open(&home, day("2026-11-15"), true).unwrap();
    assert!(!journal.contains("px/A.json"));
    journal.record("px/B.json").unwrap();
    assert!(Journal::open(&home, day("2026-11-15"), true).unwrap().contains("px/B.json"));
}

#[test]
fn an_unreadable_record_reads_as_failed() {
    let dir = tempfile::tempdir().unwrap();
    let home = Home::new(dir.path());
    std::fs::create_dir_all(dir.path().join("data")).unwrap();
    std::fs::write(dir.path().join("data/update.json"), "{\"memory\": ").unwrap();
    let status = updates::status(&home);
    assert_eq!((status.state, status.progress, status.last_success), (UpdateState::Failed, None, None));
}
