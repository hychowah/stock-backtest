//! The values a strategy's steps read on one screen day.

use crate::Error;
use crate::names::Field;
use crate::strategy::Source;
use market_data::{Candidate, Companies, Day, MarketData, Screen};

/// One screen day's candidates and each source's value per candidate. A
/// built-in reads its stored lane, and counts only when it is finite in
/// canonical units. A field reads the candidate.
///
/// Both are read from the candidates, so a `DayValues` holds no mutable
/// state: it is `Sync`, and several strategies can share one by reference
/// across threads.
pub struct DayValues<'d> {
    companies: Companies<'d>,
    candidates: Vec<Candidate>,
}

impl<'d> DayValues<'d> {
    /// The candidates of `day` (a session) on `screen`.
    pub fn new(data: &'d MarketData, day: Day, screen: Screen) -> Self {
        DayValues { companies: data.companies(), candidates: data.candidates(day, screen) }
    }

    /// The day's candidates, in company order; `of` takes a position in
    /// this list.
    pub fn candidates(&self) -> &[Candidate] {
        &self.candidates
    }

    /// The value of `source` for candidate `i`, in its stored units, or
    /// `None` when it is missing. A built-in is missing when its stored lane
    /// is absent or not finite in canonical units. Sector and Exchange are
    /// text and have no number.
    pub fn of(&self, source: &Source, i: usize) -> Result<Option<f64>, Error> {
        let candidate = &self.candidates[i];
        Ok(match *source {
            Source::Builtin(index) => {
                candidate.values[index].filter(|&v| numbers::canonical(v, source.scale()).is_some())
            }
            Source::Field(Field::MarketCap) => Some(candidate.market_cap),
            Source::Field(Field::EnterpriseValue) => Some(candidate.enterprise_value),
            Source::Field(Field::Sector | Field::Exchange) => None,
            Source::Formula(_) => return Err(Error::new("this program does not evaluate formulas yet", source.label())),
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
