//! The `data` commands: each command's request, reply and handler. `bt` turns
//! arguments into a request, calls the handler and prints the reply as JSON.
//! A handler checks its request once, at the start; an [`Error`] stops it.

use crate::annual::{self, AnnualColumns, AnnualRows};
use crate::companies::{self, Company, CompanyId};
use crate::prices::{self, PriceColumns, PriceRows};
use crate::raw::Raw;
use crate::reports::{self, ReportColumns, ReportRows, Reported};
use crate::series::{self, Series};
use crate::store::{GenerationWriter, Lock};
use crate::valuation::{self, SumRows, ValuationColumns};
use crate::{Day, Error, Market, MarketData, PROGRAM};
use chrono::{DateTime, FixedOffset};
use rayon::prelude::*;
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
    pub companies: usize,
    /// The first and last session, ISO text; `None` when it has none.
    pub first_session: Option<String>,
    pub last_session: Option<String>,
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
        let (companies, sessions) = build(home, market, &request.as_of, &mut generation)?;
        let manifest = generation.publish(&request.as_of, started.elapsed().as_secs_f64())?;
        markets.push(PreparedMarket {
            market,
            generation: manifest.generation,
            as_of: manifest.as_of.clone(),
            companies,
            first_session: sessions.first().map(Day::to_string),
            last_session: sessions.last().map(Day::to_string),
            bytes: manifest.bytes(),
            seconds: started.elapsed().as_secs_f64(),
        });
    }
    Ok(PrepareReply { markets })
}

/// The build step: reads the market's raw files and writes every column of
/// one generation; returns the number of companies and the sessions. First
/// the market-wide kinds (companies, series, US reports), then each company
/// in parallel ([`company`]), then the columns. Each kind of data adds its
/// part here, in the order its inputs need.
fn build(
    home: &Home,
    market: Market,
    as_of: &DateTime<FixedOffset>,
    out: &mut GenerationWriter<'_>,
) -> Result<(usize, Vec<Day>), Error> {
    let raw = Raw::new(home.raw());
    let listed = companies::read(&raw, market)?;
    let series = series::read(&raw, market, as_of)?;
    let reported = (market == Market::Us).then(|| reports::read_us(&raw, &listed)).transpose()?;
    let view = series.view();
    let parts: Vec<Result<CompanyParts, Error>> = listed
        .par_iter()
        .enumerate()
        .map(|(i, listing)| company(&raw, market, CompanyId(i as u32), listing, &view, reported.as_ref()))
        .collect();
    // The first failure in symbol order, as a preparation one company at a
    // time would meet it.
    let parts = parts.into_iter().collect::<Result<Vec<_>, _>>()?;
    let priced: Vec<bool> = parts.iter().map(|p| p.prices.is_some()).collect();
    let order = reported.as_ref().map_or_else(|| vec![None; listed.len()], |r| r.order().to_vec());
    companies::write(out, &listed, &priced, &order)?;
    series.write(out)?;
    prices::write(out, &parts.iter().map(|p| p.prices.as_ref()).collect::<Vec<_>>())?;
    reports::write(out, market, &parts.iter().map(|p| &p.reports).collect::<Vec<_>>())?;
    annual::write(out, &parts.iter().map(|p| p.annual.as_ref()).collect::<Vec<_>>())?;
    valuation::write(out, &parts.iter().map(|p| &p.sums).collect::<Vec<_>>())?;
    Ok((listed.len(), view.sessions().to_vec()))
}

/// One company's prepared parts.
struct CompanyParts {
    /// `None` when the company has no saved price file, or lies outside the
    /// market's price scope (US: the reported set).
    prices: Option<PriceRows>,
    reports: ReportRows,
    /// `None` for an unreported US company: the US reads statements of the
    /// reported set only.
    annual: Option<AnnualRows>,
    sums: SumRows,
}

/// The per-company build step: one company's parts from its own raw files,
/// the market's series and, in the US, the reported set: prices, reports
/// (foreign: the anchors from its statements), statements, then the
/// valuation fold over them. Companies are built in parallel. An unreadable
/// price file stops preparation.
fn company(
    raw: &Raw,
    market: Market,
    c: CompanyId,
    listing: &Company,
    series: &Series<'_>,
    reported: Option<&Reported>,
) -> Result<CompanyParts, Error> {
    let symbol = &listing.symbol;
    let (prices, annual, reports) = match reported {
        Some(reported) if !reported.is_reported(c) => (None, None, ReportRows::us(&[])),
        Some(reported) => {
            let prices = prices::read(raw, symbol, market.currency(), None)?;
            (prices, Some(annual::read(raw, market, symbol)?), ReportRows::us(reported.reports(c)))
        }
        None => {
            let sessions = series.sessions();
            let prices = prices::read(raw, symbol, &listing.currency, Some(sessions))?;
            let annual = annual::read(raw, market, symbol)?;
            let reports = ReportRows::foreign(raw, market, symbol, &listing.currency, &annual.view(), sessions)?;
            (prices, Some(annual), reports)
        }
    };
    let sums = match (&prices, &annual) {
        (Some(prices), Some(annual)) => valuation::fold(&prices.view(), &reports.view(&listing.currency), &annual.view(), series),
        _ => SumRows::default(),
    };
    Ok(CompanyParts { prices, reports, annual, sums })
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
    Generation {
        generation: u64,
        as_of: String,
        program: String,
        bytes: u64,
        companies: usize,
        first_session: Option<String>,
        last_session: Option<String>,
    },
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
                    let (m, sessions) = (data.manifest(), data.sessions());
                    Prepared::Generation {
                        generation: m.generation,
                        as_of: m.as_of.clone(),
                        program: m.program.clone(),
                        bytes: m.bytes(),
                        companies: data.companies().len(),
                        first_session: sessions.first().map(Day::to_string),
                        last_session: sessions.last().map(Day::to_string),
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
/// format) into `out`, with the oracle's table and field names: `companies`,
/// `sessions`, `market_days`, `fx_days` (Hong Kong and Tokyo), `stock_days`,
/// `reports`, `annual_facts`, `annual_metadata` and `valuation_sums`. Fails
/// when the market is not prepared or `out` exists and is not empty.
pub fn export(home: &Home, request: &ExportRequest) -> Result<ExportReply, Error> {
    let data = MarketData::open(home, request.market)?;
    let m = data.manifest();
    let settings = serde_json::json!({ "market": m.market, "generation": m.generation, "as_of": m.as_of });
    let out = &request.out;
    let fail = |message: String| Error::new(message, out.display());
    let mut writer = tables::Writer::create(out, PROGRAM, settings).map_err(fail)?;
    let (generation, companies) = (&data.generation, data.companies());
    let series = Series::open(generation);
    let mut tables = BTreeMap::new();
    let mut write = |name: &str, rows: Result<u64, String>| rows.map(|rows| tables.insert(name.to_string(), rows)).map_err(fail);
    write("companies", companies.export(request.market, &mut writer))?;
    write("sessions", series.export_sessions(&mut writer))?;
    write("market_days", series.export_market_days(&mut writer))?;
    if request.market != Market::Us {
        write("fx_days", series.export_fx_days(&mut writer))?;
    }
    write("stock_days", PriceColumns::open(generation).export(&companies, &mut writer))?;
    write("reports", ReportColumns::open(generation).export(&mut writer))?;
    let annual = AnnualColumns::open(generation);
    write("annual_facts", annual.export_facts(&companies, &mut writer))?;
    write("annual_metadata", annual.export_metadata(&companies, &mut writer))?;
    write("valuation_sums", ValuationColumns::open(generation).export(&companies, &mut writer))?;
    writer.finish().map_err(fail)?;
    Ok(ExportReply { tables })
}
