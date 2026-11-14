//! Whole runs equal the oracle's: each case runs through `bt run` with the
//! schedule of its `run.json`, and `bt export tables` of the results equals
//! the expected tables of those cases (`proof/l3.py`), row for row and bit
//! for bit.
//!
//! A case is a folder holding `strategy.json` and `run.json`; its name is the
//! case name. Every case found is run. The expected folder may hold other
//! cases and tables: only the rows of the cases found, in the tables `bt
//! export tables` writes, are compared.
//!
//! The folders default to the fictional fixture. To run the same test
//! elsewhere, such as on real data with `cargo test --release`, set
//! `L3_CASES` (the folder of case folders), `L3_EXPECTED` (the expected
//! tables) and `L3_HOME` (a prepared home).

use serde_json::Value;
use std::collections::BTreeSet;
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::Command;

const TABLES: [&str; 6] = ["trials", "statistics", "periods", "holdings", "steps", "curve"];

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
    manifest["tables"].as_object_mut().unwrap().retain(|name, _| TABLES.contains(&name.as_str()));
    std::fs::write(out.join("manifest.json"), manifest.to_string()).unwrap();
    for table in TABLES {
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
        cases.insert(name);
    }
    assert!(!cases.is_empty(), "no case in {}", cases_dir.display());
    let actual = dir.path().join("actual");
    let mut args = vec!["export", "tables"];
    args.extend(results.iter().map(String::as_str));
    args.extend(["--out", actual.to_str().unwrap()]);
    bt(&args);
    expected(&expected_dir, &cases, &dir.path().join("expected"));
    let report = tables::compare(&dir.path().join("expected"), &actual).unwrap();
    for table in &report.tables {
        eprintln!("{}: {} rows compared", table.name, table.compared);
    }
    assert!(report.equal(), "{cases:?}: {:#?}", report.tables.iter().filter(|t| !t.equal()).collect::<Vec<_>>());
}
