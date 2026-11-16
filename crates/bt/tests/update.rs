//! `bt data update` against the fake provider, on the update cases of
//! `fixtures/fictional/update/`: the raw files, the requests, the record and
//! preparation equal the old updater's; a stop, then the same command, ends
//! equal; nothing secret is written. Each run has a private `HOME` with a
//! made-up key.
//!
//! The cases were written by the Python product that this program replaced,
//! at tag `python-oracle`, and are frozen. A case folder holds:
//! - `case.json`: `as_of`; `after`, the case whose end it starts from, or
//!   null; `memory`, the update record's memory at the start; and
//!   `record`, the Python product's own record, which is not read;
//! - `before/`: raw files laid over the start;
//! - `replies.jsonl`: the reply store that the fake provider serves
//!   (`common/provider.rs`);
//! - `requests.jsonl`: one `{"endpoint", "params"}` line per attempt, sorted;
//! - `after/`: every raw file the update added or changed, except the ledger
//!   `download-coverage.json`, which is not compared;
//! - `end.json`: the `outcome`, the sorted `failed` items (a price series by
//!   its raw file, `px/QAB.json`; a report as `key-metrics/QST`), the end
//!   `memory`, and `deleted`, which is not read: no case deletes a file.
//!
//! A case's start raw is the fictional raw without `markets/jp`, then the
//! `after` case's start and its `after/`, then its own `before/`.

mod common;

use common::provider::{Encoding, FakeProvider};
use common::{fixtures, path};
use serde_json::{Value, json};
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Output, Stdio};
use std::time::{Duration, Instant};

const KEY: &str = "made-up-update-key-5c1e";

fn case_dir(name: &str) -> PathBuf {
    fixtures().join("update").join(name)
}

fn read_json(path: &Path) -> Value {
    serde_json::from_slice(&std::fs::read(path).unwrap()).unwrap()
}

/// Every file below `root` by its path below `root`, except `skip`.
fn files(root: &Path, skip: &dyn Fn(&Path) -> bool) -> BTreeMap<PathBuf, Vec<u8>> {
    let mut found = BTreeMap::new();
    let mut folders = vec![root.to_path_buf()];
    while let Some(folder) = folders.pop() {
        for entry in std::fs::read_dir(&folder).unwrap() {
            let path = entry.unwrap().path();
            let relative = path.strip_prefix(root).unwrap().to_path_buf();
            if skip(&relative) {
                continue;
            }
            if path.is_dir() {
                folders.push(path);
            } else {
                found.insert(relative, std::fs::read(&path).unwrap());
            }
        }
    }
    found
}

/// The folders laid over the fictional raw (without Tokyo) to make a
/// case's start: the earlier case's start and `after/`, then its own
/// `before/`.
fn layers(name: &str) -> Vec<PathBuf> {
    let case = read_json(&case_dir(name).join("case.json"));
    let mut layers = match case["after"].as_str() {
        Some(earlier) => [layers(earlier), vec![case_dir(earlier).join("after")]].concat(),
        None => Vec::new(),
    };
    layers.push(case_dir(name).join("before"));
    layers.into_iter().filter(|layer| layer.is_dir()).collect()
}

/// The raw files of a case's start.
fn start_raw(name: &str) -> BTreeMap<PathBuf, Vec<u8>> {
    let mut raw = files(&fixtures().join("raw"), &|p| p == Path::new("markets/jp"));
    for layer in layers(name) {
        raw.extend(files(&layer, &|_| false));
    }
    raw
}

/// The expected raw files at a case's end: its start with `after/`.
fn end_raw(name: &str) -> BTreeMap<PathBuf, Vec<u8>> {
    let mut raw = start_raw(name);
    raw.extend(files(&case_dir(name).join("after"), &|_| false));
    raw
}

/// A frozen case set up in a temporary folder: its start home, a private
/// `HOME` with the made-up key, and the fake provider serving its replies.
struct Setup {
    dir: tempfile::TempDir,
    name: &'static str,
    case: Value,
    fake: FakeProvider,
}

impl Setup {
    fn new(name: &'static str) -> Setup {
        Setup::serving(name, &case_dir(name).join("replies.jsonl"))
    }

    /// A case's start home, with the fake serving the store at `replies`.
    fn serving(name: &'static str, replies: &Path) -> Setup {
        let dir = tempfile::tempdir().unwrap();
        let case = read_json(&case_dir(name).join("case.json"));
        for (relative, bytes) in start_raw(name) {
            let path = dir.path().join("home/raw").join(relative);
            std::fs::create_dir_all(path.parent().unwrap()).unwrap();
            std::fs::write(path, bytes).unwrap();
        }
        let record = dir.path().join("home/data/update.json");
        std::fs::create_dir_all(record.parent().unwrap()).unwrap();
        std::fs::write(record, json!({"memory": case["memory"]}).to_string()).unwrap();
        let key = dir.path().join("user/.grok/secrets/fmp_api_key");
        std::fs::create_dir_all(key.parent().unwrap()).unwrap();
        std::fs::write(key, format!("{KEY}\n")).unwrap();
        let fake = FakeProvider::start(replies, Encoding::Gzip);
        Setup { dir, name, case, fake }
    }

    fn home(&self) -> PathBuf {
        self.dir.path().join("home")
    }

    /// `bt data update` of the case, started.
    fn start(&self) -> Child {
        update_command(&self.home(), &self.dir.path().join("user"), self.case["as_of"].as_str().unwrap(), self.fake.address())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .expect("start bt")
    }

    /// Runs the update to its end; its reply and output.
    fn run(&self) -> (Value, Output) {
        finish(self.start())
    }

    fn end(&self) -> Value {
        read_json(&case_dir(self.name).join("end.json"))
    }

    fn record(&self) -> Value {
        read_json(&self.home().join("data/update.json"))
    }

    /// The requests the fake has seen, one `{"endpoint", "params"}` text per
    /// attempt, sorted.
    fn requests(&self, from: usize) -> Vec<String> {
        let mut requests: Vec<String> =
            self.fake.requests()[from..].iter().map(|r| json!({"endpoint": r.endpoint, "params": r.params}).to_string()).collect();
        requests.sort();
        requests
    }

    /// Checks every request: it had a stored reply and carried the made-up
    /// key.
    fn check_requests(&self) {
        assert!(self.fake.unknown().is_empty(), "requests with no stored reply: {:?}", self.fake.unknown());
        assert!(self.fake.requests().iter().all(|r| r.key.as_deref() == Some(KEY)));
    }

    /// Checks that the home holds `expected` in `raw/` (the ledger left
    /// out), byte for byte.
    fn check_raw(&self, expected: &BTreeMap<PathBuf, Vec<u8>>) {
        let ledger = |p: &Path| p == Path::new("download-coverage.json");
        let actual = files(&self.home().join("raw"), &ledger);
        let names = |files: &BTreeMap<PathBuf, Vec<u8>>| files.keys().cloned().collect::<Vec<_>>();
        assert_eq!(names(&actual), names(&expected), "the raw files present");
        for (relative, bytes) in expected {
            assert!(actual[relative] == *bytes, "{} differs from the expected file", relative.display());
        }
    }

    /// Checks that nothing new is outside `raw/`, `data/` and `logs/`, and
    /// that neither the command's output and error output nor `data/` and
    /// `logs/` hold a URL, `apikey` or the key.
    fn check_secrets(&self, output: &Output) {
        let home = self.home();
        for entry in std::fs::read_dir(&home).unwrap() {
            let name = entry.unwrap().file_name();
            assert!(["raw", "data", "logs"].contains(&name.to_str().unwrap()), "{name:?} was written");
        }
        let mut written = vec![(PathBuf::from("output"), output.stdout.clone()), (PathBuf::from("error output"), output.stderr.clone())];
        for folder in ["data", "logs"] {
            if home.join(folder).is_dir() {
                written.extend(files(&home.join(folder), &|_| false));
            }
        }
        for (file, bytes) in written {
            let text = String::from_utf8_lossy(&bytes);
            for secret in ["http", "apikey", KEY] {
                assert!(!text.contains(secret), "{} holds {secret:?}", file.display());
            }
        }
    }

    /// Checks the outcome and the record against `end.json`: the outcome,
    /// the failed items as `end.json` names them, and the report dates and
    /// pending sets.
    fn check_record(&self, reply: &Value) {
        let end = self.end();
        assert_eq!(reply["state"], end["outcome"]);
        let record = self.record();
        assert_eq!(record["progress"]["state"], end["outcome"]);
        let mut failed: Vec<String> = reply["failures"].as_array().unwrap().iter().map(|f| expected_item(f["place"].as_str().unwrap())).collect();
        failed.sort();
        assert_eq!(json!(failed), end["failed"]);
        assert_eq!(reply["failed"], json!(failed.len()));
        for key in ["last_report_check", "last_full_sweep", "pending"] {
            assert_eq!(record["memory"][key], end["memory"][key], "{key}");
        }
        let before = &self.case["memory"]["last_success"];
        let after = &record["memory"]["last_success"];
        if end["outcome"] == "complete" {
            assert!(after.is_string() && after != before, "last_success: {after}");
        } else {
            assert_eq!(after, before);
        }
    }

    /// Checks that every market with raw data has a generation prepared at
    /// the case's time, or none when `prepared` is false.
    fn check_prepared(&self, prepared: bool) {
        let output = Command::new(env!("CARGO_BIN_EXE_bt")).args(["data", "status", "--home", path(&self.home())]).output().unwrap();
        let status: Value = serde_json::from_slice(&output.stdout).unwrap();
        for market in status["markets"].as_array().unwrap() {
            let as_of = &market["prepared"]["as_of"];
            match (market["raw"].as_bool().unwrap(), prepared) {
                (true, true) => assert_eq!(as_of, &self.case["as_of"], "{}", market["market"]),
                _ => assert_eq!(market["prepared"], Value::Null, "{}", market["market"]),
            }
        }
    }

    /// The items of the update's journal, `data/update.done`: the files
    /// saved so far, each by its path below `raw/`.
    fn journal(&self) -> Vec<String> {
        let text = std::fs::read_to_string(self.home().join("data/update.done")).unwrap();
        text.lines().skip(1).map(str::to_string).collect()
    }
}

fn update_command(home: &Path, user: &Path, as_of: &str, provider: &str) -> Command {
    let mut command = Command::new(env!("CARGO_BIN_EXE_bt"));
    command.args(["data", "update", "--as-of", as_of, "--home", path(home)]).env("HOME", user).env("BT_PROVIDER", provider);
    command
}

fn finish(child: Child) -> (Value, Output) {
    let output = child.wait_with_output().unwrap();
    let reply = serde_json::from_slice(&output.stdout).unwrap_or_else(|_| panic!("{}", String::from_utf8_lossy(&output.stdout)));
    (reply, output)
}

/// A failure's place (`raw/px/QAB.json`, `raw/financial-inputs/key-metrics/QST.json`)
/// as `end.json` names the item (`px/QAB.json`, `key-metrics/QST`).
fn expected_item(place: &str) -> String {
    let file = place.strip_prefix("raw/").unwrap();
    match file.strip_prefix("financial-inputs/") {
        Some(report) => report.strip_suffix(".json").unwrap().to_string(),
        None => file.to_string(),
    }
}

/// The raw file below `raw/` that a request updates, as the journal names it.
fn item(request: &str) -> String {
    let request: Value = serde_json::from_str(request).unwrap();
    let (endpoint, params) = (request["endpoint"].as_str().unwrap(), &request["params"]);
    let symbol = params["symbol"].as_str().unwrap_or("");
    match endpoint {
        "company-screener" if params["exchange"] == "HKSE" => "markets/hk/universe.json".to_string(),
        "company-screener" | "delisted-companies" => "universe.json".to_string(),
        "treasury-rates" => "treasury.json".to_string(),
        "historical-price-eod/dividend-adjusted" if symbol == "SPY" => "spy-div.json".to_string(),
        "historical-price-eod/dividend-adjusted" => format!("px/{symbol}.json"),
        "historical-price-eod/full" if symbol == "^HSI" => "markets/hk/calendar.json".to_string(),
        "historical-price-eod/full" if symbol.starts_with("USD") => format!("fx/{symbol}.json"),
        "historical-price-eod/full" => format!("px-full/{symbol}.json"),
        report => format!("financial-inputs/{report}/{symbol}.json"),
    }
}

/// The expected requests of a case, less one of each request in `dropped`.
fn expected_requests(name: &str, dropped: &[Value]) -> Vec<String> {
    let text = std::fs::read_to_string(case_dir(name).join("requests.jsonl")).unwrap();
    let mut requests: Vec<String> = text.lines().map(|line| serde_json::from_str::<Value>(line).unwrap().to_string()).collect();
    for request in dropped {
        let at = requests.iter().position(|r| *r == request.to_string()).unwrap_or_else(|| panic!("{request} is not in the case's requests"));
        requests.remove(at);
    }
    requests.sort();
    requests
}

fn window(endpoint: &str, symbol: Option<&str>, from: &str, to: &str) -> Value {
    let mut params = json!({"from": from, "to": to});
    if let Some(symbol) = symbol {
        params["symbol"] = json!(symbol);
    }
    json!({"endpoint": endpoint, "params": params})
}

/// The Hong Kong pass of the old updater asks SPY's recent window and the
/// Treasury again, after the US pass has updated both files; the new update
/// asks them once, in the US pass, which leaves the same files.
fn hong_kong_repeats(from: &str, end: &str) -> Vec<Value> {
    let adjusted = "historical-price-eod/dividend-adjusted";
    vec![
        window(adjusted, Some("SPY"), from, end),
        window("treasury-rates", None, from, "2023-06-30"),
        window("treasury-rates", None, "2023-07-01", end),
    ]
}

/// Runs a case through and checks it against its expected files. `dropped`
/// are the expected requests that the update does not make.
fn replay(setup: &Setup, dropped: Vec<Value>) {
    let name = setup.name;
    let (reply, output) = setup.run();
    setup.check_requests();
    let (mut extra, mut missing) = (setup.requests(0), expected_requests(name, &dropped));
    extra.retain(|r| missing.iter().position(|m| m == r).map(|i| missing.remove(i)).is_none());
    assert!(extra.is_empty() && missing.is_empty(), "requests not in the case's list: {extra:#?}\nthe case's requests not made: {missing:#?}");
    setup.check_record(&reply);
    setup.check_raw(&end_raw(name));
    setup.check_secrets(&output);
    setup.check_prepared(true);
    assert_eq!(output.status.success(), reply["state"] != "failed");
}

/// Saturday: reports and the sweep are due; new and delisted companies,
/// refetched histories, one incomplete, retried requests, two failed items.
#[test]
fn saturday_gives_the_old_updaters_files_requests_and_record() {
    replay(&Setup::new("saturday"), hong_kong_repeats("2023-06-30", "2023-07-07"));
}

/// Monday, from Saturday's end: prices only; the failed items of Saturday
/// succeed and the update is complete.
#[test]
fn monday_gives_the_old_updaters_files_requests_and_record() {
    replay(&Setup::new("monday"), hong_kong_repeats("2023-06-30", "2023-07-09"));
}

/// Monday with QAB's saved prices unreadable: the history is asked whole
/// (the case's store holds the whole history, which the case asked after a
/// changed close), so its recent window is not asked, and the file ends as
/// expected.
#[test]
fn an_unreadable_price_file_is_asked_whole_and_replaced() {
    let setup = Setup::new("monday");
    std::fs::write(setup.home().join("raw/px/QAB.json"), b"\xff\xfe not JSON").unwrap();
    let mut dropped = hong_kong_repeats("2023-06-30", "2023-07-09");
    dropped.push(window("historical-price-eod/dividend-adjusted", Some("QAB"), "2023-06-23", "2023-07-09"));
    replay(&setup, dropped);
}

/// The provider refuses the key at the first request: the update fails with
/// the refusal, exits 1 after printing its record, still prepares the saved
/// data, and leaves the files and the report dates as they were.
#[test]
fn a_refused_key_fails_the_update_and_still_prepares() {
    let store = tempfile::tempdir().unwrap();
    let replies = store.path().join("replies.jsonl");
    let line = json!({"endpoint": "company-screener", "params": nyse_first_page(), "status": 401, "body": ""});
    std::fs::write(&replies, format!("{line}\n")).unwrap();
    let setup = Setup::serving("saturday", &replies);
    let (reply, output) = setup.run();
    assert_eq!(output.status.code(), Some(1));
    assert_eq!(reply["state"], "failed");
    let error = &reply["error"];
    assert!(error["message"].as_str().unwrap().contains("status 401"), "{error}");
    assert!(error["place"].as_str().unwrap().ends_with(".grok/secrets/fmp_api_key"), "{error}");
    assert_eq!(setup.record()["progress"]["state"], "failed");
    assert_eq!(setup.record()["memory"], setup.case["memory"]);
    assert_eq!(setup.fake.requests().len(), 1);
    setup.check_requests();
    setup.check_raw(&start_raw("saturday"));
    setup.check_secrets(&output);
    setup.check_prepared(true);
}

fn nyse_first_page() -> Value {
    json!({"exchange": "NYSE", "isActivelyTrading": "true", "isEtf": "false", "isFund": "false", "limit": "1000", "page": "0"})
}

/// Waits until the fake has seen `count` requests in all.
fn wait_for(setup: &Setup, count: usize) {
    let start = Instant::now();
    while setup.fake.requests().len() < count {
        assert!(start.elapsed() < Duration::from_secs(30), "the update made fewer than {count} requests");
        std::thread::sleep(Duration::from_millis(5));
    }
}

/// Checks that a run made no request for an item the journal held when it
/// started.
fn asks_nothing_saved(setup: &Setup, from: usize, journal: &[String]) {
    for request in setup.requests(from) {
        assert!(!journal.contains(&item(&request)), "{request} was asked again");
    }
}

/// Saturday stopped twice, by the stop file and by Ctrl+C, then run to its
/// end: each stop skips preparation, each continued run asks nothing the
/// journal holds, and the end equals the uninterrupted run's.
#[test]
fn a_stopped_update_continues_and_ends_equal() {
    let setup = Setup::new("saturday");
    let stopped = |reply: &Value| {
        assert_eq!(reply["state"], "stopped", "{reply}");
        assert_eq!(setup.record()["progress"]["state"], "stopped");
        setup.check_prepared(false);
    };

    let child = setup.start();
    wait_for(&setup, 40);
    std::fs::write(setup.home().join("data/update.stop"), "").unwrap();
    let (reply, output) = finish(child);
    assert!(output.status.success());
    stopped(&reply);
    let (first, journal) = (setup.fake.requests().len(), setup.journal());
    assert!(!journal.is_empty());

    let child = setup.start();
    wait_for(&setup, first + 40);
    Command::new("kill").args(["-INT", &child.id().to_string()]).status().unwrap();
    let (reply, _) = finish(child);
    stopped(&reply);
    asks_nothing_saved(&setup, first, &journal);
    let (second, journal) = (setup.fake.requests().len(), setup.journal());

    let (reply, output) = setup.run();
    asks_nothing_saved(&setup, second, &journal);
    setup.check_requests();
    setup.check_record(&reply);
    setup.check_raw(&end_raw("saturday"));
    setup.check_secrets(&output);
    setup.check_prepared(true);
}

/// A stop while a request is in flight: the record names the process before
/// the first request, says stopping while the request is still in flight,
/// and the command then ends stopped.
#[test]
fn a_stop_is_recorded_while_a_request_is_in_flight() {
    let store = tempfile::tempdir().unwrap();
    let replies = store.path().join("replies.jsonl");
    let line = json!({"endpoint": "company-screener", "params": nyse_first_page(), "status": 200, "body": "[]", "delay": 3});
    std::fs::write(&replies, format!("{line}\n")).unwrap();
    let setup = Setup::serving("monday", &replies);
    let child = setup.start();
    wait_for(&setup, 1);
    let progress = &setup.record()["progress"];
    assert_eq!((&progress["state"], &progress["pid"]), (&json!("running"), &json!(child.id())));
    std::fs::write(setup.home().join("data/update.stop"), "").unwrap();
    let asked = Instant::now();
    while setup.record()["progress"]["state"] != "stopping" {
        assert!(asked.elapsed() < Duration::from_secs(1), "the record did not say stopping");
        std::thread::sleep(Duration::from_millis(5));
    }
    let (reply, output) = finish(child);
    assert_eq!(reply["state"], "stopped");
    assert!(asked.elapsed() >= Duration::from_secs(2), "the request in flight was not waited for");
    setup.check_requests();
    setup.check_prepared(false);
    setup.check_secrets(&output);
}
