//! The values a strategy's steps read on one screen day.

use crate::Error;
use crate::evaluation;
use crate::names::Field;
use crate::strategy::Source;
use market_data::{Candidate, Companies, Day, MarketData, Observer, Screen};

/// One screen day's candidates and each source's value per candidate. A
/// built-in reads its stored lane, and counts only when it is finite in
/// canonical units. A field reads the candidate. A formula is evaluated for
/// a candidate when a step asks for its value, so only for the candidates
/// that reach its step.
///
/// A `DayValues` holds no mutable state: it is `Sync`, and several
/// strategies can share one by reference across threads.
pub struct DayValues<'d> {
    observer: Observer<'d>,
    day: Day,
    companies: Companies<'d>,
    candidates: Vec<Candidate>,
}

impl<'d> DayValues<'d> {
    /// The candidates of `day` (a session) on `screen`.
    pub fn new(data: &'d MarketData, day: Day, screen: Screen) -> Self {
        DayValues { observer: data.observer(), day, companies: data.companies(), candidates: data.candidates(day, screen) }
    }

    /// The day's candidates, in company order; `of` takes a position in
    /// this list.
    pub fn candidates(&self) -> &[Candidate] {
        &self.candidates
    }

    /// The value of `source` for candidate `i`, in its stored units, or
    /// `None` when it is missing. A built-in is missing when its stored lane
    /// is absent or not finite in canonical units. Sector and Exchange are
    /// text and have no number. A formula's value is in its unit. Its errors
    /// stop a run, as the oracle's do: FUTURE_DATE, an `at` date after the
    /// day it is read on, and INVALID_DATE, a lookback before year 1. The
    /// place of either is the candidate's symbol and the formula's label
    /// (the variable's name or the formula's text): `ABC, Debt to EV`.
    pub fn of(&self, source: &Source, i: usize) -> Result<Option<f64>, Error> {
        let candidate = &self.candidates[i];
        Ok(match *source {
            Source::Builtin(index) => {
                candidate.values[index].filter(|&v| numbers::canonical(v, source.scale()).is_some())
            }
            Source::Field(Field::MarketCap) => Some(candidate.market_cap),
            Source::Field(Field::EnterpriseValue) => Some(candidate.enterprise_value),
            Source::Field(Field::Sector | Field::Exchange) => None,
            Source::Formula(ref formula) => evaluation::value(&self.observer, formula, candidate, self.day)
                .map_err(|e| e.within(format!("{}, {}", self.symbol(i), source.label())))?,
        })
    }

    /// Candidate `i`'s symbol.
    pub(crate) fn symbol(&self, i: usize) -> &'d str {
        self.companies.symbol(self.candidates[i].company)
    }

    /// Candidate `i`'s sector or exchange.
    pub(crate) fn text(&self, field: Field, i: usize) -> &'d str {
        let company = self.candidates[i].company;
        match field {
            Field::Sector => self.companies.sector(company),
            Field::Exchange => self.companies.exchange(company),
            Field::MarketCap | Field::EnterpriseValue => panic!("{field:?} is a number"),
        }
    }
}
