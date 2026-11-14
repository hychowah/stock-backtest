//! The companies of a market: its saved listing with the oracle's defaults
//! for missing metadata, in symbol byte order. A [`CompanyId`] is a
//! company's position in that order, and every per-company column follows it.
//!
//! Columns: `companies.symbol`, `.name`, `.exchange`, `.sector` and
//! `.currency` (text), `.listed` and `.priced` (`u8`, 0 or 1), `.order`
//! (`u32`, 0 for none).

use crate::raw::{Json, Raw, read_json};
use crate::store::{Generation, GenerationWriter, Text};
use crate::{Error, Market};
use serde_json::Value;
use std::collections::BTreeMap;
use tables::Cell;

/// A company's position in its market's prepared data.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct CompanyId(pub(crate) u32);

impl CompanyId {
    pub(crate) fn index(self) -> usize {
        self.0 as usize
    }
}

/// One saved listing, as preparation reads it.
pub(crate) struct Company {
    pub(crate) symbol: String,
    /// The name, exchange and sector, or `Unavailable` when the row has none.
    pub(crate) name: String,
    pub(crate) exchange: String,
    pub(crate) sector: String,
    /// The quote currency: the row's, or the market's when it names none.
    pub(crate) currency: String,
    /// The row says `"listed": true`.
    pub(crate) listed: bool,
}

/// Reads the market's saved listing (`facts.store_companies`), in symbol
/// order. A symbol saved twice keeps its last row. Hong Kong and Tokyo keep
/// only the rows the market admits ([`Market::admits`]). An unreadable list,
/// or a row without a text symbol, stops preparation.
pub(crate) fn read(raw: &Raw, market: Market) -> Result<Vec<Company>, Error> {
    let path = raw.universe(market);
    let unreadable = |what: &str| Error::new(format!("the saved company list {what}: download it again"), path.display());
    let rows = match read_json(&path)? {
        Json::Missing => return Ok(Vec::new()),
        Json::Unreadable => return Err(unreadable("is not JSON")),
        Json::Value(Value::Array(rows)) => rows,
        Json::Value(_) => return Err(unreadable("is not a list")),
    };
    let mut companies = BTreeMap::new();
    for row in &rows {
        let Some(symbol) = row.get("symbol").and_then(Value::as_str) else {
            return Err(unreadable("has a row without a text symbol"));
        };
        let text = |key: &str| row.get(key).and_then(Value::as_str).filter(|s| !s.is_empty());
        if !market.admits(symbol, text("name").unwrap_or("")) {
            continue;
        }
        let or_unavailable = |key: &str| text(key).unwrap_or("Unavailable").to_string();
        let company = Company {
            symbol: symbol.to_string(),
            name: or_unavailable("name"),
            exchange: or_unavailable("exchange"),
            sector: or_unavailable("sector"),
            currency: text("currency").unwrap_or(market.currency()).to_string(),
            listed: row.get("listed") == Some(&Value::Bool(true)),
        };
        companies.insert(company.symbol.clone(), company);
    }
    Ok(companies.into_values().collect())
}

/// Writes the company columns. `priced` says which companies have a saved
/// price file within the market's price scope; `order` is the US
/// first-appearance position of each reported company.
pub(crate) fn write(
    out: &mut GenerationWriter<'_>,
    companies: &[Company],
    priced: &[bool],
    order: &[Option<u32>],
) -> Result<(), Error> {
    let texts = |field: fn(&Company) -> &str| companies.iter().map(field).collect::<Vec<_>>();
    out.text("companies.symbol", &texts(|c| &c.symbol))?;
    out.text("companies.name", &texts(|c| &c.name))?;
    out.text("companies.exchange", &texts(|c| &c.exchange))?;
    out.text("companies.sector", &texts(|c| &c.sector))?;
    out.text("companies.currency", &texts(|c| &c.currency))?;
    out.column("companies.listed", &companies.iter().map(|c| u8::from(c.listed)).collect::<Vec<_>>())?;
    out.column("companies.priced", &priced.iter().map(|&p| u8::from(p)).collect::<Vec<_>>())?;
    out.column("companies.order", &order.iter().map(|o| o.unwrap_or(0)).collect::<Vec<_>>())
}

/// A market's prepared companies, read from a generation.
#[derive(Clone, Copy)]
pub struct Companies<'a> {
    symbol: Text<'a>,
    name: Text<'a>,
    exchange: Text<'a>,
    sector: Text<'a>,
    currency: Text<'a>,
    listed: &'a [u8],
    priced: &'a [u8],
    order: &'a [u32],
}

impl<'a> Companies<'a> {
    pub(crate) fn open(generation: &'a Generation) -> Companies<'a> {
        Companies {
            symbol: generation.text("companies.symbol"),
            name: generation.text("companies.name"),
            exchange: generation.text("companies.exchange"),
            sector: generation.text("companies.sector"),
            currency: generation.text("companies.currency"),
            listed: generation.column("companies.listed"),
            priced: generation.column("companies.priced"),
            order: generation.column("companies.order"),
        }
    }

    pub fn len(&self) -> usize {
        self.symbol.len()
    }

    /// Every company, in symbol order.
    pub fn ids(&self) -> impl Iterator<Item = CompanyId> + use<> {
        (0..self.len() as u32).map(CompanyId)
    }

    pub fn symbol(&self, c: CompanyId) -> &'a str {
        self.symbol.get(c.index())
    }

    pub fn name(&self, c: CompanyId) -> &'a str {
        self.name.get(c.index())
    }

    pub fn exchange(&self, c: CompanyId) -> &'a str {
        self.exchange.get(c.index())
    }

    pub fn sector(&self, c: CompanyId) -> &'a str {
        self.sector.get(c.index())
    }

    /// Whether the saved listing says the company is listed now.
    pub fn listed(&self, c: CompanyId) -> bool {
        self.listed[c.index()] == 1
    }

    /// The quote currency.
    pub(crate) fn currency(&self, c: CompanyId) -> &'a str {
        self.currency.get(c.index())
    }

    /// Whether the company has a saved price file within the market's price
    /// scope (US: the reported companies).
    pub(crate) fn priced(&self, c: CompanyId) -> bool {
        self.priced[c.index()] == 1
    }

    /// US: the position, from 1, of the company's first record in
    /// `metrics.jsonl` among the reported companies; the legacy tie rank
    /// follows it. `None` for unreported and foreign companies.
    pub(crate) fn order(&self, c: CompanyId) -> Option<u32> {
        Some(self.order[c.index()]).filter(|&o| o > 0)
    }

    /// Writes the `companies` table (key `symbol`).
    pub(crate) fn export(&self, market: Market, out: &mut tables::Writer) -> Result<u64, String> {
        let mut table = out.table("companies", &["symbol"])?;
        for c in self.ids() {
            table.row(&[
                ("symbol", Cell::Text(self.symbol(c))),
                ("market", Cell::Text(market.id())),
                ("currency", Cell::Text(self.currency(c))),
                ("name", Cell::Text(self.name(c))),
                ("exchange", Cell::Text(self.exchange(c))),
                ("sector", Cell::Text(self.sector(c))),
                ("listed", Cell::Bool(self.listed(c))),
                ("priced", Cell::Bool(self.priced(c))),
                ("order", self.order(c).map_or(Cell::Null, |o| Cell::Int(o.into()))),
            ])?;
        }
        table.finish()
    }
}
