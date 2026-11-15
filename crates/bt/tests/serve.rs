//! `bt serve`: one server per home, the origin rule and the JSON errors, the
//! run list and the queue over HTTP, Stop, recovery after a shutdown or a
//! crash, and `bt run` and `bt save` beside a server that runs a queue.

mod common;

use common::{Server, bt, bt_ok, path, prepared, serve};
use serde_json::{Value, json};
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

const RANK: &str = r#"{"sleeves": [{"steps": [{"rank": "EBITDA yield", "order": "highest", "from": 1, "to": 50}]}]}"#;

/// A short run: three random trials.
fn quick() -> Value {
    json!({"start": "2021-07-01", "end": "2023-06-28", "every": "3m", "trials": 3})
}

/// A run whose work per entry day lasts seconds, so a test sees it running
/// and stops it there: weekly dates over the whole fictional window, ranked
/// by a sum of 2,000 terms (about 1.5 s on 16 threads, 6 s on 2).
fn slow(name: &str) -> Value {
    fn sum(terms: &[String]) -> String {
        match terms {
            [one] => one.clone(),
            _ => format!("({} + {})", sum(&terms[..terms.len() / 2]), sum(&terms[terms.len() / 2..])),
        }
    }
    let terms: Vec<String> = (1..=2000).map(|k| format!("Revenue * {k}")).collect();
    let strategy = json!({"sleeves": [{"steps": [{"rank": sum(&terms), "order": "highest", "from": 1, "to": 5}]}]});
    let schedule = json!({"start": "2016-01-04", "end": "2023-06-28", "every": "1w"});
    json!({"name": name, "market": "us", "schedule": schedule, "strategy": strategy.to_string()})
}

fn run(name: &str, schedule: Value) -> Value {
    json!({"name": name, "market": "us", "schedule": schedule, "strategy": RANK})
}

/// The test's own steps on a server.
trait Steps {
    fn add(&self, run: Value) -> i64;
    fn state(&self, id: i64) -> String;
    fn wait(&self, id: i64, state: &str) -> Value;
    fn order(&self) -> Vec<i64>;
}

impl Steps for Server {
    fn add(&self, run: Value) -> i64 {
        self.ok("POST", "/api/runs", run)["id"].as_i64().unwrap()
    }

    fn state(&self, id: i64) -> String {
        self.get(&format!("/api/runs/{id}"))["state"].as_str().unwrap().to_string()
    }

    /// Waits until run `id` is in `state`.
    fn wait(&self, id: i64, state: &str) -> Value {
        let start = Instant::now();
        loop {
            let run = self.get(&format!("/api/runs/{id}"));
            if run["state"] == state {
                return run;
            }
            assert!(start.elapsed() < Duration::from_secs(300), "run {id} is not {state}: {run}");
            std::thread::sleep(Duration::from_millis(10));
        }
    }

    /// The ids of the list, in its order.
    fn order(&self) -> Vec<i64> {
        self.get("/api/runs")["runs"].as_array().unwrap().iter().map(|r| r["id"].as_i64().unwrap()).collect()
    }
}

fn result(home: &Path, id: i64) -> PathBuf {
    home.join(format!("data/runs/{id}.sqlite"))
}

/// The numbers of `bt run`'s reply that a run's outcome holds.
fn headline(reply: &Value) -> Value {
    let keys = ["cagr", "median", "worst", "best", "spy_median", "beat_spy", "min_holdings"];
    keys.iter().map(|&k| (k.to_string(), reply[k].clone())).collect::<serde_json::Map<_, _>>().into()
}

/// `bt run` of the rank strategy on `schedule`; its reply's one run.
fn bt_run(dir: &Path, home: &Path, schedule: &Value) -> Value {
    let (file, out) = (dir.join("rank.json"), dir.join("out"));
    std::fs::write(&file, RANK).unwrap();
    let mut args = vec!["run".to_string(), path(&file).into(), "--market".into(), "us".into()];
    for (key, value) in schedule.as_object().unwrap() {
        args.extend([format!("--{key}"), value.as_str().map_or(value.to_string(), str::to_string)]);
    }
    args.extend(["--out".into(), path(&out).into(), "--home".into(), path(home).into()]);
    let args: Vec<&str> = args.iter().map(String::as_str).collect();
    bt_ok(&args)["runs"][0].clone()
}

#[test]
fn a_server_answers_refuses_other_origins_and_a_second_server_and_exits_on_sigterm() {
    let dir = tempfile::tempdir().unwrap();
    let home = prepared(dir.path());
    let server = serve(&home);
    assert_eq!(server.get("/api/runs"), json!({"paused": false, "runs": []}));
    for (method, path, status, place) in
        [("GET", "/api/runs/abc", 400, "id"), ("GET", "/api/nothing", 404, "path"), ("PUT", "/api/runs", 405, "method")]
    {
        let reply = server.send(method, path, None, None);
        assert_eq!((reply.0, &reply.1["error"]["place"]), (status, &json!(place)), "{method} {path}: {reply:?}");
    }

    let (status, reply) = server.send("POST", "/api/runs", Some(&json!({})), Some("http://example.com"));
    assert_eq!((status, &reply["error"]["place"]), (403, &json!("Origin")), "{reply}");

    let (reply, success) = bt(&["serve", "--port", "0", "--home", path(&home)]);
    assert!(!success);
    assert_eq!(reply["error"]["message"], "another server is running on this home");

    assert!(server.terminate());
}

#[test]
fn an_added_run_completes_with_the_headline_of_bt_run_with_its_seed() {
    let dir = tempfile::tempdir().unwrap();
    let home = prepared(dir.path());
    let server = serve(&home);
    let id = server.add(run("first", quick()));
    let done = server.wait(id, "complete");
    let schedule = &done["schedule"];
    assert!(schedule["seed"].is_u64(), "the seed is drawn when the run is added: {done}");
    assert_eq!(done["outcome"]["headline"], headline(&bt_run(dir.path(), &home, schedule)));
    assert!(done["strategy"].as_str().unwrap().starts_with(r#"{"sleeves""#));
    assert!(server.get("/api/runs")["runs"][0].get("strategy").is_none(), "the list leaves out the strategy");
    assert!(result(&home, id).is_file());

    let mut bad = run("bad", json!({"start": "2021-07-01", "end": "2023-06-28", "every": "3x"}));
    let (status, reply) = server.change("POST", "/api/runs", bad.clone());
    assert_eq!((status, &reply["error"]["place"]), (400, &json!("every")), "{reply}");
    bad["schedule"] = json!({"start": "2021-07-01", "end": "2023-06-28", "every": "1w", "trials": 4000000000u32});
    let (status, reply) = server.change("POST", "/api/runs", bad.clone());
    assert_eq!((status, &reply["error"]["place"]), (400, &json!("trials")), "the website runs at most 1,000 trials: {reply}");
    bad["schedule"] = quick();
    bad["strategy"] = json!(r#"{"sleeves": []}"#);
    let (status, reply) = server.change("POST", "/api/runs", bad);
    assert_eq!((status, &reply["error"]["place"]), (400, &json!("strategy: sleeves")), "{reply}");
}

#[test]
fn the_queue_holds_edits_releases_moves_stops_pauses_and_resumes() {
    let dir = tempfile::tempdir().unwrap();
    let home = prepared(dir.path());
    let server = serve(&home);
    assert_eq!(server.ok("PUT", "/api/queue", json!({"paused": true})), json!({"paused": true}));
    let [a, b, c] = ["a", "b", "c"].map(|name| server.add(run(name, quick())));
    assert_eq!(server.order(), [a, b, c]);

    assert_eq!(server.ok("POST", &format!("/api/runs/{b}/hold"), json!({}))["state"], "held");
    let every = json!({"start": "2021-07-01", "end": "2023-06-28", "every": "6m"});
    let edited = server.ok("PATCH", &format!("/api/runs/{b}"), json!({"schedule": every, "name": "b2"}));
    assert_eq!((&edited["schedule"], &edited["name"], &edited["state"]), (&every, &json!("b2"), &json!("held")));
    let (status, _) = server.change("POST", &format!("/api/runs/{b}/hold"), json!({}));
    assert_eq!(status, 409, "a held run cannot be held again");
    assert_eq!(server.ok("POST", &format!("/api/runs/{b}/release"), json!({}))["state"], "waiting");

    server.ok("POST", &format!("/api/runs/{c}/move"), json!({"to": 1}));
    assert_eq!(server.order(), [c, a, b]);
    assert_eq!(server.ok("POST", &format!("/api/runs/{a}/stop"), json!({}))["state"], "stopped");
    assert_eq!(server.state(c), "waiting", "the queue is paused");

    server.ok("PUT", "/api/queue", json!({"paused": false}));
    let (c_done, b_done) = (server.wait(c, "complete"), server.wait(b, "complete"));
    assert!(c_done["finished"].as_str() <= b_done["started"].as_str(), "c runs before b");
    assert!(!result(&home, a).exists());
    let (status, reply) = server.change("PATCH", &format!("/api/runs/{c}"), json!({"schedule": every}));
    assert_eq!(status, 409, "a complete run's settings stay: {reply}");
}

#[test]
fn a_locked_run_is_not_deleted_and_a_renamed_unlocked_one_is_deleted_with_its_file() {
    let dir = tempfile::tempdir().unwrap();
    let home = prepared(dir.path());
    let server = serve(&home);
    let id = server.add(run("kept", quick()));
    server.wait(id, "complete");
    let locked = server.ok("PATCH", &format!("/api/runs/{id}"), json!({"name": "renamed", "locked": true}));
    assert_eq!((&locked["name"], &locked["locked"], &locked["state"]), (&json!("renamed"), &json!(true), &json!("complete")));
    let (status, _) = server.change("DELETE", &format!("/api/runs/{id}"), json!(null));
    assert_eq!(status, 409);
    server.ok("PATCH", &format!("/api/runs/{id}"), json!({"locked": false}));
    assert_eq!(server.ok("DELETE", &format!("/api/runs/{id}"), json!(null)), json!({}));
    assert_eq!(server.send("GET", &format!("/api/runs/{id}"), None, None).0, 404);
    assert!(!result(&home, id).exists());
}

#[test]
fn a_running_run_is_stopped_or_deleted_and_leaves_no_result_file() {
    let dir = tempfile::tempdir().unwrap();
    let home = prepared(dir.path());
    let server = serve(&home);
    let stopped = server.add(slow("stopped"));
    let deleted = server.add(slow("deleted"));
    server.wait(stopped, "running");
    assert_eq!(server.ok("POST", &format!("/api/runs/{stopped}/stop"), json!({}))["state"], "stopped");
    server.wait(deleted, "running");
    server.ok("DELETE", &format!("/api/runs/{deleted}"), json!(null));
    // The worker runs one run at a time: once a later one completes, both
    // runs above have ended.
    let last = server.add(run("last", quick()));
    server.wait(last, "complete");
    assert_eq!(server.state(stopped), "stopped");
    assert_eq!(server.send("GET", &format!("/api/runs/{deleted}"), None, None).0, 404);
    assert!(!result(&home, stopped).exists() && !result(&home, deleted).exists());
}

#[test]
fn a_run_in_progress_at_sigterm_waits_after_the_restart_and_then_completes() {
    let dir = tempfile::tempdir().unwrap();
    let home = prepared(dir.path());
    let server = serve(&home);
    let id = server.add(slow("slow"));
    server.wait(id, "running");
    // Paused, the next server shows the run waiting before it takes it.
    server.ok("PUT", "/api/queue", json!({"paused": true}));
    assert!(server.terminate());
    let server = serve(&home);
    assert_eq!(server.state(id), "waiting");
    server.ok("PUT", "/api/queue", json!({"paused": false}));
    server.wait(id, "complete");
    assert!(result(&home, id).is_file());
}

#[test]
fn a_run_in_progress_when_the_server_is_killed_is_held_after_the_restart_and_the_queue_goes_on() {
    let dir = tempfile::tempdir().unwrap();
    let home = prepared(dir.path());
    let server = serve(&home);
    let id = server.add(slow("slow"));
    let next = server.add(run("next", quick()));
    server.wait(id, "running");
    server.kill();
    let server = serve(&home);
    server.wait(next, "complete");
    assert_eq!(server.state(id), "held");
    server.ok("POST", &format!("/api/runs/{id}/release"), json!({}));
    server.wait(id, "complete");
    assert!(result(&home, id).is_file());
}

#[test]
fn bt_run_and_bt_save_work_beside_a_server_that_runs_a_queue() {
    let dir = tempfile::tempdir().unwrap();
    let home = prepared(dir.path());
    let server = serve(&home);
    let running = server.add(slow("slow"));
    server.wait(running, "running");
    let schedule = json!({"start": "2021-07-01", "end": "2023-06-28", "every": "3m", "trials": "3", "seed": "5"});
    let reply = bt_run(dir.path(), &home, &schedule);
    let saved = bt_ok(&["save", reply["result"].as_str().unwrap(), "--name", "from bt", "--home", path(&home)]);
    assert_eq!(server.state(running), "running");
    let id = saved["id"].as_i64().unwrap();
    let row = server.get(&format!("/api/runs/{id}"));
    assert_eq!((&row["name"], &row["state"], &row["schedule"]["seed"]), (&json!("from bt"), &json!("complete"), &json!(5)));
    assert_eq!(row["outcome"]["headline"], headline(&reply));
    assert!(result(&home, id).is_file());
}
