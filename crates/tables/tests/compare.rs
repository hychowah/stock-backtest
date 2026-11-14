use std::path::Path;
use tables::{compare, Report};
use tempfile::TempDir;

/// Writes an export with one table, `t`, keyed by `id`.
fn export(rows: &[&str]) -> TempDir {
    let dir = tempfile::tempdir().unwrap();
    let manifest = r#"{"producer":"test","settings":{},"tables":{"t":["id"]}}"#;
    std::fs::write(dir.path().join("manifest.json"), manifest).unwrap();
    std::fs::write(dir.path().join("t.jsonl"), rows.join("\n") + "\n").unwrap();
    dir
}

fn run(expected: &[&str], actual: &[&str]) -> Result<Report, String> {
    compare(export(expected).path(), export(actual).path())
}

#[test]
fn equal_exports_have_no_differences() {
    let rows = [r#"{"id":1,"v":0.5,"s":"a"}"#, r#"{"id":2,"v":null,"s":"b"}"#];
    let report = run(&rows, &rows).unwrap();
    assert!(report.equal());
    assert_eq!(report.tables[0].compared, 2);
}

#[test]
fn one_ulp_is_a_difference_with_its_relative_size() {
    let next = f64::from_bits(1.0f64.to_bits() + 1);
    let report = run(&[r#"{"id":1,"v":1.0}"#], &[&format!(r#"{{"id":1,"v":{next:e}}}"#)]).unwrap();
    assert!(!report.equal());
    let diff = &report.tables[0].fields["v"];
    assert_eq!(diff.count, 1);
    assert_eq!(diff.first[0].key, "[1]");
    assert_eq!(diff.first[0].relative, Some(f64::EPSILON));
}

#[test]
fn negative_zero_differs_from_zero_but_integers_equal_floats() {
    assert!(!run(&[r#"{"id":1,"v":-0.0}"#], &[r#"{"id":1,"v":0.0}"#]).unwrap().equal());
    assert!(run(&[r#"{"id":1,"v":-0.0}"#], &[r#"{"id":1,"v":-0.0}"#]).unwrap().equal());
    assert!(run(&[r#"{"id":1,"v":3}"#], &[r#"{"id":1,"v":3.0}"#]).unwrap().equal());
}

#[test]
fn missing_and_extra_rows_are_counted() {
    let report = run(
        &[r#"{"id":1,"v":1}"#, r#"{"id":2,"v":2}"#, r#"{"id":4,"v":4}"#],
        &[r#"{"id":1,"v":1}"#, r#"{"id":3,"v":3}"#, r#"{"id":4,"v":4}"#],
    )
    .unwrap();
    let table = &report.tables[0];
    assert_eq!((table.compared, table.missing, table.extra), (2, 1, 1));
    assert!(!report.equal());
}

#[test]
fn null_differs_from_a_number_and_text_must_match() {
    let report = run(&[r#"{"id":1,"v":null,"s":"a"}"#], &[r#"{"id":1,"v":0,"s":"A"}"#]).unwrap();
    let fields = &report.tables[0].fields;
    assert_eq!(fields["v"].first[0].expected, "null");
    assert_eq!(fields["v"].first[0].relative, None);
    assert_eq!(fields["s"].count, 1);
}

#[test]
fn rows_out_of_order_are_an_error() {
    let error = run(&[r#"{"id":1}"#, r#"{"id":2}"#], &[r#"{"id":2}"#, r#"{"id":1}"#]).unwrap_err();
    assert!(error.contains("t.jsonl:2"), "{error}");
    assert!(error.contains("ascending"), "{error}");
}

#[test]
fn keys_sort_numbers_numerically_and_text_by_code_point() {
    let rows = [r#"{"id":2}"#, r#"{"id":10}"#];
    assert!(run(&rows, &rows).unwrap().equal());
    let text = [r#"{"id":"Z"}"#, r#"{"id":"a"}"#, r#"{"id":"é"}"#, r#"{"id":"😀"}"#];
    assert!(run(&text, &text).unwrap().equal());
}

#[test]
fn hard_to_parse_numbers_read_back_exactly() {
    // Each spelling sits next to a rounding boundary or at the edge of the
    // range. Rust's own parser is exact; the comparer must agree with it.
    let spellings = [
        "1.00000000000000011102230246251565404236316680908203125",
        "1.00000000000000011102230246251565404236316680908203126",
        "9007199254740993",
        "9007199254740993.0",
        "0.1000000000000000055511151231257827021181583404541015625",
        "2.2250738585072011e-308",
        "2.2250738585072014e-308",
        "4.9406564584124654e-324",
        "2.4703282292062327e-324",
        "2.4703282292062328e-324",
        "1.7976931348623157e308",
        "8.98846567431158e307",
        "123456789012345678901234567890",
        "0.30000000000000004",
        "5e-324",
    ];
    for text in spellings {
        let exact: f64 = text.parse().unwrap();
        let expected = format!(r#"{{"id":1,"v":{text}}}"#);
        let actual = format!(r#"{{"id":1,"v":{exact:e}}}"#);
        assert!(run(&[&expected], &[&actual]).unwrap().equal(), "{text}");
    }
}

#[test]
fn missing_folders_and_files_are_errors() {
    let dir = export(&[r#"{"id":1}"#]);
    let gone = Path::new("/nonexistent-export-folder");
    assert!(compare(dir.path(), gone).unwrap_err().contains("t.jsonl"));
    assert!(compare(gone, dir.path()).unwrap_err().contains("manifest.json"));
}

#[test]
fn a_field_on_only_one_side_is_a_difference() {
    let report = run(&[r#"{"id":1,"v":1,"w":2}"#], &[r#"{"id":1,"v":1}"#]).unwrap();
    let diff = &report.tables[0].fields["w"];
    assert_eq!(diff.count, 1);
    assert_eq!(diff.first[0].actual, "(absent)");
}
