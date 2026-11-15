//! `bt serve`: one server per home, the run list over HTTP, the origin rule
//! and a clean exit on SIGTERM.

mod common;

use common::{bt, path, prepared, serve};
use serde_json::json;

#[test]
fn a_server_answers_refuses_other_origins_and_a_second_server_and_exits_on_sigterm() {
    let dir = tempfile::tempdir().unwrap();
    let home = prepared(dir.path());
    let server = serve(&home);
    assert_eq!(server.get("/api/runs"), json!({"paused": false, "runs": []}));

    let (status, reply) = server.send("POST", "/api/runs", Some(&json!({})), Some("http://example.com"));
    assert_eq!((status, &reply["error"]["place"]), (403, &json!("Origin")), "{reply}");

    let (reply, success) = bt(&["serve", "--port", "0", "--home", path(&home)]);
    assert!(!success);
    assert_eq!(reply["error"]["message"], "another server is running on this home");

    assert!(server.terminate());
}
