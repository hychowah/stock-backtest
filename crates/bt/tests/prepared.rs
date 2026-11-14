//! `bt data prepare` of the fictional raw cache equals the oracle: each
//! market's export of the days in its `days.txt` equals the oracle's tables
//! in `fixtures/fictional/expected/<market>/`, row for row and bit for bit;
//! and `bt data inspect` explains a stale report and a day that is not a
//! session. One test does both, so the inspect checks reuse the prepared home.

use serde_json::{Value, json};
use std::path::{Path, PathBuf};
use std::process::Command;

const MARKETS: [&str; 3] = ["us", "hk", "jp"];

/// The as-of time of the expected tables: the Hong Kong session of the last
/// day has not closed yet.
const AS_OF: &str = "2023-06-30T07:30:00+00:00";

fn fixtures() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../fixtures/fictional")
}

/// Runs `bt`; returns its reply and whether it succeeded.
fn run(home: &Path, args: &[&str]) -> (Value, bool) {
    let output = Command::new(env!("CARGO_BIN_EXE_bt")).args(args).arg("--home").arg(home).output().expect("run bt");
    (serde_json::from_slice(&output.stdout).unwrap(), output.status.success())
}

fn bt(home: &Path, args: &[&str]) -> Value {
    let (reply, success) = run(home, args);
    assert!(success, "bt {args:?}: {reply}");
    reply
}

#[test]
fn the_fictional_raw_cache_prepares_to_the_oracle_tables_and_inspect_explains_its_rows() {
    let dir = tempfile::tempdir().unwrap();
    let home = dir.path().join("home");
    std::fs::create_dir(&home).unwrap();
    std::os::unix::fs::symlink(fixtures().join("raw").canonicalize().unwrap(), home.join("raw")).unwrap();
    let reply = bt(&home, &["data", "prepare", "--as-of", AS_OF]);
    let last: Vec<&Value> = reply["markets"].as_array().unwrap().iter().map(|m| &m["last_session"]).collect();
    assert_eq!(last, [&json!("2023-06-30"), &json!("2023-06-29"), &json!("2023-06-30")]);
    let status = bt(&home, &["data", "status"]);
    for (prepared, market) in reply["markets"].as_array().unwrap().iter().zip(status["markets"].as_array().unwrap()) {
        for field in ["companies", "first_session", "last_session"] {
            assert_eq!(market["prepared"][field], prepared[field], "{} {field}", prepared["market"]);
        }
    }
    for market in MARKETS {
        let (expected, actual) = (fixtures().join("expected").join(market), dir.path().join("actual").join(market));
        let days = expected.join("days.txt");
        bt(&home, &["data", "export", "--market", market, "--out", actual.to_str().unwrap(), "--days", days.to_str().unwrap()]);
        let report = tables::compare(&expected, &actual).unwrap();
        assert!(report.equal(), "{market}: {:#?}", report.tables.iter().filter(|t| !t.equal()).collect::<Vec<_>>());
    }

    // QST's last report, of 2019-12-31, is older than 800 days after 2022-03-10.
    let inspect = |day: &str| run(&home, &["data", "inspect", "--market", "us", "--symbol", "QST", "--day", day]);
    let (current, _) = inspect("2022-03-10");
    assert_eq!(current["report"]["fiscal"], json!("2019-12-31"));
    assert!(current["candidate"].is_object(), "{current}");
    let (stale, _) = inspect("2022-03-11");
    assert_eq!((&stale["report"], &stale["denial"]["reason"]), (&Value::Null, &json!("NO_ELIGIBLE_REPORT")), "{stale}");
    let (weekend, success) = inspect("2022-03-12");
    assert!(!success);
    let message = weekend["error"]["message"].as_str().unwrap();
    assert!(message.contains("2022-03-11") && message.contains("2022-03-14"), "{message}");
}
