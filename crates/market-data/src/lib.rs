//! Market data: preparation of the raw provider cache into the prepared
//! store, and the read interface the engine uses ([`MarketData`]).
//!
//! Only this crate opens store files. The `data` commands live in
//! [`commands`]; the store layout and its publish rules in the private `store` module.

mod annual;
pub mod builtins;
pub mod commands;
mod companies;
mod day;
mod error;
mod holding;
mod market;
mod prices;
mod raw;
mod reports;
mod screen;
mod series;
mod store;
mod valuation;

pub use companies::{Companies, CompanyId};
pub use day::Day;
pub use error::Error;
pub use holding::{Exit, ExitStatus, MissingExitPrice};
pub use market::Market;
pub use screen::{Candidate, Denial, Screen};
pub use store::{ColumnInfo, Manifest};

use commands::Home;
use prices::PriceColumns;
use screen::{Columns, DayScreen};
use series::Series;
use store::Generation;

/// This program and its version, as manifests and exports record it.
const PROGRAM: &str = concat!("bt ", env!("CARGO_PKG_VERSION"));

/// The first day a screen can have, 1996-01-01 (`rules.FIRST_DAY`).
pub const FIRST_DAY: Day = Day(9496);

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
        Series::open(&self.generation).sessions()
    }

    /// Whether `day` is one of [`sessions`](Self::sessions) from
    /// [`FIRST_DAY`]: a day that [`candidates`](Self::candidates) accepts.
    /// The error is the message for the user; it names the sessions just
    /// before and after `day` ("none" at either end).
    pub fn check_session(&self, day: Day) -> Result<(), String> {
        let sessions = self.sessions();
        let sessions = &sessions[sessions.partition_point(|&d| d < FIRST_DAY)..];
        let at = sessions.partition_point(|&d| d < day);
        if sessions.get(at) == Some(&day) {
            return Ok(());
        }
        let name = |d: Option<&Day>| d.map_or("none".to_string(), Day::to_string);
        Err(format!(
            "{day} is not a session from {FIRST_DAY}: the session before it is {}, the session after it {}",
            name(at.checked_sub(1).map(|i| &sessions[i])),
            name(sessions.get(at))
        ))
    }

    /// The market's companies, in symbol order.
    pub fn companies(&self) -> Companies<'_> {
        Companies::open(&self.generation)
    }

    /// The oracle's sheet of `day` (a session from 1996-01-01): the admitted
    /// companies in company order, with the US tie rank; numbers normalized
    /// as [`Candidate`] says.
    pub fn candidates(&self, day: Day, screen: Screen) -> Vec<Candidate> {
        self.screen(day, screen).1
    }

    /// One company on one day (a session from 1996-01-01): its candidate row,
    /// or the gate that refused it. It builds the whole day's screen, since
    /// the US tie rank needs every company: a caller that needs many
    /// companies of one day calls [`candidates`](Self::candidates).
    pub fn evaluate(&self, c: CompanyId, day: Day, screen: Screen) -> Result<Candidate, Denial> {
        DayScreen::new(&Columns::open(&self.generation), day, screen).decide(c)
    }

    /// The day's number of companies with a selected report, and its
    /// candidates: what [`candidates`](Self::candidates) gives, with the
    /// count the `screens` table needs.
    pub(crate) fn screen(&self, day: Day, screen: Screen) -> (usize, Vec<Candidate>) {
        let columns = Columns::open(&self.generation);
        let day_screen = DayScreen::new(&columns, day, screen);
        (day_screen.reported(), day_screen.candidates())
    }

    /// The SPY close of `day`, with its day: US the close of `day` itself;
    /// Hong Kong and Tokyo the last close before `day`, at most 7 days earlier.
    pub fn spy(&self, day: Day) -> Option<(Day, f64)> {
        Series::open(&self.generation).spy(day)
    }

    /// How company `c`, entered at `entry` (the candidate's entry day and
    /// price in US dollars), exits when held until `exit`: at the last close
    /// on or before `exit`, at most 10 days earlier; without one, at the
    /// last earlier close ([`ExitStatus::LastAvailable`]). The close is in US
    /// dollars at the FX of its own day. No close from the entry day through
    /// `exit`, or an exit close without FX, is [`MissingExitPrice`]. The entry
    /// day is before `exit`: a run selects only candidates that enter before it.
    pub fn exit(&self, c: CompanyId, entry: (Day, f64), exit: Day) -> Result<Exit, MissingExitPrice> {
        let (series, prices) = (Series::open(&self.generation), PriceColumns::open(&self.generation).company(c));
        holding::exit(&series, &prices, self.companies().quote(self.manifest().market, c), entry, exit)
    }

    /// The closes of company `c` that a holding's daily path reads: every
    /// valid close from `from` (its entry day) through `to` (its exit day),
    /// both included, in day order, each in US dollars at the FX of its own
    /// day. Hong Kong and Tokyo closes are those of local sessions only; a
    /// close without FX is left out, so the path keeps the previous value.
    pub fn usd_closes(&self, c: CompanyId, from: Day, to: Day) -> Vec<(Day, f64)> {
        let (series, prices) = (Series::open(&self.generation), PriceColumns::open(&self.generation).company(c));
        holding::usd_closes(&series, &prices, self.companies().quote(self.manifest().market, c), from, to)
    }

    /// The 3-month Treasury rate of `day` as a fraction (the yield / 100):
    /// the last one on or before `day` (US) or before it (Hong Kong, Tokyo).
    pub fn treasury(&self, day: Day) -> Option<f64> {
        Series::open(&self.generation).treasury(day)
    }
}
