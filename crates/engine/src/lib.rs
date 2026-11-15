//! The backtest engine: strategy files and their formulas, selection,
//! schedules, portfolio results and the result file of a run.
//!
//! A strategy is read once from its text ([`Strategy::parse`], its formulas
//! by [`Formula::read`]); each screen day's candidates are read once, and a
//! formula is evaluated for the candidates that reach its step
//! ([`DayValues`]); [`select`] gives a strategy's picks of a day; and a
//! [`Plan`] holds the trade dates of a [`Schedule`]. A run values every
//! strategy of a batch on one plan, with each trial's summary and the
//! statistics over the trials, and writes one SQLite result file per
//! strategy, where its caller chooses. [`results::ResultFile`] reads a
//! result file's rows back, and [`views`] (statistics, growth curves,
//! sectors, contributions, exploration and joined holdings) derive from
//! them alone; each table and view has one row type, which the exports, the
//! HTTP replies and the website's types share. [`commands`] holds the
//! commands that `bt` and other callers call: `check` and `catalog` (what a
//! strategy file can write), `run` (with `check_run`, the check of its
//! inputs against the data), `screen` (the picks of the latest session),
//! `explore` and the exports of result files.
//! [`cross_section`] holds `export cross-section`: every candidate of a
//! schedule's entry days with the file's variables and its next return.

pub mod commands;
pub mod cross_section;
mod evaluation;
pub mod formula;
pub mod names;
mod portfolio;
pub mod results;
mod run;
mod schedule;
pub mod selection;
mod statistics;
pub mod strategy;
mod values;
pub mod views;

pub use formula::{Fault, Formula, Picture, Suggestion};
pub use market_data::Error;
pub use schedule::{Period, Plan, Schedule, Trial};
pub use selection::{Pick, select};
pub use strategy::{Source, Strategy};
pub use values::DayValues;
