//! `bt run`: its argument rules, an `is` text no company has, the place of
//! a run-stopping error, and a seed that gives the same result file again;
//! and the files `bt export tables` refuses.

mod common;

use common::{bt, path, prepared};
use serde_json::{Value, json};
use std::path::Path;

/// Writes a strategy file of one sleeve with `steps`.
fn strategy(file: &Path, steps: Value) {
    std::fs::create_dir_all(file.parent().unwrap()).unwrap();
    std::fs::write(file, json!({ "sleeves": [{ "steps": steps }] }).to_string()).unwrap();
}

const RANK: &str = r#"{"rank": "EBITDA yield", "order": "highest", "from": 1, "to": 50}"#;

#[test]
fn arguments_and_strategy_files_are_checked_before_any_data_is_read() {
    let dir = tempfile::tempdir().unwrap();
    // The home holds no prepared data, so each error below comes first.
    let (home, out) = (dir.path().join("home"), dir.path().join("out"));
    let (good, same, bad) = (dir.path().join("a.json"), dir.path().join("b/a.json"), dir.path().join("bad.json"));
    let rank: Value = serde_json::from_str(RANK).unwrap();
    strategy(&good, json!([rank]));
    strategy(&same, json!([rank]));
    strategy(&bad, json!([{"rank": "No such source", "order": "highest", "from": 1, "to": 5}]));
    let run = |files: &[&Path], schedule: &[&str]| {
        let mut args = vec!["run"];
        args.extend(files.iter().map(|f| path(f)));
        args.extend(["--market", "us", "--start", "2021-07-01", "--end", "2023-06-28", "--out", path(&out), "--home", path(&home)]);
        args.extend(schedule);
        let (reply, success) = bt(&args);
        assert!(!success, "{reply}");
        reply["error"]["place"].as_str().unwrap().to_string()
    };
    assert_eq!(run(&[&good], &["--dates", "2021-07-01", "--random", "2"]), "arguments");
    assert_eq!(run(&[&good], &["--every", "3m", "--seed", "1"]), "arguments");
    assert_eq!(run(&[&good], &["--every", "3m", "--dates", "2021-07-01"]), "arguments");
    assert_eq!(run(&[&good], &[]), "arguments");
    assert_eq!(run(&[&good], &["--every", "3x"]), "every");
    assert!(run(&[&good, &bad], &["--every", "3m"]).starts_with(path(&bad)));
    assert_eq!(run(&[&good, &same], &["--every", "3m"]), path(&same));
    std::fs::create_dir(&out).unwrap();
    std::fs::write(out.join("other"), "").unwrap();
    assert_eq!(run(&[&good], &["--every", "3m"]), path(&out));
    std::fs::remove_file(out.join("other")).unwrap();
    // Only now is the market's data read.
    assert!(run(&[&good], &["--every", "3m"]).starts_with(path(&home)));
}

#[test]
fn an_is_text_that_no_company_of_the_market_has_is_refused_before_the_run() {
    let dir = tempfile::tempdir().unwrap();
    let home = prepared(dir.path());
    let rank: Value = serde_json::from_str(RANK).unwrap();
    let run = |name: &str, op: &str, text: &str| {
        let file = dir.path().join(format!("{name}.json"));
        strategy(&file, json!([{"filter": "Sector", "op": op, "value": text}, rank]));
        let out = dir.path().join(name);
        let args = ["run", path(&file), "--market", "hk", "--start", "2021-07-01", "--end", "2022-06-30", "--every", "6m"];
        (bt(&[&args[..], &["--out", path(&out), "--home", path(&home)]].concat()), file)
    };
    // The sector is Utilities: the text's case differs.
    let ((reply, success), file) = run("wrong", "is", "utilities");
    assert!(!success);
    assert_eq!(reply["error"]["place"], format!("{}: sleeves[1].steps[1]", path(&file)), "{reply}");
    assert!(reply["error"]["message"].as_str().unwrap().contains("bt catalog --market hk"), "{reply}");
    // A file may run on several markets, so `is not` takes any text.
    assert!(run("other", "is not", "utilities").0.1);
    assert!(run("right", "is", "Utilities").0.1);
}

#[test]
fn a_run_stops_at_a_holding_without_an_exit_price_and_a_seed_repeats_its_result() {
    let dir = tempfile::tempdir().unwrap();
    let home = prepared(dir.path());
    let rank: Value = serde_json::from_str(RANK).unwrap();
    let (empty, gap) = (dir.path().join("empty.json"), dir.path().join("gap.json"));
    strategy(&empty, json!([{"filter": "Market cap in dollars", "op": ">=", "value": "1000000000000000"}, rank]));
    strategy(&gap, json!([rank]));

    // USDJPY has no fixing from 2021-06-21 to 2021-07-02, so no Tokyo
    // holding of 2021-06-01 has an exit price on 2021-07-01. The first file
    // holds nothing, yet a run-stopping error leaves no result file at all.
    let out = dir.path().join("stopped");
    let jp = ["--market", "jp", "--start", "2021-06-01", "--end", "2021-07-01", "--dates", "2021-06-01"];
    let mut args = vec!["run", path(&empty), path(&gap), "--out", path(&out), "--home", path(&home)];
    args.extend(jp);
    let (reply, success) = bt(&args);
    assert!(!success);
    assert_eq!(reply["error"]["place"], format!("{}: jp, trial 1, 2021-06-01, 7102.T", path(&gap)), "{reply}");
    assert!(std::fs::read_dir(&out).is_err_and(|e| e.kind() == std::io::ErrorKind::NotFound));

    let run = |out: &str, seed: Option<&str>| {
        let out = dir.path().join(out);
        let mut args = vec!["run", path(&gap), "--market", "hk", "--start", "2021-07-01", "--end", "2023-06-28"];
        args.extend(["--every", "6m", "--random", "3", "--out", path(&out), "--home", path(&home)]);
        args.extend(seed.map(|seed| ["--seed", seed]).into_iter().flatten());
        let (reply, success) = bt(&args);
        assert!(success, "{reply}");
        (reply, std::fs::read(out.join("gap.sqlite")).unwrap())
    };
    let (drawn, first) = run("drawn", None);
    let seed = drawn["seed"].as_u64().unwrap().to_string();
    assert_eq!(drawn["schedule"]["random"]["seed"], drawn["seed"]);
    let (again, second) = run("again", Some(&seed));
    assert_eq!(first, second);
    assert_eq!(again["runs"][0]["cagr"], drawn["runs"][0]["cagr"]);
}

#[test]
fn a_file_run_in_a_batch_gives_the_result_it_gives_alone() {
    let dir = tempfile::tempdir().unwrap();
    let home = prepared(dir.path());
    let rank: Value = serde_json::from_str(RANK).unwrap();
    let files = [dir.path().join("a.json"), dir.path().join("b.json"), dir.path().join("c.json")];
    strategy(&files[0], json!([rank]));
    strategy(&files[1], json!([{"filter": "P/E", "op": "<", "value": "40"}, {"rank": "ROE", "order": "highest", "from": 1, "to": 3}]));
    strategy(&files[2], json!([{"rank": "Revenue", "order": "lowest", "from": 2, "to": 6}]));
    let run = |out: &str, files: &[&Path]| {
        let out = dir.path().join(out);
        let mut args = vec!["run"];
        args.extend(files.iter().map(|f| path(f)));
        args.extend(["--market", "hk", "--start", "2021-07-01", "--end", "2023-06-28", "--every", "6m", "--random", "3"]);
        args.extend(["--seed", "852", "--out", path(&out), "--home", path(&home)]);
        let (reply, success) = bt(&args);
        assert!(success, "{reply}");
        std::fs::read(out.join("b.sqlite")).unwrap()
    };
    assert_eq!(run("batch", &[&files[0], &files[1], &files[2]]), run("alone", &[&files[1]]));
}

#[test]
fn export_tables_refuses_two_results_of_one_name_and_a_file_that_is_not_a_result() {
    let dir = tempfile::tempdir().unwrap();
    let home = prepared(dir.path());
    let file = dir.path().join("a.json");
    strategy(&file, json!([serde_json::from_str::<Value>(RANK).unwrap()]));
    let (first, second) = (dir.path().join("first"), dir.path().join("second"));
    for out in [&first, &second] {
        let args = ["run", path(&file), "--market", "hk", "--start", "2021-07-01", "--end", "2022-06-30", "--every", "6m"];
        assert!(bt(&[&args[..], &["--out", path(out), "--home", path(&home)]].concat()).1);
    }
    let export = |results: &[&Path]| {
        let mut args = vec!["export", "tables"];
        args.extend(results.iter().map(|r| path(r)));
        let out = dir.path().join("tables");
        args.extend(["--out", path(&out)]);
        let (reply, success) = bt(&args);
        assert!(!success && !out.exists(), "{reply}");
        reply["error"]["place"].as_str().unwrap().to_string()
    };
    let (a, b) = (first.join("a.sqlite"), second.join("a.sqlite"));
    assert_eq!(export(&[&a, &b]), path(&b));
    // The strategy file is not a result file.
    assert_eq!(export(&[&a, &file]), path(&file));
}
