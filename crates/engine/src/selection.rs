//! Selection: each sleeve's steps over a day's candidates, and the union of
//! the sleeves' picks (`selection.execute` and `selection.union`, as
//! `scalar_execution.Executor.select` runs them).
//!
//! - A Filter keeps the candidates whose value passes it; a missing value
//!   fails it. A Rank orders the candidates with a value and keeps a range
//!   of positions ([`rank`]); a missing value leaves the candidate out.
//!   Later steps see only the kept candidates, and no step adds any back.
//! - A sleeve's picks are those its last step keeps, with the ranks of its
//!   last Rank step.

use crate::Error;
use crate::strategy::{Order, Source, Step, Strategy, Test};
use crate::values::DayValues;
use market_data::{Candidate, Day};
use std::collections::HashMap;

/// One holding of a selection.
#[derive(Debug)]
pub struct Pick<'v> {
    pub candidate: &'v Candidate,
    /// One sleeve: the rank its last Rank step gave. Several sleeves: the
    /// position in their union, from 1.
    pub rank: u32,
    /// The ranking value: the value of the first picking sleeve's last Rank
    /// step, in its source's unit (a built-in's canonical value, a size
    /// field's US dollars).
    pub value: f64,
    /// Each sleeve that picked the candidate, in sleeve order.
    pub sleeves: Vec<Trail>,
}

/// One picking sleeve's step trail.
#[derive(Debug)]
pub struct Trail {
    /// The sleeve's position in the strategy, from 0.
    pub sleeve: usize,
    /// One outcome for each of the sleeve's steps, in step order.
    pub steps: Vec<Outcome>,
}

/// What one step read and gave for a pick.
#[derive(Debug)]
pub struct Outcome {
    /// The step's value in its source's unit; `None` for a field, which is
    /// the holding's own.
    pub value: Option<f64>,
    /// The rank a Rank step gave; `None` for a passed Filter.
    pub rank: Option<u32>,
}

/// A row a Rank step orders.
pub struct Row<'a> {
    pub symbol: &'a str,
    /// The US tie rank.
    pub candidate_rank: Option<u32>,
    pub value: Option<f64>,
}

/// One Rank step: the rows with a finite value sorted by (−value for
/// `Highest` or value, candidate rank present, candidate rank, symbol), and
/// of those the positions `from` to `to`. Gives each kept row's position in
/// `rows` with its rank, which counts from `from`, in rank order; needs
/// 1 ≤ `from` ≤ `to`. Equal
/// values tie, `-0.0` with `0.0`, and rows without a candidate rank come
/// first among them.
pub fn rank(rows: &[Row<'_>], order: Order, from: u32, to: u32) -> Vec<(usize, u32)> {
    let sign = if order == Order::Highest { -1.0 } else { 1.0 };
    let mut eligible: Vec<(usize, f64)> =
        rows.iter().enumerate().filter_map(|(i, row)| row.value.filter(|v| v.is_finite()).map(|v| (i, sign * v))).collect();
    eligible.sort_by(|&(a, x), &(b, y)| {
        let (a, b) = (&rows[a], &rows[b]);
        x.partial_cmp(&y)
            .expect("finite values")
            .then(a.candidate_rank.is_some().cmp(&b.candidate_rank.is_some()))
            .then(a.candidate_rank.unwrap_or(0).cmp(&b.candidate_rank.unwrap_or(0)))
            .then(a.symbol.cmp(b.symbol))
    });
    let skip = from as usize - 1;
    eligible.into_iter().skip(skip).take((to - from + 1) as usize).zip(from..).map(|((i, _), rank)| (i, rank)).collect()
}

/// `selection.execute` for each sleeve over the candidates whose entry is
/// before `exit` (all candidates on the latest screen), then the union in
/// sleeve order. Sort key: (−value or value, rank present, rank, symbol).
/// One sleeve keeps the ranks of its last Rank step. Several sleeves number
/// the union from 1. A holding's ranking value is the value from its first
/// picking sleeve.
pub fn select<'v>(strategy: &Strategy, day: &'v DayValues<'_>, exit: Option<Day>) -> Result<Vec<Pick<'v>>, Error> {
    let candidates = day.candidates();
    let scope: Vec<usize> = (0..candidates.len()).filter(|&i| exit.is_none_or(|exit| candidates[i].entry < exit)).collect();
    // Each candidate's picking sleeves, in the order of its first pick.
    let mut picks: Vec<(usize, Vec<(usize, Chosen)>)> = Vec::new();
    let mut position = HashMap::new();
    for (number, sleeve) in strategy.sleeves().iter().enumerate() {
        for chosen in execute(&sleeve.steps, day, &scope)? {
            let at = *position.entry(chosen.index).or_insert_with(|| {
                picks.push((chosen.index, Vec::new()));
                picks.len() - 1
            });
            picks[at].1.push((number, chosen));
        }
    }
    let several = strategy.sleeves().len() > 1;
    let mut out = Vec::with_capacity(picks.len());
    for (union_rank, (index, found)) in (1..).zip(picks) {
        let (first, chosen) = &found[0];
        let last = strategy.sleeves()[*first].steps.iter().rev().find(|s| matches!(s, Step::Rank { .. })).expect("a Rank step");
        let mut sleeves = Vec::with_capacity(found.len());
        for (number, chosen) in &found {
            let steps = &strategy.sleeves()[*number].steps;
            let mut outcomes = Vec::with_capacity(steps.len());
            for (step, rank) in steps.iter().zip(&chosen.ranks) {
                outcomes.push(Outcome { value: reported(step.source(), day.of(step.source(), index)?), rank: *rank });
            }
            sleeves.push(Trail { sleeve: *number, steps: outcomes });
        }
        out.push(Pick {
            candidate: &candidates[index],
            rank: if several { union_rank } else { chosen.rank },
            value: match last.source() {
                source @ Source::Builtin(_) => numbers::canonical(chosen.value, source.scale()).expect("a ranked value is canonical"),
                Source::Field(_) => chosen.value,
            },
            sleeves,
        });
    }
    Ok(out)
}

/// A step's value as a result reports it (`scalar_execution`): a built-in's
/// stored value in canonical units, and no value for a field.
fn reported(source: &Source, stored: Option<f64>) -> Option<f64> {
    match source {
        Source::Builtin(_) => stored.and_then(|v| numbers::canonical(v, source.scale())),
        Source::Field(_) => None,
    }
}

/// One sleeve's pick.
struct Chosen {
    /// The candidate's position in the day.
    index: usize,
    rank: u32,
    /// The last Rank step's value, in stored units.
    value: f64,
    /// The rank each step gave: `None` for a Filter.
    ranks: Vec<Option<u32>>,
}

/// One sleeve's steps over the candidates at positions `scope`: its picks
/// in rank order.
fn execute(steps: &[Step], day: &DayValues<'_>, scope: &[usize]) -> Result<Vec<Chosen>, Error> {
    let mut alive = scope.to_vec();
    let mut selected: HashMap<usize, Chosen> = HashMap::new();
    for (number, step) in steps.iter().enumerate() {
        match step {
            Step::Filter { source, test } => {
                let mut kept = Vec::with_capacity(alive.len());
                for i in alive {
                    let passes = match test {
                        Test::Number(compare, threshold) => day.of(source, i)?.is_some_and(|v| compare.holds(v, threshold.stored)),
                        Test::Is(text) => day.text(field(source), i) == text,
                        Test::IsNot(text) => day.text(field(source), i) != text,
                    };
                    if passes {
                        kept.push(i);
                    }
                }
                alive = kept;
            }
            &Step::Rank { ref source, order, from, to } => {
                let rows = alive
                    .iter()
                    .map(|&i| {
                        let value = day.of(source, i)?;
                        Ok(Row { symbol: day.symbol(i), candidate_rank: day.candidates()[i].rank, value })
                    })
                    .collect::<Result<Vec<_>, Error>>()?;
                let mut ranked = HashMap::new();
                let mut order_kept = Vec::new();
                for (at, rank) in rank(&rows, order, from, to) {
                    let index = alive[at];
                    let mut ranks = selected.remove(&index).map_or_else(|| vec![None; steps.len()], |c| c.ranks);
                    ranks[number] = Some(rank);
                    let value = rows[at].value.expect("a ranked row has a value");
                    ranked.insert(index, Chosen { index, rank, value, ranks });
                    order_kept.push(index);
                }
                selected = ranked;
                alive = order_kept;
            }
        }
    }
    Ok(alive.into_iter().map(|i| selected.remove(&i).expect("a kept candidate was ranked")).collect())
}

/// The text field a Sector or Exchange filter reads.
fn field(source: &Source) -> crate::names::Field {
    match source {
        Source::Field(field) => *field,
        Source::Builtin(_) => panic!("an is filter reads a text field"),
    }
}
