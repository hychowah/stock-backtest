//! The backtest engine: strategy files and their formulas, selection,
//! schedules, portfolio results and the result file of a run.
//!
//! A strategy is read once ([`Strategy::read`], its formulas by
//! [`Formula::read`]); each screen day's candidates are read once, and a
//! formula is evaluated for the candidates that reach its step
//! ([`DayValues`]); [`select`] gives a strategy's picks of a day; and a
//! [`Plan`] holds the trade dates of a run. A run values every
//! strategy of a batch on one plan, with each trial's summary and the
//! statistics over the trials, and writes one SQLite result file per
//! strategy. The views (growth curves, sectors, contributions, exploration
//! and joined holdings) read a result file alone. [`commands`] holds the
//! commands that `bt` calls: `check` and `catalog` (what a strategy file
//! can write), `run`, `screen` (the picks of the latest session), `explore`
//! and the exports of result files. [`cross_section`] holds `export
//! cross-section`: every candidate of a schedule's entry days with the
//! file's variables and its next return.

pub mod commands;
pub mod cross_section;
mod evaluation;
pub mod formula;
pub mod names;
mod portfolio;
mod results;
mod run;
mod schedule;
pub mod selection;
mod statistics;
pub mod strategy;
mod values;
mod views;

pub use formula::Formula;
pub use market_data::Error;
pub use schedule::{Dates, Interval, Period, Plan, Schedule, Trial};
pub use selection::{Pick, select};
pub use strategy::{Source, Strategy};
pub use values::DayValues;
pub use views::Selection;
