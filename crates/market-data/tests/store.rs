use chrono::DateTime;
use market_data::Market;
use market_data::commands::Home;
use market_data::store::{FORMAT, Generation, Lock};
use std::path::Path;

/// Prepares one generation of HK with column `t.x` and text column `t.name`.
fn publish(home: &Home, values: &[f64]) {
    let lock = Lock::take(home).unwrap();
    let mut out = lock.begin(Market::Hk).unwrap();
    out.column("t.x", values).unwrap();
    out.text("t.name", &["Aé", "", "b"]).unwrap();
    out.publish(&DateTime::parse_from_rfc3339("2023-06-30T07:30:00+00:00").unwrap(), 0.0).unwrap();
}

fn folders(dir: &Path) -> Vec<String> {
    let mut names: Vec<String> =
        std::fs::read_dir(dir).unwrap().map(|e| e.unwrap().file_name().into_string().unwrap()).collect();
    names.sort();
    names
}

#[test]
fn a_reader_keeps_its_generation_after_later_publishes() {
    let dir = tempfile::tempdir().unwrap();
    let home = Home::new(dir.path());
    publish(&home, &[1.0, 2.0]);
    let reader = Generation::open(&home, Market::Hk).unwrap();
    publish(&home, &[3.0]);
    publish(&home, &[4.0]); // deletes the reader's generation from disk
    assert!(!dir.path().join("data/prepared/hk/1").exists());
    assert_eq!(reader.manifest().generation, 1);
    assert_eq!(reader.column::<f64>("t.x"), &[1.0, 2.0]);
    let text = reader.text("t.name");
    assert_eq!((text.len(), text.get(0), text.get(1), text.get(2)), (3, "Aé", "", "b"));
    let newest = Generation::open(&home, Market::Hk).unwrap();
    assert_eq!((newest.manifest().generation, newest.column::<f64>("t.x")), (3, &[4.0][..]));
}

#[test]
fn a_second_preparation_fails_while_one_holds_the_lock() {
    let dir = tempfile::tempdir().unwrap();
    let home = Home::new(dir.path());
    let lock = Lock::take(&home).unwrap();
    let error = Lock::take(&home).err().expect("the lock is busy");
    assert!(error.message.contains("another preparation"), "{error}");
    drop(lock);
    Lock::take(&home).unwrap();
}

#[test]
fn a_preparation_deletes_old_and_failed_generations_but_not_current() {
    let dir = tempfile::tempdir().unwrap();
    let home = Home::new(dir.path());
    let hk = dir.path().join("data/prepared/hk");
    publish(&home, &[1.0]);
    publish(&home, &[2.0]);
    assert_eq!(folders(&hk), ["1", "2", "current"]);
    {
        let lock = Lock::take(&home).unwrap();
        let mut failed = lock.begin(Market::Hk).unwrap();
        failed.column("t.x", &[9.0]).unwrap();
    } // dropped without publishing: a failed build
    assert_eq!(folders(&hk), ["2", "3", "current"]);
    assert_eq!(Generation::open(&home, Market::Hk).unwrap().column::<f64>("t.x"), &[2.0]);
    let lock = Lock::take(&home).unwrap();
    let _next = lock.begin(Market::Hk).unwrap();
    assert_eq!(folders(&hk), ["2", "4", "current"]);
}

#[test]
fn a_store_of_another_format_asks_for_a_new_preparation() {
    let dir = tempfile::tempdir().unwrap();
    let home = Home::new(dir.path());
    let missing = Generation::open(&home, Market::Hk).err().expect("not prepared");
    assert!(missing.message.contains("run `bt data prepare`"), "{missing}");
    publish(&home, &[1.0]);
    let path = dir.path().join("data/prepared/hk/1/manifest.json");
    let text = std::fs::read_to_string(&path).unwrap();
    let old = format!("\"format\": {FORMAT},");
    assert!(text.contains(&old));
    std::fs::write(&path, text.replace(&old, &format!("\"format\": {},", FORMAT + 1))).unwrap();
    let error = Generation::open(&home, Market::Hk).err().expect("another format");
    assert!(error.message.contains("run `bt data prepare`"), "{error}");
}

#[test]
fn a_column_of_the_wrong_length_fails_open_and_names_the_column() {
    let dir = tempfile::tempdir().unwrap();
    let home = Home::new(dir.path());
    publish(&home, &[1.0, 2.0]);
    let file = std::fs::OpenOptions::new().write(true).open(dir.path().join("data/prepared/hk/1/t.x")).unwrap();
    file.set_len(12).unwrap();
    let error = Generation::open(&home, Market::Hk).err().expect("a short column");
    assert!(error.message.contains("t.x"), "{error}");
}
