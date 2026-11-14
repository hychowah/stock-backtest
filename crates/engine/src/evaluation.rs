//! Formula values: a checked formula's value for one candidate of a screen
//! day, exactly as the oracle's `columns.Formulas.evaluate` computes it.
//!
//! - The root context is the candidate on the screen day; `ago` moves to the
//!   same company `months` calendar months earlier, `at` to a fixed date. A
//!   moved context values the company afresh on its day ([`At::Dated`]).
//! - Measures and variables are their own trees at the same context.
//! - Arithmetic is binary64 in tree order, as Python's float operations: a
//!   division needs a nonzero bottom, `positive( )` a bottom above zero. The
//!   yearly mean adds oldest first; min and max keep the oldest of equal
//!   members; growth needs a first member above zero, and CAGR also a last
//!   one, then raises the ratio to `1 / years` as Python's `**`.
//! - A missing member or operand makes the result missing, and so does a
//!   result that is not finite.
//!
//! Every node is evaluated, as the oracle does, so an `at` date after its
//! context's day stops the evaluation (FUTURE_DATE) even where the value is
//! missing anyway.

use crate::Error;
use crate::formula::{Formula, Node, Op, Stat};
use market_data::{At, Candidate, Day, Observer, Parameter};

/// The value of `formula` for `candidate` of the screen of `day`, in the
/// formula's unit, or `None` when the oracle has no valid value. The error
/// is the oracle's FUTURE_DATE (or, before year 1, INVALID_DATE); its place
/// is empty.
pub(crate) fn value(observer: &Observer<'_>, formula: &Formula, candidate: &Candidate, day: Day) -> Result<Option<f64>, Error> {
    Evaluation { observer, candidate, day }.node(formula.tree(), None)
}

struct Evaluation<'a> {
    observer: &'a Observer<'a>,
    candidate: &'a Candidate,
    /// The screen day: the root context's day.
    day: Day,
}

impl Evaluation<'_> {
    /// `node` at the root context (`None`) or at a moved context's day.
    fn node(&self, node: &Node, moved: Option<Day>) -> Result<Option<f64>, Error> {
        let day = moved.unwrap_or(self.day);
        let value = match node {
            Node::Parameter(p) => self.observe(moved, *p, 1).map(|values| values[0]),
            Node::Annual { stat, count, parameter } => {
                self.observe(moved, *parameter, *count as usize).and_then(|values| statistic(*stat, &values))
            }
            Node::Constant { value, .. } => Some(value.parse().expect("a checked constant is a decimal")),
            Node::Neg(arg) => self.node(arg, moved)?.map(|x| -x),
            Node::Binary { op, left, right } => {
                let (left, right) = (self.node(left, moved)?, self.node(right, moved)?);
                left.zip(right).and_then(|(l, r)| arithmetic(*op, l, r))
            }
            Node::Lookback { months, arg } => {
                let earlier = day.add_months(-(*months as i32)).ok_or_else(|| {
                    Error::new(format!("ago( ) goes back {months} months from {day}, before year 1 (INVALID_DATE)"), "")
                })?;
                self.node(arg, Some(earlier))?
            }
            Node::At { date, arg } => {
                if *date > day {
                    let message = format!("at( ) reads {date}, after the day it is read on, {day} (FUTURE_DATE)");
                    return Err(Error::new(message, ""));
                }
                self.node(arg, Some(*date))?
            }
            Node::Measure(measure) => self.node(measure.tree(), moved)?,
            Node::Variable(formula) => self.node(formula.tree(), moved)?,
        };
        Ok(value.filter(|v| v.is_finite()))
    }

    fn observe(&self, moved: Option<Day>, p: Parameter, count: usize) -> Option<Vec<f64>> {
        let at = match moved {
            None => At::Root(self.candidate, self.day),
            Some(day) => At::Dated(self.candidate.company, day),
        };
        self.observer.observe(at, p, count)
    }
}

/// One arithmetic operation; `None` for a bottom the operation refuses.
fn arithmetic(op: Op, l: f64, r: f64) -> Option<f64> {
    match op {
        Op::Add => Some(l + r),
        Op::Sub => Some(l - r),
        Op::Mul => Some(l * r),
        Op::Div => (r != 0.0).then(|| l / r),
        Op::PositiveDiv => (r > 0.0).then(|| l / r),
    }
}

/// A statistic of yearly values, oldest first.
fn statistic(stat: Stat, values: &[f64]) -> Option<f64> {
    let (first, last, rest) = (values[0], values[values.len() - 1], &values[1..]);
    match stat {
        Stat::Mean => Some(rest.iter().fold(first, |sum, &x| sum + x) / values.len() as f64),
        Stat::Min => Some(rest.iter().fold(first, |low, &x| if x < low { x } else { low })),
        Stat::Max => Some(rest.iter().fold(first, |high, &x| if x > high { x } else { high })),
        Stat::Growth | Stat::Cagr if first <= 0.0 => None,
        Stat::Cagr if last <= 0.0 => None,
        Stat::Growth => Some(last / first - 1.0),
        // Python's float `**` is the C library's `pow`, as `powf` is.
        Stat::Cagr => Some((last / first).powf(1.0 / (values.len() - 1) as f64) - 1.0),
    }
}
