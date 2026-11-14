//! The backtest engine: strategy files, selection, schedules, portfolio
//! results and the result file of a run.
//!
//! A strategy is read once ([`Strategy::read`]); each screen day's
//! candidates and their source values are read once ([`DayValues`]);
//! [`select`] gives a strategy's picks of a day; and a [`Plan`] holds the
//! trade dates of a run. A run values every strategy of a batch on one plan,
//! with each trial's summary and the statistics over the trials, and writes
//! one SQLite result file per strategy. [`commands`] holds the `run` and
//! `export tables` commands that `bt` calls.

pub mod commands;
pub mod names;
mod portfolio;
mod results;
mod run;
mod schedule;
pub mod selection;
mod statistics;
pub mod strategy;
mod values;

pub use market_data::Error;
pub use schedule::{Dates, Interval, Period, Plan, Schedule, Trial};
pub use selection::{Pick, select};
pub use strategy::{Source, Strategy};
pub use values::DayValues;
