use std::path::Path;
use std::process::Command;

fn export(rows: &str) -> tempfile::TempDir {
    let dir = tempfile::tempdir().unwrap();
    let manifest = r#"{"producer":"test","settings":{},"tables":{"t":["id"]}}"#;
    std::fs::write(dir.path().join("manifest.json"), manifest).unwrap();
    std::fs::write(dir.path().join("t.jsonl"), rows).unwrap();
    dir
}

fn status(expected: &Path, actual: &Path) -> Option<i32> {
    Command::new(env!("CARGO_BIN_EXE_compare-tables"))
        .arg(expected)
        .arg(actual)
        .output()
        .expect("run compare-tables")
        .status
        .code()
}

#[test]
fn exit_status_tells_equal_different_and_unreadable_apart() {
    let one = export("{\"id\":1,\"v\":1.5}\n");
    let same = export("{\"id\":1,\"v\":1.5}\n");
    let other = export("{\"id\":1,\"v\":1.6}\n");
    assert_eq!(status(one.path(), same.path()), Some(0));
    assert_eq!(status(one.path(), other.path()), Some(1));
    assert_eq!(status(one.path(), Path::new("/nonexistent-export-folder")), Some(2));
}
