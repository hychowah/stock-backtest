//! Calendar days.

use std::fmt;

/// A calendar day, counted as days since 1970-01-01 (`Day(0)`), so the order
/// and differences of the numbers are those of the calendar. The years are
/// those of Python's `date`, 1 to 9999. The prepared store holds a day as its
/// `i32`, and a mapped day column reads as `&[Day]`.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
#[repr(transparent)]
pub struct Day(pub i32);

impl Day {
    /// The day of a calendar date, or `None` when no such date exists.
    pub(crate) fn from_ymd(year: i32, month: u32, day: u32) -> Option<Day> {
        if !(1..=9999).contains(&year) || !(1..=12).contains(&month) || day < 1 || day > days_in_month(year, month) {
            return None;
        }
        // Days from civil (H. Hinnant): the year starts on March 1, so the
        // leap day is the last day of the year.
        let y = if month <= 2 { year - 1 } else { year };
        let (era, yoe) = (y.div_euclid(400), y.rem_euclid(400));
        let m = if month > 2 { month - 3 } else { month + 9 } as i32;
        let doy = (153 * m + 2) / 5 + day as i32 - 1;
        let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
        Some(Day(era * 146_097 + doe - 719_468))
    }

    /// The day of the week, as Python's `date.weekday()`: Monday is 0.
    pub(crate) fn weekday(self) -> i32 {
        (self.0 + 3).rem_euclid(7)
    }

    /// Reads ISO text, exactly `YYYY-MM-DD`; `None` for any other text or an
    /// impossible date.
    pub fn parse(text: &str) -> Option<Day> {
        let b = text.as_bytes();
        let digits = |range: std::ops::Range<usize>| {
            b[range].iter().try_fold(0u32, |n, &c| c.is_ascii_digit().then(|| n * 10 + u32::from(c - b'0')))
        };
        if b.len() != 10 || b[4] != b'-' || b[7] != b'-' {
            return None;
        }
        Day::from_ymd(digits(0..4)? as i32, digits(5..7)?, digits(8..10)?)
    }

    /// The same month and day `years` earlier (later for a negative count),
    /// as the oracle's `metrics.anniversary`: Feb 29 becomes Feb 28 in a year
    /// without it. This is the only copy of that rule.
    pub fn anniversary(self, years: i32) -> Day {
        let (y, m, d) = self.ymd();
        let year = y - years;
        Day::from_ymd(year, m, d.min(days_in_month(year, m))).expect("anniversary outside years 1 to 9999")
    }

    /// The year, month and day.
    pub(crate) fn ymd(self) -> (i32, u32, u32) {
        // Civil from days (H. Hinnant), the inverse of `from_ymd`.
        let z = self.0 + 719_468;
        let (era, doe) = (z.div_euclid(146_097), z.rem_euclid(146_097));
        let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
        let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
        let mp = (5 * doy + 2) / 153;
        let day = (doy - (153 * mp + 2) / 5 + 1) as u32;
        let month = if mp < 10 { mp + 3 } else { mp - 9 } as u32;
        let year = yoe + era * 400 + i32::from(month <= 2);
        (year, month, day)
    }
}

/// ISO text, `YYYY-MM-DD`.
impl fmt::Display for Day {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let (y, m, d) = self.ymd();
        write!(f, "{y:04}-{m:02}-{d:02}")
    }
}

/// The number of days of a month.
pub(crate) fn days_in_month(year: i32, month: u32) -> u32 {
    match month {
        2 if year % 4 == 0 && (year % 100 != 0 || year % 400 == 0) => 29,
        2 => 28,
        4 | 6 | 9 | 11 => 30,
        _ => 31,
    }
}
