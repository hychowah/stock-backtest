//! A trial's summary and the statistics over a run's trials
//! (`robustness.summarize`, `summarize_trials` and `distribution`).

use market_data::Day;

/// One trial's summary. A fixed interval has no first trade or cash days.
#[derive(Clone, Debug, PartialEq)]
pub(crate) struct Summary {
    /// The trial's number, from 1.
    pub trial: u32,
    /// The entry of each period, in order.
    pub dates: Vec<Day>,
    /// The window's first session: every trial starts there, in cash until
    /// its first trade.
    pub start: Day,
    pub first_trade: Option<Day>,
    /// The final mark.
    pub end: Day,
    pub cash_days: Option<i32>,
    pub periods: u32,
    /// The product of `1 + return` over the periods, for the strategy and SPY.
    pub growth: f64,
    pub spy_growth: f64,
    /// The growth per year over the window, as a fraction.
    pub cagr: f64,
    pub spy_cagr: f64,
    /// Periods with no holding, and periods with fewer holdings than the
    /// strategy's last Rank steps keep.
    pub empty_periods: u32,
    pub short_periods: u32,
}

impl Summary {
    pub(crate) fn excess_cagr(&self) -> f64 {
        self.cagr - self.spy_cagr
    }

    pub(crate) fn total_return(&self) -> f64 {
        self.growth - 1.0
    }
}

/// One value's distribution over the trials.
#[derive(Clone, Debug, PartialEq)]
pub(crate) struct Distribution {
    pub n: usize,
    /// Exact means and population standard deviation, rounded once.
    pub mean: f64,
    pub median: f64,
    /// Percentiles by linear interpolation (R type 7).
    pub p10: f64,
    pub p25: f64,
    pub p75: f64,
    pub p90: f64,
    pub min: f64,
    pub max: f64,
    pub stddev: f64,
}

/// The statistics over a run's trials.
///
/// The oracle leaves out a trial without a CAGR; every trial here has one,
/// because the window holds two sessions or more and a period's return is
/// never missing, so every distribution covers every trial.
#[derive(Clone, Debug, PartialEq)]
pub(crate) struct Statistics {
    pub completed: usize,
    /// Trials whose CAGR is above SPY's.
    pub beat_spy: usize,
    /// Distinct lists of entry dates.
    pub unique_schedules: usize,
    pub cagr: Distribution,
    pub spy_cagr: Distribution,
    pub excess_cagr: Distribution,
    pub total_return: Distribution,
    pub growth: Distribution,
}

/// The statistics of `trials`, which is not empty.
pub(crate) fn statistics(trials: &[Summary]) -> Statistics {
    let of = |value: fn(&Summary) -> f64| distribution(&trials.iter().map(value).collect::<Vec<_>>());
    let mut schedules: Vec<&[Day]> = trials.iter().map(|t| t.dates.as_slice()).collect();
    schedules.sort_unstable();
    schedules.dedup();
    Statistics {
        completed: trials.len(),
        beat_spy: trials.iter().filter(|t| t.excess_cagr() > 0.0).count(),
        unique_schedules: schedules.len(),
        cagr: of(|t| t.cagr),
        spy_cagr: of(|t| t.spy_cagr),
        excess_cagr: of(Summary::excess_cagr),
        total_return: of(Summary::total_return),
        growth: of(|t| t.growth),
    }
}

fn distribution(values: &[f64]) -> Distribution {
    let mut sorted = values.to_vec();
    sorted.sort_by(|a, b| a.partial_cmp(b).expect("finite trial values"));
    Distribution {
        n: values.len(),
        mean: numbers::mean(values),
        median: numbers::median(values),
        p10: numbers::percentile(&sorted, 0.1),
        p25: numbers::percentile(&sorted, 0.25),
        p75: numbers::percentile(&sorted, 0.75),
        p90: numbers::percentile(&sorted, 0.9),
        min: numbers::min(values),
        max: numbers::max(values),
        stddev: numbers::pstdev(values),
    }
}
