//! `bt check`: what it reports of each step and variable; the first file
//! that fails names its place; the canonical form keeps only the variables
//! the steps read; the ranks of the holdings.

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

#[test]
fn a_variable_that_no_step_reads_changes_neither_the_canonical_form_nor_the_identity() {
    let dir = tempfile::tempdir().unwrap();
    let step = json!({"rank": "Doubled cover * 1", "order": "highest", "from": 1, "to": 5});
    let cover = json!({"formula": "Cash and equivalents / positive(Current liabilities)", "display": "multiple"});
    let doubled = json!({"formula": "Cover * 2", "display": "multiple"});
    // `json!` writes an object's keys in name order, which is the file order.
    let check = |name: &str, variables: Value| {
        let file = dir.path().join(name);
        std::fs::write(&file, json!({"variables": variables, "sleeves": [{"steps": [step]}]}).to_string()).unwrap();
        let (reply, success) = bt(&["check", file.to_str().unwrap()]);
        assert!(success, "{reply}");
        reply["files"][0].clone()
    };
    let used = check("used.json", json!({"Cover": cover, "Doubled cover": doubled}));
    let unused = json!({"Cover": cover, "Cover tripled": {"formula": "Cover * 3"}, "Doubled cover": doubled, "Half revenue": {"formula": "Revenue / 2"}});
    let leftover = check("leftover.json", unused);
    assert_eq!((&leftover["canonical"], &leftover["identity"]), (&used["canonical"], &used["identity"]));
    let names: Vec<&Value> = leftover["variables"].as_array().unwrap().iter().map(|v| &v["name"]).collect();
    assert_eq!(names, [&json!("Cover"), &json!("Doubled cover")]);
}

#[test]
fn the_ranks_are_the_last_rank_steps_of_one_sleeve_or_the_sum_of_several() {
    let dir = tempfile::tempdir().unwrap();
    let rank = |from: u32, to: u32| json!({"rank": "EBITDA yield", "order": "highest", "from": from, "to": to});
    let ranks = |sleeves: Value| {
        let file = dir.path().join("ranks.json");
        std::fs::write(&file, json!({"sleeves": sleeves}).to_string()).unwrap();
        let (reply, success) = bt(&["check", file.to_str().unwrap()]);
        assert!(success, "{reply}");
        reply["files"][0]["ranks"].clone()
    };
    assert_eq!(ranks(json!([{"steps": [rank(1, 20), rank(2, 4)]}])), json!([2, 4]));
    assert_eq!(ranks(json!([{"name": "A", "steps": [rank(3, 5)]}, {"name": "B", "steps": [rank(1, 4)]}])), json!([1, 7]));
}
