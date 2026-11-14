//! Company prices: the dividend-adjusted close and the volume of each saved
//! day, or the reason it has none, and the lookups that books and the
//! valuation fold use. The same lookups run over one company's rows being
//! prepared ([`PriceRows::view`]) and over a published generation
//! ([`PriceColumns::company`]).
//!
//! Preparation applies the rules once. A close must be positive and in the
//! company's currency, a volume not negative ([`crate::raw::observe`]). A
//! series in which one close is at least 8 times, or at most 1/8 of, both
//! neighbouring closes mixes two price scales, so every close of it becomes
//! `INCONSISTENT_SERIES`; the test runs over all saved days. A foreign series
//! then keeps its local sessions only, so no reader filters them.
//!
//! Columns: `prices.offsets` (`u64`, one more than companies; company i's
//! rows are `offsets[i]..offsets[i + 1]`), `prices.day`, `prices.close`,
//! `prices.close_reason`, `prices.volume` and `prices.volume_reason`; values
//! `NaN` where absent and reasons as [`Reason`] codes.

use crate::companies::{Companies, CompanyId};
use crate::raw::{Json, Raw, Reason, read_json, state_cells};
use crate::store::{Generation, GenerationWriter};
use crate::{Day, Error};
use serde_json::Value;
use tables::Cell;

/// A close at least this many times, or at most one over this many times,
/// both neighbouring closes is an isolated spike.
const SPIKE: f64 = 8.0;

/// One company's saved price days, as columns in memory.
pub(crate) struct PriceRows {
    day: Vec<Day>,
    close: Vec<f64>,
    close_reason: Vec<u8>,
    volume: Vec<f64>,
    volume_reason: Vec<u8>,
}

/// Reads a company's price file (`facts.stock`); `None` when it has none.
/// `currency` is the quote currency each close must have. `sessions`, for a
/// foreign company, are the local sessions the rows keep. A file that is not
/// JSON, or not an object with a `div` list, stops preparation.
pub(crate) fn read(raw: &Raw, symbol: &str, currency: &str, sessions: Option<&[Day]>) -> Result<Option<PriceRows>, Error> {
    let path = raw.prices(symbol);
    let unreadable = || Error::new("the saved price file is unreadable: download it again from the data panel", path.display());
    let rows = match read_json(&path)? {
        Json::Missing => return Ok(None),
        Json::Value(Value::Object(mut payload)) => match payload.remove("div") {
            Some(Value::Array(rows)) => rows,
            _ => return Err(unreadable()),
        },
        _ => return Err(unreadable()),
    };
    let mut dated: Vec<_> = crate::raw::observe(&rows, &["adjClose", "volume"], Some(currency)).into_iter().collect();
    let closes: Vec<usize> = (0..dated.len()).filter(|&i| dated[i].1[0].is_ok()).collect();
    let spiked = closes.windows(3).any(|w| {
        let [before, middle, after] = [w[0], w[1], w[2]].map(|i| dated[i].1[0].unwrap());
        let (up, down) = (middle / before, middle / after);
        up.min(down) >= SPIKE || up.max(down) <= 1.0 / SPIKE
    });
    if spiked {
        for &i in &closes {
            dated[i].1[0] = Err(Reason::InconsistentSeries);
        }
    }
    let mut out = PriceRows { day: Vec::new(), close: Vec::new(), close_reason: Vec::new(), volume: Vec::new(), volume_reason: Vec::new() };
    for (day, states) in dated {
        if sessions.is_some_and(|sessions| sessions.binary_search(&day).is_err()) {
            continue;
        }
        out.day.push(day);
        out.close.push(states[0].unwrap_or(f64::NAN));
        out.close_reason.push(Reason::code(states[0]));
        out.volume.push(states[1].unwrap_or(f64::NAN));
        out.volume_reason.push(Reason::code(states[1]));
    }
    Ok(Some(out))
}

impl PriceRows {
    /// The lookups over these rows.
    pub(crate) fn view(&self) -> Prices<'_> {
        Prices {
            day: &self.day,
            close: &self.close,
            close_reason: &self.close_reason,
            volume: &self.volume,
            volume_reason: &self.volume_reason,
        }
    }
}

/// Writes the price columns of every company, in [`CompanyId`] order; `None`
/// for a company without rows.
pub(crate) fn write(out: &mut GenerationWriter<'_>, rows: &[Option<&PriceRows>]) -> Result<(), Error> {
    let mut offsets = vec![0u64];
    offsets.extend(rows.iter().scan(0u64, |end, r| {
        *end += r.map_or(0, |r| r.day.len() as u64);
        Some(*end)
    }));
    out.column("prices.offsets", &offsets)?;
    out.column("prices.day", &rows.iter().flatten().flat_map(|r| r.day.iter().copied()).collect::<Vec<_>>())?;
    out.column("prices.close", &rows.iter().flatten().flat_map(|r| r.close.iter().copied()).collect::<Vec<_>>())?;
    out.column("prices.close_reason", &rows.iter().flatten().flat_map(|r| r.close_reason.iter().copied()).collect::<Vec<_>>())?;
    out.column("prices.volume", &rows.iter().flatten().flat_map(|r| r.volume.iter().copied()).collect::<Vec<_>>())?;
    out.column("prices.volume_reason", &rows.iter().flatten().flat_map(|r| r.volume_reason.iter().copied()).collect::<Vec<_>>())
}

/// The price columns of a published generation.
pub(crate) struct PriceColumns<'a> {
    offsets: &'a [u64],
    day: &'a [Day],
    close: &'a [f64],
    close_reason: &'a [u8],
    volume: &'a [f64],
    volume_reason: &'a [u8],
}

impl<'a> PriceColumns<'a> {
    pub(crate) fn open(generation: &'a Generation) -> PriceColumns<'a> {
        PriceColumns {
            offsets: generation.column("prices.offsets"),
            day: generation.column("prices.day"),
            close: generation.column("prices.close"),
            close_reason: generation.column("prices.close_reason"),
            volume: generation.column("prices.volume"),
            volume_reason: generation.column("prices.volume_reason"),
        }
    }

    /// One company's prices.
    pub(crate) fn company(&self, c: CompanyId) -> Prices<'a> {
        let rows = self.offsets[c.index()] as usize..self.offsets[c.index() + 1] as usize;
        Prices {
            day: &self.day[rows.clone()],
            close: &self.close[rows.clone()],
            close_reason: &self.close_reason[rows.clone()],
            volume: &self.volume[rows.clone()],
            volume_reason: &self.volume_reason[rows],
        }
    }

    /// Writes the `stock_days` table (key `symbol`, `day`).
    pub(crate) fn export(&self, companies: &Companies<'_>, out: &mut tables::Writer) -> Result<u64, String> {
        let mut table = out.table("stock_days", &["symbol", "day"])?;
        for c in companies.ids() {
            let p = self.company(c);
            for i in 0..p.day.len() {
                let (adjusted, adjusted_reason) = state_cells(p.close[i], p.close_reason[i]);
                let (volume, volume_reason) = state_cells(p.volume[i], p.volume_reason[i]);
                table.row(&[
                    ("symbol", Cell::Text(companies.symbol(c))),
                    ("day", Cell::Text(&p.day[i].to_string())),
                    ("adjusted", adjusted),
                    ("adjusted_reason", adjusted_reason),
                    ("volume", volume),
                    ("volume_reason", volume_reason),
                ])?;
            }
        }
        table.finish()
    }
}

/// Which way [`Prices::price`] looks from its day.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum Direction {
    /// The last close on or before the day.
    OnOrBefore,
    /// The first close on or after the day.
    OnOrAfter,
}

/// One company's prices: its saved days in order, with their states.
#[derive(Clone, Copy)]
pub(crate) struct Prices<'a> {
    day: &'a [Day],
    close: &'a [f64],
    close_reason: &'a [u8],
    volume: &'a [f64],
    volume_reason: &'a [u8],
}

impl<'a> Prices<'a> {
    /// The valid close nearest to `day` in `direction` (`day` itself
    /// included), with its day; `None` when there is none, or when it lies
    /// more than `slack` days from `day`.
    pub(crate) fn price(&self, day: Day, direction: Direction, slack: Option<i32>) -> Option<(Day, f64)> {
        let valid = |&i: &usize| self.close_reason[i] == 0;
        let found = match direction {
            Direction::OnOrBefore => (0..self.day.partition_point(|&d| d <= day)).rev().find(valid),
            Direction::OnOrAfter => (self.day.partition_point(|&d| d < day)..self.day.len()).find(valid),
        }?;
        let found = (self.day[found], self.close[found]);
        slack.is_none_or(|slack| (found.0.0 - day.0).abs() <= slack).then_some(found)
    }

    /// The valid closes on or after `start` (all when `None`), in day order:
    /// the closes [`price`](Self::price) reads.
    pub(crate) fn closes(&self, start: Option<Day>) -> impl Iterator<Item = (Day, f64)> + 'a {
        let Prices { day, close, close_reason, .. } = *self;
        let first = start.map_or(0, |start| day.partition_point(|&d| d < start));
        (first..day.len()).filter(move |&i| close_reason[i] == 0).map(move |i| (day[i], close[i]))
    }

    /// The valid volumes from `start` through `end`, in day order.
    pub(crate) fn volumes(&self, start: Day, end: Day) -> impl Iterator<Item = f64> + 'a {
        let Prices { day, volume, volume_reason, .. } = *self;
        let range = day.partition_point(|&d| d < start)..day.partition_point(|&d| d <= end);
        range.filter(move |&i| volume_reason[i] == 0).map(move |i| volume[i])
    }
}
