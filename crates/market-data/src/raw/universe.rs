//! The company lists, `universe.json` (US) and `markets/hk/universe.json`,
//! as the old updater builds and merges them (`data_manager.fetch_universe`,
//! `fetch_market_universe` and `download_market`, `data_refresh.download`).

use super::{PyJson, Raw, read_file, replace};
use super::pyjson::Object;
use crate::{Error, Market};
use std::collections::HashMap;
use std::path::PathBuf;

/// Rows by symbol in first-seen order; a repeated symbol keeps its first
/// place and its last row, as a Python dict does.
#[derive(Default, Clone)]
struct Rows {
    rows: Vec<(String, Object)>,
    index: HashMap<String, usize>,
}

impl Rows {
    fn get(&self, symbol: &str) -> Option<&Object> {
        self.index.get(symbol).map(|&i| &self.rows[i].1)
    }

    fn insert(&mut self, symbol: String, row: Object) {
        match self.index.get(&symbol) {
            Some(&i) => self.rows[i].1 = row,
            None => {
                self.index.insert(symbol.clone(), self.rows.len());
                self.rows.push((symbol, row));
            }
        }
    }

    /// Python's dict equality: the same symbols with equal rows.
    fn same(&self, other: &Rows) -> bool {
        self.rows.len() == other.rows.len() && self.rows.iter().all(|(symbol, row)| other.get(symbol) == Some(row))
    }

    fn text(&self) -> String {
        PyJson::List(self.rows.iter().map(|(_, row)| PyJson::Object(row.clone())).collect()).to_text()
    }
}

/// The companies one update's company-list replies name, in reply order: a
/// later row of the same symbol replaces the earlier one in its place.
pub struct Listing {
    market: Market,
    rows: Rows,
}

impl Listing {
    /// An empty listing of the US or Hong Kong.
    pub fn new(market: Market) -> Listing {
        assert!(market != Market::Jp, "Tokyo's company list is not updated");
        Listing { market, rows: Rows::default() }
    }

    /// Adds the common stocks of one `company-screener` page, asked for
    /// `exchange` with `isActivelyTrading` `active`; returns the page's
    /// number of rows (kept or not), which ends the paging below 1,000.
    ///
    /// US (asked with `active` only): a row is kept when its symbol is a
    /// common stock's ([`us_common_stock`]), its `exchangeShortName`, else
    /// `exchange`, else the asked exchange is a US exchange, and it is no ETF
    /// or fund; it is saved as `{symbol, exchange, sector, name, listed:
    /// true}`. Hong Kong: a row is kept when it is no ETF or fund, its symbol
    /// is `[0-35-9]ddd.HK` with no ` ETF `, ` FUND ` or ` ETN ` word in its
    /// name, and its `exchangeShortName` (the asked exchange when absent) is
    /// `HKSE`; it is saved as `{symbol, name, exchange (the asked one),
    /// sector, listed (its isActivelyTrading, else active), market: "hk",
    /// currency (else HKD)}`. A sector is `""` when the reply has none.
    ///
    /// Fails when the page is not a list of objects: a company list that
    /// cannot be read ends the update's downloads.
    pub fn screener(&mut self, exchange: &str, active: bool, page: &PyJson) -> Result<usize, Error> {
        let rows = page_rows(page, "company-screener", exchange)?;
        for row in rows {
            let symbol = text(row.get("symbol"), "");
            let name = text(row.get("companyName"), "");
            let fund = row.get("isEtf").is_some_and(PyJson::truthy) || row.get("isFund").is_some_and(PyJson::truthy);
            let sector = row.get("sector").filter(|s| s.truthy()).cloned().unwrap_or_else(|| PyJson::from(""));
            let mut saved = Object::new();
            if self.market == Market::Us {
                let listed_on = text(row.get("exchangeShortName").filter(|e| e.truthy()).or(row.get("exchange")), exchange);
                if !(us_common_stock(&symbol, &name) && us_exchange(&listed_on) && !fund) {
                    continue;
                }
                saved.insert("symbol", PyJson::from(symbol.as_str()));
                saved.insert("exchange", PyJson::from(listed_on.as_str()));
                saved.insert("sector", sector);
                saved.insert("name", PyJson::from(name.as_str()));
                saved.insert("listed", PyJson::from(true));
            } else {
                let short = row.as_object().and_then(|r| r.get("exchangeShortName"));
                let on_hkse = short.map_or(exchange == "HKSE", |e| e.as_str() == Some("HKSE"));
                if fund || !self.market.admits(&symbol, &name) || !on_hkse {
                    continue;
                }
                let listed = row.get("isActivelyTrading").map_or(active, PyJson::truthy);
                let currency = row.get("currency").filter(|c| c.truthy()).cloned().unwrap_or_else(|| PyJson::from("HKD"));
                saved.insert("symbol", PyJson::from(symbol.as_str()));
                saved.insert("name", PyJson::from(name.as_str()));
                saved.insert("exchange", PyJson::from(exchange));
                saved.insert("sector", sector);
                saved.insert("listed", PyJson::from(listed));
                saved.insert("market", PyJson::from("hk"));
                saved.insert("currency", currency);
            }
            self.rows.insert(symbol, saved);
        }
        Ok(rows.len())
    }

    /// US: adds the delisted common stocks of one `delisted-companies` page
    /// that no earlier row names, as `{symbol, exchange, sector: "", name,
    /// listed: false}`; returns the page's number of rows, which ends the
    /// paging below 100. Fails as [`screener`](Self::screener) does.
    pub fn delisted(&mut self, page: &PyJson) -> Result<usize, Error> {
        assert!(self.market == Market::Us, "only the US has a delisted list");
        let rows = page_rows(page, "delisted-companies", "")?;
        for row in rows {
            let symbol = text(row.get("symbol"), "");
            let name = text(row.get("companyName"), "");
            let listed_on = text(row.get("exchange"), "");
            if !(us_common_stock(&symbol, &name) && us_exchange(&listed_on)) || self.rows.get(&symbol).is_some() {
                continue;
            }
            let mut saved = Object::new();
            saved.insert("symbol", PyJson::from(symbol.as_str()));
            saved.insert("exchange", PyJson::from(listed_on.as_str()));
            saved.insert("sector", PyJson::from(""));
            saved.insert("name", PyJson::from(name.as_str()));
            saved.insert("listed", PyJson::from(false));
            self.rows.insert(symbol, saved);
        }
        Ok(rows.len())
    }

    /// Whether no row was kept: then the company list failed.
    pub fn is_empty(&self) -> bool {
        self.rows.rows.is_empty()
    }
}

/// A page's rows, each an object.
fn page_rows<'a>(page: &'a PyJson, endpoint: &str, exchange: &str) -> Result<&'a [PyJson], Error> {
    let place = format!("{endpoint} {exchange}").trim_end().to_string();
    let rows = page.as_list().ok_or_else(|| Error::new("the reply is not a list", &place))?;
    if !rows.iter().all(|row| row.as_object().is_some()) {
        return Err(Error::new("a row of the reply is not an object", &place));
    }
    Ok(rows)
}

/// Python's `str(value or default)`. Not ported: a list or an object is
/// written as JSON, not as Python's repr.
fn text(value: Option<&PyJson>, default: &str) -> String {
    match value.filter(|v| v.truthy()) {
        None => default.to_string(),
        Some(PyJson::Str(s)) => s.clone(),
        Some(PyJson::Bool(_)) => "True".to_string(),
        Some(other) => other.to_text(),
    }
}

/// `rules.common_stock`: an upper-case symbol of at most 6 characters,
/// letters and digits or `LETTERS-L`, with no `.`; and no ETF, fund, ETN,
/// ProShares or iShares word in the name.
fn us_common_stock(symbol: &str, name: &str) -> bool {
    let upper = symbol.chars().any(char::is_uppercase) && !symbol.chars().any(char::is_lowercase);
    if symbol.is_empty() || !upper || symbol.contains('.') || symbol.chars().count() > 6 {
        return false;
    }
    let alpha = |s: &str| !s.is_empty() && s.chars().all(char::is_alphabetic);
    let form = match symbol.split_once('-') {
        Some((left, right)) => alpha(left) && right.chars().count() == 1 && alpha(right),
        None => symbol.chars().all(char::is_alphanumeric),
    };
    let label = name.to_uppercase();
    form && ![" ETF", "ETF ", " FUND", "FUND ", " ETN", "PROSHARES", "ISHARES"].iter().any(|t| label.contains(t))
}

/// `rules.us_exchange`: NYSE, NASDAQ, AMEX or ASE in the name, and no ARCA,
/// OTC, PINK or BATS.
fn us_exchange(name: &str) -> bool {
    let text = name.to_uppercase();
    !["ARCA", "OTC", "PINK", "BATS"].iter().any(|t| text.contains(t))
        && ["NYSE", "NASDAQ", "AMEX", "ASE"].iter().any(|t| text.contains(t))
}

/// A market's saved company list. Load it, [`apply`](Self::apply) the
/// update's [`Listing`], then [`save`](Self::save).
pub struct Universe {
    market: Market,
    path: PathBuf,
    /// The file's bytes as loaded; `None` when there was no file.
    bytes: Option<Vec<u8>>,
    /// The rows as loaded: the objects with a text `symbol`.
    loaded: Rows,
    rows: Rows,
}

impl Universe {
    /// Reads the US or Hong Kong company list; no file is an empty list.
    /// Fails, naming the file, when it cannot be read or is not a list.
    pub fn load(raw: &Raw, market: Market) -> Result<Universe, Error> {
        assert!(market != Market::Jp, "Tokyo's company list is not updated");
        let path = raw.universe(market);
        let bytes = read_file(&path).map_err(|e| Error::new(format!("cannot read the company list: {e}"), path.display()))?;
        let mut loaded = Rows::default();
        if let Some(bytes) = &bytes {
            let value = PyJson::parse(bytes).map_err(|e| Error::new(format!("unreadable company list: {e}"), path.display()))?;
            let rows = value.as_list().ok_or_else(|| Error::new("the company list is not a list", path.display()))?;
            for row in rows {
                if let PyJson::Object(row) = row
                    && let Some(PyJson::Str(symbol)) = row.get("symbol")
                {
                    loaded.insert(symbol.clone(), row.clone());
                }
            }
        }
        Ok(Universe { market, path, bytes, rows: loaded.clone(), loaded })
    }

    /// Merges the update's listing; returns the companies it names that the
    /// loaded list did not, in symbol order. Every loaded row becomes
    /// `listed: false` in its place. A listed company's row then takes the
    /// listing's fields: in the US over its saved row, keeping a saved
    /// sector when the listing has none; in Hong Kong in place of it. New
    /// companies follow in listing order.
    pub fn apply(&mut self, listing: Listing) -> Vec<String> {
        assert_eq!(listing.market, self.market);
        let mut rows = Rows::default();
        for (symbol, row) in &self.loaded.rows {
            let mut row = row.clone();
            row.insert("listed", PyJson::from(false));
            rows.insert(symbol.clone(), row);
        }
        let mut new = Vec::new();
        for (symbol, row) in listing.rows.rows {
            if self.loaded.get(&symbol).is_none() {
                new.push(symbol.clone());
            }
            let row = match (self.market, rows.get(&symbol)) {
                (Market::Us, previous) => {
                    let mut merged = previous.cloned().unwrap_or_default();
                    for (key, value) in row.iter() {
                        merged.insert(key, value.clone());
                    }
                    let sector = row.get("sector").filter(|s| s.truthy());
                    let sector = sector.or(previous.and_then(|p| p.get("sector"))).cloned();
                    merged.insert("sector", sector.unwrap_or_else(|| PyJson::from("")));
                    merged
                }
                _ => row,
            };
            rows.insert(symbol, row);
        }
        self.rows = rows;
        new.sort();
        new
    }

    /// Replaces the file when its content changed, and says whether it did.
    /// US: when the rows differ from the loaded ones by Python's equality;
    /// Hong Kong: when the written bytes differ from the file's, as the old
    /// updater rewrote that list at each update.
    pub fn save(&mut self) -> Result<bool, Error> {
        let text = self.rows.text();
        let changed = match self.market {
            Market::Us => !self.rows.same(&self.loaded),
            _ => self.bytes.as_deref() != Some(text.as_bytes()),
        };
        if changed {
            replace(&self.path, text.as_bytes())?;
            self.bytes = Some(text.into_bytes());
            self.loaded = self.rows.clone();
        }
        Ok(changed)
    }

    /// A company's row.
    pub fn get(&self, symbol: &str) -> Option<&Object> {
        self.rows.get(symbol)
    }

    /// The companies and their rows, in list order.
    pub fn iter(&self) -> impl Iterator<Item = (&str, &Object)> {
        self.rows.rows.iter().map(|(symbol, row)| (symbol.as_str(), row))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn json(text: &str) -> PyJson {
        PyJson::parse(text.as_bytes()).unwrap()
    }

    #[test]
    fn us_common_stock_rules() {
        assert!(us_common_stock("BRK-B", "Berkshire Hathaway"));
        assert!(us_common_stock("A1", "Alpha"));
        assert!(!us_common_stock("BRK.B", "Berkshire"));
        assert!(!us_common_stock("ABCDEFG", "Long"));
        assert!(!us_common_stock("Abc", "Mixed case"));
        assert!(!us_common_stock("AB-CD", "Two letter class"));
        assert!(!us_common_stock("SPY", "SPDR S&P 500 ETF Trust"));
        assert!(us_exchange("NASDAQ Global Select") && !us_exchange("NYSE ARCA") && !us_exchange("OTC"));
    }

    #[test]
    fn a_repeated_symbol_keeps_its_first_place_and_last_row() {
        let mut listing = Listing::new(Market::Us);
        listing.screener("NYSE", true, &json(r#"[{"symbol": "B", "companyName": "Bee", "sector": "Energy"}, {"symbol": "A", "companyName": "Ay"}]"#)).unwrap();
        listing.screener("NASDAQ", true, &json(r#"[{"symbol": "B", "companyName": "Bee 2"}]"#)).unwrap();
        listing.delisted(&json(r#"[{"symbol": "A", "companyName": "Old Ay", "exchange": "NYSE"}, {"symbol": "C", "companyName": "Sea", "exchange": "AMEX"}, {"symbol": "D", "companyName": "Dee", "exchange": "OTC"}]"#)).unwrap();
        let names: Vec<_> = listing.rows.rows.iter().map(|(s, r)| (s.as_str(), r.get("name").unwrap().as_str().unwrap(), r.get("exchange").unwrap().as_str().unwrap())).collect();
        assert_eq!(names, [("B", "Bee 2", "NASDAQ"), ("A", "Ay", "NYSE"), ("C", "Sea", "AMEX")]);
    }
}
