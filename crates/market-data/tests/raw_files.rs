//! The typed raw files and their merge rules, from the cases the old
//! updater's checks protect (`tests/test_data_refresh.py`,
//! `tests/test_data_manager.py`).

use market_data::raw::{self, History, HistoryFile, KeyMetrics, Listing, PyJson, Raw, StatementKind, Statements, Universe};
use market_data::{Day, Market};
use std::fs;
use std::path::Path;

fn json(text: &str) -> PyJson {
    PyJson::parse(text.as_bytes()).unwrap()
}

fn day(text: &str) -> Day {
    Day::parse(text).unwrap()
}

fn raw() -> (tempfile::TempDir, Raw) {
    let dir = tempfile::tempdir().unwrap();
    let raw = Raw::new(dir.path().to_path_buf());
    (dir, raw)
}

fn put(path: &Path, text: &str) {
    fs::create_dir_all(path.parent().unwrap()).unwrap();
    fs::write(path, text).unwrap();
}

fn text(path: &Path) -> String {
    fs::read_to_string(path).unwrap()
}

#[test]
fn replacing_a_file_leaves_a_hard_link_to_the_old_one_unchanged() {
    let (dir, raw) = raw();
    put(&raw.spy(), "[]");
    fs::hard_link(raw.spy(), dir.path().join("copy.json")).unwrap();
    raw::replace(&raw.spy(), b"[{}]").unwrap();
    assert_eq!(text(&raw.spy()), "[{}]");
    assert_eq!(text(&dir.path().join("copy.json")), "[]");
    assert!(!dir.path().join("spy-div.json.tmp").exists());
}

#[test]
fn us_list_keeps_delisted_rows_and_saved_sectors_and_names_new_companies() {
    let (_dir, raw) = raw();
    let path = raw.universe(Market::Us);
    put(&path, r#"[{"symbol": "A", "listed": true, "name": "Alpha", "sector": "Energy"}, {"symbol": "OLD", "listed": true, "sector": "Energy", "name": "Old company"}]"#);
    let screener = json(r#"[{"symbol": "A", "companyName": "Alpha", "exchange": "NYSE", "sector": ""}, {"symbol": "NEW", "companyName": "New company", "exchangeShortName": "NASDAQ", "sector": "Tech"}]"#);
    let mut listing = Listing::new(Market::Us);
    assert_eq!(listing.screener("NYSE", true, &screener).unwrap(), 2);
    let mut universe = Universe::load(&raw, Market::Us).unwrap();
    assert_eq!(universe.apply(listing), ["NEW"]);
    assert!(universe.save().unwrap());
    assert_eq!(
        text(&path),
        r#"[{"symbol": "A", "listed": true, "name": "Alpha", "sector": "Energy", "exchange": "NYSE"}, {"symbol": "OLD", "listed": false, "sector": "Energy", "name": "Old company"}, {"symbol": "NEW", "exchange": "NASDAQ", "sector": "Tech", "name": "New company", "listed": true}]"#
    );
    // The same listing again changes nothing.
    let mut listing = Listing::new(Market::Us);
    listing.screener("NYSE", true, &screener).unwrap();
    let mut universe = Universe::load(&raw, Market::Us).unwrap();
    assert!(universe.apply(listing).is_empty());
    assert!(!universe.save().unwrap());
}

#[test]
fn hong_kong_rows_are_replaced_whole() {
    let (_dir, raw) = raw();
    let path = raw.universe(Market::Hk);
    put(&path, r#"[{"symbol": "0001.HK", "name": "One", "exchange": "HKSE", "sector": "Energy", "listed": true, "market": "hk", "currency": "HKD"}, {"symbol": "0002.HK", "name": "Two", "listed": true}]"#);
    let page = json(
        r#"[{"symbol": "0001.HK", "companyName": "One Ltd", "sector": null, "isActivelyTrading": false}, {"symbol": "4001.HK", "companyName": "Bond"}, {"symbol": "0003.HK", "companyName": "Three ETF Fund"}, {"symbol": "0005.HK", "companyName": "Five", "exchangeShortName": "OTC"}]"#,
    );
    let mut listing = Listing::new(Market::Hk);
    listing.screener("HKSE", true, &page).unwrap();
    let mut universe = Universe::load(&raw, Market::Hk).unwrap();
    assert!(universe.apply(listing).is_empty());
    assert!(universe.save().unwrap());
    assert_eq!(
        text(&path),
        r#"[{"symbol": "0001.HK", "name": "One Ltd", "exchange": "HKSE", "sector": "", "listed": false, "market": "hk", "currency": "HKD"}, {"symbol": "0002.HK", "name": "Two", "listed": false}]"#
    );
}

#[test]
fn unreadable_company_list_fails() {
    let (_dir, raw) = raw();
    put(&raw.universe(Market::Us), "{}");
    assert!(Universe::load(&raw, Market::Us).is_err());
}

fn prices(rows: &[(&str, f64)]) -> String {
    let rows: Vec<String> = rows.iter().map(|(d, v)| format!(r#"{{"date": "{d}", "adjClose": {v:?}}}"#)).collect();
    format!("[{}]", rows.join(", "))
}

#[test]
fn a_refresh_puts_new_rows_in_place_keeps_other_keys_and_writes_only_a_change() {
    let (_dir, raw) = raw();
    let file = HistoryFile::Prices("A".to_string());
    let path = file.path(&raw);
    put(&path, r#"{"div": [{"date": "2026-01-02", "adjClose": 11.0}, {"date": "2025-12-31", "adjClose": 10.0}], "extra": "keep"}"#);
    let mut history = History::load(&raw, &file).unwrap();
    assert_eq!((history.first(), history.last()), (Some(day("2025-12-31")), Some(day("2026-01-02"))));
    let reply = json(&prices(&[("2025-12-31", 10.0), ("2026-01-02", 11.0), ("2026-01-05", 12.0)]));
    let window = history.admit(reply, day("2025-12-31"), day("2026-01-05")).unwrap();
    assert!(!history.changes_closes(std::slice::from_ref(&window)).unwrap());
    history.apply(vec![window]);
    assert!(history.save().unwrap());
    assert_eq!(
        text(&path),
        r#"{"div": [{"date": "2026-01-05", "adjClose": 12.0}, {"date": "2026-01-02", "adjClose": 11.0}, {"date": "2025-12-31", "adjClose": 10.0}], "extra": "keep"}"#
    );
    // The same rows as integers are equal to Python: nothing is written.
    let mut history = History::load(&raw, &file).unwrap();
    let window = history.admit(json(r#"[{"date": "2026-01-05", "adjClose": 12}]"#), day("2025-12-29"), day("2026-01-05")).unwrap();
    history.apply(vec![window]);
    assert!(!history.save().unwrap());
}

#[test]
fn a_new_history_is_saved_even_when_empty() {
    let (_dir, raw) = raw();
    let file = HistoryFile::Prices("NEW".to_string());
    let mut history = History::load(&raw, &file).unwrap();
    assert!(!history.exists() && history.is_empty());
    let window = history.admit(json("[]"), day("1995-01-01"), day("2004-12-31")).unwrap();
    history.apply(vec![window]);
    assert!(history.save().unwrap());
    assert_eq!(text(&file.path(&raw)), r#"{"div": []}"#);
}

#[test]
fn non_positive_closes_are_set_aside_and_remove_their_saved_rows() {
    let (_dir, raw) = raw();
    let file = HistoryFile::Spy;
    put(&raw.spy(), &prices(&[("2026-01-05", 12.0), ("2026-01-02", 11.0)]));
    let mut history = History::load(&raw, &file).unwrap();
    let window = history.admit(json(&prices(&[("2026-01-02", 11.0), ("2026-01-05", 0.0), ("2026-01-06", -1.0)])), day("2026-01-01"), day("2026-01-06")).unwrap();
    history.apply(vec![window]);
    assert!(history.save().unwrap());
    assert_eq!(text(&raw.spy()), prices(&[("2026-01-02", 11.0)]));
    // Treasury rates of zero or below are values.
    let file = HistoryFile::Treasury;
    let mut history = History::load(&raw, &file).unwrap();
    let rates = r#"[{"date": "2020-04-02", "month3": -0.01}, {"date": "2020-04-01", "month3": 0}]"#;
    let window = history.admit(json(rates), day("2020-04-01"), day("2020-04-30")).unwrap();
    history.apply(vec![window]);
    assert!(history.save().unwrap());
    assert_eq!(text(&raw.treasury()), rates);
}

#[test]
fn a_reply_with_a_day_outside_the_window_a_repeated_day_or_no_date_fails() {
    let (_dir, raw) = raw();
    let history = History::load(&raw, &HistoryFile::Fx("HKD".to_string())).unwrap();
    let admit = |text: &str| history.admit(json(text), day("2026-01-01"), day("2026-01-31")).map(|_| ()).map_err(|e| e.message);
    assert!(admit(r#"[{"date": "2025-12-31", "close": 7.8}]"#).unwrap_err().contains("outside"));
    assert!(admit(r#"[{"date": "2026-01-02", "close": 7.8}, {"date": "2026-01-02", "close": 7.7}]"#).unwrap_err().contains("duplicate"));
    assert!(admit(r#"[{"date": "2026-01-02", "close": 0}]"#).is_err());
    assert!(admit(r#"[{"close": 7.8}]"#).is_err());
    assert!(admit(r#"{"date": "2026-01-02"}"#).is_err());
    assert!(admit(r#"[{"date": "2026-01-02", "close": "7.8"}]"#).is_ok());
}

#[test]
fn a_changed_close_asks_for_the_whole_history_which_must_be_complete_and_agree() {
    let (_dir, raw) = raw();
    let file = HistoryFile::Prices("A".to_string());
    put(&file.path(&raw), r#"{"div": [{"date": "2026-01-02", "adjClose": 11}, {"date": "2025-12-31", "adjClose": 10}, {"date": "1996-01-02", "adjClose": 5}]}"#);
    let mut history = History::load(&raw, &file).unwrap();
    let recent = |rows: &[(&str, f64)]| history.admit(json(&prices(rows)), day("2025-12-24"), day("2026-01-05")).unwrap();
    // Equal numbers, even as text, change nothing.
    let same = history.admit(json(r#"[{"date": "2025-12-31", "adjClose": "10"}]"#), day("2025-12-24"), day("2026-01-05")).unwrap();
    assert!(!history.changes_closes(&[same]).unwrap());
    let changed = vec![recent(&[("2025-12-31", 5.0), ("2026-01-02", 5.5), ("2026-01-05", 6.0)])];
    assert!(history.changes_closes(&changed).unwrap());
    let whole = |rows: &[(&str, f64)]| vec![history.admit(json(&prices(rows)), day("1995-01-01"), day("2026-01-05")).unwrap()];
    let incomplete = whole(&[("2025-12-31", 5.0), ("2026-01-02", 5.5), ("2026-01-05", 6.0)]);
    assert!(history.check_whole(&changed, &incomplete).unwrap_err().message.contains("incomplete"));
    let moved = whole(&[("1996-01-02", 2.5), ("2025-12-31", 5.0), ("2026-01-02", 5.5), ("2026-01-05", 6.5)]);
    assert!(history.check_whole(&changed, &moved).unwrap_err().message.contains("changed"));
    let complete = whole(&[("1996-01-02", 2.5), ("2025-12-31", 5.0), ("2026-01-02", 5.5), ("2026-01-05", 6.0)]);
    history.check_whole(&changed, &complete).unwrap();
    history.apply(complete);
    assert!(history.save().unwrap());
    assert_eq!(
        text(&file.path(&raw)),
        format!(r#"{{"div": {}}}"#, prices(&[("2026-01-05", 6.0), ("2026-01-02", 5.5), ("2025-12-31", 5.0), ("1996-01-02", 2.5)]))
    );
    // Without a saved day among the returned ones the item fails.
    let history = History::load(&raw, &file).unwrap();
    let apart = history.admit(json(&prices(&[("2026-01-07", 6.0)])), day("2026-01-06"), day("2026-01-08")).unwrap();
    assert!(history.changes_closes(&[apart]).unwrap_err().message.contains("overlap"));
}

#[test]
fn an_unreadable_history_is_an_item_error_and_stays() {
    let (_dir, raw) = raw();
    let file = HistoryFile::Prices("A".to_string());
    for saved in ["[]", "{\"div\": [{\"date\": \"x\"}]}", "{\"div\": [1]}", "{\"div\": [{\"date\": \"2026-01-02\", \"adjClose\": NaN}]}"] {
        put(&file.path(&raw), saved);
        let error = History::load(&raw, &file).err().unwrap();
        assert_eq!(error.place, file.path(&raw).display().to_string());
        assert_eq!(text(&file.path(&raw)), saved);
    }
}

fn report(date: &str, revenue: i64) -> String {
    format!(r#"{{"date": "{date}", "symbol": "A", "period": "FY", "revenue": {revenue}}}"#)
}

#[test]
fn statements_keep_saved_variants_without_adding_copies() {
    let (_dir, raw) = raw();
    let path = raw.statement("income-statement", "A");
    let old = report("2024-12-31", 100);
    put(&path, &format!(r#"{{"version": 2, "full_response": true, "symbol": "A", "endpoint": "income-statement", "rows": [{old}, {old}]}}"#));
    let reply = json(&format!("[{}]", report("2025-12-31", 300)));
    for written in [true, false] {
        let mut statements = Statements::load(&raw, StatementKind::Income, "A").unwrap();
        statements.apply(&reply).unwrap();
        assert_eq!(statements.save().unwrap(), written);
    }
    let new = report("2025-12-31", 300);
    assert_eq!(
        text(&path),
        format!(r#"{{"version": 2, "full_response": true, "symbol": "A", "endpoint": "income-statement", "rows": [{new}, {old}, {old}]}}"#)
    );
    // A revised value of a saved date is kept beside the saved one.
    let mut statements = Statements::load(&raw, StatementKind::Income, "A").unwrap();
    statements.apply(&json(&format!("[{}]", report("2025-12-31", 301)))).unwrap();
    assert_eq!(statements.rows().len(), 4);
}

#[test]
fn an_inadmissible_statement_reply_fails_and_the_file_stays() {
    let (_dir, raw) = raw();
    let mut statements = Statements::load(&raw, StatementKind::Income, "A").unwrap();
    for reply in [
        r#"[{"date": "2025-12-31", "revenue": true}]"#,
        r#"[{"date": "2025-12-31", "revenue": ""}]"#,
        r#"[{"date": "2025-12-31", "symbol": "B"}]"#,
        r#"[{"date": "2025-12-31", "period": "Q1"}]"#,
        r#"[{"revenue": 1}]"#,
    ] {
        assert!(statements.apply(&json(reply)).is_err(), "{reply}");
    }
    statements.apply(&json(r#"[{"date": "2025-12-31", "revenue": null, "ebitda": "x"}]"#)).unwrap();
    assert!(!statements.exists());
    put(&raw.statement("income-statement", "B"), r#"{"version": 3, "symbol": "B", "endpoint": "income-statement", "rows": []}"#);
    assert!(Statements::load(&raw, StatementKind::Income, "B").is_err());
}

#[test]
fn key_metrics_keep_first_seen_dates_and_append_records_in_symbol_order() {
    let (_dir, raw) = raw();
    let saved = r#"{"symbol": "B", "rows": [{"date": "2024-12-31", "evToEBITDA": 8}], "full_response": true}"#;
    let trimmed = r#"{"symbol": "C", "rows": [{"date": "2024-12-31"}]}"#;
    put(&raw.metrics(), &format!("{saved}\r\n{trimmed}"));
    let mut metrics = KeyMetrics::load(&raw).unwrap();
    let reply = json(r#"[{"date": "2025-12-31", "evToEBITDA": 6}, {"date": "2024-12-31", "evToEBITDA": 5}]"#);
    let rows = reply.as_list().unwrap();
    assert!(metrics.apply("C", rows));
    assert!(metrics.apply("B", rows));
    assert!(metrics.apply("A", &[]));
    assert!(!metrics.apply("B", &rows[1..]));
    assert_eq!(metrics.rows("B").unwrap().len(), 2);
    assert!(metrics.save().unwrap());
    let added = [
        r#"{"symbol": "A", "rows": [], "full_response": true}"#,
        r#"{"symbol": "B", "rows": [{"date": "2024-12-31", "evToEBITDA": 8}, {"date": "2025-12-31", "evToEBITDA": 6}], "full_response": true}"#,
        r#"{"symbol": "C", "rows": [{"date": "2024-12-31"}, {"date": "2025-12-31", "evToEBITDA": 6}], "full_response": false}"#,
    ];
    assert_eq!(text(&raw.metrics()), format!("{saved}\r\n{trimmed}\n{}\n", added.join("\n")));
    assert!(!metrics.save().unwrap());
    assert_eq!(KeyMetrics::load(&raw).unwrap().rows("C").unwrap().len(), 2);
}

#[test]
fn an_unfinished_last_line_is_dropped_and_an_invalid_line_fails() {
    let (_dir, raw) = raw();
    let record = r#"{"symbol": "A", "rows": []}"#;
    put(&raw.metrics(), &format!("{record}\n{{\"symbol\": \"B\", \"ro"));
    KeyMetrics::load(&raw).unwrap();
    assert_eq!(text(&raw.metrics()), format!("{record}\n"));
    put(&raw.metrics(), &format!("{record}\n{record}"));
    KeyMetrics::load(&raw).unwrap();
    assert_eq!(text(&raw.metrics()), format!("{record}\n{record}"));
    for invalid in [r#"{"symbol": "", "rows": []}"#, r#"{"symbol": "A", "rows": [1]}"#, "[]", "not json"] {
        put(&raw.metrics(), &format!("{record}\n{invalid}\n"));
        assert!(KeyMetrics::load(&raw).err().unwrap().message.contains("line 2"), "{invalid}");
    }
}
