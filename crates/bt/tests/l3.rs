//! Whole runs equal the oracle's: each case runs through `bt run` with the
//! schedule of its `run.json`; `bt export tables` of the results, `bt
//! explore` of each result with the oracle's selections, and `bt screen` of
//! each strategy file equal the expected tables of those cases
//! (`proof/l3.py`), row for row and bit for bit.
//!
//! A case is a folder holding `strategy.json` and `run.json`; its name is the
//! case name. Every case found is run. The explore selections need at
//! least two periods in each trial and a strategy that holds at least two
//! ranks. The expected folder may hold other cases and tables: only the rows
//! of the cases found, in the tables below, are compared.
//!
//! The folders default to the fictional fixture. To run the same test
//! elsewhere, such as on real data with `cargo test --release`, set
//! `L3_CASES` (the folder of case folders), `L3_EXPECTED` (the expected
//! tables) and `L3_HOME` (a prepared home).

use serde_json::{Map, Value};
use std::collections::{BTreeMap, BTreeSet};
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::Command;

/// The tables `bt export tables` writes.
const EXPORTED: [&str; 10] =
    ["trials", "statistics", "periods", "holdings", "steps", "curve", "growth", "band", "sectors", "contributions"];
/// The tables this test writes from `bt explore` and `bt screen`.
const READ: [&str; 3] = ["explore", "picks", "pick_steps"];

/// The as-of time of the fictional expected tables.
const AS_OF: &str = "2023-06-30T07:30:00+00:00";

fn fixtures() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../fixtures/fictional")
}

fn folder(variable: &str, default: PathBuf) -> PathBuf {
    std::env::var_os(variable).map_or(default, PathBuf::from)
}

fn bt(args: &[&str]) -> Value {
    let output = Command::new(env!("CARGO_BIN_EXE_bt")).args(args).output().expect("run bt");
    let reply: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert!(output.status.success(), "bt {args:?}: {reply}");
    reply
}

/// The `bt run` schedule arguments of a case's run settings.
fn schedule(settings: &Value) -> Vec<String> {
    let text = |key: &str| settings[key].as_str().unwrap().to_string();
    let mut args = vec!["--market".into(), text("market"), "--start".into(), text("start"), "--end".into(), text("end")];
    if let Some(dates) = settings.get("dates") {
        let dates: Vec<&str> = dates.as_array().unwrap().iter().map(|d| d.as_str().unwrap()).collect();
        args.extend(["--dates".into(), dates.join(",")]);
    } else {
        args.extend(["--every".into(), text("interval")]);
    }
    if let Some(trials) = settings.get("trials") {
        args.extend(["--random".into(), trials.to_string(), "--seed".into(), settings["seed"].to_string()]);
    }
    args
}

/// The expected rows of `cases` in the compared tables, as an export folder.
fn expected(source: &Path, cases: &BTreeSet<String>, out: &Path) {
    std::fs::create_dir(out).unwrap();
    let mut manifest: Value = serde_json::from_slice(&std::fs::read(source.join("manifest.json")).unwrap()).unwrap();
    let tables = || EXPORTED.iter().chain(&READ);
    manifest["tables"].as_object_mut().unwrap().retain(|name, _| tables().any(|t| t == name));
    std::fs::write(out.join("manifest.json"), manifest.to_string()).unwrap();
    for table in tables() {
        let file = format!("{table}.jsonl");
        let mut kept = std::io::BufWriter::new(std::fs::File::create(out.join(&file)).unwrap());
        for line in BufReader::new(std::fs::File::open(source.join(&file)).unwrap()).lines() {
            let line = line.unwrap();
            let row: Value = serde_json::from_str(&line).unwrap();
            if cases.contains(row["case"].as_str().unwrap()) {
                writeln!(kept, "{line}").unwrap();
            }
        }
    }
}

/// The ranks a period of the strategy file can hold (`selection.rank_range`).
fn rank_range(strategy: &Value) -> (u64, u64) {
    let sleeves = strategy["sleeves"].as_array().unwrap();
    let last = |sleeve: &Value| {
        let rank = sleeve["steps"].as_array().unwrap().iter().rev().find(|s| s.get("rank").is_some()).unwrap();
        (rank["from"].as_u64().unwrap(), rank["to"].as_u64().unwrap())
    };
    match sleeves.as_slice() {
        [one] => last(one),
        several => (1, several.iter().map(last).map(|(from, to)| to - from + 1).sum()),
    }
}

/// A row from a reply object: the case, then `fields` in order.
fn row(case: &str, fields: impl IntoIterator<Item = (String, Value)>) -> Map<String, Value> {
    let mut row = Map::from_iter([("case".to_string(), Value::from(case))]);
    row.extend(fields);
    row
}

/// The `explore`, `picks` and `pick_steps` rows of one case: `bt explore` of
/// its result over periods 2 to the last of trial 1 and the ranks from the
/// first to one below the last, for trial 1 and, for random dates, all
/// trials; and `bt screen` of its strategy file.
fn read_rows(case: &Path, name: &str, result: &str, periods: u64, home: &Path, rows: &mut BTreeMap<&str, Vec<Map<String, Value>>>) {
    let strategy: Value = serde_json::from_slice(&std::fs::read(case.join("strategy.json")).unwrap()).unwrap();
    let settings: Value = serde_json::from_slice(&std::fs::read(case.join("run.json")).unwrap()).unwrap();
    let (first, last) = rank_range(&strategy);
    let (periods, ranks) = (format!("2-{periods}"), format!("{first}-{}", last - 1));
    let explore = |trial: &str| bt(&["explore", result, "--trial", trial, "--periods", &periods, "--ranks", &ranks]);
    let mut explored = vec![row(name, [("selection".to_string(), Value::from("1"))].into_iter().chain(explore("1").as_object().unwrap().clone()))];
    if settings.get("trials").is_some() {
        let all = explore("all");
        let window = ["start", "end", "periods"].map(|key| (key.to_string(), all[key].clone()));
        let statistics = all["statistics"].as_object().unwrap().clone();
        explored.push(row(name, [("selection".to_string(), Value::from("all"))].into_iter().chain(window).chain(statistics)));
        for trial in all["trials"].as_array().unwrap() {
            let mut fields = trial.as_object().unwrap().clone();
            let number = fields.remove("trial").unwrap();
            let dates: Vec<&str> = trial["dates"].as_array().unwrap().iter().map(|d| d.as_str().unwrap()).collect();
            fields.insert("dates".into(), Value::from(dates.join(" ")));
            explored.push(row(name, [("selection".to_string(), Value::from(format!("all {number}")))].into_iter().chain(fields)));
        }
    }
    explored.sort_by(|a, b| a["selection"].as_str().cmp(&b["selection"].as_str()));
    rows.entry("explore").or_default().extend(explored);
    let file = case.join("strategy.json");
    let screen = bt(&["screen", file.to_str().unwrap(), "--market", settings["market"].as_str().unwrap(), "--home", home.to_str().unwrap()]);
    for pick in screen["picks"].as_array().unwrap() {
        let fields = ["rank", "symbol", "ranking_value"].map(|key| (key.to_string(), pick[key].clone()));
        rows.entry("picks").or_default().push(row(name, fields));
        for step in pick["steps"].as_array().unwrap() {
            let fields = [("rank".to_string(), pick["rank"].clone())].into_iter().chain(step.as_object().unwrap().clone());
            rows.entry("pick_steps").or_default().push(row(name, fields));
        }
    }
}

/// Writes `rows` (each table's rows in key order) as table files in `out`.
fn write_rows(rows: &BTreeMap<&str, Vec<Map<String, Value>>>, out: &Path) {
    let keys: BTreeMap<&str, &[&str]> = BTreeMap::from([
        ("explore", &["case", "selection"][..]),
        ("picks", &["case", "rank"][..]),
        ("pick_steps", &["case", "rank", "sleeve", "step"][..]),
    ]);
    let mut writer = tables::Writer::create(out, "l3 test", Value::Null).unwrap();
    for name in READ {
        let mut table = writer.table(name, keys[name]).unwrap();
        for fields in rows.get(name).into_iter().flatten() {
            let cells: Vec<(&str, tables::Cell)> = fields
                .iter()
                .map(|(key, value)| {
                    let cell = match value {
                        Value::Null => tables::Cell::Null,
                        Value::String(text) => tables::Cell::Text(text),
                        Value::Number(n) if n.is_i64() => tables::Cell::Int(n.as_i64().unwrap()),
                        Value::Number(n) => tables::Cell::Number(n.as_f64().unwrap()),
                        other => panic!("{other} in a reply row"),
                    };
                    (key.as_str(), cell)
                })
                .collect();
            table.row(&cells).unwrap();
        }
        table.finish().unwrap();
    }
}

#[test]
fn every_case_runs_to_the_oracles_tables() {
    let cases_dir = folder("L3_CASES", fixtures().join("cases/builtins"));
    let expected_dir = folder("L3_EXPECTED", fixtures().join("expected/runs"));
    let dir = tempfile::tempdir().unwrap();
    let home = match std::env::var_os("L3_HOME") {
        Some(home) => PathBuf::from(home),
        None => {
            let home = dir.path().join("home");
            std::fs::create_dir(&home).unwrap();
            std::os::unix::fs::symlink(fixtures().join("raw").canonicalize().unwrap(), home.join("raw")).unwrap();
            bt(&["data", "prepare", "--as-of", AS_OF, "--home", home.to_str().unwrap()]);
            home
        }
    };
    let mut cases = BTreeSet::new();
    let mut results = Vec::new();
    let mut folders = BTreeMap::new();
    for entry in std::fs::read_dir(&cases_dir).unwrap() {
        let case = entry.unwrap().path();
        if !case.join("strategy.json").is_file() {
            continue;
        }
        let name = case.file_name().unwrap().to_str().unwrap().to_string();
        // The result file, and so the case, is named after the strategy file.
        let strategy = dir.path().join(format!("{name}.json"));
        std::os::unix::fs::symlink(case.join("strategy.json"), &strategy).unwrap();
        let settings: Value = serde_json::from_slice(&std::fs::read(case.join("run.json")).unwrap()).unwrap();
        let out = dir.path().join("results").join(&name);
        let mut args = vec!["run".to_string(), strategy.display().to_string()];
        args.extend(schedule(&settings));
        args.extend(["--out".into(), out.display().to_string(), "--home".into(), home.display().to_string()]);
        bt(&args.iter().map(String::as_str).collect::<Vec<_>>());
        results.push(out.join(format!("{name}.sqlite")).display().to_string());
        folders.insert(name.clone(), (case, results.last().unwrap().clone()));
        cases.insert(name);
    }
    assert!(!cases.is_empty(), "no case in {}", cases_dir.display());
    let actual = dir.path().join("actual");
    let mut args = vec!["export", "tables"];
    args.extend(results.iter().map(String::as_str));
    args.extend(["--out", actual.to_str().unwrap()]);
    bt(&args);
    // Trial 1's periods, from the exported trials.
    let trials = std::fs::read_to_string(actual.join("trials.jsonl")).unwrap();
    let periods: BTreeMap<String, u64> = trials
        .lines()
        .map(|line| serde_json::from_str::<Value>(line).unwrap())
        .filter(|row| row["trial"] == 1)
        .map(|row| (row["case"].as_str().unwrap().to_string(), row["periods"].as_u64().unwrap()))
        .collect();
    let mut rows = BTreeMap::new();
    for (name, (case, result)) in &folders {
        read_rows(case, name, result, periods[name], &home, &mut rows);
    }
    let read = dir.path().join("read");
    write_rows(&rows, &read);
    for table in READ {
        std::fs::rename(read.join(format!("{table}.jsonl")), actual.join(format!("{table}.jsonl"))).unwrap();
    }
    expected(&expected_dir, &cases, &dir.path().join("expected"));
    let report = tables::compare(&dir.path().join("expected"), &actual).unwrap();
    for table in &report.tables {
        eprintln!("{}: {} rows compared", table.name, table.compared);
    }
    assert!(report.equal(), "{cases:?}: {:#?}", report.tables.iter().filter(|t| !t.equal()).collect::<Vec<_>>());
}
