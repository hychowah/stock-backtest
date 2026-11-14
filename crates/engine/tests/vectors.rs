//! The engine against the oracle's number vectors (fixtures/numbers/, written
//! by proof/number_vectors.py).

use engine::selection::{Row, rank};
use engine::strategy::{Order, Threshold};
use serde::Deserialize;
use serde::de::DeserializeOwned;
use serde_json::Value;

fn cases<T: DeserializeOwned>(behavior: &str) -> Vec<T> {
    #[derive(Deserialize)]
    struct File<T> {
        cases: Vec<T>,
    }
    let path = format!("{}/../../fixtures/numbers/{behavior}.json", env!("CARGO_MANIFEST_DIR"));
    let file: File<T> = serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap();
    assert!(!file.cases.is_empty());
    file.cases
}

/// A number of a vector: a JSON number, `null`, or `"NaN"`, `"Infinity"`
/// or `"-Infinity"`.
fn number(value: &Value) -> Option<f64> {
    match value {
        Value::Null => None,
        Value::String(text) => Some(match text.as_str() {
            "NaN" => f64::NAN,
            "Infinity" => f64::INFINITY,
            "-Infinity" => f64::NEG_INFINITY,
            _ => panic!("not a number: {text}"),
        }),
        value => Some(value.as_f64().unwrap()),
    }
}

/// A case of `selection_order.json`: one Rank step over the candidates.
#[derive(Deserialize)]
struct SelectionCase {
    /// `highest` or `lowest`.
    direction: String,
    rank_from: u32,
    rank_to: u32,
    /// The rows in input order: `symbol`, `candidate_rank` (or null) and the
    /// step's `value` (a number, null, or a non-finite number as text).
    candidates: Vec<Candidate>,
    /// The kept rows in rank order: `symbol`, `rank` and `value`.
    selected: Vec<Selected>,
    /// The number of rows with a finite value.
    matches: usize,
}

#[derive(Deserialize)]
struct Candidate {
    symbol: String,
    candidate_rank: Option<u32>,
    value: Value,
}

#[derive(Deserialize)]
struct Selected {
    symbol: String,
    rank: u32,
    value: f64,
}

#[test]
fn selection_order_vectors() {
    for case in cases::<SelectionCase>("selection_order") {
        let rows: Vec<Row<'_>> = case
            .candidates
            .iter()
            .map(|c| Row { symbol: &c.symbol, candidate_rank: c.candidate_rank, value: number(&c.value) })
            .collect();
        let order = if case.direction == "highest" { Order::Highest } else { Order::Lowest };
        let got: Vec<(String, u32, u64)> = rank(&rows, order, case.rank_from, case.rank_to)
            .into_iter()
            .map(|(i, r)| (rows[i].symbol.to_string(), r, rows[i].value.unwrap().to_bits()))
            .collect();
        let want: Vec<(String, u32, u64)> = case.selected.iter().map(|s| (s.symbol.clone(), s.rank, s.value.to_bits())).collect();
        assert_eq!(got, want);
        assert_eq!(rank(&rows, order, 1, 5000).len(), case.matches);
    }
}

/// A case of `threshold.json`: a submitted threshold for a source. The
/// case's `variable_unit` is the unit `unit` belongs to, and its `threshold`
/// is the decimal text in that unit, which `comparison_value` reads.
#[derive(Deserialize)]
struct ThresholdCase {
    /// The submitted decimal text.
    value: String,
    /// The display unit the text is in.
    unit: String,
    /// The decimal exponent from the source's stored values to its unit.
    storage_scale: i32,
    /// The threshold read in the source's unit.
    comparison_value: Option<f64>,
    /// The threshold in stored units, which a filter compares with.
    storage_comparison_value: Option<f64>,
    /// The product's error code when it refuses the threshold.
    error: Option<String>,
}

#[test]
fn threshold_vectors() {
    for case in cases::<ThresholdCase>("threshold") {
        let got = Threshold::new(&case.value, &case.unit, case.storage_scale);
        if case.error.is_some() {
            assert!(got.is_err(), "{} {} accepted", case.value, case.unit);
            continue;
        }
        let stored = got.unwrap().stored;
        assert_eq!(stored.to_bits(), case.storage_comparison_value.unwrap().to_bits(), "{}", case.value);
        // At scale 0 the stored threshold is the threshold in the source's unit.
        let comparison = Threshold::new(&case.value, &case.unit, 0).unwrap().stored;
        assert_eq!(comparison.to_bits(), case.comparison_value.unwrap().to_bits(), "{}", case.value);
    }
}
