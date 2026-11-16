//! The read routes of `bt serve`: each result route answers the rows that
//! `bt export tables` (and `bt export holdings`) write for the same result
//! file, which the `l3` test compares with the expected tables; explore,
//! catalog, screen and data status answer what the `bt` commands print, the
//! statistics with SPY's total return beside them; one trial's sector
//! weights by period give that trial's sector shares, and their counts the
//! period's holdings; each trial's cash share is its empty periods' share.

mod common;

use common::{bt_ok, fixtures, path, prepared, serve};
use serde_json::{Value, json};
use std::path::Path;

/// Whether a statistics row is one of `spy_total_return`, which only the
/// HTTP replies carry.
fn spy(row: &Value) -> bool {
    row["statistic"].as_str().unwrap().starts_with("spy_total_return.")
}

/// A reply with its `spy_total_return` statistics left out.
fn without_spy(mut reply: Value) -> Value {
    if let Some(statistics) = reply.get_mut("statistics") {
        statistics.as_array_mut().unwrap().retain(|s| !spy(s));
    }
    reply
}

/// A table file's rows without their `case`.
fn rows(dir: &Path, table: &str) -> Vec<Value> {
    let text = std::fs::read_to_string(dir.join(format!("{table}.jsonl"))).unwrap();
    text.lines()
        .map(|line| {
            let mut row: Value = serde_json::from_str(line).unwrap();
            row.as_object_mut().unwrap().remove("case");
            row
        })
        .collect()
}

#[test]
fn the_read_routes_answer_the_exported_rows_and_the_commands_replies() {
    let dir = tempfile::tempdir().unwrap();
    let home = prepared(dir.path());
    let strategy = dir.path().join("sleeves.json");
    std::fs::copy(fixtures().join("cases/builtins/hk-sleeves/strategy.json"), &strategy).unwrap();
    let (strategy, out, home_arg) = (path(&strategy), dir.path().join("out"), path(&home));
    let schedule = ["--market", "hk", "--start", "2021-07-01", "--end", "2023-06-28", "--every", "6m", "--trials", "2", "--seed", "852"];
    bt_ok(&[&["run", strategy][..], &schedule, &["--out", path(&out), "--home", home_arg]].concat());
    let result = out.join("sleeves.sqlite");
    let (tables, holdings) = (dir.path().join("tables"), dir.path().join("holdings"));
    bt_ok(&["export", "tables", path(&result), "--out", path(&tables)]);
    bt_ok(&["export", "holdings", path(&result), "--out", path(&holdings)]);

    let server = serve(&home);
    assert_eq!(bt_ok(&["save", path(&result), "--name", "sleeves", "--home", home_arg])["id"], 1);
    let api = |route: &str| server.get(&format!("/api/runs/1/{route}"));
    let each = |route: &str, field: Option<&str>| -> Vec<Value> {
        (1..=2)
            .flat_map(|trial| {
                let reply = api(&format!("{route}?trial={trial}"));
                let list = field.map_or(reply.clone(), |f| reply[f].clone());
                list.as_array().unwrap().clone()
            })
            .collect()
    };

    let trials = api("trials");
    assert_eq!(trials["trials"].as_array().unwrap(), &rows(&tables, "trials"));
    assert_eq!(without_spy(trials.clone())["statistics"].as_array().unwrap(), &rows(&tables, "statistics"));
    assert_eq!(each("periods", None), rows(&tables, "periods"));
    assert_eq!(each("holdings", Some("holdings")), rows(&holdings, "holdings"));
    assert_eq!(each("holdings", Some("steps")), rows(&tables, "steps"));
    let period: Vec<Value> = rows(&holdings, "holdings").into_iter().filter(|h| h["trial"] == 2 && h["period"] == 3).collect();
    assert_eq!(api("holdings?trial=2&period=3")["holdings"].as_array().unwrap(), &period);
    assert_eq!(api("holdings?trial=1")["sources"], json!(["source:EBITDA yield", "source:Dividend yield", "source:P/E 5-year average"]));
    assert_eq!(api("curve")["band"].as_array().unwrap(), &rows(&tables, "band"));
    assert_eq!(each("curve", Some("growth")), rows(&tables, "growth"));
    let sectors = api("sectors");
    let (all, by_trial): (Vec<Value>, Vec<Value>) = rows(&tables, "sectors").into_iter().partition(|s| s["trial"] == "all");
    assert_eq!(sectors["trials"].as_array().unwrap(), &by_trial);
    let spread: Vec<Value> = all
        .into_iter()
        .map(|mut s| {
            s.as_object_mut().unwrap().remove("trial");
            s
        })
        .collect();
    assert_eq!(sectors["spread"].as_array().unwrap(), &spread);
    // The pies' slices: the top holdings and the other gains and losses add
    // up to the exported row's net, as far as the order of addition allows.
    let attributions = each("contributions", None);
    let exported = rows(&tables, "contributions");
    assert_eq!(attributions.len(), exported.len());
    for (a, row) in attributions.iter().zip(&exported) {
        let top = a["top"].as_array().unwrap();
        let symbols: Vec<&str> = top.iter().map(|t| t["symbol"].as_str().unwrap()).collect();
        assert_eq!(symbols.join(" "), row["top"].as_str().unwrap());
        for key in ["trial", "period", "count", "gains", "losses", "net", "top_total", "other_total"] {
            assert_eq!(a[key], row[key], "{key}: {a}");
        }
        let number = |v: &Value| v.as_f64().unwrap();
        let slices = top.iter().map(|t| number(&t["contribution"])).sum::<f64>() + number(&a["other_gains"]) - number(&a["other_losses"]);
        assert!((slices - number(&row["net"])).abs() < 1e-12, "{a}");
    }
    for trial in ["1", "all"] {
        let explored = bt_ok(&["explore", path(&result), "--trial", trial, "--periods", "2-3", "--ranks", "1-4"]);
        assert_eq!(without_spy(api(&format!("explore?trial={trial}&periods=2-3&ranks=1-4"))), explored);
    }

    assert_eq!(server.get("/api/catalog/hk"), bt_ok(&["catalog", "--market", "hk", "--home", home_arg]));
    let file: Value = serde_json::from_str(&std::fs::read_to_string(strategy).unwrap()).unwrap();
    let (status, picks) = server.send("POST", "/api/screen", Some(&json!({"strategy": file, "market": "hk"})), None);
    assert_eq!((status, picks), (200, bt_ok(&["screen", strategy, "--market", "hk", "--home", home_arg])));
    assert_eq!(server.get("/api/data/status"), bt_ok(&["data", "status", "--home", home_arg]));

    let refused = |route: &str| {
        let (status, reply) = server.send("GET", route, None, None);
        (status, reply["error"]["place"].as_str().unwrap().to_string())
    };
    assert_eq!(refused("/api/runs/2/trials"), (404, "id".to_string()));
    assert_eq!(refused("/api/runs/1/periods"), (400, "trial".to_string()));
    assert_eq!(refused("/api/runs/1/periods?trial=3"), (400, "trial".to_string()));
    assert_eq!(refused("/api/runs/1/holdings?trial=1&period=99"), (400, "period".to_string()));
    assert_eq!(refused("/api/runs/1/explore?trial=1&periods=2&ranks=1-4"), (400, "periods".to_string()));
    let (status, reply) = server.send("POST", "/api/screen", Some(&json!({"strategy": {}, "market": "hk"})), None);
    assert_eq!(status, 400, "{reply}");
    assert!(reply["error"]["place"].as_str().unwrap().starts_with("strategy"), "{reply}");
    assert!(server.terminate());
}

#[test]
fn one_trials_sector_weights_by_period_average_to_its_sector_shares() {
    let dir = tempfile::tempdir().unwrap();
    let home = prepared(dir.path());
    let strategy = dir.path().join("sleeves.json");
    std::fs::copy(fixtures().join("cases/builtins/hk-sleeves/strategy.json"), &strategy).unwrap();
    let (out, home_arg) = (dir.path().join("out"), path(&home));
    let schedule = ["--market", "hk", "--start", "2021-07-01", "--end", "2023-06-28", "--every", "6m", "--trials", "2", "--seed", "852"];
    bt_ok(&[&["run", path(&strategy)][..], &schedule, &["--out", path(&out), "--home", home_arg]].concat());
    let server = serve(&home);
    bt_ok(&["save", path(&out.join("sleeves.sqlite")), "--name", "sleeves", "--home", home_arg]);
    let all = server.get("/api/runs/1/sectors");
    assert_eq!(all.as_object().unwrap().keys().collect::<Vec<_>>(), ["cash", "mean_cash", "spread", "trials"]);
    for trial in 1..=2 {
        let periods = server.get(&format!("/api/runs/1/periods?trial={trial}")).as_array().unwrap().len() as f64;
        let weights = server.get(&format!("/api/runs/1/sectors?trial={trial}"))["weights"].as_array().unwrap().clone();
        let shares: Vec<&Value> = all["trials"].as_array().unwrap().iter().filter(|s| s["trial"] == trial).collect();
        assert!(!shares.is_empty());
        for share in shares {
            let held: Vec<f64> = weights.iter().filter(|w| w["sector"] == share["sector"]).map(|w| w["weight"].as_f64().unwrap()).collect();
            assert_eq!(held.len() as u64, share["present"].as_u64().unwrap(), "{share}");
            assert_eq!(held.iter().sum::<f64>() / periods, share["mean"].as_f64().unwrap(), "{share}");
        }
    }
    assert!(server.terminate());
}

#[test]
fn the_trials_replies_give_spys_total_return_and_the_exported_statistics_do_not() {
    let dir = tempfile::tempdir().unwrap();
    let home = prepared(dir.path());
    let strategy = dir.path().join("sleeves.json");
    std::fs::copy(fixtures().join("cases/builtins/hk-sleeves/strategy.json"), &strategy).unwrap();
    let (out, home_arg) = (dir.path().join("out"), path(&home));
    let schedule = ["--market", "hk", "--start", "2021-07-01", "--end", "2023-06-28", "--every", "6m", "--trials", "3", "--seed", "852"];
    bt_ok(&[&["run", path(&strategy)][..], &schedule, &["--out", path(&out), "--home", home_arg]].concat());
    let (result, tables) = (out.join("sleeves.sqlite"), dir.path().join("tables"));
    bt_ok(&["export", "tables", path(&result), "--out", path(&tables)]);
    assert!(!rows(&tables, "statistics").iter().any(spy));
    let explored = bt_ok(&["explore", path(&result), "--trial", "all", "--periods", "1-3", "--ranks", "1-4"]);
    assert!(!explored["statistics"].as_array().unwrap().iter().any(spy));

    let server = serve(&home);
    bt_ok(&["save", path(&result), "--name", "sleeves", "--home", home_arg]);
    let trials = server.get("/api/runs/1/trials");
    let explore = server.get("/api/runs/1/explore?trial=all&periods=1-3&ranks=1-4");
    for (reply, trials) in [(&trials["statistics"], &trials["trials"]), (&explore["statistics"], &explore["trials"])] {
        let mut returns: Vec<f64> = trials.as_array().unwrap().iter().map(|t| t["spy_growth"].as_f64().unwrap() - 1.0).collect();
        returns.sort_by(f64::total_cmp);
        let value = |name: &str| reply.as_array().unwrap().iter().find(|s| s["statistic"] == format!("spy_total_return.{name}")).unwrap()["value"].clone();
        assert_eq!(value("n"), 3);
        assert_eq!([value("min"), value("median"), value("max")], [returns[0], returns[1], returns[2]].map(Value::from));
        assert_eq!(reply.as_array().unwrap().iter().filter(|s| spy(s)).count(), 10);
    }
    assert!(server.terminate());
}

/// A server on a prepared home whose run 1 is `bt run` of a fictional case's
/// strategy file on `schedule`.
fn served(dir: &Path, case: &str, schedule: &[&str]) -> common::Server {
    let home = prepared(dir);
    let strategy = dir.join("case.json");
    std::fs::copy(fixtures().join(format!("cases/builtins/{case}/strategy.json")), &strategy).unwrap();
    let out = dir.join("out");
    bt_ok(&[&["run", path(&strategy)][..], schedule, &["--out", path(&out), "--home", path(&home)]].concat());
    let server = serve(&home);
    bt_ok(&["save", path(&out.join("case.sqlite")), "--name", case, "--home", path(&home)]);
    server
}

#[test]
fn a_periods_sector_counts_add_up_to_its_holdings_and_give_the_weights() {
    let dir = tempfile::tempdir().unwrap();
    let schedule = ["--market", "hk", "--start", "2021-07-01", "--end", "2023-06-28", "--every", "6m", "--trials", "2", "--seed", "852"];
    let server = served(dir.path(), "hk-sleeves", &schedule);
    for trial in 1..=2 {
        let weights = server.get(&format!("/api/runs/1/sectors?trial={trial}"))["weights"].as_array().unwrap().clone();
        for period in server.get(&format!("/api/runs/1/periods?trial={trial}")).as_array().unwrap() {
            let names = period["names"].as_u64().unwrap();
            let held: Vec<&Value> = weights.iter().filter(|w| w["period"] == period["period"]).collect();
            assert_eq!(held.iter().map(|w| w["count"].as_u64().unwrap()).sum::<u64>(), names, "{period}");
            for w in held {
                assert_eq!(w["weight"].as_f64().unwrap(), w["count"].as_f64().unwrap() / names as f64, "{w}");
            }
        }
    }
    assert!(server.terminate());
}

#[test]
fn each_trials_cash_is_the_share_of_its_periods_that_hold_no_stock() {
    let dir = tempfile::tempdir().unwrap();
    // Trial 2 of this schedule holds no stock in one of its four periods.
    let schedule = ["--market", "jp", "--start", "2021-07-01", "--end", "2023-06-28", "--every", "6m", "--trials", "3", "--seed", "6"];
    let server = served(dir.path(), "jp-built-ins-months", &schedule);
    let (sectors, trials) = (server.get("/api/runs/1/sectors"), server.get("/api/runs/1/trials"));
    let expected: Vec<Value> = trials["trials"]
        .as_array()
        .unwrap()
        .iter()
        .map(|t| json!({"trial": t["trial"], "cash": t["empty_periods"].as_f64().unwrap() / t["periods"].as_f64().unwrap()}))
        .collect();
    assert_eq!(sectors["cash"].as_array().unwrap(), &expected);
    assert!(expected.iter().any(|t| t["cash"].as_f64().unwrap() > 0.0), "{expected:?}");
    let mean = expected.iter().map(|t| t["cash"].as_f64().unwrap()).sum::<f64>() / 3.0;
    assert_eq!(sectors["mean_cash"].as_f64().unwrap(), mean);
    assert!(server.terminate());
}
