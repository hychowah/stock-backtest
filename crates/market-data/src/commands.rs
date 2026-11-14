//! The `data` commands: each command's request, reply and handler. `bt` turns
//! arguments into a request, calls the handler and prints the reply as JSON.
//! A handler checks its request once, at the start; an [`Error`] stops it.

use crate::store::{GenerationWriter, Lock};
use crate::{Error, Market, MarketData, PROGRAM};
use chrono::{DateTime, FixedOffset};
use serde::Serialize;
use std::collections::BTreeMap;
use std::path::PathBuf;
use std::time::Instant;

/// The runtime folder: the paths of its parts. Commands read raw provider
/// files below [`raw`](Self::raw) and keep prepared data below
/// [`prepared`](Self::prepared).
#[derive(Debug, Clone)]
pub struct Home {
    root: PathBuf,
}

impl Home {
    pub fn new(root: impl Into<PathBuf>) -> Home {
        Home { root: root.into() }
    }

    /// `raw/`: the provider cache. The program only reads it.
    pub fn raw(&self) -> PathBuf {
        self.root.join("raw")
    }

    /// `data/prepared/`: the prepared store (see [`crate::store`]).
    pub fn prepared(&self) -> PathBuf {
        self.root.join("data").join("prepared")
    }
}

/// `bt data prepare [--as-of T]`.
pub struct PrepareRequest {
    /// The time the data is prepared for. `bt` supplies the current time
    /// when none is given; this crate reads no clock.
    pub as_of: DateTime<FixedOffset>,
}

#[derive(Debug, Serialize)]
pub struct PrepareReply {
    /// One entry for each market with raw data, in [`Market::ALL`] order.
    pub markets: Vec<PreparedMarket>,
}

#[derive(Debug, Serialize)]
pub struct PreparedMarket {
    pub market: Market,
    pub generation: u64,
    pub as_of: String,
    /// The size of the generation's columns.
    pub bytes: u64,
    /// The time the market took, from cleanup to publish.
    pub seconds: f64,
}

/// Prepares every market that has raw data, one at a time, and publishes a
/// new generation of each. Fails when another preparation is running. A
/// market that fails keeps its `current` generation; markets prepared before
/// it stay published.
pub fn prepare(home: &Home, request: &PrepareRequest) -> Result<PrepareReply, Error> {
    let lock = Lock::take(home)?;
    let mut markets = Vec::new();
    for market in Market::ALL.into_iter().filter(|&m| raw_present(home, m)) {
        let started = Instant::now();
        let mut generation = lock.begin(market)?;
        build(home, market, &request.as_of, &mut generation)?;
        let manifest = generation.publish(&request.as_of, started.elapsed().as_secs_f64())?;
        markets.push(PreparedMarket {
            market,
            generation: manifest.generation,
            as_of: manifest.as_of.clone(),
            bytes: manifest.bytes(),
            seconds: started.elapsed().as_secs_f64(),
        });
    }
    Ok(PrepareReply { markets })
}

/// The build step: reads the market's raw files and writes every column of
/// one generation. Each kind of data adds its columns here, in the order its
/// inputs need.
fn build(
    _home: &Home,
    _market: Market,
    _as_of: &DateTime<FixedOffset>,
    _out: &mut GenerationWriter<'_>,
) -> Result<(), Error> {
    Ok(())
}

/// Whether the market has raw data: its universe file exists. The US files
/// are at the top of `raw/`, the others in `raw/markets/<market>/`.
fn raw_present(home: &Home, market: Market) -> bool {
    let dir = match market {
        Market::Us => home.raw(),
        _ => home.raw().join("markets").join(market.id()),
    };
    dir.join("universe.json").is_file()
}

/// `bt data status`.
#[derive(Debug, Serialize)]
pub struct StatusReply {
    /// One entry per market, in [`Market::ALL`] order.
    pub markets: Vec<MarketStatus>,
}

#[derive(Debug, Serialize)]
pub struct MarketStatus {
    pub market: Market,
    /// Whether `raw/` holds the market's data.
    pub raw: bool,
    pub prepared: Prepared,
}

/// The market's current generation, or why it cannot be opened.
#[derive(Debug, Serialize)]
#[serde(untagged)]
pub enum Prepared {
    Generation { generation: u64, as_of: String, program: String, bytes: u64 },
    /// The open error's message, such as "us is not prepared: run `bt data prepare`".
    Not(String),
}

/// Reports each market's raw data and current generation. Does not fail.
pub fn status(home: &Home) -> StatusReply {
    let markets = Market::ALL
        .into_iter()
        .map(|market| MarketStatus {
            market,
            raw: raw_present(home, market),
            prepared: match MarketData::open(home, market) {
                Ok(data) => {
                    let m = data.manifest();
                    Prepared::Generation {
                        generation: m.generation,
                        as_of: m.as_of.clone(),
                        program: m.program.clone(),
                        bytes: m.bytes(),
                    }
                }
                Err(error) => Prepared::Not(error.message),
            },
        })
        .collect();
    StatusReply { markets }
}

/// `bt data export --market M --out DIR`.
pub struct ExportRequest {
    pub market: Market,
    /// The export folder: new or empty.
    pub out: PathBuf,
}

#[derive(Debug, Serialize)]
pub struct ExportReply {
    /// The rows written per table.
    pub tables: BTreeMap<String, u64>,
}

/// Writes the market's current generation as keyed tables (`tables` crate
/// format) into `out`. Fails when the market is not prepared or `out` exists
/// and is not empty.
pub fn export(home: &Home, request: &ExportRequest) -> Result<ExportReply, Error> {
    let data = MarketData::open(home, request.market)?;
    let m = data.manifest();
    let settings = serde_json::json!({ "market": m.market, "generation": m.generation, "as_of": m.as_of });
    let out = &request.out;
    let fail = |message: String| Error::new(message, out.display());
    let writer = tables::Writer::create(out, PROGRAM, settings).map_err(fail)?;
    writer.finish().map_err(fail)?;
    Ok(ExportReply { tables: BTreeMap::new() })
}
