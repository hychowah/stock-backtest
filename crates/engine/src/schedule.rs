//! The trade dates of a run: the window and every trial's periods.

use market_data::{Day, Error, FIRST_DAY, MarketData};
use numbers::Random;
use serde::{Deserialize, Serialize};

/// The run settings that set the trade dates. Days are ISO text,
/// `YYYY-MM-DD`; [`Plan::new`] checks every setting against the data.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Schedule {
    /// The first day of the window.
    pub start: String,
    /// The last day of the window, included.
    pub end: String,
    #[serde(flatten)]
    pub dates: Dates,
}

/// How a schedule chooses its trade dates.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Dates {
    /// One trial that trades at every interval from the start.
    Every(Interval),
    /// `trials` trials (1 to 100), each trading on one random session in
    /// every interval from the start.
    Random { every: Interval, trials: u32, seed: u32 },
    /// One trial that trades on these sessions, in increasing order.
    #[serde(rename = "dates")]
    Explicit(Vec<String>),
}

/// 1 to 104 weeks or 1 to 24 months.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Interval {
    Weeks(u32),
    Months(u32),
}

/// The trade dates of every trial of a run, as the oracle plans them.
///
/// The window runs from the first session on or after the start to the
/// final mark, the last session on or before the end. Every trial starts at
/// the window's first session and ends at the final mark. Trials are in the
/// order of their numbers. A trial's periods are in date order; each period
/// exits on the next one's entry, so they do not overlap, and the last one
/// exits at the final mark. Every entry is a session before the final mark.
/// The same schedule on the same sessions gives the same plan.
#[derive(Debug)]
pub struct Plan {
    window: (Day, Day),
    final_mark: bool,
    trials: Vec<Trial>,
}

/// One trial of a [`Plan`].
#[derive(Debug)]
pub struct Trial {
    /// The first entry of a random or explicit schedule: the trial holds
    /// cash from the window's first session until then. `None` for a fixed
    /// interval, as in the oracle.
    pub first_trade: Option<Day>,
    /// The calendar days from the window's first session to the first trade;
    /// `None` for a fixed interval.
    pub cash_days: Option<i32>,
    pub periods: Vec<Period>,
}

/// A holding period: bought at the entry session, held until the exit.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Period {
    pub entry: Day,
    pub exit: Day,
}

impl Plan {
    /// Checks the schedule against the market's sessions, in the oracle's
    /// order: the interval, the start and end, the trials, the window, then
    /// each explicit date. An error names the setting at fault in `place`.
    pub fn new(data: &MarketData, schedule: &Schedule) -> Result<Plan, Error> {
        if let Dates::Every(every) | Dates::Random { every, .. } = schedule.dates {
            let (count, maximum) = match every {
                Interval::Weeks(count) => (count, 104),
                Interval::Months(count) => (count, 24),
            };
            if !(1..=maximum).contains(&count) {
                return Err(Error::new("choose 1 to 104 weeks or 1 to 24 months", "every"));
            }
        }
        let (start, end) = (day(&schedule.start, "start")?, day(&schedule.end, "end")?);
        if start < FIRST_DAY {
            return Err(Error::new(format!("the start must be on or after {FIRST_DAY}"), "start"));
        }
        if end <= start {
            return Err(Error::new("the end must be after the start", "end"));
        }
        if let Dates::Random { trials, .. } = schedule.dates
            && !(1..=100).contains(&trials)
        {
            return Err(Error::new("choose 1 to 100 trials", "trials"));
        }
        let sessions = data.sessions();
        if sessions.last().is_none_or(|&last| end > last) {
            let last = sessions.last().map_or("none".to_string(), Day::to_string);
            return Err(Error::new(format!("the end must be on or before the last session, {last}"), "end"));
        }
        let first = sessions.partition_point(|&d| d < start);
        let last = sessions.partition_point(|&d| d <= end).checked_sub(1).filter(|&last| last > first).ok_or_else(|| {
            Error::new(format!("the window from {start} to {end} holds fewer than two sessions"), "end")
        })?;
        let window = (sessions[first], sessions[last]);
        let final_day = window.1;
        let target = |every: Interval, number: u32| match every {
            Interval::Weeks(count) => Day(start.0 + 7 * (count * number) as i32),
            Interval::Months(count) => months_after(&schedule.start, count * number),
        };
        // The nominal blocks [left, right): each target derives from the
        // requested start, never from a rolled one, and the last block is
        // clipped at the final mark.
        let blocks = |every: Interval| {
            (0..).map(move |n| (target(every, n), target(every, n + 1).min(final_day))).take_while(|&(left, _)| left < final_day)
        };
        let at = |d: Day| sessions.partition_point(|&s| s < d);
        let traded = |entries: Vec<Day>| Trial {
            first_trade: Some(entries[0]),
            cash_days: Some(entries[0].0 - window.0.0),
            periods: periods(&entries, final_day),
        };
        let (final_mark, trials) = match &schedule.dates {
            &Dates::Every(every) => {
                let mut entries: Vec<Day> = Vec::new();
                for (left, _) in blocks(every) {
                    let entry = sessions[at(left)];
                    if entry < final_day && entries.last() != Some(&entry) {
                        entries.push(entry);
                    }
                }
                // The last period exits on a schedule when the first target
                // after the session before the final mark is not after it.
                let previous = sessions[last - 1];
                let next = (1..).map(|n| target(every, n)).find(|&t| t > previous).unwrap();
                let fixed = Trial { first_trade: None, cash_days: None, periods: periods(&entries, final_day) };
                (next > final_day, vec![fixed])
            }
            &Dates::Random { every, trials, seed } => {
                let populations: Vec<&[Day]> =
                    blocks(every).map(|(left, right)| &sessions[at(left)..at(right)]).filter(|p| !p.is_empty()).collect();
                let mut random = Random::new(seed);
                let trials = (0..trials).map(|_| traded(populations.iter().map(|p| p[random.choice(p.len())]).collect()));
                (true, trials.collect())
            }
            Dates::Explicit(dates) => {
                let mut entries: Vec<Day> = Vec::new();
                for text in dates {
                    let entry = day(text, "dates")?;
                    if entry < window.0 || entry >= final_day {
                        let message = format!("{entry} is outside the window: dates must be from {} and before {final_day}", window.0);
                        return Err(Error::new(message, "dates"));
                    }
                    data.check_session(entry).map_err(|message| Error::new(message, "dates"))?;
                    if let Some(&previous) = entries.last().filter(|&&previous| previous >= entry) {
                        return Err(Error::new(format!("{entry} is not after the date before it, {previous}"), "dates"));
                    }
                    entries.push(entry);
                }
                if entries.is_empty() {
                    return Err(Error::new("give at least one date", "dates"));
                }
                (true, vec![traded(entries)])
            }
        };
        Ok(Plan { window, final_mark, trials })
    }

    /// The window's first session and the final mark.
    pub fn window(&self) -> (Day, Day) {
        self.window
    }

    /// Whether the last period of every trial ends on a mark to date rather
    /// than on a scheduled exit: always for random and explicit dates; for a
    /// fixed interval, when no target rolls forward to the final mark. Its
    /// holdings that exit on schedule are then marked to date.
    pub fn final_mark(&self) -> bool {
        self.final_mark
    }

    pub fn trials(&self) -> &[Trial] {
        &self.trials
    }

    /// Every entry day of the plan, once, in date order.
    pub fn entry_days(&self) -> Vec<Day> {
        let mut days: Vec<Day> = self.trials.iter().flat_map(|t| t.periods.iter().map(|p| p.entry)).collect();
        days.sort_unstable();
        days.dedup();
        days
    }
}

fn day(text: &str, place: &str) -> Result<Day, Error> {
    Day::parse(text).ok_or_else(|| Error::new(format!("not an ISO day: {text:?}"), place))
}

/// The day `months` months after the ISO day `start`, on the same day of the
/// month or the month's last day when it is shorter.
fn months_after(start: &str, months: u32) -> Day {
    let number = |range: std::ops::Range<usize>| start[range].parse::<i32>().unwrap();
    let month = number(0..4) * 12 + number(5..7) - 1 + months as i32;
    let first = |m: i32| Day::parse(&format!("{:04}-{:02}-01", m / 12, m % 12 + 1)).expect("a month of years 1 to 9999");
    let (this, next) = (first(month), first(month + 1));
    Day(this.0 + number(8..10).min(next.0 - this.0) - 1)
}

/// Contiguous periods from increasing entries; the last exits at `final_day`.
fn periods(entries: &[Day], final_day: Day) -> Vec<Period> {
    let exits = entries.iter().skip(1).copied().chain([final_day]);
    entries.iter().zip(exits).map(|(&entry, exit)| Period { entry, exit }).collect()
}
