//! `bt explore`: its argument rules, and a selection of whole trials that
//! gives the stored results; `bt export holdings`: a column for each numeric
//! source of the steps; `bt catalog`: a name and the market's sectors, and
//! the heading of each name.

mod common;

use common::{bt, path, prepared};
use serde_json::{Value, json};

#[test]
fn explore_holdings_and_the_catalog_read_a_run_and_its_market() {
    let dir = tempfile::tempdir().unwrap();
    let home = prepared(dir.path());
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
    let (random, result) = run("random", &["--every", "6m", "--trials", "2", "--seed", "1"]);
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
    let median = all["statistics"].as_array().unwrap().iter().find(|s| s["statistic"] == "cagr.median").unwrap();
    assert_eq!(median["value"], random["runs"][0]["median"]);
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

#[test]
fn the_catalog_gives_each_name_the_heading_it_is_listed_under() {
    let dir = tempfile::tempdir().unwrap();
    let home = prepared(dir.path());
    let (catalog, success) = bt(&["catalog", "--market", "us", "--home", path(&home)]);
    assert!(success, "{catalog}");
    let names = catalog["names"].as_array().unwrap();
    let heading = |name: &str| names.iter().find(|n| n["name"] == name).unwrap()["category"].clone();
    let expected = [
        ("Revenue", "Income statement"),
        ("Diluted EPS", "Income statement"),
        ("Net debt", "Balance sheet"),
        ("CapEx", "Cash flow"),
        ("Treasury 10 year yield", "Market"),
        ("Market cap", "Market"),
        ("P/E", "Valuation"),
        ("Turnover rate 1-week average", "Valuation"),
        ("Gross margin", "Margins and returns"),
        ("Debt/assets", "Debt and liquidity"),
        ("Free cash flow", "Built-in values"),
        ("Sector", "Size and listing"),
        ("Enterprise value in dollars", "Size and listing"),
    ];
    for (name, category) in expected {
        assert_eq!(heading(name), category, "{name}");
    }
}
