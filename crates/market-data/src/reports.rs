//! Company reports. The US part: the annual key metrics of `metrics.jsonl`,
//! the only reader of that file. It owns the rules the oracle applies there:
//!
//! - The last record of a symbol wins, but the symbol keeps the position of
//!   its first record (`cache_assets.financial_records`).
//! - A report is accepted when its date reads, its market cap, enterprise
//!   value and EV/EBITDA are positive numbers and its `reportedCurrency` is
//!   USD or absent; it is known 90 days after its fiscal date, its EBITDA is
//!   EV / multiple and its yield 1 / multiple (`books.statements`). Of two
//!   reports with the same fiscal date, the later row wins.
//! - The reported set: the listed US companies with an accepted report. Its
//!   first-appearance order breaks the legacy ranking's ties, and it is the US
//!   price scope.
//!
//! Columns: `reports.offsets` (`u64`, one more than companies), and per
//! report in fiscal order `reports.fiscal`, `reports.known`,
//! `reports.market_cap`, `reports.enterprise_value`, `reports.ebitda` and
//! `reports.ebitda_yield`.

use crate::companies::{Companies, Company, CompanyId};
use crate::raw::{Raw, number, parse_day};
use crate::store::{Generation, GenerationWriter};
use crate::{Day, Error};
use serde_json::Value;
use std::collections::HashMap;
use std::io;
use tables::Cell;

/// One accepted US report.
#[derive(Clone, Copy, Debug)]
pub(crate) struct UsReport {
    pub(crate) fiscal: Day,
    pub(crate) known: Day,
    pub(crate) market_cap: f64,
    pub(crate) enterprise_value: f64,
    pub(crate) ebitda: f64,
    pub(crate) ebitda_yield: f64,
}

/// The US reported set: each company's accepted reports and its
/// first-appearance position, by [`CompanyId`].
pub(crate) struct Reported {
    reports: Vec<Vec<UsReport>>,
    order: Vec<Option<u32>>,
}

/// Reads `metrics.jsonl` for the listed `companies` (in [`CompanyId`]
/// order). A missing file gives no reports. Text that is not UTF-8, or a line
/// that is not a record with a symbol and a list of row objects, stops
/// preparation; an unreadable last line without a final newline is an
/// unfinished append and is skipped.
pub(crate) fn read_us(raw: &Raw, companies: &[Company]) -> Result<Reported, Error> {
    let path = raw.metrics();
    let bytes = match std::fs::read(&path) {
        Ok(bytes) => bytes,
        Err(e) if e.kind() == io::ErrorKind::NotFound => Vec::new(),
        Err(e) => return Err(Error::new(format!("cannot read the file: {e}"), path.display())),
    };
    let invalid = |what: String| Error::new(format!("{what}: repair annual financials from the data panel"), path.display());
    let records = records(&bytes).map_err(invalid)?;
    let mut reported = Reported { reports: vec![Vec::new(); companies.len()], order: vec![None; companies.len()] };
    let mut position = 0;
    for (symbol, rows) in records {
        let Ok(c) = companies.binary_search_by(|company| company.symbol.as_str().cmp(&symbol)) else {
            continue;
        };
        let accepted = accepted(&rows);
        if !accepted.is_empty() {
            position += 1;
            reported.reports[c] = accepted;
            reported.order[c] = Some(position);
        }
    }
    Ok(reported)
}

/// The records of `metrics.jsonl` as (symbol, rows), in first-appearance
/// order, each with its last record's rows. A line ends with `\n`, `\r\n`
/// (the raw cache's lines, written on Windows) or `\r`; blank lines are
/// skipped.
fn records(bytes: &[u8]) -> Result<Vec<(String, Vec<Value>)>, String> {
    let mut bytes = bytes;
    if bytes.last().is_some_and(|&b| b != b'\n') {
        let boundary = bytes.iter().rposition(|&b| b == b'\n').map_or(0, |i| i + 1);
        if serde_json::from_slice::<Value>(&bytes[boundary..]).is_err() {
            bytes = &bytes[..boundary];
        }
    }
    let text = std::str::from_utf8(bytes).map_err(|_| "the annual financial cache is not UTF-8 text".to_string())?;
    let mut records: Vec<(String, Vec<Value>)> = Vec::new();
    let mut positions = HashMap::new();
    for (number, line) in text.replace("\r\n", "\n").split(['\n', '\r']).enumerate() {
        if line.trim().is_empty() {
            continue;
        }
        let record = serde_json::from_str::<Value>(line).ok().and_then(|record| {
            let Value::Object(mut record) = record else { return None };
            let symbol = record.get("symbol")?.as_str().filter(|s| !s.is_empty())?.to_string();
            let Some(Value::Array(rows)) = record.remove("rows") else { return None };
            rows.iter().all(Value::is_object).then_some((symbol, rows))
        });
        let Some((symbol, rows)) = record else {
            return Err(format!("the annual financial cache has an invalid record on line {}", number + 1));
        };
        match positions.get(&symbol) {
            Some(&i) => records[i] = (symbol, rows),
            None => {
                positions.insert(symbol.clone(), records.len());
                records.push((symbol, rows));
            }
        }
    }
    Ok(records)
}

/// The accepted reports of one record's rows, in fiscal order; of equal
/// fiscal dates the later row.
fn accepted(rows: &[Value]) -> Vec<UsReport> {
    let mut reports: Vec<UsReport> = Vec::new();
    for row in rows {
        // The raw cache names the currency in capitals, or not at all.
        let usd = row.get("reportedCurrency").is_none_or(|code| code == "USD");
        let values = ["marketCap", "enterpriseValue", "evToEBITDA"].map(|key| number(row.get(key)).filter(|&v| v > 0.0));
        let (Some(fiscal), [Some(market_cap), Some(enterprise_value), Some(multiple)], true) = (parse_day(row.get("date")), values, usd)
        else {
            continue;
        };
        let report = UsReport {
            fiscal,
            known: Day(fiscal.0 + 90),
            market_cap,
            enterprise_value,
            ebitda: enterprise_value / multiple,
            ebitda_yield: 1.0 / multiple,
        };
        // Stable: equal fiscal dates keep row order, and the later replaces.
        let at = reports.partition_point(|r| r.fiscal <= fiscal);
        if at > 0 && reports[at - 1].fiscal == fiscal {
            reports[at - 1] = report;
        } else {
            reports.insert(at, report);
        }
    }
    reports
}

impl Reported {
    /// Whether the company is in the reported set: it has an accepted report.
    pub(crate) fn is_reported(&self, c: CompanyId) -> bool {
        !self.reports[c.index()].is_empty()
    }

    /// Each company's position, from 1, in the reported set's
    /// first-appearance order; `None` when unreported.
    pub(crate) fn order(&self) -> &[Option<u32>] {
        &self.order
    }

    pub(crate) fn write(&self, out: &mut GenerationWriter<'_>) -> Result<(), Error> {
        let mut offsets = vec![0u64];
        offsets.extend(self.reports.iter().scan(0u64, |end, r| {
            *end += r.len() as u64;
            Some(*end)
        }));
        let all = || self.reports.iter().flatten();
        out.column("reports.offsets", &offsets)?;
        out.column("reports.fiscal", &all().map(|r| r.fiscal).collect::<Vec<_>>())?;
        out.column("reports.known", &all().map(|r| r.known).collect::<Vec<_>>())?;
        out.column("reports.market_cap", &all().map(|r| r.market_cap).collect::<Vec<_>>())?;
        out.column("reports.enterprise_value", &all().map(|r| r.enterprise_value).collect::<Vec<_>>())?;
        out.column("reports.ebitda", &all().map(|r| r.ebitda).collect::<Vec<_>>())?;
        out.column("reports.ebitda_yield", &all().map(|r| r.ebitda_yield).collect::<Vec<_>>())
    }
}

/// Writes the US `reports` table (key `symbol`, `fiscal`) of a generation.
pub(crate) fn export_us(generation: &Generation, companies: &Companies<'_>, out: &mut tables::Writer) -> Result<u64, String> {
    let offsets = generation.column::<u64>("reports.offsets");
    let fiscal = generation.column::<Day>("reports.fiscal");
    let known = generation.column::<Day>("reports.known");
    let values = ["market_cap", "enterprise_value", "ebitda", "ebitda_yield"].map(|name| generation.column::<f64>(&format!("reports.{name}")));
    let mut table = out.table("reports", &["symbol", "fiscal"])?;
    for c in companies.ids() {
        for i in offsets[c.index()] as usize..offsets[c.index() + 1] as usize {
            table.row(&[
                ("symbol", Cell::Text(companies.symbol(c))),
                ("fiscal", Cell::Text(&fiscal[i].to_string())),
                ("known", Cell::Text(&known[i].to_string())),
                ("market_cap", Cell::Number(values[0][i])),
                ("enterprise_value", Cell::Number(values[1][i])),
                ("ebitda", Cell::Number(values[2][i])),
                ("ebitda_yield", Cell::Number(values[3][i])),
            ])?;
        }
    }
    table.finish()
}

#[cfg(test)]
mod tests {
    use super::*;

    /// metrics.jsonl was written on Windows: every line ends with `\r\n`.
    /// A symbol saved twice (510 in the raw cache) keeps the position of its
    /// first record and the rows of its last.
    #[test]
    fn crlf_lines_and_repeated_records_read_as_the_oracle_reads_them() {
        let text = b"{\"symbol\": \"B\", \"rows\": []}\r\n{\"symbol\": \"A\", \"rows\": [{}]}\r\n\r\n{\"symbol\": \"B\", \"rows\": [{}, {}]}\r\n{\"symbol\": \"C\"";
        let read = records(text).unwrap();
        let summary: Vec<(&str, usize)> = read.iter().map(|(s, rows)| (s.as_str(), rows.len())).collect();
        assert_eq!(summary, [("B", 2), ("A", 1)]);
        assert!(records(b"{\"symbol\": \"B\", \"rows\": [1]}\n").unwrap_err().contains("line 1"));
    }

    /// 22 records of the raw cache repeat a fiscal date: the later row wins.
    #[test]
    fn a_repeated_fiscal_date_keeps_the_later_row() {
        let rows: Vec<Value> = serde_json::from_str(
            r#"[{"date": "2020-12-31", "marketCap": 4, "enterpriseValue": 8, "evToEBITDA": 2, "reportedCurrency": "USD"},
                {"date": "2019-12-31", "marketCap": 1, "enterpriseValue": 1, "evToEBITDA": 1},
                {"date": "2020-12-31", "marketCap": 5, "enterpriseValue": 10, "evToEBITDA": 4},
                {"date": "2021-12-31", "marketCap": 5, "enterpriseValue": 10, "evToEBITDA": 4, "reportedCurrency": "CAD"}]"#,
        )
        .unwrap();
        let reports = accepted(&rows);
        let summary: Vec<(String, f64, f64)> = reports.iter().map(|r| (r.fiscal.to_string(), r.market_cap, r.ebitda)).collect();
        assert_eq!(summary, [("2019-12-31".into(), 1.0, 1.0), ("2020-12-31".into(), 5.0, 2.5)]);
        assert_eq!(reports[1].known.to_string(), "2021-03-31");
    }
}
