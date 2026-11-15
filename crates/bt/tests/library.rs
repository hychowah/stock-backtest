//! The variable library over HTTP: dependency order, and the changes that
//! would leave it unreadable refused.

mod common;

use common::{Server, prepared, serve};
use serde_json::{Value, json};

fn add(server: &Server, name: &str, formula: &str) -> i64 {
    let (status, reply) = server.change("POST", "/api/variables", json!({"name": name, "formula": formula, "favourite": false}));
    assert_eq!(status, 200, "{reply}");
    reply["id"].as_i64().unwrap()
}

#[test]
fn an_older_entry_can_use_a_newer_one_and_cycles_duplicates_and_used_entries_are_refused() {
    let dir = tempfile::tempdir().unwrap();
    let server = serve(&prepared(dir.path()));
    let older = add(&server, "Net cash", "Cash and equivalents - Total debt");
    let newer = add(&server, "Debt doubled", "Total debt * 2");

    let edited = json!({"name": "Net cash", "formula": "cash and equivalents - debt doubled", "favourite": true});
    let (status, reply) = server.change("PUT", &format!("/api/variables/{older}"), edited);
    assert_eq!(status, 200, "{reply}");
    assert_eq!(reply["formula"], "Cash and equivalents - Debt doubled", "the canonical text is stored");
    let entries = server.get("/api/variables");
    let names: Vec<&Value> = entries.as_array().unwrap().iter().map(|e| &e["name"]).collect();
    assert_eq!(names, [&json!("Debt doubled"), &json!("Net cash")], "an entry comes after the entries it names");
    assert_eq!((&entries[1]["uses"], &entries[1]["favourite"]), (&json!(["Debt doubled"]), &json!(true)));

    let cycle = json!({"name": "Debt doubled", "formula": "Net cash * 2", "favourite": false});
    let (status, reply) = server.change("PUT", &format!("/api/variables/{newer}"), cycle);
    assert_eq!(status, 409, "{reply}");
    assert!(reply["error"]["message"].as_str().unwrap().contains("Net cash"), "{reply}");

    let (status, _) = server.change("POST", "/api/variables", json!({"name": "net  CASH", "formula": "Revenue", "favourite": false}));
    assert_eq!(status, 409, "names compare as the list compares them");

    let (status, reply) = server.change("DELETE", &format!("/api/variables/{newer}"), json!(null));
    assert_eq!((status, &reply["error"]["message"]), (409, &json!("Net cash uses \"Debt doubled\": change it first")));

    let (status, reply) = server.change("POST", "/api/variables", json!({"name": "Bad", "formula": "Revenue +", "favourite": false}));
    assert_eq!(status, 400, "{reply}");
    assert!(reply["error"]["place"].as_str().unwrap().starts_with("formula, character"), "{reply}");

    let (status, _) = server.change("DELETE", &format!("/api/variables/{older}"), json!(null));
    assert_eq!(status, 200);
    assert_eq!(server.get("/api/variables").as_array().unwrap().len(), 1);
}
