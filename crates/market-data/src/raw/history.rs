//! Dated histories: company prices (`px/`, rows under `div`), native prices
//! (`px-full/`), SPY, Treasury rates, index calendars and FX rates, as the
//! old updater admits and refreshes them.

use super::{ItemError, PyJson, Raw, read_file, replace};
use super::pyjson::Object;
use crate::{Day, Error, Market};
use std::collections::BTreeMap;
use std::path::PathBuf;

/// Which history file.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum HistoryFile {
    /// A company's dividend-adjusted prices, `px/<symbol>.json`: an object
    /// whose `div` holds the rows; its other keys are kept.
    Prices(String),
    /// A Hong Kong company's unadjusted prices, `px-full/<symbol>.json`.
    Native(String),
    /// SPY's dividend-adjusted prices, `spy-div.json`.
    Spy,
    /// The Treasury rates, `treasury.json`.
    Treasury,
    /// A foreign market's index, `markets/<market>/calendar.json`.
    Calendar(Market),
    /// The daily US dollar rate of a currency, `fx/USD<currency>.json`.
    Fx(String),
}

impl HistoryFile {
    pub fn path(&self, raw: &Raw) -> PathBuf {
        match self {
            HistoryFile::Prices(symbol) => raw.prices(symbol),
            HistoryFile::Native(symbol) => raw.native(symbol),
            HistoryFile::Spy => raw.spy(),
            HistoryFile::Treasury => raw.treasury(),
            HistoryFile::Calendar(market) => raw.calendar(*market),
            HistoryFile::Fx(currency) => raw.fx_rate(currency),
        }
    }

    /// The field a row's value is read from.
    pub fn field(&self) -> &'static str {
        match self {
            HistoryFile::Prices(_) | HistoryFile::Spy => "adjClose",
            HistoryFile::Treasury => "month3",
            HistoryFile::Native(_) | HistoryFile::Calendar(_) | HistoryFile::Fx(_) => "close",
        }
    }
}

/// One window's reply, admitted by [`History::admit`]: its rows by day and
/// the days whose adjusted close is not positive, which are set aside.
#[derive(Debug, Clone)]
pub struct Window {
    rows: BTreeMap<Day, PyJson>,
    skipped: Vec<Day>,
}

/// A saved history. Load it, check the replies (admit, then for adjusted
/// prices [`changes_closes`](Self::changes_closes) and
/// [`check_whole`](Self::check_whole)), [`apply`](Self::apply) them, then
/// [`save`](Self::save).
///
/// A row is usable when its `date` begins with `YYYY-MM-DD` and its value
/// field is a number ([`PyJson::number`]): positive, except a Treasury rate.
pub struct History {
    path: PathBuf,
    field: &'static str,
    /// Whether the rows are under `div` (`px/`).
    stock: bool,
    /// The saved value: for `px/` the object holding `div`, else the row
    /// list; `None` when there is no file.
    saved: Option<PyJson>,
    /// The usable saved rows by day; of rows of one day the last.
    loaded: BTreeMap<Day, PyJson>,
    rows: BTreeMap<Day, PyJson>,
}

impl History {
    /// Reads a history; no file is an empty history. An item error when the
    /// file cannot be read, is not JSON that [`PyJson`] reads, its rows are
    /// not a list of objects, or it has rows but none usable.
    pub fn load(raw: &Raw, file: &HistoryFile) -> Result<History, ItemError> {
        let path = file.path(raw);
        let field = file.field();
        let bytes = read_file(&path).map_err(|e| ItemError::new(format!("cannot read the file: {e}"), &path))?;
        let stock = matches!(file, HistoryFile::Prices(_));
        let mut history = History { path, field, stock, saved: None, loaded: BTreeMap::new(), rows: BTreeMap::new() };
        let Some(bytes) = bytes else { return Ok(history) };
        let saved = PyJson::parse(&bytes).map_err(|e| ItemError::new(format!("the saved file is not JSON: {e}"), &history.path))?;
        let rows = if stock { saved.get("div").and_then(PyJson::as_list) } else { saved.as_list() };
        let invalid = || ItemError::new("the saved file is not a valid history", &history.path);
        let rows = rows.ok_or_else(invalid)?;
        if !rows.iter().all(|row| row.as_object().is_some()) {
            return Err(invalid());
        }
        for row in rows {
            if let Some(day) = history.usable(row) {
                history.loaded.insert(day, row.clone());
            }
        }
        if !rows.is_empty() && history.loaded.is_empty() {
            return Err(invalid());
        }
        history.rows = history.loaded.clone();
        history.saved = Some(saved);
        Ok(history)
    }

    /// A history as if its file were missing, for a saved file that
    /// [`load`](Self::load) refuses: asked whole, its reply replaces the file.
    pub fn missing(raw: &Raw, file: &HistoryFile) -> History {
        let stock = matches!(file, HistoryFile::Prices(_));
        History { path: file.path(raw), field: file.field(), stock, saved: None, loaded: BTreeMap::new(), rows: BTreeMap::new() }
    }

    /// The row's day when the row is usable.
    fn usable(&self, row: &PyJson) -> Option<Day> {
        let day = PyJson::day(row.get("date"))?;
        let value = PyJson::number(row.get(self.field))?;
        (self.field == "month3" || value > 0.0).then_some(day)
    }

    /// Whether the file exists.
    pub fn exists(&self) -> bool {
        self.saved.is_some()
    }

    /// Whether the history has no usable row.
    pub fn is_empty(&self) -> bool {
        self.rows.is_empty()
    }

    /// The first and last days with a usable row.
    pub fn first(&self) -> Option<Day> {
        self.rows.keys().next().copied()
    }

    pub fn last(&self) -> Option<Day> {
        self.rows.keys().next_back().copied()
    }

    /// Admits the reply of the window `from..=to`: a list of objects, each
    /// with a `date` in the window. Adjusted prices set aside rows whose
    /// close is a number not above zero. Every other row must be usable,
    /// one a day. An item error otherwise; the file stays as it was.
    pub fn admit(&self, reply: PyJson, from: Day, to: Day) -> Result<Window, ItemError> {
        let fail = |what: &str| ItemError::new(format!("{from} to {to}: the provider returned {what}"), &self.path);
        let PyJson::List(reply) = reply else { return Err(fail("invalid dated values")) };
        let (mut rows, mut skipped, mut candidates) = (BTreeMap::new(), Vec::new(), 0);
        for row in reply {
            let Some(day) = row.as_object().and(PyJson::day(row.get("date"))) else {
                return Err(fail("invalid dated values"));
            };
            if day < from || day > to {
                return Err(fail("values outside the requested dates"));
            }
            if self.field == "adjClose" && PyJson::number(row.get(self.field)).is_some_and(|v| v <= 0.0) {
                skipped.push(day);
                continue;
            }
            candidates += 1;
            if self.usable(&row).is_some() {
                rows.insert(day, row);
            }
        }
        if rows.len() != candidates {
            return Err(fail("invalid or duplicate dated values"));
        }
        Ok(Window { rows, skipped })
    }

    /// Whether admitted recent windows change a saved adjusted close, so
    /// that the whole history must be asked again. Only adjusted prices with
    /// saved rows and returned rows are compared; their days must overlap,
    /// or the item fails. Values compare as numbers, so `"10"` equals `10`.
    pub fn changes_closes(&self, recent: &[Window]) -> Result<bool, ItemError> {
        let current = self.values(recent);
        if self.field != "adjClose" || self.loaded.is_empty() || current.is_empty() {
            return Ok(false);
        }
        let overlap: Vec<(f64, f64)> =
            current.iter().filter_map(|(day, &new)| Some((new, self.value(self.loaded.get(day)?)))).collect();
        if overlap.is_empty() {
            return Err(ItemError::new("the price update has no saved overlap", &self.path));
        }
        Ok(overlap.iter().any(|(new, old)| new != old))
    }

    /// Checks the whole history asked again after
    /// [`changes_closes`](Self::changes_closes): it holds every saved day
    /// and every day of the recent windows, and agrees with the recent
    /// windows. An item error otherwise.
    pub fn check_whole(&self, recent: &[Window], whole: &[Window]) -> Result<(), ItemError> {
        let (current, replacement) = (self.values(recent), self.values(whole));
        if !self.loaded.keys().chain(current.keys()).all(|day| replacement.contains_key(day)) {
            return Err(ItemError::new("the adjusted history is incomplete", &self.path));
        }
        if current.iter().any(|(day, value)| replacement[day] != *value) {
            return Err(ItemError::new("the adjusted history changed during the update", &self.path));
        }
        Ok(())
    }

    /// Each day's value in admitted windows; a later window's row wins.
    fn values(&self, windows: &[Window]) -> BTreeMap<Day, f64> {
        windows.iter().flat_map(|w| w.rows.iter()).map(|(&day, row)| (day, self.value(row))).collect()
    }

    fn value(&self, row: &PyJson) -> f64 {
        PyJson::number(row.get(self.field)).expect("a usable row")
    }

    /// Applies admitted windows in order: each removes the rows of its
    /// set-aside days, then puts its rows in place of the saved ones.
    pub fn apply(&mut self, windows: Vec<Window>) {
        for window in windows {
            for day in &window.skipped {
                self.rows.remove(day);
            }
            self.rows.extend(window.rows);
        }
    }

    /// Replaces the file when there was none or its usable rows changed
    /// (Python's equality), and says whether it did. The file holds the
    /// rows newest first; `px/` keeps its other keys, `div` in its place.
    pub fn save(&mut self) -> Result<bool, Error> {
        if self.saved.is_some() && self.rows == self.loaded {
            return Ok(false);
        }
        let rows = PyJson::List(self.rows.values().rev().cloned().collect());
        let value = match self.saved.take() {
            Some(PyJson::Object(mut object)) => {
                object.insert("div", rows);
                PyJson::Object(object)
            }
            None if self.stock => {
                let mut object = Object::new();
                object.insert("div", rows);
                PyJson::Object(object)
            }
            _ => rows,
        };
        replace(&self.path, value.to_text().as_bytes())?;
        self.saved = Some(value);
        self.loaded = self.rows.clone();
        Ok(true)
    }
}
