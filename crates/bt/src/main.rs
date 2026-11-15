//! `bt`: turns arguments into a request, calls its handler and prints the
//! reply as JSON. An error, including a wrong argument, prints
//! `{"error": {"message", "place"}}` and exits with status 1. Help and
//! version print as text.

use chrono::{DateTime, SubsecRound, Utc};
use clap::error::ErrorKind;
use clap::{Args, Parser, Subcommand};
use engine::commands::{CheckReply, RunReply, RunRequest, ScreenRequest, Target};
use engine::cross_section::CrossSectionRequest;
use engine::views::{Selection, range};
use engine::{Schedule, Strategy};
use market_data::commands::{self, ExportRequest, Home, InspectRequest, PrepareRequest};
use market_data::{Day, Error, Market};
use serde::Serialize;
use std::collections::BTreeSet;
use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::sync::atomic::AtomicBool;

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
    /// Serve the website and its API on 127.0.0.1 and run the queue, until Ctrl+C or SIGTERM
    Serve {
        /// The port; 0 for a free one
        #[arg(long, default_value_t = 3000)]
        port: u16,
    },
    /// Add a result file to the home's run list as a complete run
    Save {
        /// A result file of `bt run`
        result: PathBuf,
        /// The run's name in the list
        #[arg(long)]
        name: String,
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
    // The schedule's flags are the keys of `engine::Schedule`, which checks
    // how they combine.
    /// Trade every N weeks (Nw) or months (Nm)
    #[arg(long)]
    every: Option<String>,
    /// Run this many trials, each trading on one random session in every interval
    #[arg(long)]
    trials: Option<u32>,
    /// The seed of the random dates [default: drawn and reported]
    #[arg(long)]
    seed: Option<u32>,
    /// Trade on these sessions, comma-separated
    #[arg(long, value_delimiter = ',')]
    dates: Option<Vec<String>>,
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
    /// Export every candidate of the schedule's entry days with the file's variables and its return to each exit
    #[command(mut_arg("files", |a| a.help("A strategy file").value_name("FILE").num_args(1).action(clap::ArgAction::Set)))]
    CrossSection(RunArgs),
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
    let root = match cli.home {
        Some(path) => Ok(path),
        None => own_home(),
    };
    let home = root.clone().map(Home::new);
    match cli.command {
        Command::Run(args) => reply(home.and_then(|home| run(&home, args))),
        Command::Export(Export::Tables(ExportArgs { results, out })) => reply(engine::commands::export_tables(&results, &out)),
        Command::Export(Export::Holdings(ExportArgs { results, out })) => reply(engine::commands::export_holdings(&results, &out)),
        Command::Export(Export::CrossSection(args)) => reply(home.and_then(|home| {
            let (market, schedule) = schedule(&args)?;
            let file = &args.files[0];
            let request = CrossSectionRequest { name: name(file), strategy: strategy(file)?, market, schedule, out: args.out };
            engine::cross_section::cross_section(&home, &request)
        })),
        Command::Explore { result, trial, periods, ranks } => reply((|| {
            let trial = match trial.as_str() {
                "all" => None,
                text => Some(text.parse().map_err(|_| Error::new(format!("{text:?} is not a trial: use its number, or all"), "trial"))?),
            };
            let selection = Selection { trial, periods: range(&periods, "periods")?, ranks: range(&ranks, "ranks")? };
            engine::commands::explore(&result, &selection)
        })()),
        Command::Check { files } => reply((|| {
            let files = files.iter().map(|file| Ok(engine::commands::check(&name(file), &strategy(file)?))).collect::<Result<_, Error>>()?;
            Ok(CheckReply { files })
        })()),
        Command::Catalog { market } => reply(home.and_then(|home| engine::commands::catalog(&home, market.parse()?))),
        Command::Screen { file, market } => reply(home.and_then(|home| {
            let market: Market = market.parse()?;
            let strategy = strategy(&file)?;
            engine::commands::screen(&home, &ScreenRequest { name: name(&file), strategy, market })
        })),
        Command::Serve { port } => match root.and_then(|root| {
            app::serve(&root, port, |address| println!("{}", serde_json::json!({ "serving": format!("http://{address}") })))
        }) {
            Ok(()) => ExitCode::SUCCESS,
            Err(error) => reply::<()>(Err(error)),
        },
        Command::Save { result, name } => reply(root.and_then(|root| app::save(&root, &result, &name))),
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

/// `bt run`: every strategy file is read before any data, and each result
/// is `DIR/<file stem>.sqlite` in a new or empty folder.
fn run(home: &Home, args: RunArgs) -> Result<RunReply, Error> {
    let (market, schedule) = schedule(&args)?;
    let strategies = args.files.iter().map(|file| strategy(file)).collect::<Result<Vec<_>, _>>()?;
    let mut stems = BTreeSet::new();
    for file in &args.files {
        if !stems.insert(file.file_stem()) {
            return Err(Error::new("another strategy file has the same name; their results would share one file", file.display()));
        }
    }
    let out = &args.out;
    tables::new_or_empty(out).map_err(|message| Error::new(message, out.display()))?;
    let runs = args
        .files
        .iter()
        .zip(strategies)
        .map(|(file, strategy)| {
            let stem = file.file_stem().unwrap_or_default().to_string_lossy();
            Target { name: name(file), strategy, result: out.join(format!("{stem}.sqlite")) }
        })
        .collect();
    engine::commands::run(home, &RunRequest { market, schedule, runs }, &AtomicBool::new(false))
}

/// The market and schedule of `bt run` and `bt export cross-section`.
fn schedule(args: &RunArgs) -> Result<(Market, Schedule), Error> {
    let market: Market = args.market.parse()?;
    let schedule = Schedule {
        start: args.start.clone(),
        end: args.end.clone(),
        every: args.every.clone(),
        trials: args.trials,
        seed: args.seed,
        dates: args.dates.clone(),
    };
    Ok((market, schedule))
}

/// A strategy file, read and checked; an error's place starts with the file.
fn strategy(file: &Path) -> Result<Strategy, Error> {
    let text = std::fs::read_to_string(file).map_err(|_| Error::new("the strategy file cannot be read as text", file.display()))?;
    Strategy::parse(&text).map_err(|e| e.in_file(file.display()))
}

/// A strategy file's name in replies and error places: its path as given.
fn name(file: &Path) -> String {
    file.display().to_string()
}

/// The runtime folder holds `bin/bt`, so it is the parent of the folder that
/// holds this program.
fn own_home() -> Result<PathBuf, Error> {
    let exe = std::env::current_exe().map_err(|e| Error::new(format!("cannot find this program: {e}"), "--home"))?;
    let home = exe.parent().and_then(|bin| bin.parent());
    home.map(Path::to_path_buf).ok_or_else(|| Error::new("this program is not in `bin/` of a runtime folder: pass --home", exe.display()))
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
