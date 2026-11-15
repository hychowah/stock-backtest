//! The update's routes. The stop and the refused start run beside an update
//! that is only a lock and a record in the home's `data/`, which the tests
//! write themselves. The started update is the real command, whose provider
//! is a fake on `127.0.0.1` (`serve_with`) and whose key is made up: no
//! request leaves the machine.

mod common;

use common::provider::{Encoding, FakeProvider};
use common::{Server, fixtures, serve, serve_with};
use market_data::commands::Home;
use market_data::updates::UpdateLock;
use serde_json::{Value, json};
use std::path::Path;
use std::time::{Duration, Instant};

const KEY: &str = "made-up-update-key-8d2f";

/// A fresh home with a server on it.
fn started(dir: &Path) -> (Home, Server) {
    (Home::new(dir), serve(dir))
}

/// Writes `data/update.json` with `state` and the other fields of an update
/// that has downloaded part of the prices.
fn record(home: &Home, state: &str, last_success: Option<&str>) {
    let progress = json!({
        "state": state, "pid": 4242, "stage": "prices", "market": "us", "done": 120, "total": 700, "failed": 0,
        "failures": [], "started": "2026-11-15T06:00:00Z", "finished": null, "end": "2026-11-13",
        "reports": "not_due", "error": null,
    });
    let text = json!({"memory": {"last_success": last_success}, "progress": progress}).to_string();
    std::fs::create_dir_all(home.root().join("data")).unwrap();
    std::fs::write(home.root().join("data/update.json"), text).unwrap();
}

fn stop_file(home: &Home) -> bool {
    home.root().join("data/update.stop").exists()
}

#[test]
fn stop_with_no_update_running_is_refused() {
    let dir = tempfile::tempdir().unwrap();
    let (home, server) = started(dir.path());
    let (status, reply) = server.change("POST", "/api/data/stop", json!({}));
    assert_eq!(status, 409);
    assert_eq!(reply["error"]["message"], "no update is running");
    assert!(!stop_file(&home));
    // A record that says running while nothing holds the lock is a crashed update.
    record(&home, "running", None);
    assert_eq!(server.change("POST", "/api/data/stop", json!({})).0, 409);
    assert!(!stop_file(&home));
}

#[test]
fn start_while_an_update_runs_is_refused_and_stop_asks_it_to_end() {
    let dir = tempfile::tempdir().unwrap();
    let (home, server) = started(dir.path());
    let lock = UpdateLock::take(&home).unwrap();
    record(&home, "running", None);

    let (status, reply) = server.change("POST", "/api/data/update", json!({}));
    assert_eq!(status, 409);
    assert_eq!(reply["error"]["message"], "an update is already running");
    assert!(!home.root().join("logs").exists(), "no process was started");

    let reply = server.ok("POST", "/api/data/stop", json!({}));
    assert!(stop_file(&home));
    assert_eq!(reply["state"], "running");
    assert_eq!(reply["progress"]["done"], 120);

    // The update ends: the record and the lock say so, and a stop is refused.
    record(&home, "stopped", None);
    drop(lock);
    assert_eq!(server.change("POST", "/api/data/stop", json!({})).0, 409);
}

/// Copies the fictional raw files (without Tokyo, which an update never
/// touches) into `home/raw`, so that an update has a company list to start
/// from and never writes into the fixtures.
fn copy_raw(home: &Path) {
    fn copy(from: &Path, to: &Path) {
        std::fs::create_dir_all(to).unwrap();
        for entry in std::fs::read_dir(from).unwrap() {
            let entry = entry.unwrap();
            let target = to.join(entry.file_name());
            if entry.path().is_dir() {
                copy(&entry.path(), &target);
            } else {
                std::fs::copy(entry.path(), target).unwrap();
            }
        }
    }
    copy(&fixtures().join("raw"), &home.join("raw"));
    std::fs::remove_dir_all(home.join("raw/markets/jp")).unwrap();
}

/// A fake provider whose company lists refuse the key (401), so that an
/// update ends at once, with its message: the store of a Monday update holds
/// replies for one fixed date, and this server's update runs at today's date.
fn refusing_provider(dir: &Path) -> FakeProvider {
    let mut lines = Vec::new();
    for exchange in ["AMEX", "NASDAQ", "NYSE"] {
        let params = json!({"exchange": exchange, "isActivelyTrading": "true", "isEtf": "false", "isFund": "false", "limit": "1000", "page": "0"});
        lines.push(json!({"endpoint": "company-screener", "params": params, "status": 401, "body": "{}"}).to_string());
    }
    let store = dir.join("replies.jsonl");
    std::fs::write(&store, lines.join("\n")).unwrap();
    FakeProvider::start(&store, Encoding::Plain)
}

/// Polls the status until the update of process `pid` has ended; returns it.
fn ended(server: &Server, pid: u64) -> Value {
    let start = Instant::now();
    loop {
        let update = server.get("/api/data/status")["update"].clone();
        let state = update["state"].as_str().unwrap();
        if update["progress"]["pid"] == pid && !["running", "stopping"].contains(&state) {
            return update;
        }
        assert!(start.elapsed() < Duration::from_secs(120), "the update does not end: {update}");
        std::thread::sleep(Duration::from_millis(50));
    }
}

#[test]
fn a_start_runs_the_update_command_and_a_second_start_is_accepted_after_it_ends() {
    let dir = tempfile::tempdir().unwrap();
    let home = dir.path().join("home");
    copy_raw(&home);
    let fake = refusing_provider(dir.path());
    let server = serve_with(&home, fake.address());
    let key = server.user.path().join(".grok/secrets/fmp_api_key");
    std::fs::create_dir_all(key.parent().unwrap()).unwrap();
    std::fs::write(key, format!("{KEY}\n")).unwrap();

    // The reply comes once the record names the new process.
    let first = server.ok("POST", "/api/data/update", json!({}));
    let pid = first["progress"]["pid"].as_u64().unwrap();
    assert!(pid != 0 && pid != std::process::id() as u64);
    let update = ended(&server, pid);
    assert_eq!(update["state"], "failed");
    assert!(update["progress"]["error"]["message"].as_str().unwrap().contains("401"), "{update}");
    assert_eq!(update["last_success"], Value::Null);

    // A second start is accepted: nothing runs now.
    let second = server.ok("POST", "/api/data/update", json!({}));
    let update = ended(&server, second["progress"]["pid"].as_u64().unwrap());
    assert_eq!(update["state"], "failed");

    // Every request had the made-up key, and the log holds no URL or key.
    assert!(!fake.requests().is_empty());
    assert!(fake.requests().iter().all(|r| r.key.as_deref() == Some(KEY)));
    let log = std::fs::read_to_string(home.join("logs/update.log")).unwrap();
    for secret in ["http", "apikey", KEY] {
        assert!(!log.contains(secret), "logs/update.log holds {secret:?}: {log}");
    }
}

#[test]
fn a_start_that_loses_the_race_for_the_lock_is_refused_when_the_update_gives_it_up() {
    let dir = tempfile::tempdir().unwrap();
    let (home, server) = started(dir.path());
    // An update started elsewhere holds the lock and has not written its record yet.
    let _lock = UpdateLock::take(&home).unwrap();
    let begun = Instant::now();
    let (status, reply) = server.change("POST", "/api/data/update", json!({}));
    assert_eq!(status, 409, "{reply}");
    assert_eq!(reply["error"]["message"], "an update is already running");
    // The command waits 2 s for the lock before it gives up.
    assert!(begun.elapsed() >= Duration::from_secs(2));
    // The command's own refusal is in the log.
    assert!(std::fs::read_to_string(home.root().join("logs/update.log")).unwrap().contains("an update is already running"));
}
