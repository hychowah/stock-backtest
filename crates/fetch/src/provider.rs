//! The data provider's client: its ten endpoints, its limits and its retries.
//!
//! The request URL holds the key, so it stays local to `Provider::get`.
//! `Provider::attempt` drops the HTTP library's errors, which can hold the
//! URL; they become `Reason::NoReply`. The HTTP library writes the full
//! query, key included, to the `log` crate at trace level; `bt` installs no
//! logger, and a logger added later must keep that library below trace.

use chrono::NaiveDate;
use std::fmt;
use std::fmt::Write as _;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

/// The provider's address when `BT_PROVIDER` is not set.
const ADDRESS: &str = "https://financialmodelingprep.com";

/// The most requests in flight at once: the update runs this many workers,
/// each with one request at a time. The client itself does not count them.
pub const IN_FLIGHT: usize = 32;

const STARTS_PER_SECOND: u32 = 45;
/// Repeated 429s halve the start rate down to one start every 2 s.
const SLOWEST_START_INTERVAL: Duration = Duration::from_secs(2);
const ATTEMPTS: u32 = 3;
const SOCKET_TIMEOUT: Duration = Duration::from_secs(15);
const ATTEMPT_TIMEOUT: Duration = Duration::from_secs(30);
const LONGEST_WAIT_SECONDS: f64 = 3600.0;
/// How often a waiting request looks at the stop flag.
const STOP_CHECK: Duration = Duration::from_millis(100);

/// The provider's address: `BT_PROVIDER` when it is set (tests point it at a
/// local server, `http://127.0.0.1:PORT`), else the provider's own address.
pub fn address() -> String {
    std::env::var("BT_PROVIDER").unwrap_or_else(|_| ADDRESS.to_string())
}

/// The account's key file, `~/.grok/secrets/fmp_api_key`.
pub fn key_file() -> PathBuf {
    std::env::home_dir().unwrap_or_default().join(".grok/secrets/fmp_api_key")
}

/// One request to one of the provider's ten endpoints. Each member holds the
/// parameters that vary; the fixed ones are written with it, so no other
/// request can be made. The query's parameters, in order, are given with
/// each member; the key (`apikey`) follows them.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Endpoint {
    /// `company-screener`: `exchange`, `isEtf=false`, `isFund=false`,
    /// `isActivelyTrading` (`true` or `false`), `limit=1000`, `page` (from 0).
    CompanyScreener { exchange: String, active: bool, page: u32 },
    /// `delisted-companies`: `page` (from 0), `limit=100`.
    DelistedCompanies { page: u32 },
    /// `income-statement`: `symbol`, `period=annual`, `limit=40`.
    IncomeStatement { symbol: String },
    /// `balance-sheet-statement`: `symbol`, `period=annual`, `limit=40`.
    BalanceSheetStatement { symbol: String },
    /// `cash-flow-statement`: `symbol`, `period=annual`, `limit=40`.
    CashFlowStatement { symbol: String },
    /// `key-metrics`: `symbol`, `period=annual`, `limit=40`.
    KeyMetrics { symbol: String },
    /// `ratios`: `symbol`, `period=annual`, `limit=40`.
    Ratios { symbol: String },
    /// `historical-price-eod/dividend-adjusted`: `from`, `to`, `symbol` (a
    /// company or `SPY`).
    DividendAdjusted { symbol: String, from: NaiveDate, to: NaiveDate },
    /// `historical-price-eod/full`: `from`, `to`, `symbol` (a company, a
    /// market's index or an exchange rate such as `USDHKD`).
    Full { symbol: String, from: NaiveDate, to: NaiveDate },
    /// `treasury-rates`: `from`, `to`.
    TreasuryRates { from: NaiveDate, to: NaiveDate },
}

impl Endpoint {
    /// The endpoint's path under `/stable/`.
    fn path(&self) -> &'static str {
        match self {
            Endpoint::CompanyScreener { .. } => "company-screener",
            Endpoint::DelistedCompanies { .. } => "delisted-companies",
            Endpoint::IncomeStatement { .. } => "income-statement",
            Endpoint::BalanceSheetStatement { .. } => "balance-sheet-statement",
            Endpoint::CashFlowStatement { .. } => "cash-flow-statement",
            Endpoint::KeyMetrics { .. } => "key-metrics",
            Endpoint::Ratios { .. } => "ratios",
            Endpoint::DividendAdjusted { .. } => "historical-price-eod/dividend-adjusted",
            Endpoint::Full { .. } => "historical-price-eod/full",
            Endpoint::TreasuryRates { .. } => "treasury-rates",
        }
    }

    fn params(&self) -> Vec<(&'static str, String)> {
        let report = |symbol: &str| {
            vec![("symbol", symbol.to_string()), ("period", "annual".to_string()), ("limit", "40".to_string())]
        };
        let window = |from: &NaiveDate, to: &NaiveDate| vec![("from", from.to_string()), ("to", to.to_string())];
        match self {
            Endpoint::CompanyScreener { exchange, active, page } => vec![
                ("exchange", exchange.clone()),
                ("isEtf", "false".to_string()),
                ("isFund", "false".to_string()),
                ("isActivelyTrading", active.to_string()),
                ("limit", "1000".to_string()),
                ("page", page.to_string()),
            ],
            Endpoint::DelistedCompanies { page } => vec![("page", page.to_string()), ("limit", "100".to_string())],
            Endpoint::IncomeStatement { symbol }
            | Endpoint::BalanceSheetStatement { symbol }
            | Endpoint::CashFlowStatement { symbol }
            | Endpoint::KeyMetrics { symbol }
            | Endpoint::Ratios { symbol } => report(symbol),
            Endpoint::DividendAdjusted { symbol, from, to } | Endpoint::Full { symbol, from, to } => {
                let mut params = window(from, to);
                params.push(("symbol", symbol.clone()));
                params
            }
            Endpoint::TreasuryRates { from, to } => window(from, to),
        }
    }
}

/// `path symbol from..to`, or the exchange and page of a company list.
impl fmt::Display for Endpoint {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let path = self.path();
        match self {
            Endpoint::CompanyScreener { exchange, active, page } => {
                let listed = if *active { "listed" } else { "not listed" };
                write!(f, "{path} {exchange} {listed} page {page}")
            }
            Endpoint::DelistedCompanies { page } => write!(f, "{path} page {page}"),
            Endpoint::IncomeStatement { symbol }
            | Endpoint::BalanceSheetStatement { symbol }
            | Endpoint::CashFlowStatement { symbol }
            | Endpoint::KeyMetrics { symbol }
            | Endpoint::Ratios { symbol } => write!(f, "{path} {symbol}"),
            Endpoint::DividendAdjusted { symbol, from, to } | Endpoint::Full { symbol, from, to } => {
                write!(f, "{path} {symbol} {from}..{to}")
            }
            Endpoint::TreasuryRates { from, to } => write!(f, "{path} {from}..{to}"),
        }
    }
}

/// A request that gave no 200 reply.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Failure {
    pub endpoint: Endpoint,
    pub reason: Reason,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Reason {
    /// The last attempt's status: one that is not tried again (such as 401,
    /// 403 or 404), or a 429, 500, 502, 503 or 504 at the third attempt.
    Status(u16),
    /// The last of three attempts got no usable reply: no connection, a
    /// timeout, a cut reply or a body that cannot be decoded.
    NoReply,
    /// The key file is missing, unreadable or empty. No request was made.
    NoKey,
    /// The stop flag was set. A reply that came after it is dropped.
    Stopped,
}

impl fmt::Display for Failure {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}: ", self.endpoint)?;
        match self.reason {
            Reason::Status(status) => write!(f, "the provider answered with status {status}"),
            Reason::NoReply => f.write_str("the provider did not reply"),
            Reason::NoKey => f.write_str("the key file cannot be read"),
            Reason::Stopped => f.write_str("stopped"),
        }
    }
}

impl std::error::Error for Failure {}

/// The client, shared by the update's workers. The stop flag is given at
/// construction.
pub struct Provider<'a> {
    agent: ureq::Agent,
    stable: String,
    key_file: PathBuf,
    key: Mutex<Option<String>>,
    stop: &'a AtomicBool,
    gate: Mutex<Gate>,
}

/// When the next attempt may start: one start per `interval`, none before
/// `paused_until`.
struct Gate {
    interval: Duration,
    last: Option<Instant>,
    paused_until: Option<Instant>,
}

enum Reply {
    Body(Vec<u8>),
    Status(u16, Option<Duration>),
    Failed,
}

impl<'a> Provider<'a> {
    /// A client of the provider at `address` (`scheme://host[:port]`, see
    /// [`address`]) with the key in `key_file`. Nothing is read or sent yet.
    pub fn new(address: &str, key_file: &Path, stop: &'a AtomicBool) -> Provider<'a> {
        let agent = ureq::Agent::config_builder()
            .http_status_as_error(false)
            .max_redirects(0)
            .proxy(None)
            .user_agent(ureq::config::AutoHeaderValue::None)
            .timeout_global(Some(ATTEMPT_TIMEOUT))
            .timeout_connect(Some(SOCKET_TIMEOUT))
            .timeout_per_read(Some(SOCKET_TIMEOUT))
            .timeout_per_write(Some(SOCKET_TIMEOUT))
            .max_idle_connections(IN_FLIGHT)
            .max_idle_connections_per_host(IN_FLIGHT)
            .build()
            .into();
        Provider {
            agent,
            stable: format!("{address}/stable/"),
            key_file: key_file.to_path_buf(),
            key: Mutex::new(None),
            stop,
            gate: Mutex::new(Gate {
                interval: Duration::from_secs(1) / STARTS_PER_SECOND,
                last: None,
                paused_until: None,
            }),
        }
    }

    /// The data provider, FMP's `/stable/` API at `address`, with the
    /// account's measured limits: at most 45 starts a second over all
    /// attempts; gzip. The requests at once are as many as the threads that
    /// call it, IN_FLIGHT (32) for the update. No reply, 429, 500, 502, 503
    /// or 504 is tried three times in all; the wait (Retry-After up to an
    /// hour, else 2 s, then 4 s) pauses every worker, and each retried 429
    /// halves the start rate for the rest of the update, down to one start
    /// every 2 s. 15 s socket
    /// timeout, 30 s per attempt. The key is read from `key_file` at the first
    /// request. No error, log line or panic holds the key, a URL or a body: a
    /// Failure names `endpoint symbol from..to` and a status.
    ///
    /// Returns a 200's decoded body. Retry-After is seconds or an HTTP date;
    /// the stop flag ends a wait at once and drops a reply that comes after it.
    pub fn get(&self, endpoint: &Endpoint) -> Result<Vec<u8>, Failure> {
        let failure = |reason| Failure { endpoint: endpoint.clone(), reason };
        let url = self.url(endpoint).ok_or_else(|| failure(Reason::NoKey))?;
        let mut reason = Reason::NoReply;
        for attempt in 1..=ATTEMPTS {
            self.start().ok_or_else(|| failure(Reason::Stopped))?;
            let reply = self.attempt(&url);
            if self.stopped() {
                return Err(failure(Reason::Stopped));
            }
            let (status, retry_after) = match reply {
                Reply::Body(body) => return Ok(body),
                Reply::Status(status, retry_after) => (Some(status), retry_after),
                Reply::Failed => (None, None),
            };
            reason = status.map_or(Reason::NoReply, Reason::Status);
            let transient = status.is_none_or(|status| matches!(status, 429 | 500 | 502 | 503 | 504));
            if !transient || attempt == ATTEMPTS {
                break;
            }
            let wait = retry_after.unwrap_or(Duration::from_secs(2u64.pow(attempt)));
            self.pause(wait, status == Some(429));
        }
        Err(failure(reason))
    }

    fn stopped(&self) -> bool {
        self.stop.load(Ordering::Relaxed)
    }

    /// The request's URL with the key, or None without a key.
    fn url(&self, endpoint: &Endpoint) -> Option<String> {
        let mut key = self.key.lock().unwrap();
        if key.is_none() {
            let text = std::fs::read_to_string(&self.key_file).ok()?;
            let text = text.trim();
            if text.is_empty() {
                return None;
            }
            *key = Some(text.to_string());
        }
        let mut url = format!("{}{}?", self.stable, endpoint.path());
        for (name, value) in endpoint.params() {
            encode(name, &mut url);
            url.push('=');
            encode(&value, &mut url);
            url.push('&');
        }
        url.push_str("apikey=");
        encode(key.as_deref().unwrap(), &mut url);
        Some(url)
    }

    /// Waits for the start rate and any pause; None when stopped.
    fn start(&self) -> Option<()> {
        loop {
            if self.stopped() {
                return None;
            }
            let delay = {
                let mut gate = self.gate.lock().unwrap();
                let now = Instant::now();
                let ready = gate.last.map(|last| last + gate.interval).max(gate.paused_until);
                match ready {
                    Some(ready) if ready > now => ready - now,
                    _ => {
                        gate.last = Some(now);
                        return Some(());
                    }
                }
            };
            std::thread::sleep(delay.min(STOP_CHECK));
        }
    }

    /// Pauses every start for `wait`; a 429 also halves the start rate.
    fn pause(&self, wait: Duration, throttled: bool) {
        let mut gate = self.gate.lock().unwrap();
        let until = Instant::now() + wait;
        gate.paused_until = Some(gate.paused_until.map_or(until, |paused| paused.max(until)));
        if throttled {
            gate.interval = (gate.interval * 2).min(SLOWEST_START_INTERVAL);
        }
    }

    /// One attempt. The library's error is dropped here: its text can hold
    /// the URL.
    fn attempt(&self, url: &str) -> Reply {
        let Ok(mut response) = self.agent.get(url).header("Accept", "application/json").call() else {
            return Reply::Failed;
        };
        let status = response.status().as_u16();
        if status != 200 {
            // The body is not read: an error's body is never decoded or kept.
            let retry_after = response.headers().get("retry-after").and_then(|value| value.to_str().ok());
            return Reply::Status(status, retry_after.and_then(retry_after_wait));
        }
        // The library decodes `gzip` and removes the header; any coding left
        // but `identity` is an unusable reply.
        let coding = response.headers().get("content-encoding").map(|value| value.to_str().unwrap_or("?"));
        if !coding.is_none_or(|coding| coding.trim().eq_ignore_ascii_case("identity")) {
            return Reply::Failed;
        }
        // `with_config()` reads without a size limit, unlike `read_to_vec()`'s
        // 10 MB default: a company list can be larger. The attempt's 30 s
        // bounds a reply.
        match response.body_mut().with_config().read_to_vec() {
            Ok(body) => Reply::Body(body),
            Err(_) => Reply::Failed,
        }
    }
}

/// A Retry-After value as a wait of at most an hour: seconds, or an HTTP
/// date. None when it is neither.
fn retry_after_wait(value: &str) -> Option<Duration> {
    let value = value.trim();
    let seconds = match value.parse::<f64>() {
        Ok(seconds) => seconds,
        Err(_) => {
            let date = chrono::DateTime::parse_from_rfc2822(value).ok()?;
            let now = SystemTime::now().duration_since(UNIX_EPOCH).ok()?.as_millis() as f64;
            (date.timestamp_millis() as f64 - now) / 1000.0
        }
    };
    let seconds = if seconds.is_nan() { 0.0 } else { seconds.clamp(0.0, LONGEST_WAIT_SECONDS) };
    Some(Duration::from_secs_f64(seconds))
}

/// Appends `text` form-encoded: letters, digits and `_.-~` as they are, a
/// space as `+`, every other byte as `%XX`.
fn encode(text: &str, url: &mut String) {
    for byte in text.bytes() {
        match byte {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'_' | b'.' | b'-' | b'~' => url.push(byte as char),
            b' ' => url.push('+'),
            _ => write!(url, "%{byte:02X}").unwrap(),
        }
    }
}
