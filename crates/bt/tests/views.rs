//! `bt explore`: its argument rules, and a selection of whole trials that
//! gives the stored results; `bt export holdings`: a column for each numeric
//! source of the steps; `bt catalog`: a name and the market's sectors.

use serde_json::{Value, json};
use std::path::Path;
use std::process::Command;

/// Runs `bt`; returns its reply and whether it succeeded.
fn bt(args: &[&str]) -> (Value, bool) {
    let output = Command::new(env!("CARGO_BIN_EXE_bt")).args(args).output().expect("run bt");
    (serde_json::from_slice(&output.stdout).unwrap(), output.status.success())
}

fn path(p: &Path) -> &str {
    p.to_str().unwrap()
}

#[test]
fn explore_holdings_and_the_catalog_read_a_run_and_its_market() {
    let dir = tempfile::tempdir().unwrap();
    let home = dir.path().join("home");
    std::fs::create_dir(&home).unwrap();
    let raw = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../fixtures/fictional/raw");
    std::os::unix::fs::symlink(raw.canonicalize().unwrap(), home.join("raw")).unwrap();
    assert!(bt(&["data", "prepare", "--as-of", "2023-06-30T07:30:00+00:00", "--home", path(&home)]).1);
    let file = dir.path().join("value.json");
    let steps = json!([
        {"filter": "Market cap in dollars", "op": ">=", "value": "100000000"},
        {"filter": "EBITDA yield", "op": ">=", "value": "0"},
        {"rank": "EBITDA yield", "order": "highest", "from": 1, "to": 5}
    ]);
    std::fs::write(&file, json!({ "sleeves": [{ "steps": steps }] }).to_string()).unwrap();
    let run = |out: &str, schedule: &[&str]| {
        let out = dir.path().join(out);
        let mut args = vec!["run", path(&file), "--market", "hk", "--start", "2021-07-01", "--end", "2023-06-28"];
        args.extend(schedule);
        args.extend(["--out", path(&out), "--home", path(&home)]);
        let (reply, success) = bt(&args);
        assert!(success, "{reply}");
        (reply, out.join("value.sqlite").display().to_string())
    };
    let (random, result) = run("random", &["--every", "6m", "--random", "2", "--seed", "1"]);
    let (_, fixed) = run("fixed", &["--every", "6m"]);

    let explore = |result: &str, trial: &str, periods: &str, ranks: &str| {
        bt(&["explore", result, "--trial", trial, "--periods", periods, "--ranks", ranks])
    };
    let refused = |result: &str, trial: &str, periods: &str, ranks: &str| {
        let (reply, success) = explore(result, trial, periods, ranks);
        assert!(!success, "{reply}");
        reply["error"]["place"].as_str().unwrap().to_string()
    };
    assert_eq!(refused(&result, "0", "1-2", "1-5"), "trial");
    assert_eq!(refused(&result, "3", "1-2", "1-5"), "trial");
    assert_eq!(refused(&fixed, "all", "1-2", "1-5"), "trial");
    assert_eq!(refused(&result, "1", "3-1", "1-5"), "periods");
    assert_eq!(refused(&result, "all", "1-99", "1-5"), "periods");
    assert_eq!(refused(&result, "1", "1-2", "0-5"), "ranks");
    assert_eq!(refused(&result, "1", "1-2", "1-6"), "ranks");

    let (one, success) = explore(&result, "2", "1-4", "1-5");
    assert!(success, "{one}");
    assert_eq!(one["cagr"], random["runs"][0]["cagr"][1]);
    let (all, success) = explore(&result, "all", "1-4", "1-5");
    assert!(success, "{all}");
    assert_eq!(all["statistics"]["cagr.median"], random["runs"][0]["median"]);
    assert_eq!(all["trials"][0]["last_exit"], Value::Null);

    let out = dir.path().join("holdings");
    let (reply, success) = bt(&["export", "holdings", &result, "--out", path(&out)]);
    assert!(success && reply["tables"]["holdings"].as_u64().unwrap() > 0, "{reply}");
    for line in std::fs::read_to_string(out.join("holdings.jsonl")).unwrap().lines() {
        let row: Value = serde_json::from_str(line).unwrap();
        // The Rank step's value is the ranking value; a field has no column.
        assert_eq!(row["source:EBITDA yield"], row["ranking_value"], "{row}");
        assert!(row.get("source:Market cap in dollars").is_none(), "{row}");
    }

    let (catalog, success) = bt(&["catalog", "--market", "hk", "--home", path(&home)]);
    assert!(success, "{catalog}");
    let fcf = catalog["names"].as_array().unwrap().iter().find(|n| n["name"] == "Free cash flow").unwrap();
    assert_eq!((&fcf["step_only"], &fcf["unit"]), (&json!(true), &json!("USD")), "{fcf}");
    assert_eq!(catalog["sectors"], json!(["Financial Services", "Industrials", "Real Estate", "Utilities"]));
}
