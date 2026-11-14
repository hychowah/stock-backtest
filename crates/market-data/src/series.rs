//! The market series: a market's sessions, the SPY closes and Treasury
//! yields that every market shares, and the FX fixings of Hong Kong and
//! Tokyo; with each market's rule for looking them up. The same lookups run
//! over the columns being prepared ([`SeriesData::view`]) and over a
//! published generation ([`Series::open`]).
//!
//! Columns, values `NaN` where absent and reasons as [`crate::raw::Reason`]
//! codes:
//! - `series.sessions`: US: the SPY days; foreign: the completed local
//!   sessions of the index calendar.
//! - `series.spy_day`, `series.spy`: the days with a valid SPY close.
//! - `series.treasury_day`, `series.month3`, `series.month3_reason`,
//!   `series.year10`, `series.year10_reason`: each saved Treasury day, in
//!   percent.
//! - Hong Kong and Tokyo: `series.fx_currency` (text), `series.fx_offsets`
//!   (`u64`, one more than currencies), `series.fx_day`, `series.fx_usd` (USD
//!   per unit) and `series.fx_reason`: every `fx/USD<currency>.json` file.

use crate::raw::{Json, Raw, Reason, State, observe, read_json, state_cells};
use crate::store::{Generation, GenerationWriter};
use crate::{Day, Error, Market};
use chrono::{DateTime, FixedOffset};
use serde_json::Value;
use std::ops::Range;
use tables::Cell;

/// One market's series, as columns in memory.
pub(crate) struct SeriesData {
    market: Market,
    sessions: Vec<Day>,
    spy_day: Vec<Day>,
    spy: Vec<f64>,
    treasury_day: Vec<Day>,
    month3: Vec<f64>,
    month3_reason: Vec<u8>,
    year10: Vec<f64>,
    year10_reason: Vec<u8>,
    fx_currency: Vec<String>,
    fx_offsets: Vec<u64>,
    fx_day: Vec<Day>,
    fx_usd: Vec<f64>,
    fx_reason: Vec<u8>,
}

/// Reads the market's series from `raw/`. An unreadable SPY or Treasury
/// file, or a SPY file without a valid close, stops preparation. A missing
/// or unreadable index calendar or FX file gives no rows.
pub(crate) fn read(raw: &Raw, market: Market, as_of: &DateTime<FixedOffset>) -> Result<SeriesData, Error> {
    let mut data = SeriesData {
        market,
        sessions: Vec::new(),
        spy_day: Vec::new(),
        spy: Vec::new(),
        treasury_day: Vec::new(),
        month3: Vec::new(),
        month3_reason: Vec::new(),
        year10: Vec::new(),
        year10_reason: Vec::new(),
        fx_currency: Vec::new(),
        fx_offsets: vec![0],
        fx_day: Vec::new(),
        fx_usd: Vec::new(),
        fx_reason: Vec::new(),
    };
    let spy = raw.spy();
    for (day, states) in observe(&required_rows(&spy)?, &["adjClose"], Some("USD")) {
        if let Ok(close) = states[0] {
            data.spy_day.push(day);
            data.spy.push(close);
        }
    }
    if data.spy_day.is_empty() {
        return Err(Error::new("the saved SPY calendar has no usable sessions: download it again", spy.display()));
    }
    for (day, states) in observe(&required_rows(&raw.treasury())?, &["month3", "year10"], Some("USD")) {
        data.treasury_day.push(day);
        push_state(&mut data.month3, &mut data.month3_reason, states[0]);
        push_state(&mut data.year10, &mut data.year10_reason, states[1]);
    }
    if market == Market::Us {
        data.sessions = data.spy_day.clone();
        return Ok(data);
    }
    for (day, states) in observe(&optional_rows(&raw.calendar(market))?, &["close"], None) {
        if states[0].is_ok() && market.completed_session(day, as_of) {
            data.sessions.push(day);
        }
    }
    for (currency, path) in raw.fx()? {
        for (day, states) in observe(&optional_rows(&path)?, &["close"], None) {
            // usd = 1/close; a close so small that 1/close is infinite is invalid.
            let state = states[0].map(|close| 1.0 / close).and_then(|usd| if usd.is_finite() { Ok(usd) } else { Err(Reason::Invalid) });
            data.fx_day.push(day);
            push_state(&mut data.fx_usd, &mut data.fx_reason, state);
        }
        data.fx_currency.push(currency);
        data.fx_offsets.push(data.fx_day.len() as u64);
    }
    Ok(data)
}

fn push_state(values: &mut Vec<f64>, reasons: &mut Vec<u8>, state: State) {
    values.push(state.unwrap_or(f64::NAN));
    reasons.push(Reason::code(state));
}

/// The dated rows of a SPY or Treasury file: none when it is missing. A file
/// that is not JSON, or not a list, stops preparation.
fn required_rows(path: &std::path::Path) -> Result<Vec<Value>, Error> {
    match read_json(path)? {
        Json::Missing => Ok(Vec::new()),
        Json::Value(Value::Array(rows)) => Ok(rows),
        _ => Err(Error::new("the saved file is unreadable: download it again from the data panel", path.display())),
    }
}

/// The dated rows of an index calendar or FX file: none when it is missing,
/// not JSON or not a list.
fn optional_rows(path: &std::path::Path) -> Result<Vec<Value>, Error> {
    Ok(match read_json(path)? {
        Json::Value(Value::Array(rows)) => rows,
        _ => Vec::new(),
    })
}

impl SeriesData {
    /// The lookups over these columns.
    pub(crate) fn view(&self) -> Series<'_> {
        Series {
            market: self.market,
            sessions: &self.sessions,
            spy_day: &self.spy_day,
            spy: &self.spy,
            treasury_day: &self.treasury_day,
            month3: &self.month3,
            month3_reason: &self.month3_reason,
            year10: &self.year10,
            year10_reason: &self.year10_reason,
            fx: fx_ranges(self.fx_currency.iter().map(String::as_str), &self.fx_offsets),
            fx_day: &self.fx_day,
            fx_usd: &self.fx_usd,
            fx_reason: &self.fx_reason,
        }
    }

    pub(crate) fn write(&self, out: &mut GenerationWriter<'_>) -> Result<(), Error> {
        out.column("series.sessions", &self.sessions)?;
        out.column("series.spy_day", &self.spy_day)?;
        out.column("series.spy", &self.spy)?;
        out.column("series.treasury_day", &self.treasury_day)?;
        out.column("series.month3", &self.month3)?;
        out.column("series.month3_reason", &self.month3_reason)?;
        out.column("series.year10", &self.year10)?;
        out.column("series.year10_reason", &self.year10_reason)?;
        if self.market != Market::Us {
            out.text("series.fx_currency", &self.fx_currency)?;
            out.column("series.fx_offsets", &self.fx_offsets)?;
            out.column("series.fx_day", &self.fx_day)?;
            out.column("series.fx_usd", &self.fx_usd)?;
            out.column("series.fx_reason", &self.fx_reason)?;
        }
        Ok(())
    }
}

fn fx_ranges<'a>(currencies: impl Iterator<Item = &'a str>, offsets: &[u64]) -> Vec<(&'a str, Range<usize>)> {
    currencies.zip(offsets.windows(2)).map(|(c, w)| (c, w[0] as usize..w[1] as usize)).collect()
}

/// One market's series and its lookup rules.
pub(crate) struct Series<'a> {
    market: Market,
    sessions: &'a [Day],
    spy_day: &'a [Day],
    spy: &'a [f64],
    treasury_day: &'a [Day],
    month3: &'a [f64],
    month3_reason: &'a [u8],
    year10: &'a [f64],
    year10_reason: &'a [u8],
    /// Each currency's rows in the `fx_` columns.
    fx: Vec<(&'a str, Range<usize>)>,
    fx_day: &'a [Day],
    fx_usd: &'a [f64],
    fx_reason: &'a [u8],
}

impl<'a> Series<'a> {
    pub(crate) fn open(generation: &'a Generation) -> Series<'a> {
        let market = generation.manifest().market;
        let (fx, fx_day, fx_usd, fx_reason) = if market == Market::Us {
            (Vec::new(), &[][..], &[][..], &[][..])
        } else {
            let names = generation.text("series.fx_currency");
            let offsets = generation.column::<u64>("series.fx_offsets");
            (
                fx_ranges((0..names.len()).map(|i| names.get(i)), offsets),
                generation.column("series.fx_day"),
                generation.column("series.fx_usd"),
                generation.column("series.fx_reason"),
            )
        };
        Series {
            market,
            sessions: generation.column("series.sessions"),
            spy_day: generation.column("series.spy_day"),
            spy: generation.column("series.spy"),
            treasury_day: generation.column("series.treasury_day"),
            month3: generation.column("series.month3"),
            month3_reason: generation.column("series.month3_reason"),
            year10: generation.column("series.year10"),
            year10_reason: generation.column("series.year10_reason"),
            fx,
            fx_day,
            fx_usd,
            fx_reason,
        }
    }

    /// The market's sessions, ascending.
    pub(crate) fn sessions(&self) -> &'a [Day] {
        self.sessions
    }

    /// The SPY close a book on `day` uses, with its day: US: the close of
    /// `day` itself; foreign: the last close strictly before `day`, at most 7
    /// days earlier.
    #[expect(dead_code, reason = "the valuation fold and the screen are its first callers")]
    pub(crate) fn spy(&self, day: Day) -> Option<(Day, f64)> {
        let at = if self.market == Market::Us {
            self.spy_day.binary_search(&day).ok()?
        } else {
            self.spy_day.partition_point(|&d| d < day).checked_sub(1).filter(|&i| self.spy_day[i].0 >= day.0 - 7)?
        };
        Some((self.spy_day[at], self.spy[at]))
    }

    /// The 3-month Treasury rate of `day` as a fraction (the yield / 100): the
    /// last valid yield on or before `day` (US) or strictly before it
    /// (foreign), however old.
    #[expect(dead_code, reason = "the screen is its first caller")]
    pub(crate) fn treasury(&self, day: Day) -> Option<f64> {
        let end = self.treasury_day.partition_point(|&d| if self.market == Market::Us { d <= day } else { d < day });
        (0..end).rev().find(|&i| self.month3_reason[i] == 0).map(|i| self.month3[i] / 100.0)
    }

    /// The USD value of one unit of `currency` on `day`, with the fixing's
    /// day: the last valid fixing strictly before `day`, at most 7 days old.
    /// USD is 1 on `day`; a currency without a file, or a gap, is `None`.
    #[expect(dead_code, reason = "the foreign reports and the valuation fold are its first callers")]
    pub(crate) fn fx(&self, currency: &str, day: Day) -> Option<(Day, f64)> {
        if currency == "USD" {
            return Some((day, 1.0));
        }
        let (_, range) = self.fx.iter().find(|(c, _)| *c == currency)?;
        let days = &self.fx_day[range.clone()];
        let end = days.partition_point(|&d| d < day);
        let at = (0..end).rev().find(|&i| self.fx_reason[range.start + i] == 0)?;
        (day.0 - days[at].0 <= 7).then(|| (days[at], self.fx_usd[range.start + at]))
    }

    /// Writes the `sessions` table (key `day`).
    pub(crate) fn export_sessions(&self, out: &mut tables::Writer) -> Result<u64, String> {
        let mut table = out.table("sessions", &["day"])?;
        for day in self.sessions {
            table.row(&[("day", Cell::Text(&day.to_string()))])?;
        }
        table.finish()
    }

    /// Writes the `market_days` table (key `day`): each day with a SPY close
    /// or a Treasury row.
    pub(crate) fn export_market_days(&self, out: &mut tables::Writer) -> Result<u64, String> {
        let mut table = out.table("market_days", &["day"])?;
        let (mut s, mut t) = (0, 0);
        while s < self.spy_day.len() || t < self.treasury_day.len() {
            let day = match (self.spy_day.get(s), self.treasury_day.get(t)) {
                (Some(&a), Some(&b)) => a.min(b),
                (Some(&a), None) => a,
                (None, Some(&b)) => b,
                (None, None) => unreachable!(),
            };
            let spy = (self.spy_day.get(s) == Some(&day)).then(|| self.spy[s]);
            let treasury = (self.treasury_day.get(t) == Some(&day)).then_some(t);
            let field = |values: &[f64], reasons: &[u8]| match treasury {
                Some(i) => state_cells(values[i], reasons[i]),
                None => (Cell::Null, Cell::Null),
            };
            let (month3, month3_reason) = field(self.month3, self.month3_reason);
            let (year10, year10_reason) = field(self.year10, self.year10_reason);
            table.row(&[
                ("day", Cell::Text(&day.to_string())),
                ("spy", spy.map_or(Cell::Null, Cell::Number)),
                ("month3", month3),
                ("month3_reason", month3_reason),
                ("year10", year10),
                ("year10_reason", year10_reason),
            ])?;
            s += usize::from(spy.is_some());
            t += usize::from(treasury.is_some());
        }
        table.finish()
    }

    /// Writes the `fx_days` table (key `currency`, `day`).
    pub(crate) fn export_fx_days(&self, out: &mut tables::Writer) -> Result<u64, String> {
        let mut table = out.table("fx_days", &["currency", "day"])?;
        for (currency, range) in &self.fx {
            for i in range.clone() {
                let (usd, reason) = state_cells(self.fx_usd[i], self.fx_reason[i]);
                table.row(&[
                    ("currency", Cell::Text(currency)),
                    ("day", Cell::Text(&self.fx_day[i].to_string())),
                    ("usd", usd),
                    ("reason", reason),
                ])?;
            }
        }
        table.finish()
    }
}
