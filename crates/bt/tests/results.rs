//! The read routes of `bt serve`: each result route answers the rows that
//! `bt export tables` (and `bt export holdings`) write for the same result
//! file, which the proof tests compare with the oracle's; explore, catalog,
//! screen and data status answer what the `bt` commands print.

mod common;

use common::{bt_ok, fixtures, path, prepared, serve};
use serde_json::{Value, json};
use std::path::Path;

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
    assert_eq!(trials["statistics"].as_array().unwrap(), &rows(&tables, "statistics"));
    assert_eq!(each("periods", None), rows(&tables, "periods"));
    assert_eq!(each("holdings", Some("holdings")), rows(&holdings, "holdings"));
    assert_eq!(each("holdings", Some("steps")), rows(&tables, "steps"));
    let period: Vec<Value> = rows(&holdings, "holdings").into_iter().filter(|h| h["trial"] == 2 && h["period"] == 3).collect();
    assert_eq!(api("holdings?trial=2&period=3")["holdings"].as_array().unwrap(), &period);
    assert_eq!(api("holdings?trial=1")["sources"], json!(["source:EBITDA yield", "source:Dividend yield", "source:P/E 5-year average"]));
    assert_eq!(api("curve").as_array().unwrap(), &rows(&tables, "band"));
    assert_eq!(each("curve", None), rows(&tables, "growth"));
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
    assert_eq!(each("contributions", None), rows(&tables, "contributions"));
    for trial in ["1", "all"] {
        let explored = bt_ok(&["explore", path(&result), "--trial", trial, "--periods", "2-3", "--ranks", "1-4"]);
        assert_eq!(api(&format!("explore?trial={trial}&periods=2-3&ranks=1-4")), explored);
    }

    assert_eq!(server.get("/api/catalog/hk"), bt_ok(&["catalog", "--market", "hk", "--home", home_arg]));
    let text = std::fs::read_to_string(strategy).unwrap();
    let (status, picks) = server.send("POST", "/api/screen", Some(&json!({"strategy": text, "market": "hk"})), None);
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
    let (status, reply) = server.send("POST", "/api/screen", Some(&json!({"strategy": "{}", "market": "hk"})), None);
    assert_eq!(status, 400, "{reply}");
    assert!(reply["error"]["place"].as_str().unwrap().starts_with("strategy"), "{reply}");
    assert!(server.terminate());
}
