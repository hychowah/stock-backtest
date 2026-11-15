//! `PyJson` against CPython's `json` module: the vectors in
//! fixtures/numbers/pyjson.json, and raw files read and written back
//! byte for byte.

use market_data::Market;
use market_data::raw::{History, HistoryFile, PyJson, Raw, StatementKind, Statements, Universe};
use rayon::prelude::*;
use serde::Deserialize;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;

#[derive(Deserialize)]
struct Vectors {
    cases: Vec<Case>,
}

#[derive(Deserialize)]
#[serde(untagged)]
enum Case {
    /// `json.dumps(json.loads(text))` and the same with sorted keys; both
    /// `None` when refused.
    Text { text: String, written: Option<String>, sorted: Option<String> },
    /// Python's `json.loads(left) == json.loads(right)`.
    Pair { left: String, right: String, equal: bool },
}

#[test]
fn values_read_and_write_as_python_json_does() {
    let path = concat!(env!("CARGO_MANIFEST_DIR"), "/../../fixtures/numbers/pyjson.json");
    let vectors: Vectors = serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap();
    let (mut refused, mut pairs) = (0, 0);
    for case in vectors.cases {
        match case {
            Case::Text { text, written, sorted } => {
                let value = PyJson::parse(text.as_bytes());
                assert_eq!(value.as_ref().ok().map(PyJson::to_text), written, "{text:?}: {value:?}");
                assert_eq!(value.as_ref().ok().map(PyJson::sorted_text), sorted, "{text:?}");
                refused += usize::from(written.is_none());
            }
            Case::Pair { left, right, equal } => {
                let read = |text: &str| PyJson::parse(text.as_bytes()).unwrap();
                assert_eq!(read(&left) == read(&right), equal, "{left} == {right}");
                pairs += 1;
            }
        }
    }
    assert!(refused >= 2 && pairs > 0);
}

/// Every raw file below `dir`, read and written back: JSON files whole,
/// `metrics.jsonl` line by line. Returns the number of files and lines that
/// differ, each with its reason (at most 50 named).
fn round_trip(dir: &Path) -> (u64, u64, Vec<String>) {
    let mut files = Vec::new();
    let mut folders = vec![dir.to_path_buf()];
    while let Some(folder) = folders.pop() {
        for entry in std::fs::read_dir(&folder).unwrap() {
            let entry = entry.unwrap();
            let kind = entry.file_type().unwrap();
            if kind.is_dir() {
                folders.push(entry.path());
            } else if kind.is_file() {
                files.push(entry.path());
            }
        }
    }
    let (checked, lines) = (AtomicU64::new(0), AtomicU64::new(0));
    let failures = Mutex::new(Vec::new());
    files.par_iter().for_each(|path| {
        let name = path.file_name().unwrap().to_str().unwrap();
        let bytes = std::fs::read(path).unwrap();
        let fail = |reason: String| failures.lock().unwrap().push(format!("{}: {reason}", path.display()));
        if name.ends_with(".json") {
            checked.fetch_add(1, Ordering::Relaxed);
            match PyJson::parse(&bytes) {
                Err(e) => fail(format!("refused: {e}")),
                Ok(value) if value.to_text().as_bytes() != bytes => fail(first_difference(&bytes, value.to_text().as_bytes())),
                Ok(_) => {}
            }
        } else if name.ends_with(".jsonl") {
            checked.fetch_add(1, Ordering::Relaxed);
            for (number, line) in bytes.split(|&b| b == b'\n').enumerate() {
                let line = line.strip_suffix(b"\r").unwrap_or(line);
                if line.is_empty() {
                    continue;
                }
                lines.fetch_add(1, Ordering::Relaxed);
                match PyJson::parse(line) {
                    Err(e) => fail(format!("line {}: refused: {e}", number + 1)),
                    Ok(value) if value.to_text().as_bytes() != line => {
                        fail(format!("line {}: {}", number + 1, first_difference(line, value.to_text().as_bytes())))
                    }
                    Ok(_) => {}
                }
            }
        }
    });
    (checked.into_inner(), lines.into_inner(), failures.into_inner().unwrap())
}

fn first_difference(saved: &[u8], written: &[u8]) -> String {
    let at = saved.iter().zip(written).position(|(a, b)| a != b).unwrap_or(saved.len().min(written.len()));
    let around = |b: &[u8]| String::from_utf8_lossy(&b[at.saturating_sub(30)..(at + 30).min(b.len())]).into_owned();
    format!("differs at byte {at}: saved {:?}, written {:?}", around(saved), around(written))
}

/// The symbol of a file name in `px/` and the statement folders.
fn symbol(path: &Path) -> String {
    let name = path.file_stem().unwrap().to_str().unwrap().as_bytes();
    let mut bytes = Vec::new();
    let mut i = 0;
    while i < name.len() {
        if name[i] == b'%' {
            bytes.push(u8::from_str_radix(std::str::from_utf8(&name[i + 1..i + 3]).unwrap(), 16).unwrap());
            i += 3;
        } else {
            bytes.push(name[i]);
            i += 1;
        }
    }
    String::from_utf8(bytes).unwrap()
}

fn json_files(folder: PathBuf) -> Vec<PathBuf> {
    let Ok(entries) = std::fs::read_dir(folder) else { return Vec::new() };
    entries.map(|e| e.unwrap().path()).filter(|p| p.extension().is_some_and(|e| e == "json")).collect()
}

/// A copy of a home's raw cache, read only: `RAW_DIR=<raw> cargo test
/// --release -p market-data --test pyjson -- --ignored --nocapture`. Every
/// JSON file and `metrics.jsonl` line must write back byte-equal; the typed
/// loaders' refusals are printed.
#[test]
#[ignore = "reads a whole raw cache named by RAW_DIR"]
fn a_raw_cache_writes_back_byte_equal() {
    let dir = PathBuf::from(std::env::var("RAW_DIR").expect("RAW_DIR"));
    let started = std::time::Instant::now();
    let (files, lines, failures) = round_trip(&dir);
    println!("{files} files ({lines} metrics.jsonl lines) in {:.1} s; {} differ", started.elapsed().as_secs_f64(), failures.len());
    for failure in failures.iter().take(50) {
        println!("  {failure}");
    }
    let raw = Raw::new(dir.clone());
    let refused = Mutex::new(Vec::new());
    let histories: Vec<HistoryFile> = json_files(dir.join("px"))
        .iter()
        .map(|p| HistoryFile::Prices(symbol(p)))
        .chain(json_files(dir.join("px-full")).iter().map(|p| HistoryFile::Native(symbol(p))))
        .chain(json_files(dir.join("fx")).iter().map(|p| HistoryFile::Fx(p.file_stem().unwrap().to_str().unwrap()[3..].to_string())))
        .chain([HistoryFile::Spy, HistoryFile::Treasury, HistoryFile::Calendar(Market::Hk)])
        .collect();
    histories.par_iter().for_each(|file| {
        if let Err(e) = History::load(&raw, file) {
            refused.lock().unwrap().push(e.to_string());
        }
    });
    let mut statements = Vec::new();
    for kind in StatementKind::US {
        statements.extend(json_files(dir.join("financial-inputs").join(kind.endpoint())).into_iter().map(|p| (kind, symbol(&p))));
    }
    statements.par_iter().for_each(|(kind, symbol)| {
        if let Err(e) = Statements::load(&raw, *kind, symbol) {
            refused.lock().unwrap().push(e.to_string());
        }
    });
    for market in [Market::Us, Market::Hk] {
        if let Err(e) = Universe::load(&raw, market) {
            refused.lock().unwrap().push(e.to_string());
        }
    }
    let refused = refused.into_inner().unwrap();
    println!("typed loads: {} histories, {} statements files, 2 company lists; {} refused", histories.len(), statements.len(), refused.len());
    for refusal in refused.iter().take(50) {
        println!("  {refusal}");
    }
    assert!(failures.is_empty());
}
