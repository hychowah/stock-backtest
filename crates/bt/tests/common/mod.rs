//! Helpers the `bt` tests share. Each test file compiles its own copy and
//! uses only some of them.
#![allow(dead_code)]

use serde_json::Value;
use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};

/// The as-of time of the fictional fixture's expected tables: the Hong Kong
/// session of the last day has not closed yet.
pub const AS_OF: &str = "2023-06-30T07:30:00+00:00";

pub fn fixtures() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../fixtures/fictional")
}

/// The folder an environment variable names, or `default`.
pub fn folder(variable: &str, default: PathBuf) -> PathBuf {
    std::env::var_os(variable).map_or(default, PathBuf::from)
}

pub fn path(p: &Path) -> &str {
    p.to_str().unwrap()
}

/// Runs `bt`; returns its reply and whether it succeeded.
pub fn bt(args: &[&str]) -> (Value, bool) {
    let output = Command::new(env!("CARGO_BIN_EXE_bt")).args(args).output().expect("run bt");
    (serde_json::from_slice(&output.stdout).unwrap(), output.status.success())
}

/// Runs `bt`, which must succeed; returns its reply.
pub fn bt_ok(args: &[&str]) -> Value {
    let (reply, success) = bt(args);
    assert!(success, "bt {args:?}: {reply}");
    reply
}

/// A home in `dir` with the fictional raw cache prepared.
pub fn prepared(dir: &Path) -> PathBuf {
    let home = dir.join("home");
    std::fs::create_dir(&home).unwrap();
    std::os::unix::fs::symlink(fixtures().join("raw").canonicalize().unwrap(), home.join("raw")).unwrap();
    bt_ok(&["data", "prepare", "--as-of", AS_OF, "--home", path(&home)]);
    home
}

/// The proof folders: `L3_CASES` holds kind folders of case folders
/// (default the fictional `cases`), `L3_EXPECTED` the expected tables
/// (default the fictional `expected/runs`), and `L3_HOME` a prepared home
/// (default the fictional raw cache prepared in `dir`).
pub struct Proof {
    pub cases: Vec<PathBuf>,
    pub expected: PathBuf,
    pub home: PathBuf,
}

impl Proof {
    pub fn new(dir: &Path) -> Proof {
        let root = folder("L3_CASES", fixtures().join("cases"));
        // A case is every `KIND/NAME/` folder that holds `strategy.json`.
        let mut cases = Vec::new();
        for kind in std::fs::read_dir(&root).unwrap() {
            let kind = kind.unwrap().path();
            if kind.is_dir() {
                for case in std::fs::read_dir(kind).unwrap() {
                    let case = case.unwrap().path();
                    if case.join("strategy.json").is_file() {
                        cases.push(case);
                    }
                }
            }
        }
        cases.sort();
        assert!(!cases.is_empty(), "no case in {}", root.display());
        let home = std::env::var_os("L3_HOME").map_or_else(|| prepared(dir), PathBuf::from);
        Proof { cases, expected: folder("L3_EXPECTED", fixtures().join("expected/runs")), home }
    }
}

/// A case's name: its folder's.
pub fn name(case: &Path) -> String {
    case.file_name().unwrap().to_str().unwrap().to_string()
}

/// A case's kind: the folder that holds it, `builtins` or `formulas`.
pub fn kind(case: &Path) -> &str {
    case.parent().unwrap().file_name().unwrap().to_str().unwrap()
}

/// A JSON file of a case.
pub fn read(case: &Path, file: &str) -> Value {
    serde_json::from_slice(&std::fs::read(case.join(file)).unwrap()).unwrap()
}

/// The `bt run` schedule arguments of a case's run settings, whose
/// `interval` is the flag `--every`.
pub fn schedule(settings: &Value) -> Vec<String> {
    let text = |key: &str| settings[key].as_str().unwrap().to_string();
    let mut args = vec!["--market".into(), text("market"), "--start".into(), text("start"), "--end".into(), text("end")];
    if let Some(dates) = settings.get("dates") {
        let dates: Vec<&str> = dates.as_array().unwrap().iter().map(|d| d.as_str().unwrap()).collect();
        args.extend(["--dates".into(), dates.join(",")]);
    } else {
        args.extend(["--every".into(), text("interval")]);
    }
    if let Some(trials) = settings.get("trials") {
        args.extend(["--trials".into(), trials.to_string(), "--seed".into(), settings["seed"].to_string()]);
    }
    args
}

/// A `bt serve` child process of a home, on a free port that the system
/// chooses. Dropping it stops it with SIGTERM.
pub struct Server {
    child: Child,
    /// `http://127.0.0.1:PORT`.
    pub url: String,
}

/// Starts `bt serve` on `home` and waits until it says it is ready.
pub fn serve(home: &Path) -> Server {
    let mut child = Command::new(env!("CARGO_BIN_EXE_bt"))
        .args(["serve", "--port", "0", "--home", path(home)])
        .stdout(Stdio::piped())
        .spawn()
        .expect("start bt serve");
    let mut line = String::new();
    BufReader::new(child.stdout.take().unwrap()).read_line(&mut line).unwrap();
    let ready: Value = serde_json::from_str(&line).unwrap_or_else(|_| panic!("bt serve did not start: {line}"));
    Server { child, url: ready["serving"].as_str().unwrap().to_string() }
}

impl Server {
    /// Sends `method` to `path` with a JSON body, and an `Origin` header when
    /// one is given; returns the status and the JSON reply.
    pub fn send(&self, method: &str, path: &str, body: Option<&Value>, origin: Option<&str>) -> (u16, Value) {
        let agent: ureq::Agent = ureq::Agent::config_builder().http_status_as_error(false).build().into();
        let mut request = ureq::http::Request::builder().method(method).uri(format!("{}{path}", self.url));
        if let Some(origin) = origin {
            request = request.header("Origin", origin);
        }
        let request = request.header("Content-Type", "application/json").body(body.map_or(String::new(), Value::to_string)).unwrap();
        let mut response = agent.run(request).unwrap_or_else(|e| panic!("{method} {path}: {e}"));
        let text = response.body_mut().read_to_string().unwrap();
        let reply = serde_json::from_str(&text).unwrap_or_else(|_| panic!("{method} {path}: {text}"));
        (response.status().as_u16(), reply)
    }

    /// GET `path`, which must answer 200; its JSON reply.
    pub fn get(&self, path: &str) -> Value {
        let (status, reply) = self.send("GET", path, None, None);
        assert_eq!(status, 200, "GET {path}: {reply}");
        reply
    }

    /// Sends SIGTERM and waits; whether the server exited with success.
    pub fn terminate(mut self) -> bool {
        self.stop()
    }

    fn stop(&mut self) -> bool {
        let pid = self.child.id().to_string();
        if self.child.try_wait().unwrap().is_none() {
            Command::new("kill").args(["-TERM", &pid]).status().unwrap();
        }
        self.child.wait().unwrap().success()
    }
}

impl Drop for Server {
    fn drop(&mut self) {
        self.stop();
    }
}
