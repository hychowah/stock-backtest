//! The trade dates of a run: the window and every trial's periods.

use market_data::{Day, Error, FIRST_DAY, MarketData};
use numbers::Random;
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};
use ts_rs::TS;

/// The run settings that set the trade dates, in one flat form: the keys
/// are the flags of `bt run` (`--every`, `--trials`, `--seed`, `--dates`),
/// the JSON of a request and a reply, and what a result file stores. Values
/// stay as given (days as ISO text, `YYYY-MM-DD`; an interval as `Nw` or
/// `Nm`); the server checks them all together against the market's data
/// when the run is added or changed, and names the key at fault as the
/// error's place. A schedule is one of:
/// - `every`: one trial that trades at every interval from the start;
/// - `every` and `trials` (at least 1), with an optional `seed`: that many
///   trials, each trading on one random session in every interval;
/// - `dates`: one trial that trades on these sessions, in increasing order.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, TS)]
#[serde(deny_unknown_fields)]
#[ts(export)]
pub struct Schedule {
    /// The first day of the window.
    pub start: String,
    /// The last day of the window, included.
    pub end: String,
    /// 1 to 104 weeks (`Nw`) or 1 to 24 months (`Nm`).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    #[ts(optional)]
    pub every: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    #[ts(optional)]
    pub trials: Option<u32>,
    /// The seed of random dates: the same seed on the same sessions gives
    /// the same dates. A missing seed is drawn when the run is added.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    #[ts(optional)]
    pub seed: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    #[ts(optional)]
    pub dates: Option<Vec<String>>,
}

impl Schedule {
    /// The schedule with a seed drawn when it has trials and no seed: the
    /// one place a seed is drawn, so a run and the record of what it ran
    /// hold the same seed.
    pub fn drawn(&self) -> Schedule {
        use std::hash::{BuildHasher, RandomState};
        let mut schedule = self.clone();
        if schedule.trials.is_some() && schedule.seed.is_none() {
            // The process's random hash keys, which the system seeds.
            schedule.seed = Some(RandomState::new().hash_one(std::time::SystemTime::now()) as u32);
        }
        schedule
    }
}

/// 1 to 104 weeks or 1 to 24 months.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Interval {
    Weeks(u32),
    Months(u32),
}

impl Interval {
    /// `Nw` or `Nm`.
    fn parse(text: &str) -> Result<Interval, Error> {
        let invalid = || Error::new(format!("{text:?} is not an interval: use N weeks (Nw) or N months (Nm), such as 13w or 3m"), "every");
        let count = |count: &str| count.parse::<u32>().map_err(|_| invalid());
        match (text.strip_suffix('w'), text.strip_suffix('m')) {
            (Some(weeks), _) => Ok(Interval::Weeks(count(weeks)?)),
            (_, Some(months)) => Ok(Interval::Months(count(months)?)),
            _ => Err(invalid()),
        }
    }
}

/// How a checked schedule chooses its trade dates.
#[derive(Clone, Copy)]
enum Dates<'a> {
    Every(Interval),
    Random { every: Interval, trials: u32, seed: u32 },
    Explicit(&'a [String]),
}

/// The trade dates of every trial of a run.
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
    /// interval.
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
    /// Checks the schedule against the market's sessions: first which keys
    /// it combines, then, in this order, the interval, the start and
    /// end, the trials, the window and each explicit date. An error names
    /// the key at fault in `place`. A schedule with trials and no seed is
    /// refused: [draw](Schedule::drawn) its seed first.
    pub fn new(data: &MarketData, schedule: &Schedule) -> Result<Plan, Error> {
        if schedule.dates.is_some() && (schedule.every.is_some() || schedule.trials.is_some()) {
            return Err(Error::new("dates cannot be combined with every or trials", "dates"));
        }
        if schedule.trials.is_some() && schedule.every.is_none() {
            return Err(Error::new("trials need every: a random trial trades once in every interval", "trials"));
        }
        if schedule.seed.is_some() && schedule.trials.is_none() {
            return Err(Error::new("a seed is only for random trials: give trials too", "seed"));
        }
        let dates = match (&schedule.every, &schedule.dates) {
            (Some(every), _) => {
                let every = Interval::parse(every)?;
                match (schedule.trials, schedule.seed) {
                    (Some(trials), Some(seed)) => Dates::Random { every, trials, seed },
                    (Some(_), None) => return Err(Error::new("a random schedule needs its seed drawn first", "seed")),
                    (None, _) => Dates::Every(every),
                }
            }
            (None, Some(dates)) => Dates::Explicit(dates),
            (None, None) => return Err(Error::new("choose a schedule: every, every with trials, or dates", "every")),
        };
        if let Dates::Every(every) | Dates::Random { every, .. } = dates {
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
        if let Dates::Random { trials: 0, .. } = dates {
            return Err(Error::new("choose at least 1 trial", "trials"));
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
            Interval::Months(count) => start.add_months((count * number) as i32).expect("a target at most one interval after the last session"),
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
        let (final_mark, trials) = match dates {
            Dates::Every(every) => {
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
            Dates::Random { every, trials, seed } => {
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

    /// Every entry day of the plan with its distinct exits, both in date
    /// order.
    pub fn exits_by_entry(&self) -> Vec<(Day, Vec<Day>)> {
        let mut days: BTreeMap<Day, BTreeSet<Day>> = BTreeMap::new();
        for period in self.trials.iter().flat_map(|t| &t.periods) {
            days.entry(period.entry).or_default().insert(period.exit);
        }
        days.into_iter().map(|(day, exits)| (day, exits.into_iter().collect())).collect()
    }
}

fn day(text: &str, place: &str) -> Result<Day, Error> {
    Day::parse(text).ok_or_else(|| Error::new(format!("not an ISO day: {text:?}"), place))
}

/// Contiguous periods from increasing entries; the last exits at `final_day`.
fn periods(entries: &[Day], final_day: Day) -> Vec<Period> {
    let exits = entries.iter().skip(1).copied().chain([final_day]);
    entries.iter().zip(exits).map(|(&entry, exit)| Period { entry, exit }).collect()
}
