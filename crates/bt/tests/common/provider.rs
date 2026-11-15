//! A fake data provider: serves a reply store on `127.0.0.1` and logs each
//! request.
//!
//! The store is JSONL. Each line is `{"endpoint", "params", "status",
//! "retry_after"?, "body"}`: `params` holds the decoded query without the key
//! (a number stands for its text), `status` 0 closes the connection without
//! a reply, and `body` is the exact decoded text. The lines of one request
//! (one endpoint with one set of parameters) are served in file order, and
//! the last one repeats. A request that is not in the store gets a 404 with
//! an empty body and is also kept apart ([`FakeProvider::unknown`]), so a
//! test can assert that every request had a stored reply. A line may also
//! hold `delay`, seconds to wait before replying, which keeps a request in
//! flight.

use flate2::Compression;
use flate2::write::GzEncoder;
use serde_json::Value;
use std::collections::{BTreeMap, HashMap};
use std::io::{BufRead, BufReader, Write};
use std::net::{TcpListener, TcpStream};
use std::path::Path;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

/// How the fake sends a body.
#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Encoding {
    Plain,
    /// gzip, to a request that accepts it.
    Gzip,
}

/// One request as it arrived.
#[derive(Clone, Debug)]
pub struct Arrival {
    /// The path after `/stable/`.
    pub endpoint: String,
    /// The decoded query without `apikey`.
    pub params: BTreeMap<String, String>,
    /// The decoded `apikey`.
    pub key: Option<String>,
    /// The request's `Accept-Encoding` named gzip.
    pub accepts_gzip: bool,
    /// The request's `User-Agent`.
    pub user_agent: Option<String>,
    /// The time since the fake started.
    pub at: Duration,
}

struct Reply {
    status: u16,
    retry_after: Option<String>,
    body: String,
    delay: Duration,
}

type Request = (String, BTreeMap<String, String>);

struct Store {
    replies: HashMap<Request, Vec<Reply>>,
    served: HashMap<Request, usize>,
    log: Vec<Arrival>,
    unknown: Vec<Arrival>,
}

pub struct FakeProvider {
    address: String,
    store: Arc<Mutex<Store>>,
}

impl FakeProvider {
    /// Serves the store at `store` on a free port of `127.0.0.1`. The fake
    /// runs until the test process ends.
    pub fn start(store: &Path, encoding: Encoding) -> FakeProvider {
        let mut replies: HashMap<Request, Vec<Reply>> = HashMap::new();
        for line in std::fs::read_to_string(store).unwrap().lines().filter(|line| !line.trim().is_empty()) {
            let line: Value = serde_json::from_str(line).unwrap();
            let params = line["params"].as_object().unwrap().iter().map(|(name, value)| (name.clone(), text(value)));
            let request = (line["endpoint"].as_str().unwrap().to_string(), params.collect());
            replies.entry(request).or_default().push(Reply {
                status: line["status"].as_u64().unwrap() as u16,
                retry_after: line.get("retry_after").map(text),
                body: line["body"].as_str().unwrap().to_string(),
                delay: Duration::from_secs_f64(line.get("delay").map_or(0.0, |d| d.as_f64().unwrap())),
            });
        }
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = format!("http://{}", listener.local_addr().unwrap());
        let store = Arc::new(Mutex::new(Store { replies, served: HashMap::new(), log: Vec::new(), unknown: Vec::new() }));
        let started = Instant::now();
        let shared = store.clone();
        std::thread::spawn(move || {
            for stream in listener.incoming() {
                let store = shared.clone();
                std::thread::spawn(move || serve(stream.unwrap(), &store, encoding, started));
            }
        });
        FakeProvider { address, store }
    }

    /// `http://127.0.0.1:PORT`, the address to give the client.
    pub fn address(&self) -> &str {
        &self.address
    }

    /// The requests so far, in order of arrival.
    pub fn requests(&self) -> Vec<Arrival> {
        self.store.lock().unwrap().log.clone()
    }

    /// The requests that had no stored reply (each got a 404).
    pub fn unknown(&self) -> Vec<Arrival> {
        self.store.lock().unwrap().unknown.clone()
    }
}

fn text(value: &Value) -> String {
    match value {
        Value::String(text) => text.clone(),
        Value::Number(number) => number.to_string(),
        other => panic!("not a parameter value: {other}"),
    }
}

/// Serves one connection's requests until the client closes it.
fn serve(stream: TcpStream, store: &Mutex<Store>, encoding: Encoding, started: Instant) {
    let mut reader = BufReader::new(stream.try_clone().unwrap());
    let mut stream = stream;
    loop {
        let mut line = String::new();
        if reader.read_line(&mut line).unwrap_or(0) == 0 {
            return;
        }
        let mut accepts_gzip = false;
        let mut user_agent = None;
        loop {
            let mut header = String::new();
            if reader.read_line(&mut header).unwrap_or(0) == 0 {
                return;
            }
            if header == "\r\n" {
                break;
            }
            let (name, value) = header.split_once(':').unwrap();
            if name.eq_ignore_ascii_case("accept-encoding") && value.to_ascii_lowercase().contains("gzip") {
                accepts_gzip = true;
            }
            if name.eq_ignore_ascii_case("user-agent") {
                user_agent = Some(value.trim().to_string());
            }
        }
        let target = line.split(' ').nth(1).unwrap();
        let (path, query) = target.split_once('?').unwrap_or((target, ""));
        let endpoint = path.strip_prefix("/stable/").unwrap_or(path).to_string();
        let mut params: BTreeMap<String, String> =
            query.split('&').filter(|pair| !pair.is_empty()).map(|pair| {
                let (name, value) = pair.split_once('=').unwrap_or((pair, ""));
                (decode(name), decode(value))
            }).collect();
        let key = params.remove("apikey");
        let reply = {
            let mut store = store.lock().unwrap();
            let at = started.elapsed();
            let arrival = Arrival { endpoint: endpoint.clone(), params: params.clone(), key, accepts_gzip, user_agent, at };
            store.log.push(arrival.clone());
            let request = (endpoint, params);
            let index = *store.served.entry(request.clone()).and_modify(|n| *n += 1).or_insert(0);
            let reply = store.replies.get(&request).map(|replies| {
                let reply = &replies[index.min(replies.len() - 1)];
                (reply.status, reply.retry_after.clone(), reply.body.clone(), reply.delay)
            });
            if reply.is_none() {
                store.unknown.push(arrival);
            }
            reply
        };
        let (status, retry_after, body, delay) = reply.unwrap_or((404, None, String::new(), Duration::ZERO));
        std::thread::sleep(delay);
        if status == 0 {
            return;
        }
        let gzip = encoding == Encoding::Gzip && accepts_gzip;
        let body = if gzip {
            let mut encoder = GzEncoder::new(Vec::new(), Compression::default());
            encoder.write_all(body.as_bytes()).unwrap();
            encoder.finish().unwrap()
        } else {
            body.into_bytes()
        };
        let mut head = format!("HTTP/1.1 {status} Reply\r\nContent-Type: application/json\r\nContent-Length: {}\r\n", body.len());
        if gzip {
            head.push_str("Content-Encoding: gzip\r\n");
        }
        if let Some(retry_after) = retry_after {
            head.push_str(&format!("Retry-After: {retry_after}\r\n"));
        }
        head.push_str("\r\n");
        // One write: a head and body sent apart wait for the client's
        // delayed acknowledgement.
        let mut message = head.into_bytes();
        message.extend_from_slice(&body);
        if stream.write_all(&message).is_err() {
            return;
        }
    }
}

/// Decodes one form-encoded query part: `+` is a space, `%XX` a byte.
fn decode(text: &str) -> String {
    let bytes = text.as_bytes();
    let mut decoded = Vec::new();
    let mut i = 0;
    while i < bytes.len() {
        match bytes[i] {
            b'+' => decoded.push(b' '),
            b'%' => {
                decoded.push(u8::from_str_radix(&text[i + 1..i + 3], 16).unwrap());
                i += 2;
            }
            byte => decoded.push(byte),
        }
        i += 1;
    }
    String::from_utf8(decoded).unwrap()
}
