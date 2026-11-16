//! The rules that decide what an update asks for: the last price day, when
//! reports are checked, which companies' reports and prices are asked, and
//! the date windows of a history. No file or network access.

use chrono::{DateTime, Datelike, FixedOffset, NaiveDate, TimeDelta, Utc, Weekday};
use market_data::raw::{PyJson, Universe};
use market_data::updates::ReportCheck;
use market_data::Day;
use std::collections::BTreeSet;

/// The first day a new history is asked from.
const FIRST: NaiveDate = NaiveDate::from_ymd_opt(1995, 1, 1).unwrap();

/// The last price day: the last day whose 22:00 UTC has passed at `as_of`.
pub fn last_day(as_of: DateTime<FixedOffset>) -> NaiveDate {
    (as_of.with_timezone(&Utc) - TimeDelta::hours(22)).date_naive()
}

/// The Hong Kong date at `as_of`, which the report check counts in.
pub fn hong_kong_date(as_of: DateTime<FixedOffset>) -> NaiveDate {
    as_of.with_timezone(&FixedOffset::east_opt(8 * 3600).unwrap()).date_naive()
}

/// Whether an update checks reports, and whether its report set holds every
/// company of the lists (the sweep), not only the listed and pending ones.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Reports {
    pub due: bool,
    /// Also decides the Hong Kong exchange rates when reports are not due.
    pub sweep: bool,
}

impl Reports {
    /// Reports are due on a Hong Kong Saturday not yet checked, or when the
    /// last check is over 7 days old or missing. The sweep is due when the
    /// last full sweep is over 90 days old or missing.
    pub fn decide(today: NaiveDate, last_check: Option<NaiveDate>, last_sweep: Option<NaiveDate>) -> Reports {
        let older = |last: Option<NaiveDate>, days: i64| last.is_none_or(|last| (today - last).num_days() > days);
        let due = (today.weekday() == Weekday::Sat && last_check != Some(today)) || older(last_check, 7);
        Reports { due, sweep: older(last_sweep, 90) }
    }

    /// A continued update keeps the check of the update it continues;
    /// `fresh` (decided now) gives the sweep only when that check was not
    /// due, where it chooses only the exchange rates.
    pub fn continued(check: ReportCheck, fresh: Reports) -> Reports {
        match check {
            ReportCheck::NotDue => Reports { due: false, sweep: fresh.sweep },
            ReportCheck::Due => Reports { due: true, sweep: false },
            ReportCheck::Sweep => Reports { due: true, sweep: true },
        }
    }

    pub fn check(self) -> ReportCheck {
        match (self.due, self.sweep) {
            (false, _) => ReportCheck::NotDue,
            (true, false) => ReportCheck::Due,
            (true, true) => ReportCheck::Sweep,
        }
    }
}

/// The companies whose reports are asked, in symbol order: the listed and
/// pending companies of the list, or on a sweep every company of the list.
pub fn report_set(universe: &Universe, pending: &[String], sweep: bool) -> Vec<String> {
    let mut symbols: Vec<String> = universe
        .iter()
        .filter(|(symbol, row)| {
            sweep || row.get("listed").is_some_and(PyJson::truthy) || pending.iter().any(|p| p == symbol)
        })
        .map(|(symbol, _)| symbol.to_string())
        .collect();
    symbols.sort();
    symbols
}

/// The companies whose prices are asked: each company of the list for which
/// `saved` is true, and each pending company. The update's `saved` is a
/// price file, or in the US also an income statement, which asks again for
/// a lost price file: the US asks statements only of price targets. In Hong
/// Kong every listed company's statements are asked, so a statement says
/// nothing about prices there.
pub fn price_targets(universe: &Universe, pending: &[String], saved: impl Fn(&str) -> bool) -> BTreeSet<String> {
    let mut targets: BTreeSet<String> = universe.iter().map(|(s, _)| s).filter(|s| saved(s)).map(str::to_string).collect();
    targets.extend(pending.iter().cloned());
    targets
}

/// Whether a US company's key metrics give it a report that preparation
/// accepts: a row with a fiscal date, a positive `marketCap`,
/// `enterpriseValue` and `evToEBITDA`, and `reportedCurrency` USD in any case,
/// or none. A company that gains one in an update becomes pending and a price
/// target in the same update. Preparation's reader (`accepted` in
/// `market-data`'s `reports.rs`) holds the same rule on the forms the raw
/// cache holds: the two read text numbers, a lower-case currency and a null
/// currency differently, and none of the real cache's 166,286 key-metrics rows
/// has those forms. A change to one is made to both.
pub fn reported(rows: &[PyJson]) -> bool {
    rows.iter().any(|row| {
        let positive = |key| PyJson::number(row.get(key)).is_some_and(|v| v > 0.0);
        let usd = match row.get("reportedCurrency").filter(|c| c.truthy()) {
            None => true,
            Some(code) => code.as_str().is_some_and(|c| c.to_uppercase() == "USD"),
        };
        PyJson::day(row.get("date")).is_some() && positive("marketCap") && positive("enterpriseValue") && positive("evToEBITDA") && usd
    })
}

/// The Hong Kong exchange rates asked, in order: HKD, each price target's
/// listing currency (`listing`) and each three-letter `reportedCurrency` of
/// the saved statements of the report set and the price targets
/// (`reported`, read in capitals), without USD.
pub fn fx_currencies<'a>(listing: impl IntoIterator<Item = &'a str>, reported: impl IntoIterator<Item = &'a str>) -> Vec<String> {
    let mut currencies: BTreeSet<String> = BTreeSet::from(["HKD".to_string()]);
    currencies.extend(listing.into_iter().map(str::to_string));
    currencies.extend(reported.into_iter().map(str::to_uppercase).filter(|c| c.chars().count() == 3));
    currencies.remove("USD");
    currencies.into_iter().collect()
}

/// What a history file holds before the update.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Saved {
    /// No file.
    Missing,
    /// A file with no usable row.
    Empty,
    /// The first and last days with a usable row.
    Rows(NaiveDate, NaiveDate),
}

/// The windows asked for a history through `end`: a new history from
/// 1995-01-01; a saved one from its last row less 7 days (not before its
/// first row); an empty one its last 7 days, or from the day after
/// `covered` when that is earlier. `covered` is the last price day of the
/// last complete update ([`last_day`] of its time): after a pause of more
/// than a week, a company that began trading during the pause keeps its
/// first days. Each window is at most ten calendar years ending 31
/// December, or one month for the Treasury (`monthly`), whose long requests
/// return only recent rows.
pub fn windows(saved: Saved, end: NaiveDate, covered: Option<NaiveDate>, monthly: bool) -> Vec<(NaiveDate, NaiveDate)> {
    let week = TimeDelta::days(7);
    let start = match saved {
        Saved::Missing => FIRST,
        Saved::Empty => FIRST.max(covered.map_or(end - week, |day| (end - week).min(day + TimeDelta::days(1)))),
        Saved::Rows(first, last) => first.max(last - week),
    };
    spans(start, end, monthly)
}

/// The windows that ask a whole history again through `end`, from 1995-01-01
/// or its first row when that is earlier.
pub fn whole(first: NaiveDate, end: NaiveDate, monthly: bool) -> Vec<(NaiveDate, NaiveDate)> {
    spans(FIRST.min(first), end, monthly)
}

/// `from..=to` cut into windows that end on 31 December (at most ten
/// calendar years each) or, `monthly`, at each month's end.
fn spans(mut from: NaiveDate, to: NaiveDate, monthly: bool) -> Vec<(NaiveDate, NaiveDate)> {
    let mut spans = Vec::new();
    while from <= to {
        let last = if monthly {
            let next = if from.month() == 12 { (from.year() + 1, 1) } else { (from.year(), from.month() + 1) };
            NaiveDate::from_ymd_opt(next.0, next.1, 1).unwrap().pred_opt().unwrap()
        } else {
            NaiveDate::from_ymd_opt((from.year() + 9).min(to.year()), 12, 31).unwrap()
        };
        let last = last.min(to);
        spans.push((from, last));
        from = last.succ_opt().unwrap();
    }
    spans
}

/// The day of a date, as the raw files and the record count days.
pub fn day(date: NaiveDate) -> Day {
    Day((date - NaiveDate::from_ymd_opt(1970, 1, 1).unwrap()).num_days() as i32)
}

/// The date of a day.
pub fn date(day: Day) -> NaiveDate {
    NaiveDate::from_ymd_opt(1970, 1, 1).unwrap() + TimeDelta::days(day.0.into())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn d(text: &str) -> NaiveDate {
        text.parse().unwrap()
    }

    fn time(text: &str) -> DateTime<FixedOffset> {
        DateTime::parse_from_rfc3339(text).unwrap()
    }

    #[test]
    fn the_last_day_is_the_last_whose_22_utc_has_passed() {
        assert_eq!(last_day(time("2023-07-07T23:00:00+00:00")), d("2023-07-07"));
        assert_eq!(last_day(time("2023-07-07T21:59:00+00:00")), d("2023-07-06"));
        assert_eq!(last_day(time("2023-07-08T07:00:00+08:00")), d("2023-07-07"));
        assert_eq!(hong_kong_date(time("2023-07-07T23:00:00+00:00")), d("2023-07-08"));
    }

    #[test]
    fn reports_are_due_on_an_unchecked_saturday_or_after_a_week() {
        let saturday = d("2023-07-08");
        let due = |today, last: Option<&str>| Reports::decide(today, last.map(d), Some(d("2023-07-01"))).due;
        assert!(due(saturday, Some("2023-07-01")));
        assert!(!due(saturday, Some("2023-07-08")));
        assert!(!due(d("2023-07-10"), Some("2023-07-08")));
        assert!(due(d("2023-07-16"), Some("2023-07-08")));
        assert!(due(d("2023-07-10"), None));
        let sweep = |last: Option<&str>| Reports::decide(saturday, Some(saturday), last.map(d)).sweep;
        assert!(sweep(None) && sweep(Some("2023-03-25")) && !sweep(Some("2023-04-09")));
        let fresh = Reports { due: true, sweep: true };
        assert_eq!(Reports::continued(ReportCheck::Due, fresh), Reports { due: true, sweep: false });
        assert_eq!(Reports::continued(ReportCheck::NotDue, fresh), Reports { due: false, sweep: true });
    }

    #[test]
    fn windows_start_a_week_before_the_last_row_and_split_by_decade_or_month() {
        let end = d("2023-07-07");
        assert_eq!(
            windows(Saved::Missing, end, None, false),
            [(d("1995-01-01"), d("2004-12-31")), (d("2005-01-01"), d("2014-12-31")), (d("2015-01-01"), end)]
        );
        assert_eq!(windows(Saved::Rows(d("2023-06-28"), d("2023-06-30")), end, None, false), [(d("2023-06-28"), end)]);
        assert_eq!(
            windows(Saved::Rows(d("2000-01-03"), d("2023-06-30")), end, None, true),
            [(d("2023-06-23"), d("2023-06-30")), (d("2023-07-01"), end)]
        );
        assert_eq!(windows(Saved::Rows(d("2000-01-03"), d("2023-07-20")), end, None, false), []);
        assert_eq!(whole(d("1990-05-01"), d("1999-03-01"), false), [(d("1990-05-01"), d("1999-03-01"))]);
        assert_eq!(date(day(end)), end);
    }

    /// An empty history: the last 7 days, or from the day after the last
    /// complete update's last price day when that is earlier.
    #[test]
    fn an_empty_history_starts_after_the_last_complete_update_or_a_week_back() {
        let covered = |at: &str| Some(last_day(time(at)));
        let empty = |end: &str, covered| windows(Saved::Empty, d(end), covered, false);
        assert_eq!(empty("2023-07-07", None), [(d("2023-06-30"), d("2023-07-07"))]);
        // Within a week, the last 7 days.
        assert_eq!(empty("2023-07-09", covered("2023-07-06T23:07:41.512903+00:00")), [(d("2023-07-02"), d("2023-07-09"))]);
        // After a longer pause, from the day after the covered day.
        assert_eq!(empty("2026-11-06", covered("2026-10-21T23:30:00+00:00")), [(d("2026-10-22"), d("2026-11-06"))]);
        // A covered day after the update's own last day.
        assert_eq!(empty("2023-07-09", covered("2026-11-15T10:00:00+00:00")), [(d("2023-07-02"), d("2023-07-09"))]);
    }

    #[test]
    fn exchange_rates_are_hkd_and_the_three_letter_codes_without_usd() {
        let rates = fx_currencies(["HKD", "CNY"], ["usd", "sgd", "", "RMB1"]);
        assert_eq!(rates, ["CNY", "HKD", "SGD"]);
    }

    #[test]
    fn a_report_needs_positive_values_and_dollars() {
        let rows = |text: &str| PyJson::parse(text.as_bytes()).unwrap().as_list().unwrap().to_vec();
        assert!(reported(&rows(r#"[{"date": "2022-12-31", "marketCap": "5", "enterpriseValue": 8, "evToEBITDA": 2, "reportedCurrency": "usd"}]"#)));
        assert!(reported(&rows(r#"[{"date": "2022-12-31", "marketCap": 5, "enterpriseValue": 8, "evToEBITDA": 2, "reportedCurrency": null}]"#)));
        assert!(!reported(&rows(r#"[{"date": "2022-12-31", "marketCap": 5, "enterpriseValue": 8, "evToEBITDA": 0}]"#)));
        assert!(!reported(&rows(r#"[{"date": "2022-12-31", "marketCap": 5, "enterpriseValue": 8, "evToEBITDA": 2, "reportedCurrency": "CAD"}]"#)));
        assert!(!reported(&rows(r#"[{"marketCap": 5, "enterpriseValue": 8, "evToEBITDA": 2}]"#)));
    }
}
