//! `bt export cross-section`: its variable columns equal the oracle's
//! formula values (the expected table `formula_values` of `proof/l3.py`),
//! bit for bit and null for null, for every case of kind `formulas`; its
//! returns are those a run's holdings get; and an `at` date after the screen
//! day stops a run only when a candidate reaches its formula.
//!
//! The proof's folders are the `l3` test's (`L3_CASES`, `L3_EXPECTED`,
//! `L3_HOME`). The oracle's table of a long random case may hold only its
//! first trials' entry days: set `L3_TRIALS` to export at most that many
//! trials (random dates are drawn trial by trial, so the days are the same).

mod common;

use common::{Proof, bt, bt_ok, path, prepared, read, schedule};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
use std::io::{BufRead, BufReader, Write};
use std::path::Path;
use tables::Cell;

const KEYS: [&str; 4] = ["case", "day", "symbol", "variable"];

/// Reads a table file line by line.
fn rows(file: &Path) -> impl Iterator<Item = Value> {
    BufReader::new(std::fs::File::open(file).unwrap()).lines().map(|line| serde_json::from_str(&line.unwrap()).unwrap())
}

#[test]
fn cross_section_variables_equal_the_oracles_formula_values() {
    let dir = tempfile::tempdir().unwrap();
    let proof = Proof::new(dir.path());
    // (case, day, symbol, variable): value, from each case's cross-section.
    let mut actual: BTreeMap<[String; 4], Value> = BTreeMap::new();
    for case in proof.cases.iter().filter(|case| common::kind(case) == "formulas") {
        let name = common::name(case);
        let mut settings = read(case, "run.json");
        if let (Some(trials), Ok(most)) = (settings.get("trials"), std::env::var("L3_TRIALS")) {
            settings["trials"] = trials.as_u64().unwrap().min(most.parse().unwrap()).into();
        }
        let out = dir.path().join("sections").join(&name);
        let strategy = case.join("strategy.json");
        let mut args = vec!["export".to_string(), "cross-section".into(), strategy.display().to_string()];
        args.extend(schedule(&settings));
        args.extend(["--out".into(), out.display().to_string(), "--home".into(), proof.home.display().to_string()]);
        bt_ok(&args.iter().map(String::as_str).collect::<Vec<_>>());
        for row in rows(&out.join("cross_section.jsonl")) {
            for (field, value) in row.as_object().unwrap() {
                if let Some(variable) = field.strip_prefix("variable:") {
                    let key = [name.clone(), row["day"].as_str().unwrap().into(), row["symbol"].as_str().unwrap().into(), variable.into()];
                    // A day with several exits repeats its values.
                    assert!(actual.insert(key, value.clone()).is_none_or(|v| v == *value));
                }
            }
        }
    }
    let cases: BTreeSet<&String> = actual.keys().map(|k| &k[0]).collect();
    if cases.is_empty() {
        eprintln!("no case of kind formulas");
        return;
    }

    let manifest = json!({ "producer": "test", "settings": null, "tables": { "formula_values": KEYS } }).to_string();
    let expected = dir.path().join("expected");
    std::fs::create_dir(&expected).unwrap();
    std::fs::write(expected.join("manifest.json"), &manifest).unwrap();
    let mut kept = std::io::BufWriter::new(std::fs::File::create(expected.join("formula_values.jsonl")).unwrap());
    for line in BufReader::new(std::fs::File::open(proof.expected.join("formula_values.jsonl")).unwrap()).lines() {
        let line = line.unwrap();
        let row: Value = serde_json::from_str(&line).unwrap();
        if cases.contains(&row["case"].as_str().unwrap().to_string()) {
            writeln!(kept, "{line}").unwrap();
        }
    }
    kept.flush().unwrap();

    let mut writer = tables::Writer::create(&dir.path().join("actual"), "test", Value::Null).unwrap();
    let mut table = writer.table("formula_values", &KEYS).unwrap();
    for ([case, day, symbol, variable], value) in &actual {
        let value = value.as_f64().map_or(Cell::Null, Cell::Number);
        let fields = [("case", Cell::Text(case)), ("day", Cell::Text(day)), ("symbol", Cell::Text(symbol)), ("variable", Cell::Text(variable))];
        table.row(&[fields[0], fields[1], fields[2], fields[3], ("value", value)]).unwrap();
    }
    table.finish().unwrap();
    writer.finish().unwrap();

    let report = tables::compare(&expected, &dir.path().join("actual")).unwrap();
    for table in &report.tables {
        eprintln!("{}: {} rows compared", table.name, table.compared);
    }
    assert!(report.equal(), "{cases:?}: {:#?}", report.tables);
}

#[test]
fn a_cross_section_row_has_the_return_a_holding_gets() {
    let dir = tempfile::tempdir().unwrap();
    let home = prepared(dir.path());
    let file = dir.path().join("value.json");
    let rank = json!({"rank": "EBITDA yield", "order": "highest", "from": 1, "to": 5});
    std::fs::write(&file, json!({ "sleeves": [{ "steps": [rank] }] }).to_string()).unwrap();
    // Two random trials: some entry days have two exits.
    let schedule = ["--market", "hk", "--start", "2021-07-01", "--end", "2023-06-28", "--every", "6m", "--random", "2", "--seed", "852"];
    let (results, tables, section) = (dir.path().join("results"), dir.path().join("tables"), dir.path().join("section"));
    bt_ok(&[&["run", path(&file)], &schedule[..], &["--out", path(&results), "--home", path(&home)]].concat());
    bt_ok(&["export", "tables", path(&results.join("value.sqlite")), "--out", path(&tables)]);
    bt_ok(&[&["export", "cross-section", path(&file)], &schedule[..], &["--out", path(&section), "--home", path(&home)]].concat());

    let returns: BTreeMap<(String, String, String), Value> = rows(&section.join("cross_section.jsonl"))
        .map(|row| ((row["day"].to_string(), row["exit"].to_string(), row["symbol"].to_string()), row["return"].clone()))
        .collect();
    let periods: BTreeMap<(String, String), (String, String)> = rows(&tables.join("periods.jsonl"))
        .map(|p| ((p["trial"].to_string(), p["period"].to_string()), (p["entry"].to_string(), p["exit"].to_string())))
        .collect();
    let mut held = 0;
    for h in rows(&tables.join("holdings.jsonl")) {
        let (entry, exit) = periods[&(h["trial"].to_string(), h["period"].to_string())].clone();
        assert_eq!(returns[&(entry, exit, h["symbol"].to_string())], h["return"], "{h}");
        held += 1;
    }
    assert!(held > 0);

    // USDJPY has no fixing from 2021-06-21 to 2021-07-02: no Tokyo candidate
    // of 2021-06-01 has an exit price on 2021-07-01, where a run would stop.
    let jp = dir.path().join("jp");
    let dates = ["--market", "jp", "--start", "2021-06-01", "--end", "2021-07-01", "--dates", "2021-06-01"];
    bt_ok(&[&["export", "cross-section", path(&file)], &dates[..], &["--out", path(&jp), "--home", path(&home)]].concat());
    let row = rows(&jp.join("cross_section.jsonl")).find(|row| row["symbol"] == "7102.T").unwrap();
    assert_eq!(row["return"], Value::Null, "{row}");
}

#[test]
fn a_future_date_stops_a_run_only_when_a_candidate_reaches_it() {
    let dir = tempfile::tempdir().unwrap();
    let home = prepared(dir.path());
    // `at( )` reads a day after the screen day, in a Rank step that a
    // filter keeps from every candidate, or not.
    let run = |name: &str, floor: &str| {
        let file = dir.path().join(format!("{name}.json"));
        let strategy = json!({
            "variables": { "Later revenue": { "formula": "at(Revenue, 2022-12-30)" } },
            "sleeves": [{ "steps": [
                { "filter": "Market cap in dollars", "op": ">=", "value": floor },
                { "rank": "Later revenue", "order": "highest", "from": 1, "to": 3 }
            ] }]
        });
        std::fs::write(&file, strategy.to_string()).unwrap();
        let schedule = ["--market", "us", "--start", "2021-07-01", "--end", "2023-06-28", "--dates", "2022-07-01,2023-01-02"];
        let out = dir.path().join(name);
        let ran = bt(&[&["run", path(&file)], &schedule[..], &["--out", path(&out), "--home", path(&home)]].concat());
        let section = out.with_extension("section");
        let exported = bt(&[&["export", "cross-section", path(&file)], &schedule[..], &["--out", path(&section), "--home", path(&home)]].concat());
        (ran, exported)
    };
    let ((reply, success), (section, exported)) = run("unreached", "1000000000000000");
    assert!(success, "{reply}");
    // The cross-section evaluates every variable for every candidate.
    assert!(!exported);
    assert!(section["error"]["place"].as_str().unwrap().contains(": us, 2022-07-01, "), "{section}");

    let ((reply, success), _) = run("reached", "0");
    assert!(!success);
    let place = reply["error"]["place"].as_str().unwrap();
    assert!(place.contains("reached.json: us, trial 1, 2022-07-01, ") && place.ends_with(", Later revenue"), "{reply}");
    assert!(reply["error"]["message"].as_str().unwrap().contains("FUTURE_DATE"), "{reply}");
}
