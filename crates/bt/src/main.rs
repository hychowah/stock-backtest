//! `bt`: turns arguments into a request, calls its handler and prints the
//! reply as JSON. An error, including a wrong argument, prints
//! `{"error": {"message", "place"}}` and exits with status 1. Help and
//! version print as text.

use chrono::{DateTime, SubsecRound, Utc};
use clap::error::ErrorKind;
use clap::{Parser, Subcommand};
use market_data::commands::{self, ExportRequest, Home, InspectRequest, PrepareRequest};
use market_data::{Day, Error, Market};
use serde::Serialize;
use std::path::PathBuf;
use std::process::ExitCode;

/// Stock screener and backtest.
#[derive(Parser)]
#[command(version)]
struct Cli {
    /// The runtime folder [default: the folder above the one holding bt]
    #[arg(long, global = true)]
    home: Option<PathBuf>,
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    /// Prepared market data
    #[command(subcommand)]
    Data(Data),
}

#[derive(Subcommand)]
enum Data {
    /// Prepare every market with raw data and publish a new generation
    Prepare {
        /// The as-of time, RFC 3339 [default: now]
        #[arg(long)]
        as_of: Option<String>,
    },
    /// Show each market's raw data and prepared generation
    Status,
    /// Export a market's prepared data as keyed tables
    Export {
        /// us, hk or jp
        #[arg(long)]
        market: String,
        /// The export folder: new or empty
        #[arg(long)]
        out: PathBuf,
        /// A file of ISO days, one per line, whose dated candidates to export
        #[arg(long)]
        days: Option<PathBuf>,
    },
    /// Explain one company's candidate row or denial on one day
    Inspect {
        /// us, hk or jp
        #[arg(long)]
        market: String,
        /// The company's symbol
        #[arg(long)]
        symbol: String,
        /// A session from 1996-01-01, YYYY-MM-DD
        #[arg(long)]
        day: String,
    },
}

fn main() -> ExitCode {
    let cli = match Cli::try_parse() {
        Ok(cli) => cli,
        Err(e) if matches!(e.kind(), ErrorKind::DisplayHelp | ErrorKind::DisplayVersion) => e.exit(),
        Err(e) => return reply::<()>(Err(Error::new(usage_message(&e), "arguments"))),
    };
    let home = match cli.home {
        Some(path) => Ok(Home::new(path)),
        None => own_home(),
    };
    let Command::Data(command) = cli.command;
    match command {
        Data::Prepare { as_of } => reply(home.and_then(|home| {
            let as_of = match as_of {
                Some(text) => DateTime::parse_from_rfc3339(&text)
                    .map_err(|_| Error::new(format!("not an RFC 3339 time: {text:?}"), "as-of"))?,
                None => Utc::now().trunc_subsecs(0).fixed_offset(),
            };
            commands::prepare(&home, &PrepareRequest { as_of })
        })),
        Data::Status => reply(home.map(|home| commands::status(&home))),
        Data::Export { market, out, days } => reply(home.and_then(|home| {
            let market: Market = market.parse()?;
            commands::export(&home, &ExportRequest { market, out, days })
        })),
        Data::Inspect { market, symbol, day } => reply(home.and_then(|home| {
            let market: Market = market.parse()?;
            let day = Day::parse(&day).ok_or_else(|| Error::new(format!("not an ISO day: {day:?}"), "day"))?;
            commands::inspect(&home, &InspectRequest { market, symbol, day })
        })),
    }
}

/// The runtime folder holds `bin/bt`, so it is the parent of the folder that
/// holds this program.
fn own_home() -> Result<Home, Error> {
    let exe = std::env::current_exe().map_err(|e| Error::new(format!("cannot find this program: {e}"), "--home"))?;
    let home = exe.parent().and_then(|bin| bin.parent());
    home.map(Home::new).ok_or_else(|| Error::new("this program is not in `bin/` of a runtime folder: pass --home", exe.display()))
}

/// Clap's message without its `error:` prefix and usage lines, on one line.
fn usage_message(error: &clap::Error) -> String {
    let text = error.render().to_string();
    let text = text.split("\n\nUsage:").next().unwrap_or_default();
    let text = text.strip_prefix("error: ").unwrap_or(text);
    text.split_whitespace().collect::<Vec<_>>().join(" ")
}

fn reply<T: Serialize>(result: Result<T, Error>) -> ExitCode {
    let (text, code) = match result {
        Ok(reply) => (serde_json::to_string_pretty(&reply), ExitCode::SUCCESS),
        Err(error) => (serde_json::to_string_pretty(&serde_json::json!({ "error": error })), ExitCode::from(1)),
    };
    println!("{}", text.expect("a reply is JSON"));
    code
}
