//! The US annual key metrics, `metrics.jsonl`: one JSON record `{symbol,
//! rows, full_response}` per line, where a symbol's last line is its record.
//! An update keeps the values of fiscal dates already saved and appends new
//! records.

use super::{PyJson, Raw, read_file, replace};
use super::pyjson::Object;
use crate::{Day, Error};
use std::collections::{BTreeMap, HashMap, HashSet};
use std::ops::Range;
use std::path::PathBuf;

/// The saved key metrics and this stage's new records. Load it,
/// [`apply`](Self::apply) each accepted reply, then [`save`](Self::save)
/// once, at the stage's end or at a stop.
pub struct KeyMetrics {
    path: PathBuf,
    bytes: Vec<u8>,
    /// Each symbol's last record, as its line's place in `bytes`.
    last: HashMap<String, Range<usize>>,
    /// The new records by symbol.
    added: BTreeMap<String, PyJson>,
}

impl KeyMetrics {
    /// Reads the key metrics; no file is no records. An unfinished last
    /// line (no final line break) that is not JSON is dropped first, by
    /// replacing the file without it, as the old updater truncated it. A
    /// line ends with `\n`, `\r\n` or `\r`; blank lines are skipped. Fails,
    /// naming the file and line, when a line is not a record (an object with
    /// a non-empty text `symbol` and a list of objects `rows`): the old
    /// updater then updated nothing.
    pub fn load(raw: &Raw) -> Result<KeyMetrics, Error> {
        let path = raw.metrics();
        let read = read_file(&path).map_err(|e| Error::new(format!("cannot read the key metrics: {e}"), path.display()))?;
        let mut bytes = read.unwrap_or_default();
        if bytes.last().is_some_and(|&b| b != b'\n') {
            let boundary = bytes.iter().rposition(|&b| b == b'\n').map_or(0, |i| i + 1);
            if PyJson::parse(&bytes[boundary..]).is_err() {
                bytes.truncate(boundary);
                replace(&path, &bytes)?;
            }
        }
        let mut last = HashMap::new();
        for (number, line) in lines(&bytes).into_iter().enumerate() {
            let text = std::str::from_utf8(&bytes[line.clone()]).ok();
            if text.is_some_and(|t| t.trim().is_empty()) {
                continue;
            }
            let record = PyJson::parse(&bytes[line.clone()]).ok();
            let symbol = record.as_ref().and_then(|r| {
                let rows = r.get("rows")?.as_list()?;
                rows.iter().all(|row| row.as_object().is_some()).then_some(())?;
                r.get("symbol")?.as_str().filter(|s| !s.is_empty())
            });
            let Some(symbol) = symbol else {
                return Err(Error::new(format!("line {} is not a key-metrics record", number + 1), path.display()));
            };
            last.insert(symbol.to_string(), line);
        }
        Ok(KeyMetrics { path, bytes, last, added: BTreeMap::new() })
    }

    /// A symbol's record: this stage's new one, else its last saved line.
    fn record(&self, symbol: &str) -> Option<PyJson> {
        if let Some(record) = self.added.get(symbol) {
            return Some(record.clone());
        }
        let line = self.last.get(symbol)?;
        Some(PyJson::parse(&self.bytes[line.clone()]).expect("a line checked at load"))
    }

    /// A symbol's rows, `None` when it has no record.
    pub fn rows(&self, symbol: &str) -> Option<Vec<PyJson>> {
        let record = self.record(symbol)?;
        Some(record.get("rows").and_then(PyJson::as_list).expect("a record's rows").to_vec())
    }

    /// Merges a key-metrics reply that [`Statements`](super::Statements)
    /// accepted: the saved rows, then the reply's rows of fiscal dates that
    /// no saved row has. A new record is kept for [`save`](Self::save) when
    /// the symbol had none or rows were added; it is `full_response: false`
    /// when saved rows came from a record without a true `full_response`.
    /// Returns whether a record was kept.
    pub fn apply(&mut self, symbol: &str, reply: &[PyJson]) -> bool {
        let previous = self.record(symbol);
        let saved: Vec<PyJson> = previous.as_ref().map_or_else(Vec::new, |p| p.get("rows").and_then(PyJson::as_list).unwrap().to_vec());
        let dates: HashSet<Option<Day>> = saved.iter().map(|row| PyJson::day(row.get("date"))).collect();
        let new: Vec<PyJson> = reply.iter().filter(|row| !dates.contains(&PyJson::day(row.get("date")))).cloned().collect();
        if previous.is_some() && new.is_empty() {
            return false;
        }
        let full = saved.is_empty() || previous.as_ref().and_then(|p| p.get("full_response")).is_some_and(PyJson::truthy);
        let mut record = Object::new();
        record.insert("symbol", PyJson::from(symbol));
        record.insert("rows", PyJson::List(saved.into_iter().chain(new).collect()));
        record.insert("full_response", PyJson::from(full));
        self.added.insert(symbol.to_string(), PyJson::Object(record));
        true
    }

    /// Appends the new records, one line each in symbol order, after a line
    /// break when the file lacks a final one, by replacing the file; says
    /// whether there were any.
    pub fn save(&mut self) -> Result<bool, Error> {
        if self.added.is_empty() {
            return Ok(false);
        }
        let mut bytes = self.bytes.clone();
        if bytes.last().is_some_and(|&b| b != b'\n') {
            bytes.push(b'\n');
        }
        let mut places = Vec::new();
        for (symbol, record) in &self.added {
            let start = bytes.len();
            bytes.extend_from_slice(record.to_text().as_bytes());
            places.push((symbol.clone(), start..bytes.len()));
            bytes.push(b'\n');
        }
        replace(&self.path, &bytes)?;
        self.bytes = bytes;
        self.last.extend(places);
        self.added.clear();
        Ok(true)
    }
}

/// The lines of `bytes` without their ends (`\n`, `\r\n` or `\r`).
fn lines(bytes: &[u8]) -> Vec<Range<usize>> {
    let (mut lines, mut start, mut i) = (Vec::new(), 0, 0);
    while i < bytes.len() {
        match bytes[i] {
            b'\n' => {
                lines.push(start..i);
                start = i + 1;
            }
            b'\r' => {
                lines.push(start..i);
                if bytes.get(i + 1) == Some(&b'\n') {
                    i += 1;
                }
                start = i + 1;
            }
            _ => {}
        }
        i += 1;
    }
    if start < bytes.len() {
        lines.push(start..bytes.len());
    }
    lines
}
