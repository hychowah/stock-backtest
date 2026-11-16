//! A company's annual statements of one endpoint,
//! `financial-inputs/<endpoint>/<symbol>.json`, as the old updater admits
//! and merges them.

use super::{ItemError, PyJson, Raw, read_file, replace};
use super::pyjson::Object;
use crate::Error;
use std::collections::HashMap;
use std::path::PathBuf;

/// The annual endpoints whose replies are saved as statements files.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum StatementKind {
    Income,
    Balance,
    CashFlow,
    KeyMetrics,
    Ratios,
}

impl StatementKind {
    /// The US endpoints, in the old updater's order.
    pub const US: [StatementKind; 5] = [
        StatementKind::Income,
        StatementKind::Balance,
        StatementKind::CashFlow,
        StatementKind::KeyMetrics,
        StatementKind::Ratios,
    ];

    /// The Hong Kong endpoints.
    pub const FOREIGN: [StatementKind; 3] = [StatementKind::Income, StatementKind::Balance, StatementKind::CashFlow];

    /// The endpoint's name, which is also its folder.
    pub fn endpoint(self) -> &'static str {
        match self {
            StatementKind::Income => "income-statement",
            StatementKind::Balance => "balance-sheet-statement",
            StatementKind::CashFlow => "cash-flow-statement",
            StatementKind::KeyMetrics => "key-metrics",
            StatementKind::Ratios => "ratios",
        }
    }

    /// The fields that must be numbers when present (`ENDPOINTS`).
    fn numbers(self) -> &'static [&'static str] {
        match self {
            StatementKind::Income => &["revenue", "operatingIncome", "netIncome", "epsDiluted", "ebit", "interestExpense"],
            StatementKind::Balance => &["totalStockholdersEquity", "totalCurrentAssets", "totalCurrentLiabilities", "totalDebt"],
            StatementKind::CashFlow => &["freeCashFlow"],
            StatementKind::KeyMetrics | StatementKind::Ratios => &[],
        }
    }
}

/// A saved statements file: `{"version": 2, "full_response": true,
/// "symbol", "endpoint", "rows"}`, version 1 or 2 when read. Load it,
/// [`apply`](Self::apply) a reply, then [`save`](Self::save).
pub struct Statements {
    path: PathBuf,
    kind: StatementKind,
    symbol: String,
    /// The file's bytes as loaded or last saved; `None` when there is no file.
    bytes: Option<Vec<u8>>,
    rows: Vec<PyJson>,
}

impl Statements {
    /// Reads a company's statements of one endpoint; no file is no rows. An
    /// item error when the file cannot be read, is not JSON that [`PyJson`]
    /// reads, is not a statements file of this company and endpoint, or a
    /// row is not admissible (see [`apply`](Self::apply)).
    pub fn load(raw: &Raw, kind: StatementKind, symbol: &str) -> Result<Statements, ItemError> {
        let path = raw.statement(kind.endpoint(), symbol);
        let bytes = read_file(&path).map_err(|e| ItemError::new(format!("cannot read the file: {e}"), &path))?;
        let mut statements = Statements { path, kind, symbol: symbol.to_string(), bytes: None, rows: Vec::new() };
        let Some(bytes) = bytes else { return Ok(statements) };
        let record = PyJson::parse(&bytes).map_err(|e| ItemError::new(format!("the saved file is not JSON: {e}"), &statements.path))?;
        let version = record.get("version");
        let identified = (version == Some(&PyJson::from(1)) || version == Some(&PyJson::from(2)))
            && record.get("symbol") == Some(&PyJson::from(symbol))
            && record.get("endpoint") == Some(&PyJson::from(kind.endpoint()));
        let invalid = |what: &str| ItemError::new(format!("the saved file is not a valid statements file: {what}"), &statements.path);
        let rows = record.get("rows").filter(|_| identified).ok_or_else(|| invalid("another version, company or endpoint"))?;
        statements.check(rows).map_err(|what| invalid(&what))?;
        statements.rows = rows.as_list().unwrap().to_vec();
        statements.bytes = Some(bytes);
        Ok(statements)
    }

    /// The saved rows, or after [`apply`](Self::apply) the merged ones.
    pub fn rows(&self) -> &[PyJson] {
        &self.rows
    }

    /// Whether the file exists.
    pub fn exists(&self) -> bool {
        self.bytes.is_some()
    }

    /// The check of the rows of a saved file or of a reply: a list of
    /// objects, each with a `date` that begins with `YYYY-MM-DD`, its `symbol`
    /// (when present) the company's, its `period` (when present) `FY`, and
    /// each of the endpoint's number fields absent, `null` or a number
    /// ([`PyJson::number`], not a boolean).
    fn check(&self, rows: &PyJson) -> Result<(), String> {
        let rows = rows.as_list().ok_or("the rows are not a list")?;
        for row in rows {
            if row.as_object().is_none() || PyJson::day(row.get("date")).is_none() {
                return Err("a row has no valid date".to_string());
            }
            let symbol = row.get("symbol").is_none_or(|s| *s == PyJson::from(self.symbol.as_str()));
            let period = row.get("period").is_none_or(|p| *p == PyJson::from("FY"));
            if !symbol || !period {
                return Err("a row is of another company or period".to_string());
            }
            for field in self.kind.numbers() {
                let number = row.get(field);
                let invalid = matches!(number, Some(PyJson::Bool(_)))
                    || number.is_some_and(|n| *n != PyJson::Null && PyJson::number(Some(n)).is_none());
                if invalid {
                    return Err(format!("{field} is not a number"));
                }
            }
        }
        Ok(())
    }

    /// Merges a reply: the reply's rows, then each saved row beyond the
    /// number of rows with its text (`json.dumps(sort_keys=True)`) that the
    /// result already holds, so saved variants stay and an unchanged reply
    /// adds nothing. An item error when the reply is not admissible (as
    /// [`load`](Self::load) checks a row); the rows stay as they were.
    pub fn apply(&mut self, reply: &PyJson) -> Result<(), ItemError> {
        self.check(reply).map_err(|what| ItemError::new(format!("the provider returned an invalid statement: {what}"), &self.path))?;
        let mut merged = reply.as_list().unwrap().to_vec();
        let mut counts: HashMap<String, usize> = HashMap::new();
        for row in &merged {
            *counts.entry(row.sorted_text()).or_default() += 1;
        }
        let mut seen: HashMap<String, usize> = HashMap::new();
        for row in &self.rows {
            let text = row.sorted_text();
            let seen = seen.entry(text.clone()).or_default();
            *seen += 1;
            let count = counts.entry(text).or_default();
            if *seen > *count {
                merged.push(row.clone());
                *count += 1;
            }
        }
        self.rows = merged;
        Ok(())
    }

    /// Replaces the file when its bytes change, and says whether it did.
    pub fn save(&mut self) -> Result<bool, Error> {
        let mut record = Object::new();
        record.insert("version", PyJson::from(2));
        record.insert("full_response", PyJson::from(true));
        record.insert("symbol", PyJson::from(self.symbol.as_str()));
        record.insert("endpoint", PyJson::from(self.kind.endpoint()));
        record.insert("rows", PyJson::List(self.rows.clone()));
        let text = PyJson::Object(record).to_text().into_bytes();
        if self.bytes.as_ref() == Some(&text) {
            return Ok(false);
        }
        replace(&self.path, &text)?;
        self.bytes = Some(text);
        Ok(true)
    }
}
