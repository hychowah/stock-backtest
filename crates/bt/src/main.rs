//! `bt`: turns arguments into a request, calls its handler and prints the
//! reply as JSON. An error, including a wrong argument, prints
//! `{"error": {"message", "place"}}` and exits with status 1. Help and
//! version print as text.

use chrono::{DateTime, SubsecRound, Utc};
use clap::error::ErrorKind;
use clap::{Args, Parser, Subcommand};
use engine::commands::{CatalogRequest, CheckRequest, ExploreRequest, ExportResultsRequest, RunRequest, ScreenRequest};
use engine::{Dates, Interval, Schedule, Selection};
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
    /// Run strategy files on one schedule; write one result file for each
    Run(RunArgs),
    /// Export result files
    #[command(subcommand)]
    Export(Export),
    /// Explore one result over a window of periods and a range of ranks
    Explore {
        /// A result file
        result: PathBuf,
        /// A trial's number, or all (the trials of random dates)
        #[arg(long)]
        trial: String,
        /// The periods A-B of each trial, from 1
        #[arg(long)]
        periods: String,
        /// The ranks A-B, within the strategy's
        #[arg(long)]
        ranks: String,
    },
    /// Read strategy files without market data: canonical form, identity and each step's source
    Check {
        /// Strategy files
        #[arg(required = true)]
        files: Vec<PathBuf>,
    },
    /// What a strategy file can write, and the market's sectors and exchanges
    Catalog {
        /// us, hk or jp
        #[arg(long)]
        market: String,
    },
    /// The picks of a strategy file on the market's latest session
    Screen {
        /// A strategy file
        file: PathBuf,
        /// us, hk or jp
        #[arg(long)]
        market: String,
    },
}

#[derive(Args)]
struct RunArgs {
    /// Strategy files, run as one batch on the same trade dates
    #[arg(required = true)]
    files: Vec<PathBuf>,
    /// us, hk or jp
    #[arg(long)]
    market: String,
    /// The first day of the window, YYYY-MM-DD
    #[arg(long)]
    start: String,
    /// The last day of the window, YYYY-MM-DD
    #[arg(long)]
    end: String,
    /// Trade every N weeks (Nw) or months (Nm)
    #[arg(long, required_unless_present = "dates", conflicts_with = "dates")]
    every: Option<String>,
    /// Run this many trials, each trading on one random session in every interval
    // Clap skips `requires` when --dates excludes --every, so this conflict is needed.
    #[arg(long, requires = "every", conflicts_with = "dates")]
    random: Option<u32>,
    /// Trade on these sessions, comma-separated
    #[arg(long, value_delimiter = ',')]
    dates: Option<Vec<String>>,
    /// The seed of the random dates [default: drawn and reported]
    #[arg(long, requires = "random")]
    seed: Option<u32>,
    /// The result folder: new or empty
    #[arg(long)]
    out: PathBuf,
}

#[derive(Subcommand)]
enum Export {
    /// Export result files' rows, statistics and views as keyed tables
    Tables(ExportArgs),
    /// Export every holding with the value of each numeric source of its steps
    Holdings(ExportArgs),
}

#[derive(Args)]
struct ExportArgs {
    /// Result files; each one's stem names its case
    #[arg(required = true)]
    results: Vec<PathBuf>,
    /// The export folder: new or empty
    #[arg(long)]
    out: PathBuf,
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
    match cli.command {
        Command::Run(args) => reply(home.and_then(|home| run(&home, args))),
        Command::Export(Export::Tables(ExportArgs { results, out })) => {
            reply(engine::commands::export_tables(&ExportResultsRequest { results, out }))
        }
        Command::Export(Export::Holdings(ExportArgs { results, out })) => {
            reply(engine::commands::export_holdings(&ExportResultsRequest { results, out }))
        }
        Command::Explore { result, trial, periods, ranks } => reply((|| {
            let trial = match trial.as_str() {
                "all" => None,
                text => Some(text.parse().map_err(|_| Error::new(format!("{text:?} is not a trial: use its number, or all"), "trial"))?),
            };
            let selection = Selection { trial, periods: range(&periods, "periods")?, ranks: range(&ranks, "ranks")? };
            engine::commands::explore(&ExploreRequest { result, selection })
        })()),
        Command::Check { files } => reply(engine::commands::check(&CheckRequest { files })),
        Command::Catalog { market } => reply(home.and_then(|home| {
            let market: Market = market.parse()?;
            engine::commands::catalog(&home, &CatalogRequest { market })
        })),
        Command::Screen { file, market } => reply(home.and_then(|home| {
            let market: Market = market.parse()?;
            engine::commands::screen(&home, &ScreenRequest { file, market })
        })),
        Command::Data(Data::Prepare { as_of }) => reply(home.and_then(|home| {
            let as_of = match as_of {
                Some(text) => DateTime::parse_from_rfc3339(&text)
                    .map_err(|_| Error::new(format!("not an RFC 3339 time: {text:?}"), "as-of"))?,
                None => Utc::now().trunc_subsecs(0).fixed_offset(),
            };
            commands::prepare(&home, &PrepareRequest { as_of })
        })),
        Command::Data(Data::Status) => reply(home.map(|home| commands::status(&home))),
        Command::Data(Data::Export { market, out, days }) => reply(home.and_then(|home| {
            let market: Market = market.parse()?;
            commands::export(&home, &ExportRequest { market, out, days })
        })),
        Command::Data(Data::Inspect { market, symbol, day }) => reply(home.and_then(|home| {
            let market: Market = market.parse()?;
            let day = Day::parse(&day).ok_or_else(|| Error::new(format!("not an ISO day: {day:?}"), "day"))?;
            commands::inspect(&home, &InspectRequest { market, symbol, day })
        })),
    }
}

/// `bt run`: the schedule from the arguments, with a drawn seed when random
/// dates have none.
fn run(home: &Home, args: RunArgs) -> Result<engine::commands::RunReply, Error> {
    let market: Market = args.market.parse()?;
    let dates = match (args.every, args.random, args.dates) {
        (Some(every), None, None) => Dates::Every(interval(&every)?),
        (Some(every), Some(trials), None) => Dates::Random { every: interval(&every)?, trials, seed: args.seed.unwrap_or_else(draw_seed) },
        (None, None, Some(dates)) => Dates::Explicit(dates),
        _ => unreachable!("clap checks that --every or --dates is given, and --random only with --every"),
    };
    let schedule = Schedule { start: args.start, end: args.end, dates };
    engine::commands::run(home, &RunRequest { files: args.files, market, schedule, out: args.out })
}

/// `Nw` or `Nm`.
fn interval(text: &str) -> Result<Interval, Error> {
    let invalid = || Error::new(format!("{text:?} is not an interval: use N weeks (Nw) or N months (Nm), such as 13w or 3m"), "every");
    let count = |count: &str| count.parse::<u32>().map_err(|_| invalid());
    match (text.strip_suffix('w'), text.strip_suffix('m')) {
        (Some(weeks), _) => Ok(Interval::Weeks(count(weeks)?)),
        (_, Some(months)) => Ok(Interval::Months(count(months)?)),
        _ => Err(invalid()),
    }
}

/// `A-B`: two whole numbers, which the command checks.
fn range(text: &str, place: &str) -> Result<(u32, u32), Error> {
    let bounds = text.split_once('-').and_then(|(a, b)| Some((a.parse::<u32>().ok()?, b.parse::<u32>().ok()?)));
    bounds.ok_or_else(|| Error::new(format!("{text:?} is not a range: use A-B, such as 2-5"), place))
}

/// A seed from the process's random hash keys, which the system seeds.
fn draw_seed() -> u32 {
    use std::hash::{BuildHasher, RandomState};
    RandomState::new().hash_one(std::time::SystemTime::now()) as u32
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
