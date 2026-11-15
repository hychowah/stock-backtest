//! `bt check`: what it reports of each step and variable; the first file
//! that fails names its place.

mod common;

use common::bt;
use serde_json::{Value, json};

#[test]
fn check_reports_each_source_and_the_first_file_that_fails() {
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

    let bad = dir.path().join("bad.json");
    std::fs::write(&bad, r#"{"sleeves": [{"steps": [{"rank": "Revenue +", "order": "highest", "from": 1, "to": 3}]}]}"#).unwrap();
    let (reply, success) = bt(&["check", file.to_str().unwrap(), bad.to_str().unwrap()]);
    assert!(!success);
    assert_eq!(reply["error"]["place"], format!("{}: sleeves[1].steps[1], character 10", bad.display()), "{reply}");
}
