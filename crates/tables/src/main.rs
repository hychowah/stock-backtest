//! `compare-tables EXPECTED ACTUAL`: compares two exported table folders.
//! Exit status: 0 when equal, 1 when they differ, 2 when a folder or file
//! cannot be read.

use std::path::Path;
use std::process::ExitCode;

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let [expected, actual] = args.as_slice() else {
        eprintln!("usage: compare-tables EXPECTED ACTUAL");
        return ExitCode::from(2);
    };
    let report = match tables::compare(Path::new(expected), Path::new(actual)) {
        Ok(report) => report,
        Err(message) => {
            eprintln!("compare-tables: {message}");
            return ExitCode::from(2);
        }
    };
    for table in &report.tables {
        println!("{}: {} rows compared, {} missing, {} extra", table.name, table.compared, table.missing, table.extra);
        for (field, diff) in &table.fields {
            println!("  {field}: {} differences", diff.count);
            for d in &diff.first {
                let relative = d.relative.map_or("-".to_string(), |r| format!("{r:e}"));
                println!("    key {} expected {} actual {} relative {relative}", d.key, d.expected, d.actual);
            }
        }
    }
    if report.equal() { ExitCode::SUCCESS } else { ExitCode::from(1) }
}
