//! The number vectors in fixtures/numbers/, each written by CPython 3.14 from
//! the call that the Python product makes. Every expected value must equal
//! the Rust result bit for bit; `-0.0` differs from `0.0`.
//!
//! A vector file is `{"behavior", "python", "source", "cases": [...]}`.
//! Numbers have the shortest round-trip spelling, the strings `"NaN"`,
//! `"Infinity"` and `"-Infinity"` stand for non-finite numbers, and `null`
//! for a missing value.

use serde::Deserialize;
use serde::de::DeserializeOwned;
use std::fs;

/// A vector number: a JSON number or one of the non-finite strings.
#[derive(Deserialize, Clone, Copy)]
#[serde(from = "Spelling")]
struct Float(f64);

#[derive(Deserialize)]
#[serde(untagged)]
enum Spelling {
    Number(f64),
    Text(String),
}

impl From<Spelling> for Float {
    fn from(spelling: Spelling) -> Float {
        Float(match spelling {
            Spelling::Number(x) => x,
            Spelling::Text(text) => match text.as_str() {
                "NaN" => f64::NAN,
                "Infinity" => f64::INFINITY,
                "-Infinity" => f64::NEG_INFINITY,
                _ => panic!("not a number: {text}"),
            },
        })
    }
}

#[derive(Deserialize)]
struct File<Case> {
    cases: Vec<Case>,
}

fn cases<Case: DeserializeOwned>(behavior: &str) -> Vec<Case> {
    let path = format!("{}/../../fixtures/numbers/{behavior}.json", env!("CARGO_MANIFEST_DIR"));
    let text = fs::read_to_string(&path).unwrap_or_else(|error| panic!("{path}: {error}"));
    let file: File<Case> = serde_json::from_str(&text).unwrap_or_else(|error| panic!("{path}: {error}"));
    assert!(!file.cases.is_empty(), "{path}: no cases");
    file.cases
}

fn floats(values: &[Float]) -> Vec<f64> {
    values.iter().map(|value| value.0).collect()
}

/// Bit equality, with `None` for a JSON `null`.
fn same(actual: Option<f64>, expected: Option<Float>) -> bool {
    actual.map(f64::to_bits) == expected.map(|value| value.0.to_bits())
}

/// Python's `sorted()`: stable and ascending, so `-0.0` and `0.0` keep their order.
fn sorted(values: &[f64]) -> Vec<f64> {
    let mut values = values.to_vec();
    values.sort_by(|a, b| a.partial_cmp(b).unwrap());
    values
}

/// The built-in `sum()` and the product's mean of holding returns.
#[derive(Deserialize)]
struct SumCase {
    /// Holding returns in order.
    values: Vec<Float>,
    /// `sum(values)`; the integer 0 for no values.
    sum: Float,
    /// `sum(values) / len(values)`, or `0.0` for no values.
    mean_return: Float,
}

#[test]
fn float_sum() {
    let cases: Vec<SumCase> = cases("float_sum");
    for case in &cases {
        let values = floats(&case.values);
        let total = numbers::sum(&values);
        let mean_return = numbers::mean_return(&values);
        assert!(same(Some(total), Some(case.sum)), "sum {values:?}: {total:?}");
        assert!(same(Some(mean_return), Some(case.mean_return)), "mean return {values:?}: {mean_return:?}");
    }
}

/// The trial statistics of a non-empty list.
#[derive(Deserialize)]
struct StatisticsCase {
    /// The values in their given order.
    values: Vec<Float>,
    /// `statistics.mean(values)`.
    mean: Float,
    /// `statistics.median(values)`.
    median: Float,
    /// `statistics.pstdev(values)`.
    pstdev: Float,
    /// `min(values)`.
    min: Float,
    /// `max(values)`.
    max: Float,
}

#[test]
fn statistics() {
    let cases: Vec<StatisticsCase> = cases("statistics");
    for case in &cases {
        let values = floats(&case.values);
        let checks = [
            ("mean", numbers::mean(&values), case.mean),
            ("median", numbers::median(&values), case.median),
            ("pstdev", numbers::pstdev(&values), case.pstdev),
            ("min", numbers::min(&values), case.min),
            ("max", numbers::max(&values), case.max),
        ];
        for (name, actual, expected) in checks {
            assert!(same(Some(actual), Some(expected)), "{name} {values:?}: {actual:?}, expected {:?}", expected.0);
        }
    }
}

/// The trial-statistics percentile.
#[derive(Deserialize)]
struct PercentileCase {
    /// The values before sorting.
    values: Vec<Float>,
    /// The probability in `[0, 1]`.
    probability: f64,
    /// The percentile of the sorted values.
    result: Float,
}

#[test]
fn percentile() {
    let cases: Vec<PercentileCase> = cases("percentile");
    for case in &cases {
        let values = sorted(&floats(&case.values));
        let actual = numbers::percentile(&values, case.probability);
        assert!(same(Some(actual), Some(case.result)), "{values:?} at {}: {actual:?}", case.probability);
    }
}

/// The draws of one generator, as the session calendar makes them.
#[derive(Deserialize)]
struct ChoiceCase {
    /// The seed of `random.Random(seed)`.
    seed: u32,
    /// The length of each list drawn from, in draw order.
    lengths: Vec<usize>,
    /// The index that `choice()` drew from each list.
    indices: Vec<usize>,
}

#[test]
fn random_choice() {
    let cases: Vec<ChoiceCase> = cases("random_choice");
    for case in &cases {
        let mut random = numbers::Random::new(case.seed);
        let indices: Vec<usize> = case.lengths.iter().map(|&len| random.choice(len)).collect();
        assert_eq!(indices, case.indices, "seed {}", case.seed);
    }
}

/// A value written to a REAL column of an entry sheet and read back.
#[derive(Deserialize)]
struct RealCase {
    /// The value written.
    value: Float,
    /// The value read back; `null` when SQLite stored NULL.
    stored: Option<Float>,
}

#[test]
fn sqlite_real() {
    let cases: Vec<RealCase> = cases("sqlite_real");
    for case in &cases {
        let actual = numbers::stored_real(case.value.0);
        assert!(same(actual, case.stored), "{:?}: {actual:?}", case.value.0);
    }
}

/// A stored lane value converted to canonical units.
#[derive(Deserialize)]
struct CanonicalCase {
    /// The stored value.
    value: Float,
    /// The decimal exponent from the stored lane to canonical units.
    scale: i32,
    /// The value in canonical units; `null` when it is not a valid input.
    result: Option<Float>,
}

#[test]
fn canonical() {
    let cases: Vec<CanonicalCase> = cases("canonical");
    for case in &cases {
        let actual = numbers::canonical(case.value.0, case.scale);
        assert!(same(actual, case.result), "{:?} scaled {}: {actual:?}", case.value.0, case.scale);
    }
}

/// A formula's annual CAGR over yearly members.
#[derive(Deserialize)]
struct AnnualCase {
    /// The first member.
    first: f64,
    /// The last member.
    last: f64,
    /// The number of yearly members, at least 2.
    count: u32,
    /// `(last / first) ** (1 / (count - 1)) - 1`.
    result: Float,
}

/// `pow` against Python's `**`, which calls the C library's `pow`.
#[test]
fn annual_cagr_pow() {
    let cases: Vec<AnnualCase> = cases("annual_cagr");
    for case in &cases {
        let actual = numbers::pow(case.last / case.first, 1.0 / (case.count - 1) as f64) - 1.0;
        assert!(same(Some(actual), Some(case.result)), "{} {} {}: {actual:?}", case.first, case.last, case.count);
    }
}

/// No vector holds a float exactly halfway between two shortest decimals.
/// Python's `str()` then takes the even last digit: `973012718181.5312` is
/// `973012718181.53125` exactly, and the decimal shifted by -2 reads back as
/// `9730127181.815311`, not `9730127181.815313`.
#[test]
fn canonical_tie() {
    assert_eq!(numbers::canonical(973012718181.5312, -2), Some(9730127181.815311));
    assert_eq!(numbers::canonical(-973012718181.5312, 6), Some(-9.730127181815311e17));
}
