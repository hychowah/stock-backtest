use std::path::Path;
use tables::{Cell, Writer, compare};

/// Writes table `t` (key `id`) with one row whose field `v` is `v`.
fn write(dir: &Path, v: f64) {
    let mut out = Writer::create(dir, "test", serde_json::json!({})).unwrap();
    let mut t = out.table("t", &["id"]).unwrap();
    let row = |id: i64, value: Cell<'static>| {
        [("id", Cell::Int(id)), ("v", value), ("s", Cell::Text("é\"\n")), ("b", Cell::Bool(true)), ("n", Cell::Null)]
    };
    t.row(&row(1, Cell::Number(f64::NAN))).unwrap();
    t.row(&row(2, Cell::Number(-0.0))).unwrap();
    t.row(&row(10, Cell::Number(f64::NEG_INFINITY))).unwrap();
    t.row(&row(11, Cell::Number(v))).unwrap();
    assert!(t.row(&row(3, Cell::Null)).unwrap_err().contains("ascending"));
    assert!(t.row(&row(12, Cell::Int((1 << 53) + 1))).unwrap_err().contains("53 bits"));
    assert_eq!(t.finish().unwrap(), 4);
    out.finish().unwrap();
}

#[test]
fn a_written_export_equals_itself_and_a_changed_value_differs() {
    let (a, b) = (tempfile::tempdir().unwrap(), tempfile::tempdir().unwrap());
    write(a.path(), 0.1 + 0.2);
    assert!(compare(a.path(), a.path()).unwrap().equal());
    write(b.path(), 0.3);
    let report = compare(a.path(), b.path()).unwrap();
    assert_eq!(report.tables[0].compared, 4);
    assert_eq!(report.tables[0].fields.keys().collect::<Vec<_>>(), ["v"]);
    assert_eq!(report.tables[0].fields["v"].count, 1);
    let error = Writer::create(a.path(), "test", serde_json::json!({})).err().unwrap();
    assert!(error.contains("new or empty"), "{error}");
}

#[test]
fn a_record_writes_its_leading_cells_then_the_rows_fields_in_order() {
    let dir = tempfile::tempdir().unwrap();
    let mut out = Writer::create(dir.path(), "test", serde_json::json!({})).unwrap();
    let mut t = out.table("t", &["case", "id"]).unwrap();
    let row = |id: i64, v: f64| serde_json::json!({"id": id, "v": v, "w": null});
    t.record(&[("case", Cell::Text("a"))], &row(2, 0.1 + 0.2)).unwrap();
    assert!(t.record(&[("case", Cell::Text("a"))], &row(1, 0.0)).unwrap_err().contains("ascending"));
    assert!(t.record(&[], &serde_json::json!({"case": "b", "id": [3]})).unwrap_err().contains("flat"));
    assert_eq!(t.finish().unwrap(), 1);
    out.finish().unwrap();
    let text = std::fs::read_to_string(dir.path().join("t.jsonl")).unwrap();
    assert_eq!(text, "{\"case\":\"a\",\"id\":2,\"v\":0.30000000000000004,\"w\":null}\n");
}
