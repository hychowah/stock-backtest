//! `bt check`: what it reports of each step and variable; every case's
//! strategy file reads and its canonical form reads back to itself; the
//! first file that fails names its place.

use serde_json::{Value, json};
use std::path::Path;
use std::process::Command;

/// Runs `bt`; returns its reply and whether it succeeded.
fn bt(args: &[&str]) -> (Value, bool) {
    let output = Command::new(env!("CARGO_BIN_EXE_bt")).args(args).output().expect("run bt");
    (serde_json::from_slice(&output.stdout).unwrap(), output.status.success())
}

#[test]
fn check_reports_each_source_and_its_canonical_form_is_a_fixed_point() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("kinds.json");
    let strategy = json!({
        "variables": {"Half revenue": {"formula": "Revenue / 2"}},
        "sleeves": [{"steps": [
            {"filter": "Revenue", "op": ">", "value": "10"},
            {"filter": "(Debt/assets)", "op": "<", "value": "50"},
            {"filter": "Half revenue", "op": ">", "value": "1"},
            {"rank": "EBITDA yield", "order": "highest", "from": 1, "to": 5}
        ]}]
    });
    std::fs::write(&file, strategy.to_string()).unwrap();
    let (reply, success) = bt(&["check", file.to_str().unwrap()]);
    assert!(success, "{reply}");
    let checked = &reply["files"][0];
    assert_eq!(
        checked["variables"],
        json!([{"name": "Half revenue", "formula": "Revenue / 2", "unit": "USD", "display": "usd_million"}])
    );
    let steps: Vec<Value> = checked["sleeves"][0]["steps"]
        .as_array()
        .unwrap()
        .iter()
        .map(|s| json!([s["source"]["kind"], s["source"]["name"], s["unit"], s["display"]]))
        .collect();
    assert_eq!(
        steps,
        [
            json!(["input", "Revenue", "USD", "usd_million"]),
            // Formula text, not the measure "Debt/assets", whose display is multiple.
            json!(["formula", "(Debt/assets)", "scalar", "percent"]),
            json!(["variable", "Half revenue", "USD", "usd_million"]),
            json!(["built-in", "EBITDA yield", "scalar", "percent"]),
        ]
    );
    assert_eq!(checked["sleeves"][0]["steps"][1]["stored"], json!(0.5));

    let cases = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../fixtures/fictional/cases");
    let mut files = Vec::new();
    for kind in std::fs::read_dir(cases).unwrap() {
        for case in std::fs::read_dir(kind.unwrap().path()).unwrap() {
            files.push(case.unwrap().path().join("strategy.json").display().to_string());
        }
    }
    let canonical: Vec<String> = files
        .iter()
        .enumerate()
        .map(|(n, _)| dir.path().join(format!("{n}.json")).display().to_string())
        .collect();
    let (first, success) = bt(&[&["check"], &files.iter().map(String::as_str).collect::<Vec<_>>()[..]].concat());
    assert!(success, "{first}");
    for (path, read) in canonical.iter().zip(first["files"].as_array().unwrap()) {
        std::fs::write(path, read["canonical"].as_str().unwrap()).unwrap();
    }
    let (again, success) = bt(&[&["check"], &canonical.iter().map(String::as_str).collect::<Vec<_>>()[..]].concat());
    assert!(success, "{again}");
    for (a, b) in first["files"].as_array().unwrap().iter().zip(again["files"].as_array().unwrap()) {
        assert_eq!((&a["canonical"], &a["identity"]), (&b["canonical"], &b["identity"]), "{}", a["file"]);
    }

    let bad = dir.path().join("bad.json");
    std::fs::write(&bad, r#"{"sleeves": [{"steps": [{"rank": "Revenue +", "order": "highest", "from": 1, "to": 3}]}]}"#).unwrap();
    let (reply, success) = bt(&["check", file.to_str().unwrap(), bad.to_str().unwrap()]);
    assert!(!success);
    assert_eq!(reply["error"]["place"], format!("{}: sleeves[1].steps[1], character 10", bad.display()), "{reply}");
}
