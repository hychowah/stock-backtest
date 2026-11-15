//! The provider client against the fake provider: bodies, attempts and
//! waits, the shared pause and start rate, stop, and failure texts.

mod common;

use chrono::NaiveDate;
use common::provider::{Arrival, Encoding, FakeProvider};
use fetch::provider::{Endpoint, Failure, Provider, Reason};
use serde_json::{Value, json};
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::{Duration, Instant};
use tempfile::TempDir;

const KEY: &str = "made-up-key-7f3a";

/// A temporary folder with the store and a key file path (the file is not
/// written yet).
fn setup(lines: &[Value], encoding: Encoding) -> (TempDir, FakeProvider, PathBuf) {
    let dir = tempfile::tempdir().unwrap();
    let store = dir.path().join("replies.jsonl");
    let text: Vec<String> = lines.iter().map(Value::to_string).collect();
    std::fs::write(&store, text.join("\n") + "\n").unwrap();
    let fake = FakeProvider::start(&store, encoding);
    let key_file = dir.path().join("key");
    (dir, fake, key_file)
}

fn write_key(key_file: &PathBuf) {
    std::fs::write(key_file, format!("{KEY}\n")).unwrap();
}

fn reply(endpoint: &str, params: Value, status: u16, body: &str) -> Value {
    json!({"endpoint": endpoint, "params": params, "status": status, "body": body})
}

fn day(text: &str) -> NaiveDate {
    text.parse().unwrap()
}

fn income(symbol: &str) -> Endpoint {
    Endpoint::IncomeStatement { symbol: symbol.to_string() }
}

fn income_params(symbol: &str) -> Value {
    json!({"symbol": symbol, "period": "annual", "limit": "40"})
}

fn arrivals(fake: &FakeProvider, symbol: &str) -> Vec<Duration> {
    let requests: Vec<Arrival> = fake.requests();
    requests.iter().filter(|r| r.params.get("symbol").map(String::as_str) == Some(symbol)).map(|r| r.at).collect()
}

/// Waits until the fake has seen `count` requests.
fn wait_for(fake: &FakeProvider, count: usize) {
    let start = Instant::now();
    while fake.requests().len() < count {
        assert!(start.elapsed() < Duration::from_secs(10), "no request came");
        std::thread::sleep(Duration::from_millis(10));
    }
}

#[test]
fn every_endpoint_sends_the_old_parameters_and_gets_its_body_plain_or_gzip() {
    let from = day("2015-01-01");
    let to = day("2024-12-31");
    let report = |symbol: &str| json!({"symbol": symbol, "period": "annual", "limit": 40});
    let window = json!({"from": "2015-01-01", "to": "2024-12-31"});
    let cases = [
        (
            Endpoint::CompanyScreener { exchange: "NYSE".into(), active: false, page: 2 },
            reply(
                "company-screener",
                json!({"exchange": "NYSE", "isEtf": "false", "isFund": "false", "isActivelyTrading": "false", "limit": 1000, "page": 2}),
                200,
                "[{\"symbol\": \"A\"}]",
            ),
        ),
        (
            Endpoint::DelistedCompanies { page: 0 },
            reply("delisted-companies", json!({"page": 0, "limit": 100}), 200, "[]"),
        ),
        (Endpoint::IncomeStatement { symbol: "BRK-B".into() }, reply("income-statement", report("BRK-B"), 200, "[1]")),
        (
            Endpoint::BalanceSheetStatement { symbol: "0700.HK".into() },
            reply("balance-sheet-statement", report("0700.HK"), 200, "[2]"),
        ),
        (
            Endpoint::CashFlowStatement { symbol: "A B&C".into() },
            reply("cash-flow-statement", report("A B&C"), 200, "[3]"),
        ),
        (Endpoint::KeyMetrics { symbol: "Ünï".into() }, reply("key-metrics", report("Ünï"), 200, "[\"é\\u00e9\"]")),
        (Endpoint::Ratios { symbol: "A".into() }, reply("ratios", report("A"), 200, "[5, 1e400]")),
        (
            Endpoint::DividendAdjusted { symbol: "SPY".into(), from, to },
            reply("historical-price-eod/dividend-adjusted", json!({"from": "2015-01-01", "to": "2024-12-31", "symbol": "SPY"}), 200, "[6]"),
        ),
        (
            Endpoint::Full { symbol: "^HSI".into(), from, to },
            reply("historical-price-eod/full", json!({"from": "2015-01-01", "to": "2024-12-31", "symbol": "^HSI"}), 200, "[7]"),
        ),
        (Endpoint::TreasuryRates { from, to }, reply("treasury-rates", window, 200, "[8]")),
    ];
    let lines: Vec<Value> = cases.iter().map(|(_, line)| line.clone()).collect();
    for encoding in [Encoding::Plain, Encoding::Gzip] {
        let (_dir, fake, key_file) = setup(&lines, encoding);
        let stop = AtomicBool::new(false);
        let provider = Provider::new(fake.address(), &key_file, &stop);
        // The key is read at the first request, not before.
        write_key(&key_file);
        for (endpoint, line) in &cases {
            let body = provider.get(endpoint).unwrap_or_else(|failure| panic!("{failure}"));
            assert_eq!(String::from_utf8(body).unwrap(), line["body"].as_str().unwrap());
        }
        let requests = fake.requests();
        assert_eq!(requests.len(), cases.len());
        for request in &requests {
            assert_eq!(request.key.as_deref(), Some(KEY));
            assert!(request.accepts_gzip);
            assert_eq!(request.user_agent, None);
        }
    }
}

#[test]
fn no_reply_and_server_errors_are_tried_three_times_with_growing_waits() {
    let full = |symbol: &str| Endpoint::Full { symbol: symbol.into(), from: day("2024-01-01"), to: day("2024-12-31") };
    let params = |symbol: &str| json!({"from": "2024-01-01", "to": "2024-12-31", "symbol": symbol});
    // Every wait pauses every request, so only A waits the default 2 s and
    // 4 s; B's Retry-After of 0 keeps its attempts quick.
    let lines = [
        reply("historical-price-eod/full", params("A"), 0, ""),
        reply("historical-price-eod/full", params("A"), 500, "x"),
        reply("historical-price-eod/full", params("A"), 200, "[1]"),
        json!({"endpoint": "historical-price-eod/full", "params": params("B"), "status": 503, "retry_after": "0", "body": "x"}),
    ];
    let (_dir, fake, key_file) = setup(&lines, Encoding::Gzip);
    write_key(&key_file);
    let stop = AtomicBool::new(false);
    let provider = Provider::new(fake.address(), &key_file, &stop);
    let [a, b] = std::thread::scope(|scope| {
        let handles = ["A", "B"].map(|symbol| {
            let (provider, endpoint) = (&provider, full(symbol));
            scope.spawn(move || provider.get(&endpoint))
        });
        handles.map(|handle| handle.join().unwrap())
    });
    assert_eq!(a.unwrap(), b"[1]");
    assert_eq!(b.unwrap_err().reason, Reason::Status(503));
    assert_eq!(arrivals(&fake, "B").len(), 3);
    let times = arrivals(&fake, "A");
    assert_eq!(times.len(), 3);
    assert!(times[1] - times[0] >= Duration::from_secs(2), "{times:?}");
    assert!(times[2] - times[1] >= Duration::from_secs(4), "{times:?}");
}

#[test]
fn retry_after_pauses_every_worker_and_a_429_halves_the_start_rate() {
    let others: Vec<String> = (0..10).map(|i| format!("Y{i}")).collect();
    let mut lines = vec![
        json!({"endpoint": "income-statement", "params": income_params("X"), "status": 429, "retry_after": "3", "body": "slow down"}),
        reply("income-statement", income_params("X"), 200, "[0]"),
    ];
    lines.extend(others.iter().map(|symbol| reply("income-statement", income_params(symbol), 200, "[]")));
    let (_dir, fake, key_file) = setup(&lines, Encoding::Plain);
    write_key(&key_file);
    let stop = AtomicBool::new(false);
    let provider = Provider::new(fake.address(), &key_file, &stop);
    std::thread::scope(|scope| {
        let first = scope.spawn(|| provider.get(&income("X")));
        // The other workers start once the client has had 1 s to take the
        // 429, well inside its 3 s pause.
        wait_for(&fake, 1);
        std::thread::sleep(Duration::from_secs(1));
        let rest: Vec<_> = others.iter().map(|symbol| scope.spawn(|| provider.get(&income(symbol)))).collect();
        assert_eq!(first.join().unwrap().unwrap(), b"[0]");
        for handle in rest {
            assert_eq!(handle.join().unwrap().unwrap(), b"[]");
        }
    });
    let requests = fake.requests();
    let throttled = requests[0].at;
    let mut after: Vec<Duration> = requests[1..].iter().map(|r| r.at).collect();
    after.sort();
    assert_eq!(after.len(), 11);
    assert!(after[0] >= throttled + Duration::from_secs(3), "{throttled:?} {after:?}");
    // 11 starts at 22.5 a second span 444 ms; at 45 a second they would
    // span 222 ms. The bound lies halfway, for arrival jitter.
    let span = after[10] - after[0];
    assert!(span >= Duration::from_millis(333), "{span:?}");
}

#[test]
fn retry_after_may_be_an_http_date() {
    let date = (chrono::Utc::now() + chrono::Duration::seconds(6)).format("%a, %d %b %Y %H:%M:%S GMT").to_string();
    let lines = [
        json!({"endpoint": "income-statement", "params": income_params("X"), "status": 503, "retry_after": date, "body": ""}),
        reply("income-statement", income_params("X"), 200, "[0]"),
    ];
    let (_dir, fake, key_file) = setup(&lines, Encoding::Plain);
    write_key(&key_file);
    let stop = AtomicBool::new(false);
    let provider = Provider::new(fake.address(), &key_file, &stop);
    assert_eq!(provider.get(&income("X")).unwrap(), b"[0]");
    let times = arrivals(&fake, "X");
    // The date has whole seconds: the wait is 5 to 6 s less the set-up time,
    // not the 2 s default. The bound leaves 2 s for the set-up.
    assert!(times[1] - times[0] >= Duration::from_secs(3), "{times:?}");
}

#[test]
fn permanent_statuses_are_not_tried_again() {
    let statuses = [400u16, 401, 402, 403, 404, 302, 501];
    let lines: Vec<Value> = statuses
        .iter()
        .map(|status| reply("income-statement", income_params(&status.to_string()), *status, "no"))
        .collect();
    let (_dir, fake, key_file) = setup(&lines, Encoding::Gzip);
    write_key(&key_file);
    let stop = AtomicBool::new(false);
    let provider = Provider::new(fake.address(), &key_file, &stop);
    let start = Instant::now();
    for status in statuses {
        let failure = provider.get(&income(&status.to_string())).unwrap_err();
        assert_eq!(failure.reason, Reason::Status(status));
    }
    assert_eq!(fake.requests().len(), statuses.len());
    assert!(start.elapsed() < Duration::from_secs(2));
}

#[test]
fn a_stop_ends_a_wait_and_starts_nothing() {
    let lines = [json!({"endpoint": "income-statement", "params": income_params("X"), "status": 429, "retry_after": "60", "body": ""})];
    let (_dir, fake, key_file) = setup(&lines, Encoding::Plain);
    write_key(&key_file);
    let stop = AtomicBool::new(false);
    let provider = Provider::new(fake.address(), &key_file, &stop);
    let stopped = std::thread::scope(|scope| {
        let waiting = scope.spawn(|| provider.get(&income("X")));
        wait_for(&fake, 1);
        std::thread::sleep(Duration::from_millis(200));
        stop.store(true, Ordering::Relaxed);
        let stopped = Instant::now();
        assert_eq!(waiting.join().unwrap().unwrap_err().reason, Reason::Stopped);
        stopped.elapsed()
    });
    assert!(stopped < Duration::from_secs(1), "{stopped:?}");
    assert_eq!(provider.get(&income("Y")).unwrap_err().reason, Reason::Stopped);
    assert_eq!(fake.requests().len(), 1);
}

#[test]
fn failure_texts_hold_no_address_key_or_body() {
    let canary = "BODY-CANARY";
    let full = |symbol: &str| Endpoint::Full { symbol: symbol.into(), from: day("2015-01-01"), to: day("2024-12-31") };
    let params = |symbol: &str| json!({"from": "2015-01-01", "to": "2024-12-31", "symbol": symbol});
    let lines = [
        reply("historical-price-eod/full", params("0700.HK"), 404, canary),
        json!({"endpoint": "historical-price-eod/full", "params": params("B"), "status": 503, "retry_after": "0", "body": canary}),
        json!({"endpoint": "historical-price-eod/full", "params": params("C"), "status": 0, "retry_after": "0", "body": canary}),
    ];
    let (dir, fake, key_file) = setup(&lines, Encoding::Gzip);
    let stop = AtomicBool::new(false);
    let mut failures: Vec<Failure> = Vec::new();
    // Without a key file, then with an empty one: no request is made.
    let provider = Provider::new(fake.address(), &key_file, &stop);
    failures.push(provider.get(&full("A")).unwrap_err());
    std::fs::write(&key_file, "\n").unwrap();
    failures.push(provider.get(&full("A")).unwrap_err());
    assert!(failures.iter().all(|failure| failure.reason == Reason::NoKey));
    assert!(fake.requests().is_empty());
    write_key(&key_file);
    for symbol in ["0700.HK", "B", "C"] {
        failures.push(provider.get(&full(symbol)).unwrap_err());
    }
    assert_eq!(
        failures[2].to_string(),
        "historical-price-eod/full 0700.HK 2015-01-01..2024-12-31: the provider answered with status 404"
    );
    assert_eq!(failures[3].reason, Reason::Status(503));
    assert_eq!(failures[4].reason, Reason::NoReply);
    // A refused connection.
    let closed = {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        format!("http://{}", listener.local_addr().unwrap())
    };
    let other_key = dir.path().join("other-key");
    std::fs::write(&other_key, KEY).unwrap();
    let refused = Provider::new(&closed, &other_key, &stop);
    let start = Instant::now();
    std::thread::scope(|scope| {
        let waiting = scope.spawn(|| refused.get(&Endpoint::DelistedCompanies { page: 3 }));
        // The first attempt fails at once; stop ends the 2 s wait.
        std::thread::sleep(Duration::from_millis(300));
        stop.store(true, Ordering::Relaxed);
        failures.push(waiting.join().unwrap().unwrap_err());
    });
    assert!(start.elapsed() < Duration::from_secs(2));
    assert_eq!(failures[5].reason, Reason::Stopped);
    assert_eq!(failures[5].to_string(), "delisted-companies page 3: stopped");
    for failure in &failures {
        for text in [failure.to_string(), format!("{failure:?}")] {
            for secret in ["http", "127.0.0.1", "apikey", KEY, canary, "stable"] {
                assert!(!text.contains(secret), "{text}");
            }
        }
    }
}
