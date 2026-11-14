//! Market data: preparation of the raw provider cache into the prepared
//! store, and the read interface the engine uses ([`MarketData`]).
//!
//! Only this crate opens store files. The `data` commands live in
//! [`commands`]; the store layout and its publish rules in [`store`].

pub mod commands;
mod companies;
mod day;
mod error;
mod market;
mod prices;
mod raw;
mod reports;
mod series;
pub mod store;

pub use companies::{Companies, CompanyId};
pub use day::Day;
pub use error::Error;
pub use market::Market;

use commands::Home;
use store::{Generation, Manifest};

/// This program and its version, as manifests and exports record it.
const PROGRAM: &str = concat!("bt ", env!("CARGO_PKG_VERSION"));

/// One market's prepared data: the generation `current` named at open,
/// memory-mapped. It stays readable until dropped, even after a later
/// preparation publishes another. Values equal the oracle's; reads do not fail.
pub struct MarketData {
    generation: Generation,
}

impl MarketData {
    /// Opens the market's current generation. Fails, asking to run
    /// `bt data prepare`, when the market is not prepared or was prepared by a
    /// program with another store format.
    pub fn open(home: &Home, market: Market) -> Result<MarketData, Error> {
        Ok(MarketData { generation: Generation::open(home, market)? })
    }

    /// The generation's record: its number, as-of time and program.
    pub fn manifest(&self) -> &Manifest {
        self.generation.manifest()
    }

    /// The market's sessions, ascending: US the SPY days, Hong Kong and Tokyo
    /// the completed local sessions at the as-of time.
    pub fn sessions(&self) -> &[Day] {
        series::Series::open(&self.generation).sessions()
    }

    /// The market's companies, in symbol order.
    pub fn companies(&self) -> Companies<'_> {
        Companies::open(&self.generation)
    }
}
