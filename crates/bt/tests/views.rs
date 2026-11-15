//! `bt explore`: its argument rules, and a selection of whole trials that
//! gives the stored results; `bt export holdings`: a column for each numeric
//! source of the steps; `bt catalog`: a name and the market's sectors, and
//! the heading of each name; `bt screen`: each pick's price and report
//! dates, and the medians of the picks.

mod common;

use common::{bt, bt_ok, fixtures, path, prepared};
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

/// `bt screen` of the fictional Hong Kong sleeves on the latest session.
fn screen_sleeves(dir: &std::path::Path, strategy: &std::path::Path) -> Value {
    let home = prepared(dir);
    bt_ok(&["screen", path(strategy), "--market", "hk", "--home", path(&home)])
}

#[test]
fn a_pick_gives_the_price_and_report_dates_of_the_oracles_latest_candidate() {
    let dir = tempfile::tempdir().unwrap();
    let screen = screen_sleeves(dir.path(), &fixtures().join("cases/builtins/hk-sleeves/strategy.json"));
    let text = std::fs::read_to_string(fixtures().join("expected/hk/candidates.jsonl")).unwrap();
    let latest: Vec<Value> = text.lines().map(|l| serde_json::from_str::<Value>(l).unwrap()).filter(|c| c["screen"] == "latest" && c["day"] == screen["day"]).collect();
    let picks = screen["picks"].as_array().unwrap();
    assert!(!picks.is_empty());
    for pick in picks {
        let candidate = latest.iter().find(|c| c["symbol"] == pick["symbol"]).unwrap();
        assert_eq!([&pick["known"], &pick["price"], &pick["price_date"]], [&candidate["known"], &candidate["price"], &candidate["entry"]], "{pick}");
    }
}

#[test]
fn the_screen_gives_the_median_market_cap_and_ebitda_yield_of_its_picks() {
    let dir = tempfile::tempdir().unwrap();
    let screen = screen_sleeves(dir.path(), &fixtures().join("cases/builtins/hk-sleeves/strategy.json"));
    let median = |field: &str| {
        let mut values: Vec<f64> = screen["picks"].as_array().unwrap().iter().map(|p| p[field].as_f64().unwrap()).collect();
        values.sort_by(f64::total_cmp);
        let middle = values.len() / 2;
        if values.len() % 2 == 1 { values[middle] } else { (values[middle - 1] + values[middle]) / 2.0 }
    };
    assert_eq!(screen["median_market_cap"], median("market_cap"));
    assert_eq!(screen["median_ebitda_yield"], median("ebitda_yield"));

    let none = dir.path().join("none.json");
    let steps = json!([{"filter": "Market cap in dollars", "op": ">=", "value": "1e20"}, {"rank": "EBITDA yield", "order": "highest", "from": 1, "to": 3}]);
    std::fs::write(&none, json!({"sleeves": [{"steps": steps}]}).to_string()).unwrap();
    let empty = bt_ok(&["screen", path(&none), "--market", "hk", "--home", path(&dir.path().join("home"))]);
    assert!(empty["picks"].as_array().unwrap().is_empty());
    assert!(empty.get("median_market_cap").is_none() && empty.get("median_ebitda_yield").is_none(), "{empty}");
}
