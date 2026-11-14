//! `bt data prepare` of the fictional raw cache equals the oracle: each
//! market's export equals the oracle's tables in
//! `fixtures/fictional/expected/<market>/`, row for row and bit for bit.

use serde_json::{Value, json};
use std::path::{Path, PathBuf};
use std::process::Command;

/// The tables `bt data export` writes, per market. A kind of data adds its
/// tables here when it is built.
const TABLES: [(&str, &[&str]); 3] = [
    ("us", &["companies", "sessions", "market_days", "stock_days", "reports", "annual_facts", "annual_metadata", "valuation_sums"]),
    ("hk", &["companies", "sessions", "market_days", "fx_days", "stock_days", "reports", "annual_facts", "annual_metadata", "valuation_sums"]),
    ("jp", &["companies", "sessions", "market_days", "fx_days", "stock_days", "reports", "annual_facts", "annual_metadata", "valuation_sums"]),
];

/// The as-of time of the expected tables: the Hong Kong session of the last
/// day has not closed yet.
const AS_OF: &str = "2023-06-30T07:30:00+00:00";

fn fixtures() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../fixtures/fictional")
}

fn bt(home: &Path, args: &[&str]) -> Value {
    let output = Command::new(env!("CARGO_BIN_EXE_bt")).args(args).arg("--home").arg(home).output().expect("run bt");
    let reply: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert!(output.status.success(), "bt {args:?}: {reply}");
    reply
}

/// A copy of the expected export of `market` that holds only `tables`.
fn expected(market: &str, tables: &[&str], dir: &Path) -> PathBuf {
    let source = fixtures().join("expected").join(market);
    let target = dir.join("expected").join(market);
    std::fs::create_dir_all(&target).unwrap();
    let manifest: Value = serde_json::from_str(&std::fs::read_to_string(source.join("manifest.json")).unwrap()).unwrap();
    let keys: serde_json::Map<String, Value> = tables.iter().map(|&t| (t.to_string(), manifest["tables"][t].clone())).collect();
    std::fs::write(target.join("manifest.json"), json!({ "tables": keys }).to_string()).unwrap();
    for table in tables {
        std::fs::copy(source.join(format!("{table}.jsonl")), target.join(format!("{table}.jsonl"))).unwrap();
    }
    target
}

#[test]
fn the_fictional_raw_cache_prepares_to_the_oracle_tables() {
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
    for (market, tables) in TABLES {
        let actual = dir.path().join("actual").join(market);
        bt(&home, &["data", "export", "--market", market, "--out", actual.to_str().unwrap()]);
        let report = tables::compare(&expected(market, tables, dir.path()), &actual).unwrap();
        assert!(report.equal(), "{market}: {:#?}", report.tables.iter().filter(|t| !t.equal()).collect::<Vec<_>>());
    }
}
