use serde_json::{Value, json};
use std::process::Command;

#[test]
fn status_on_an_empty_home_reports_no_raw_data_and_nothing_prepared() {
    let home = tempfile::tempdir().unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_bt"))
        .args(["data", "status", "--home"])
        .arg(home.path())
        .output()
        .expect("run bt");
    assert!(output.status.success());
    let reply: Value = serde_json::from_slice(&output.stdout).unwrap();
    let markets = reply["markets"].as_array().unwrap();
    let ids: Vec<&Value> = markets.iter().map(|m| &m["market"]).collect();
    assert_eq!(ids, [&json!("us"), &json!("hk"), &json!("jp")]);
    for market in markets {
        assert_eq!(market["raw"], json!(false));
        let prepared = market["prepared"].as_str().unwrap();
        assert!(prepared.contains("not prepared: run `bt data prepare`"), "{prepared}");
    }
    let wrong = Command::new(env!("CARGO_BIN_EXE_bt")).args(["data", "status", "--nonsense"]).output().unwrap();
    assert_eq!(wrong.status.code(), Some(1));
    let reply: Value = serde_json::from_slice(&wrong.stdout).unwrap();
    assert_eq!(reply["error"]["place"], json!("arguments"));
}
