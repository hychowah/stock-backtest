//! Keyed tables: an exact way to write and compare two exports of the same
//! data. [`Writer`] writes the format below and [`compare`] reads it.
//!
//! # Format
//!
//! An export is a folder. It holds:
//!
//! - `manifest.json`: one JSON object with `producer` (text naming the
//!   program that wrote the export), `settings` (any JSON value that records
//!   how it was run) and `tables`, an object that maps each table name to the
//!   list of its key fields, for example `{"holdings": ["date", "symbol"]}`;
//! - one `<name>.jsonl` file for each table in `tables`.
//!
//! Each line of a `.jsonl` file is one row: a flat JSON object that maps field
//! names to values. Rows are sorted by key, ascending. The key is the list of
//! the key fields' values. Numbers compare numerically and text compares by
//! Unicode code point; a number sorts before any text. Keys are unique, and a
//! key field is never `null`.
//!
//! Values are:
//!
//! - numbers, written in the shortest spelling that reads back to the same
//!   binary64 value; `-0.0` keeps its sign. Every number is read as a binary64
//!   value, so two different integers above 2^53 compare as equal: an exporter
//!   must write an integer wider than 53 bits as text;
//! - the strings `"NaN"`, `"Infinity"` and `"-Infinity"` for values JSON
//!   cannot hold;
//! - `null` for a missing value;
//! - text and booleans.
//!
//! # Equality
//!
//! Two exports are equal when, for every table the expected manifest lists,
//! both sides have the same row keys and every other field of every row is
//! equal. Numbers are equal when their binary64 bits are equal, so `-0.0`
//! differs from `0.0`, and the integer `3` equals the float `3.0`. Text,
//! booleans and `null` must match exactly. A field that only one of two
//! matching rows has is a difference.
//!
//! [`compare`] takes the key fields from the manifest of the expected folder.
//! The actual folder needs only its table files. It reads both sides once, as
//! a streaming merge, so memory holds two rows, not two tables. A table that is
//! not in ascending key order is an error.

use serde_json::{Map, Value};
use std::cmp::Ordering;
use std::collections::BTreeMap;
use std::fs::File;
use std::io::{BufRead, BufReader, BufWriter, Lines, Write};
use std::path::{Path, PathBuf};

/// How many differing examples the report keeps for each field.
const EXAMPLES: usize = 5;

/// The result of comparing two exports.
#[derive(Debug)]
pub struct Report {
    /// One entry for each table in the expected manifest, in name order.
    pub tables: Vec<TableReport>,
}

impl Report {
    /// True when no table has a missing row, an extra row or a differing field.
    pub fn equal(&self) -> bool {
        self.tables.iter().all(TableReport::equal)
    }
}

/// The comparison of one table.
#[derive(Debug)]
pub struct TableReport {
    pub name: String,
    /// Rows whose key is on both sides.
    pub compared: u64,
    /// Rows whose key is only on the expected side.
    pub missing: u64,
    /// Rows whose key is only on the actual side.
    pub extra: u64,
    /// The differences of each field that has any, by field name.
    pub fields: BTreeMap<String, FieldDiff>,
}

impl TableReport {
    pub fn equal(&self) -> bool {
        self.missing == 0 && self.extra == 0 && self.fields.is_empty()
    }
}

/// All differences of one field in one table.
#[derive(Debug, Default)]
pub struct FieldDiff {
    pub count: u64,
    /// The first few differences, in key order.
    pub first: Vec<Diff>,
}

/// One differing value.
#[derive(Debug)]
pub struct Diff {
    /// The row's key as a JSON list.
    pub key: String,
    /// The value as JSON text, or `(absent)` when the row lacks the field.
    pub expected: String,
    pub actual: String,
    /// `|actual - expected| / |expected|` when both are numbers.
    pub relative: Option<f64>,
}

/// Compares the exports in two folders. An error message names the file and,
/// for a bad row, the line.
pub fn compare(expected: &Path, actual: &Path) -> Result<Report, String> {
    let path = expected.join("manifest.json");
    let text = std::fs::read_to_string(&path).map_err(|e| format!("cannot read {}: {e}", path.display()))?;
    let manifest: Value = serde_json::from_str(&text).map_err(|e| format!("{}: {e}", path.display()))?;
    let tables = manifest
        .get("tables")
        .and_then(Value::as_object)
        .ok_or_else(|| format!("{}: no \"tables\" object", path.display()))?;
    let mut report = Report { tables: Vec::new() };
    for (name, keys) in tables {
        let keys: Vec<&str> = keys
            .as_array()
            .and_then(|list| list.iter().map(Value::as_str).collect())
            .ok_or_else(|| format!("{}: the key fields of {name} are not a list of text", path.display()))?;
        report.tables.push(compare_table(name, &keys, expected, actual)?);
    }
    Ok(report)
}

fn compare_table(name: &str, keys: &[&str], expected: &Path, actual: &Path) -> Result<TableReport, String> {
    let file = format!("{name}.jsonl");
    let mut left = Rows::open(&expected.join(&file), keys)?;
    let mut right = Rows::open(&actual.join(&file), keys)?;
    let mut table = TableReport { name: name.to_string(), compared: 0, missing: 0, extra: 0, fields: BTreeMap::new() };
    let mut e = left.next()?;
    let mut a = right.next()?;
    loop {
        let order = match (&e, &a) {
            (None, None) => break,
            (Some(_), None) => Ordering::Less,
            (None, Some(_)) => Ordering::Greater,
            (Some(x), Some(y)) => compare_keys(&x.key, &y.key),
        };
        match order {
            Ordering::Less => {
                table.missing += 1;
                e = left.next()?;
            }
            Ordering::Greater => {
                table.extra += 1;
                a = right.next()?;
            }
            Ordering::Equal => {
                table.compared += 1;
                compare_fields(e.as_ref().unwrap(), a.as_ref().unwrap(), &mut table.fields);
                e = left.next()?;
                a = right.next()?;
            }
        }
    }
    Ok(table)
}

struct Row {
    key: Vec<Value>,
    fields: Map<String, Value>,
}

/// The rows of one table file, checked to be in ascending key order.
struct Rows<'a> {
    path: String,
    keys: &'a [&'a str],
    lines: Lines<BufReader<File>>,
    line: u64,
    last: Option<Vec<Value>>,
}

impl<'a> Rows<'a> {
    fn open(path: &Path, keys: &'a [&'a str]) -> Result<Self, String> {
        let file = File::open(path).map_err(|e| format!("cannot open {}: {e}", path.display()))?;
        Ok(Rows { path: path.display().to_string(), keys, lines: BufReader::new(file).lines(), line: 0, last: None })
    }

    fn next(&mut self) -> Result<Option<Row>, String> {
        let Some(line) = self.lines.next() else {
            return Ok(None);
        };
        self.line += 1;
        let at = |msg: String| format!("{}:{}: {msg}", self.path, self.line);
        let line = line.map_err(|e| at(e.to_string()))?;
        let Value::Object(fields) = serde_json::from_str(&line).map_err(|e| at(e.to_string()))? else {
            return Err(at("the row is not a JSON object".into()));
        };
        let mut key = Vec::with_capacity(self.keys.len());
        for name in self.keys {
            match fields.get(*name) {
                Some(v @ (Value::Number(_) | Value::String(_))) => key.push(v.clone()),
                _ => return Err(at(format!("key field {name} is missing, null or not a number or text"))),
            }
        }
        if self.last.as_deref().is_some_and(|last| compare_keys(last, &key) != Ordering::Less) {
            return Err(at("the rows are not in ascending key order".into()));
        }
        self.last = Some(key.clone());
        Ok(Some(Row { key, fields }))
    }
}

/// Numbers by value, then text by code point. A number sorts before text.
fn compare_keys(a: &[Value], b: &[Value]) -> Ordering {
    for (x, y) in a.iter().zip(b) {
        let order = match (x, y) {
            (Value::Number(x), Value::Number(y)) => x.as_f64().unwrap().partial_cmp(&y.as_f64().unwrap()).unwrap(),
            // UTF-8 byte order is code point order.
            (Value::String(x), Value::String(y)) => x.cmp(y),
            (Value::Number(_), _) => Ordering::Less,
            _ => Ordering::Greater,
        };
        if order != Ordering::Equal {
            return order;
        }
    }
    Ordering::Equal
}

fn compare_fields(e: &Row, a: &Row, out: &mut BTreeMap<String, FieldDiff>) {
    let names = e.fields.keys().chain(a.fields.keys().filter(|k| !e.fields.contains_key(*k)));
    for name in names {
        let (x, y) = (e.fields.get(name), a.fields.get(name));
        if same(x, y) {
            continue;
        }
        let diff = out.entry(name.clone()).or_default();
        diff.count += 1;
        if diff.first.len() < EXAMPLES {
            diff.first.push(Diff {
                key: Value::Array(e.key.clone()).to_string(),
                expected: x.map_or("(absent)".into(), Value::to_string),
                actual: y.map_or("(absent)".into(), Value::to_string),
                relative: relative(x, y),
            });
        }
    }
}

fn same(x: Option<&Value>, y: Option<&Value>) -> bool {
    match (x, y) {
        (Some(Value::Number(x)), Some(Value::Number(y))) => x.as_f64().unwrap().to_bits() == y.as_f64().unwrap().to_bits(),
        _ => x == y,
    }
}

fn relative(x: Option<&Value>, y: Option<&Value>) -> Option<f64> {
    let (Some(Value::Number(x)), Some(Value::Number(y))) = (x, y) else {
        return None;
    };
    let (x, y) = (x.as_f64().unwrap(), y.as_f64().unwrap());
    let gap = (y - x).abs();
    Some(if gap == 0.0 { 0.0 } else { gap / x.abs() })
}

/// Writes one export folder in the format above. Start each table with
/// [`table`](Self::table), write and finish its rows, then [`finish`](Self::finish)
/// the export to write `manifest.json`. What it writes, [`compare`] reads.
pub struct Writer {
    dir: PathBuf,
    producer: String,
    settings: Value,
    tables: Map<String, Value>,
}

impl Writer {
    /// Starts an export in `dir`, creating the folder when missing. Fails when
    /// the folder exists and is not empty, so no table of an earlier export
    /// can stay beside this one.
    pub fn create(dir: &Path, producer: &str, settings: Value) -> Result<Writer, String> {
        if std::fs::read_dir(dir).is_ok_and(|mut entries| entries.next().is_some()) {
            return Err(format!("the export folder is not empty: {}", dir.display()));
        }
        std::fs::create_dir_all(dir).map_err(|e| format!("cannot create {}: {e}", dir.display()))?;
        Ok(Writer { dir: dir.to_path_buf(), producer: producer.to_string(), settings, tables: Map::new() })
    }

    /// Starts table `name` with key fields `keys`, in `<name>.jsonl`.
    pub fn table(&mut self, name: &str, keys: &[&str]) -> Result<Table, String> {
        let path = self.dir.join(format!("{name}.jsonl"));
        let file = File::create(&path).map_err(|e| format!("cannot create {}: {e}", path.display()))?;
        self.tables.insert(name.to_string(), keys.iter().map(|k| Value::from(*k)).collect());
        let keys = keys.iter().map(|k| k.to_string()).collect();
        Ok(Table { path, keys, out: BufWriter::new(file), line: Vec::new(), last: None, rows: 0 })
    }

    /// Writes `manifest.json`, which lists every table started.
    pub fn finish(self) -> Result<(), String> {
        let manifest = serde_json::json!({ "producer": self.producer, "settings": self.settings, "tables": self.tables });
        let path = self.dir.join("manifest.json");
        let text = serde_json::to_string_pretty(&manifest).expect("a manifest is JSON") + "\n";
        std::fs::write(&path, text).map_err(|e| format!("cannot write {}: {e}", path.display()))
    }
}

/// One table being written. Rows must come in ascending, unique key order;
/// a row out of order, or whose key field is missing, null or a boolean, is
/// an error that names the file.
pub struct Table {
    path: PathBuf,
    keys: Vec<String>,
    out: BufWriter<File>,
    line: Vec<u8>,
    last: Option<Vec<Value>>,
    rows: u64,
}

/// One value of a row. Numbers are written in the shortest spelling that
/// reads back to the same binary64 value; non-finite numbers as the strings
/// the format names.
#[derive(Debug, Clone, Copy)]
pub enum Cell<'a> {
    Null,
    Bool(bool),
    Int(i64),
    Number(f64),
    Text(&'a str),
}

impl Table {
    /// Writes one row: its fields in the given order. An integer wider than
    /// 53 bits is an error: the format holds it only as text.
    pub fn row(&mut self, fields: &[(&str, Cell<'_>)]) -> Result<(), String> {
        let at = |msg: &str| format!("{}:{}: {msg}", self.path.display(), self.rows + 1);
        if let Some((name, _)) = fields.iter().find(|(_, cell)| matches!(cell, Cell::Int(n) if n.unsigned_abs() > 1 << 53)) {
            return Err(at(&format!("field {name}: integer wider than 53 bits: write it as text")));
        }
        let mut key = Vec::with_capacity(self.keys.len());
        for name in &self.keys {
            let value = match fields.iter().find(|(field, _)| field == name).map(|(_, cell)| cell) {
                Some(Cell::Int(n)) => Value::from(*n),
                Some(Cell::Number(x)) if x.is_finite() => Value::from(*x),
                Some(Cell::Text(s)) => Value::from(*s),
                _ => return Err(at(&format!("key field {name} is missing, null or not a number or text"))),
            };
            key.push(value);
        }
        if self.last.as_deref().is_some_and(|last| compare_keys(last, &key) != Ordering::Less) {
            return Err(at("the rows are not in ascending key order"));
        }
        self.last = Some(key);
        self.line.clear();
        self.line.push(b'{');
        for (i, (name, cell)) in fields.iter().enumerate() {
            if i > 0 {
                self.line.push(b',');
            }
            serde_json::to_writer(&mut self.line, name).expect("writing to memory");
            self.line.push(b':');
            match *cell {
                Cell::Null => self.line.extend_from_slice(b"null"),
                Cell::Bool(b) => serde_json::to_writer(&mut self.line, &b).expect("writing to memory"),
                Cell::Int(n) => serde_json::to_writer(&mut self.line, &n).expect("writing to memory"),
                Cell::Number(x) if x.is_nan() => self.line.extend_from_slice(b"\"NaN\""),
                Cell::Number(x) if x.is_infinite() => {
                    self.line.extend_from_slice(if x > 0.0 { b"\"Infinity\"" } else { b"\"-Infinity\"" })
                }
                Cell::Number(x) => serde_json::to_writer(&mut self.line, &x).expect("writing to memory"),
                Cell::Text(s) => serde_json::to_writer(&mut self.line, s).expect("writing to memory"),
            }
        }
        self.line.extend_from_slice(b"}\n");
        self.out.write_all(&self.line).map_err(|e| at(&e.to_string()))?;
        self.rows += 1;
        Ok(())
    }

    /// Flushes the file and returns the number of rows written.
    pub fn finish(mut self) -> Result<u64, String> {
        self.out.flush().map_err(|e| format!("cannot write {}: {e}", self.path.display()))?;
        Ok(self.rows)
    }
}
