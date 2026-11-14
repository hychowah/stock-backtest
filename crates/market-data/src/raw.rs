//! The raw provider cache (`raw/`): where each file lives, and reading its
//! JSON, numbers, dates and dated rows exactly as the oracle's Python does.
//! The program only reads `raw/`.
//!
//! JSON is read with `serde_json`. On the forms that the raw cache holds, it
//! gives Python's `json.loads` values: integers beyond 2^53 and beyond 64 bits
//! round to the nearest binary64 as Python's `float(int)` does, and a repeated
//! key keeps its last value. Numbers are JSON numbers, and dates are
//! `YYYY-MM-DD`, alone or followed by a time.
//!
//! Forms that no raw file holds are not ported and differ from the oracle:
//! - `NaN`, `Infinity`, numbers beyond the binary64 range, lone surrogates
//!   and a byte-order mark make a file unreadable; the literal `-0` reads as
//!   `-0.0` (Python: `0`).
//! - A number stored as text, `""` or a boolean is not a number (Python: text
//!   is parsed, `""` is missing rather than invalid, a boolean is 1 or 0 in
//!   reports).
//! - A date in another spelling (`YYYYMMDD`, one-digit months or days, ISO
//!   weeks) is no date.
//! - A currency code must equal the expected code exactly (Python: `""` is
//!   absent; a report's code is compared in capitals).
//! - A SPY file must be a list (Python also reads rows wrapped in an object).

use crate::{Day, Error, Market};
use serde_json::{Map, Value};
use std::collections::BTreeMap;
use std::io;
use std::path::{Path, PathBuf};
use tables::Cell;

/// The paths of the raw files that preparation reads.
pub(crate) struct Raw {
    root: PathBuf,
}

impl Raw {
    pub(crate) fn new(root: PathBuf) -> Raw {
        Raw { root }
    }

    /// The market's saved company list: US `universe.json`, the others
    /// `markets/<market>/universe.json`.
    pub(crate) fn universe(&self, market: Market) -> PathBuf {
        match market {
            Market::Us => self.root.join("universe.json"),
            _ => self.root.join("markets").join(market.id()).join("universe.json"),
        }
    }

    /// A foreign market's index calendar, `markets/<market>/calendar.json`.
    pub(crate) fn calendar(&self, market: Market) -> PathBuf {
        self.root.join("markets").join(market.id()).join("calendar.json")
    }

    /// The dividend-adjusted price file of a company, `px/<symbol>.json`.
    pub(crate) fn prices(&self, symbol: &str) -> PathBuf {
        self.root.join("px").join(file_name(symbol))
    }

    pub(crate) fn spy(&self) -> PathBuf {
        self.root.join("spy-div.json")
    }

    pub(crate) fn treasury(&self) -> PathBuf {
        self.root.join("treasury.json")
    }

    /// The US annual key metrics, one JSON record per line.
    pub(crate) fn metrics(&self) -> PathBuf {
        self.root.join("metrics.jsonl")
    }

    /// The FX files `fx/USD<currency>.json`, as (currency, path) in path order.
    pub(crate) fn fx(&self) -> Result<Vec<(String, PathBuf)>, Error> {
        let dir = self.root.join("fx");
        let entries = match std::fs::read_dir(&dir) {
            Ok(entries) => entries,
            Err(e) if e.kind() == io::ErrorKind::NotFound => return Ok(Vec::new()),
            Err(e) => return Err(Error::new(format!("cannot list the folder: {e}"), dir.display())),
        };
        let mut files = Vec::new();
        for entry in entries {
            let entry = entry.map_err(|e| Error::new(format!("cannot list the folder: {e}"), dir.display()))?;
            let name = entry.file_name();
            // The oracle's glob USD???.json: three characters of any kind.
            if let Some(currency) = name.to_str().and_then(|n| n.strip_prefix("USD")?.strip_suffix(".json"))
                && currency.chars().count() == 3
            {
                files.push((currency.to_string(), entry.path()));
            }
        }
        files.sort_by(|a, b| a.1.cmp(&b.1));
        Ok(files)
    }
}

/// A symbol's file name in `px/` and the statement folders:
/// `urllib.parse.quote(symbol, safe='')` plus `.json`.
pub(crate) fn file_name(symbol: &str) -> String {
    let mut name = String::with_capacity(symbol.len() + 5);
    for &b in symbol.as_bytes() {
        if b.is_ascii_alphanumeric() || b"_.-~".contains(&b) {
            name.push(b as char);
        } else {
            name.push_str(&format!("%{b:02X}"));
        }
    }
    name + ".json"
}

/// A raw JSON file as the oracle reads it with `json.loads(path.read_bytes())`.
pub(crate) enum Json {
    Missing,
    /// Not JSON, as the oracle's `ValueError` or `UnicodeDecodeError`.
    Unreadable,
    Value(Value),
}

/// Reads a raw JSON file. Any read failure other than a missing file is an
/// error that names the file.
pub(crate) fn read_json(path: &Path) -> Result<Json, Error> {
    match std::fs::read(path) {
        Ok(bytes) => Ok(serde_json::from_slice(&bytes).map_or(Json::Unreadable, Json::Value)),
        Err(e) if e.kind() == io::ErrorKind::NotFound => Ok(Json::Missing),
        Err(e) => Err(Error::new(format!("cannot read the file: {e}"), path.display())),
    }
}

/// A number as both oracle number readers read the raw cache's forms: a JSON
/// number (`rules.num` of reports, `facts._number` of dated rows); anything
/// else is absent.
pub(crate) fn number(value: Option<&Value>) -> Option<f64> {
    value?.as_f64()
}

/// A day as both oracle date readers read the raw cache's forms: the first
/// ten characters of a text as `YYYY-MM-DD` (`rules.parse_day` of report and
/// publication dates, some of which carry a time; `facts.row_day` of the
/// `date` of a dated row). Other values are `None`.
pub(crate) fn parse_day(value: Option<&Value>) -> Option<Day> {
    let Some(Value::String(text)) = value else { return None };
    Day::parse(text.char_indices().nth(10).map_or(text.as_str(), |(i, _)| &text[..i]))
}

/// Why a field of a dated row has no value: the oracle's reason texts.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
#[repr(u8)]
pub(crate) enum Reason {
    Missing = 1,
    Invalid = 2,
    Conflicting = 3,
    NonUsd = 4,
    /// A price series with an isolated spike keeps no close.
    InconsistentSeries = 5,
}

impl Reason {
    /// The reason's code in a reason column. 0 means valid.
    pub(crate) fn code(state: State) -> u8 {
        state.err().map_or(0, |reason| reason as u8)
    }

    /// The reason text of a code, or `None` for 0 (valid).
    pub(crate) fn text(code: u8) -> Option<&'static str> {
        Some(match code {
            0 => return None,
            1 => "MISSING_INPUT",
            2 => "INVALID_INPUT",
            3 => "CONFLICTING_INPUT",
            4 => "NON_USD_INPUT",
            5 => "INCONSISTENT_SERIES",
            _ => panic!("unknown reason code {code}"),
        })
    }
}

/// One field of one day: its value, or why it has none.
pub(crate) type State = Result<f64, Reason>;

/// A stored value and reason code as the oracle's value and reason columns
/// of an export.
pub(crate) fn state_cells(value: f64, reason: u8) -> (Cell<'static>, Cell<'static>) {
    match Reason::text(reason) {
        None => (Cell::Number(value), Cell::Null),
        Some(text) => (Cell::Null, Cell::Text(text)),
    }
}

/// `facts.observe`, the one value rule of a day: each day's state of each
/// field, by day, from rows whose `date` reads ([`parse_day`]). Equal
/// admissible values agree (the first is kept, so `0.0` and `-0.0` agree on
/// the first); different ones are [`Reason::Conflicting`]. `adjClose` and `close` must be positive
/// and, when `currency` is given, the row's `currency` and `reportedCurrency`
/// must be absent, null or equal to it; `volume` must not be negative; other
/// fields take any finite value.
pub(crate) fn observe(rows: &[Value], fields: &[&str], currency: Option<&str>) -> BTreeMap<Day, Vec<State>> {
    let mut grouped: BTreeMap<Day, Vec<&Map<String, Value>>> = BTreeMap::new();
    for row in rows {
        if let Value::Object(row) = row
            && let Some(day) = parse_day(row.get("date"))
        {
            grouped.entry(day).or_default().push(row);
        }
    }
    grouped
        .into_iter()
        .map(|(day, variants)| (day, fields.iter().map(|&field| state(&variants, field, currency)).collect()))
        .collect()
}

fn state(variants: &[&Map<String, Value>], field: &str, currency: Option<&str>) -> State {
    let price = field == "adjClose" || field == "close";
    let (mut candidates, mut invalid, mut foreign) = (Vec::<f64>::new(), false, false);
    for row in variants {
        let value = number(row.get(field));
        let incompatible = price
            && currency.is_some_and(|currency| {
                ["currency", "reportedCurrency"].iter().any(|key| match row.get(*key) {
                    None | Some(Value::Null) => false,
                    Some(code) => code != currency,
                })
            });
        let acceptable = value.is_some_and(|v| if price { v > 0.0 } else if field == "volume" { v >= 0.0 } else { true });
        if acceptable && !incompatible && !candidates.contains(&value.unwrap()) {
            candidates.push(value.unwrap());
        }
        foreign |= incompatible && value.is_some();
        invalid |= !matches!(row.get(field), None | Some(Value::Null)) && !acceptable;
    }
    match candidates[..] {
        [value] => Ok(value),
        [_, _, ..] => Err(Reason::Conflicting),
        [] if foreign => Err(Reason::NonUsd),
        [] if invalid => Err(Reason::Invalid),
        [] => Err(Reason::Missing),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Python's float(int) of the raw cache's long integers (marketCap in
    /// metrics.jsonl, fields of key-metrics and ratios files).
    #[test]
    fn integers_beyond_2_to_53_and_64_bits_round_as_python_float() {
        let read = |text: &str| number(Some(&serde_json::from_str::<Value>(text).unwrap()));
        assert_eq!(read("9007199254740993"), Some(9007199254740992.0));
        assert_eq!(read("43685852600832001"), Some(43685852600832000.0));
        assert_eq!(read("329018250000000160000"), Some(3.2901825000000016e20));
    }

    /// Publication dates carry a time (`2024-03-28 16:05:12`); report and
    /// price dates are plain.
    #[test]
    fn dates_with_a_time_read_as_their_day() {
        let day = |text: &str| parse_day(Some(&Value::from(text))).map(|d| d.to_string());
        assert_eq!(day("2024-03-28 16:05:12").as_deref(), Some("2024-03-28"));
        assert_eq!(day("2024-03-28").as_deref(), Some("2024-03-28"));
        assert_eq!(day("2023-02-29"), None);
    }
}
