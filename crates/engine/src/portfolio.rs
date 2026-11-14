//! A period's holdings valued from their entry to the period's exit, and a
//! trial's periods compounded (`schedules._backtest_periods`,
//! `portfolio_results` and `curves.book`).
//!
//! - A holding exits as [`MarketData::exit`] says; the last period's
//!   scheduled exits are marked to date when the plan ends on a mark.
//! - The holdings are equally weighted: the period's return is Python's
//!   `sum` of their returns / their number, or 0 for a period without one.
//! - SPY's return is its close at the exit / its close at the entry − 1.
//! - The curve has one row for each session after the entry through the
//!   exit: the holdings' mean return to date, added from left to right as the
//!   oracle does, and SPY's. Its last row holds the period's own returns, so
//!   the curve compounds to the result.

use crate::Error;
use crate::run::{Holding, PeriodRun, Point, Status};
use crate::schedule::Period;
use crate::selection::Pick;
use market_data::{Day, ExitStatus, MarketData};

/// The oracle's causes of a run that stops.
const NO_EXIT: &str = "a selected company has no valid exit (MISSING_EXIT_PRICE): it has no close from its entry \
                       through the exit day, or the last one has no FX";
const NO_SPY: &str = "SPY comparison coverage is missing for this market window";

/// Values the picks of `period`, in rank order. `marked`: the period is the
/// last one and the plan ends on a mark to date. `sessions` are the market's.
/// An error's place is the symbol at fault, or empty for SPY.
pub(crate) fn value(data: &MarketData, sessions: &[Day], picks: Vec<Pick<'_>>, period: Period, marked: bool) -> Result<PeriodRun, Error> {
    let companies = data.companies();
    let mut holdings = Vec::with_capacity(picks.len());
    for pick in picks {
        let c = pick.candidate;
        let symbol = companies.symbol(c.company);
        let exit = data.exit(c.company, (c.entry, c.price), period.exit).map_err(|_| Error::new(NO_EXIT, symbol))?;
        let status = match exit.status {
            ExitStatus::Scheduled if marked => Status::Marked,
            ExitStatus::Scheduled => Status::Scheduled,
            ExitStatus::LastAvailable => Status::LastAvailable,
        };
        holdings.push(Holding {
            company: c.company,
            symbol: symbol.to_string(),
            name: companies.name(c.company).to_string(),
            sector: companies.sector(c.company).to_string(),
            exchange: companies.exchange(c.company).to_string(),
            candidate_rank: c.rank,
            fiscal: c.fiscal,
            entry: c.entry,
            price: c.price,
            exit: exit.day,
            market_cap: c.market_cap,
            enterprise_value: c.enterprise_value,
            ebitda: c.ebitda,
            ebitda_yield: c.ebitda_yield,
            ev_ebitda: c.ev_ebitda,
            spread: c.spread,
            return_value: exit.return_value,
            status,
            rank: pick.rank,
            ranking_value: pick.value,
            sleeves: pick.sleeves,
        });
    }
    let (Some((_, spy_entry)), Some((_, spy_exit))) = (data.spy(period.entry), data.spy(period.exit)) else {
        return Err(Error::new(NO_SPY, ""));
    };
    let returns: Vec<f64> = holdings.iter().map(|h| h.return_value).collect();
    let portfolio = numbers::mean_return(&returns);
    let curve = curve(data, sessions, &holdings, period, spy_entry, portfolio);
    Ok(PeriodRun { entry: period.entry, exit: period.exit, portfolio, spy: spy_exit / spy_entry - 1.0, holdings, curve })
}

/// The period's daily rows (`curves.book`). A holding's return to date is
/// 0 before its first close and keeps its last close on a day without one.
fn curve(data: &MarketData, sessions: &[Day], holdings: &[Holding], period: Period, spy_entry: f64, portfolio: f64) -> Vec<Point> {
    let days = &sessions[sessions.partition_point(|&d| d <= period.entry)..sessions.partition_point(|&d| d <= period.exit)];
    let mut sums = vec![0.0; days.len()];
    for holding in holdings {
        let closes = data.usd_closes(holding.company, holding.entry, period.exit);
        let (mut next, mut value) = (0, 0.0);
        for (sum, &day) in sums.iter_mut().zip(days) {
            while next < closes.len() && closes[next].0 <= day {
                value = closes[next].1 / holding.price - 1.0;
                next += 1;
            }
            *sum += value;
        }
    }
    let mut spy = 0.0;
    let mut points: Vec<Point> = days
        .iter()
        .zip(sums)
        .map(|(&day, sum)| {
            if let Some((_, close)) = data.spy(day) {
                spy = close / spy_entry - 1.0;
            }
            let portfolio = if holdings.is_empty() { 0.0 } else { sum / holdings.len() as f64 };
            Point { day, portfolio, spy }
        })
        .collect();
    // A running sum can differ from the period's return in the last digit.
    points.last_mut().expect("the exit is a session after the entry").portfolio = portfolio;
    points
}

/// A trial's growth, SPY growth, CAGR and SPY CAGR over the window from
/// `start` to `end` (`portfolio_results.reduce_returns`), from each
/// period's (return, SPY return) in order.
pub(crate) fn compound(returns: impl Iterator<Item = (f64, f64)>, start: Day, end: Day) -> [f64; 4] {
    let (mut growth, mut spy_growth) = (1.0, 1.0);
    for (portfolio, spy) in returns {
        growth *= 1.0 + portfolio;
        spy_growth *= 1.0 + spy;
    }
    let years = f64::from(end.0 - start.0) / 365.25;
    let cagr = |growth: f64| numbers::pow(growth, 1.0 / years) - 1.0;
    [growth, spy_growth, cagr(growth), cagr(spy_growth)]
}
