//! The backtest engine: strategy files, selection, schedules, portfolio
//! results and the result file of a run.

mod schedule;

pub use schedule::{Dates, Interval, Period, Plan, Schedule, Trial};
