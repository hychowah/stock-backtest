//! A run's stop flag: once set, the run returns an error and writes no
//! result file.

use engine::commands::{RunRequest, Target, run};
use engine::{Schedule, Strategy};
use market_data::Market;
use market_data::commands::{Home, PrepareRequest, prepare};
use std::path::Path;
use std::sync::atomic::AtomicBool;

#[test]
fn a_stopped_run_returns_an_error_and_writes_no_result_file() {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path().join("home");
    std::fs::create_dir(&root).unwrap();
    let raw = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../fixtures/fictional/raw");
    std::os::unix::fs::symlink(raw.canonicalize().unwrap(), root.join("raw")).unwrap();
    let home = Home::new(root);
    prepare(&home, &PrepareRequest { as_of: "2023-06-30T07:30:00+00:00".parse().unwrap() }).unwrap();
    let request = |result: &Path| {
        let text = r#"{"sleeves": [{"steps": [{"rank": "EBITDA yield", "order": "highest", "from": 1, "to": 5}]}]}"#;
        let schedule = Schedule {
            start: "2021-07-01".into(),
            end: "2023-06-28".into(),
            every: Some("6m".into()),
            trials: Some(3),
            seed: None,
            dates: None,
        };
        let target = Target { name: "a".into(), strategy: Strategy::parse(text).unwrap(), result: result.to_path_buf() };
        RunRequest { market: Market::Hk, schedule, runs: vec![target] }
    };
    let stopped = dir.path().join("stopped/a.sqlite");
    let error = run(&home, &request(&stopped), &AtomicBool::new(true)).unwrap_err();
    assert_eq!((error.message.as_str(), error.place.as_str()), ("the run was stopped", "stop"));
    assert!(!stopped.exists());
    // The same request with the flag unset writes the file, with a drawn seed.
    let finished = dir.path().join("finished/a.sqlite");
    let reply = run(&home, &request(&finished), &AtomicBool::new(false)).unwrap();
    assert!(finished.is_file() && reply.schedule.seed.is_some());
}
