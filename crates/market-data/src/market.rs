//! The markets: which saved listings each admits, its currency, which index
//! days are completed local sessions at an as-of time, and when a report
//! becomes known.

use crate::day::days_in_month;
use crate::{Day, Error};
use chrono::{DateTime, Datelike, FixedOffset, TimeDelta, Timelike};
use serde::{Deserialize, Serialize};
use std::str::FromStr;

/// A stock market whose data the program prepares and reads.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Market {
    Us,
    Hk,
    Jp,
}

impl Market {
    /// Every market, in the order commands report them.
    pub const ALL: [Market; 3] = [Market::Us, Market::Hk, Market::Jp];

    /// The market's id: `us`, `hk` or `jp`. Folder names and replies use it.
    pub fn id(self) -> &'static str {
        match self {
            Market::Us => "us",
            Market::Hk => "hk",
            Market::Jp => "jp",
        }
    }

    /// The currency of a listing whose saved row names none.
    pub(crate) fn currency(self) -> &'static str {
        match self {
            Market::Us => "USD",
            Market::Hk => "HKD",
            Market::Jp => "JPY",
        }
    }

    /// Whether preparation keeps a saved listing (`market.common_stock` of
    /// symbol and name). Hong Kong: `[0-35-9]ddd.HK`, which leaves out the 4xxx
    /// lines and the five-digit RMB counters; Tokyo: `dddd.T` or `dddL.T`; and
    /// no ` ETF `, ` FUND ` or ` ETN ` word in the name. The saved US list is
    /// kept as saved: its rules run when the list is downloaded.
    pub(crate) fn admits(self, symbol: &str, name: &str) -> bool {
        let b = symbol.as_bytes();
        let digits = |range: std::ops::Range<usize>| b[range].iter().all(u8::is_ascii_digit);
        let form = match self {
            Market::Us => return true,
            Market::Hk => b.len() == 7 && b[0] != b'4' && digits(0..4) && symbol.ends_with(".HK"),
            Market::Jp => b.len() == 6 && digits(0..3) && (b[3].is_ascii_digit() || b[3].is_ascii_uppercase()) && symbol.ends_with(".T"),
        };
        let words = format!(" {} ", name.to_uppercase());
        form && ![" ETF ", " FUND ", " ETN "].iter().any(|word| words.contains(word))
    }

    /// Whether an index row of `day` names a completed local session at
    /// `as_of` (`market.completed_session`, with the as-of time as the
    /// clock): a weekday that is not a holiday the index wrongly lists (Hong
    /// Kong 1 January; Tokyo 1 to 3 January and 31 December), before the local
    /// date of `as_of`, or on it once the close has passed (Hong Kong 16:00 at
    /// UTC+8, Tokyo 15:30 at UTC+9). Foreign markets only.
    pub(crate) fn completed_session(self, day: Day, as_of: &DateTime<FixedOffset>) -> bool {
        let (_, month, date) = day.ymd();
        let holiday = match self {
            Market::Hk => month == 1 && date == 1,
            Market::Jp => (month == 1 && date <= 3) || (month == 12 && date == 31),
            Market::Us => unreachable!("US sessions are the SPY days"),
        };
        if day.weekday() > 4 || holiday {
            return false;
        }
        let (offset, closing) = if self == Market::Hk { (8, (16, 0)) } else { (9, (15, 30)) };
        let local = as_of.naive_utc() + TimeDelta::hours(offset);
        let today = Day::from_ymd(local.year(), local.month(), local.day()).expect("an as-of date in years 1 to 9999");
        day < today || (day == today && (local.hour(), local.minute()) >= closing)
    }

    /// When an annual statement of fiscal date `fiscal` becomes known, and
    /// why (`market.available`). US: 90 days after the fiscal date, whatever
    /// the publication date. Hong Kong and Tokyo: `publication`, the
    /// statement's one publication date, when it is later than the fiscal
    /// date; otherwise 4 (Hong Kong) or 3 (Tokyo) months after the fiscal
    /// date, on the same day of the month or the month's last day.
    pub(crate) fn available(self, fiscal: Day, publication: Option<Day>) -> (Day, Basis) {
        let months = match self {
            Market::Us => return (Day(fiscal.0 + 90), Basis::FiscalPlus90),
            Market::Hk => 4,
            Market::Jp => 3,
        };
        if let Some(published) = publication.filter(|&p| p > fiscal) {
            return (published, Basis::PublicationDate);
        }
        let (year, month, day) = fiscal.ymd();
        let absolute = year * 12 + month as i32 - 1 + months;
        let (year, month) = (absolute.div_euclid(12), absolute.rem_euclid(12) as u32 + 1);
        let known = Day::from_ymd(year, month, day.min(days_in_month(year, month))).expect("a known date in years 1 to 9999");
        (known, Basis::FiscalPlusMonths)
    }
}

/// Why a statement is known on its known date ([`Market::available`]). The
/// prepared store holds the code.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
#[repr(u8)]
pub(crate) enum Basis {
    FiscalPlus90 = 0,
    PublicationDate = 1,
    FiscalPlusMonths = 2,
}

impl Basis {
    /// The basis of a stored code.
    pub(crate) fn from_code(code: u8) -> Basis {
        match code {
            0 => Basis::FiscalPlus90,
            1 => Basis::PublicationDate,
            2 => Basis::FiscalPlusMonths,
            _ => panic!("unknown basis code {code}"),
        }
    }

    /// The oracle's text.
    pub(crate) fn text(self) -> &'static str {
        match self {
            Basis::FiscalPlus90 => "fiscal-plus-90",
            Basis::PublicationDate => "publication-date",
            Basis::FiscalPlusMonths => "fiscal-plus-months",
        }
    }
}

/// Reads a market id; the error names the input `market`.
impl FromStr for Market {
    type Err = Error;

    fn from_str(text: &str) -> Result<Market, Error> {
        Market::ALL
            .into_iter()
            .find(|m| m.id() == text)
            .ok_or_else(|| Error::new(format!("unknown market {text:?}: use us, hk or jp"), "market"))
    }
}
