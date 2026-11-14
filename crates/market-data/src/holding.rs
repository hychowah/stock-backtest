//! A holding's prices after its entry: its exit (`books.close`) and the
//! closes its daily path reads (`curves.holding`). Each close is converted to
//! US dollars at the FX of its own day ([`convert`]).

use crate::prices::{Direction, Prices};
use crate::reports::convert;
use crate::series::Series;
use crate::Day;

/// How many days before the exit day a scheduled exit's close may be.
const EXIT_SLACK: i32 = 10;

/// How a holding exits.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Exit {
    /// The day of the exit close: on or before the exit day, and on or after
    /// the entry day.
    pub day: Day,
    /// The exit close in US dollars / the entry price − 1.
    pub return_value: f64,
    pub status: ExitStatus,
}

/// Which close a holding exits at.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ExitStatus {
    /// The last close on or before the exit day, at most 10 days earlier.
    Scheduled,
    /// No close in those 10 days: the last earlier one, as a stopped stock
    /// keeps its last price.
    LastAvailable,
}

/// A holding has no close from its entry day through its exit day, or the
/// last one has no FX at its day. The oracle stops the run ("A selected sheet
/// row has no valid exit: MISSING_EXIT_PRICE").
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct MissingExitPrice;

/// The exit of a holding bought at `entry` (day, US-dollar price) and held
/// until `exit`, a later day; `quote` is the currency of `prices`.
pub(crate) fn exit(series: &Series<'_>, prices: &Prices<'_>, quote: &str, entry: (Day, f64), exit: Day) -> Result<Exit, MissingExitPrice> {
    let usd = |slack| {
        let (day, close) = prices.price(exit, Direction::OnOrBefore, slack)?;
        Some((day, convert(series, close, quote, day)?))
    };
    let (end, status) = match usd(Some(EXIT_SLACK)) {
        Some(end) => (end, ExitStatus::Scheduled),
        None => (usd(None).ok_or(MissingExitPrice)?, ExitStatus::LastAvailable),
    };
    if end.0 < entry.0 {
        return Err(MissingExitPrice);
    }
    Ok(Exit { day: end.0, return_value: end.1 / entry.1 - 1.0, status })
}

/// The closes from `from` through `to`, each in US dollars at its day's FX;
/// a close without FX is left out.
pub(crate) fn usd_closes(series: &Series<'_>, prices: &Prices<'_>, quote: &str, from: Day, to: Day) -> Vec<(Day, f64)> {
    prices
        .closes(Some(from))
        .take_while(|&(day, _)| day <= to)
        .filter_map(|(day, close)| Some((day, convert(series, close, quote, day)?)))
        .collect()
}
