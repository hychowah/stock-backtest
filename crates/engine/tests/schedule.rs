//! `Plan` gives the oracle's trade dates on the fictional data. The expected
//! dates are those of `backtest.calendar` on the same sessions.

use engine::{Dates, Interval, Plan, Schedule};
use market_data::commands::{Home, PrepareRequest, prepare};
use market_data::{Day, Market, MarketData};
use std::path::Path;
use std::sync::OnceLock;

/// The fictional raw cache prepared once for all tests, at the as-of time of
/// its expected tables.
fn data(market: Market) -> MarketData {
    static HOME: OnceLock<Home> = OnceLock::new();
    let home = HOME.get_or_init(|| {
        let root = Path::new(env!("CARGO_TARGET_TMPDIR")).join("schedule-home");
        if root.exists() {
            std::fs::remove_dir_all(&root).unwrap();
        }
        std::fs::create_dir_all(&root).unwrap();
        let raw = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../fixtures/fictional/raw");
        std::os::unix::fs::symlink(raw.canonicalize().unwrap(), root.join("raw")).unwrap();
        let home = Home::new(root);
        prepare(&home, &PrepareRequest { as_of: "2023-06-30T07:30:00+00:00".parse().unwrap() }).unwrap();
        home
    });
    MarketData::open(home, market).unwrap()
}

fn plan(market: Market, start: &str, end: &str, dates: Dates) -> Plan {
    Plan::new(&data(market), &Schedule { start: start.into(), end: end.into(), dates }).unwrap()
}

fn day(text: &str) -> Day {
    Day::parse(text).unwrap()
}

/// Each trial's entries, space-separated, after checking that its periods
/// chain from entry to entry and that the last one exits at the final mark.
fn entries(plan: &Plan) -> Vec<String> {
    let trial = |t: &engine::Trial| {
        assert!(t.periods.windows(2).all(|p| p[0].exit == p[1].entry && p[0].entry < p[0].exit));
        assert_eq!(t.periods.last().unwrap().exit, plan.window().1);
        t.periods.iter().map(|p| p.entry.to_string()).collect::<Vec<_>>().join(" ")
    };
    plan.trials().iter().map(trial).collect()
}

/// Each trial's first trade and cash days.
fn cash(plan: &Plan) -> Vec<(Option<Day>, Option<i32>)> {
    plan.trials().iter().map(|t| (t.first_trade, t.cash_days)).collect()
}

fn random(every: Interval, trials: u32, seed: u32) -> Dates {
    Dates::Random { every, trials, seed }
}

#[test]
fn the_fictional_tests_trade_on_the_oracles_dates() {
    let us = plan(Market::Us, "2021-07-01", "2023-06-28", random(Interval::Months(6), 3, 20210701));
    assert_eq!(us.window(), (day("2021-07-01"), day("2023-06-28")));
    assert_eq!(
        entries(&us),
        [
            "2021-09-02 2022-06-15 2022-10-07 2023-03-09",
            "2021-11-29 2022-05-06 2022-12-23 2023-01-16",
            "2021-11-09 2022-04-07 2022-11-29 2023-02-16"
        ]
    );
    let first = [(day("2021-09-02"), 63), (day("2021-11-29"), 151), (day("2021-11-09"), 131)];
    assert_eq!(cash(&us), first.map(|(d, n)| (Some(d), Some(n))));
    assert!(us.final_mark());

    let hk = plan(Market::Hk, "2021-07-01", "2023-06-28", random(Interval::Months(6), 2, 852));
    assert_eq!(hk.window(), (day("2021-07-01"), day("2023-06-28")));
    assert_eq!(entries(&hk), ["2021-07-21 2022-03-23 2022-12-27 2023-03-23", "2021-11-10 2022-05-23 2022-09-26 2023-03-15"]);
    assert_eq!(cash(&hk), [(Some(day("2021-07-21")), Some(20)), (Some(day("2021-11-10")), Some(132))]);

    let jp = plan(Market::Jp, "2021-07-01", "2023-06-28", Dates::Every(Interval::Months(1)));
    assert_eq!(jp.window(), (day("2021-07-01"), day("2023-06-28")));
    assert_eq!(
        entries(&jp),
        ["2021-07-01 2021-08-02 2021-09-01 2021-10-01 2021-11-01 2021-12-01 2022-01-04 2022-02-01 2022-03-01 \
          2022-04-01 2022-05-02 2022-06-01 2022-07-01 2022-08-01 2022-09-01 2022-10-03 2022-11-01 2022-12-01 \
          2023-01-04 2023-02-01 2023-03-01 2023-04-03 2023-05-01 2023-06-01"]
    );
    assert_eq!(cash(&jp), [(None, None)]);
    assert!(jp.final_mark());
}

#[test]
fn fixed_weeks_roll_forward_and_end_on_a_schedule_only_when_a_target_rolls_to_the_final_mark() {
    let us = plan(Market::Us, "2022-01-03", "2022-03-28", Dates::Every(Interval::Weeks(2)));
    assert_eq!(entries(&us), ["2022-01-03 2022-01-17 2022-01-31 2022-02-14 2022-02-28 2022-03-14"]);
    assert!(!us.final_mark());
    // 2022-02-10 is no Hong Kong session and rolls to 2022-02-14.
    let hk = plan(Market::Hk, "2022-01-27", "2022-03-01", Dates::Every(Interval::Weeks(1)));
    assert_eq!(entries(&hk), ["2022-01-27 2022-02-03 2022-02-14 2022-02-17 2022-02-24"]);
    assert!(hk.final_mark());
}

#[test]
fn month_targets_keep_the_start_day_or_the_month_end() {
    // 2022-04-30 rolls to 2022-05-02; the next target is still 2022-05-31.
    let jp = plan(Market::Jp, "2022-01-31", "2022-12-30", Dates::Every(Interval::Months(1)));
    assert_eq!(
        entries(&jp),
        ["2022-01-31 2022-02-28 2022-03-31 2022-05-02 2022-05-31 2022-06-30 2022-08-01 2022-08-31 2022-09-30 \
          2022-10-31 2022-11-30"]
    );
}

#[test]
fn explicit_dates_hold_cash_from_the_window_start_until_the_first_trade() {
    let dates = ["2022-03-01", "2022-09-01", "2022-11-15"].map(String::from).to_vec();
    let us = plan(Market::Us, "2022-01-01", "2022-12-30", Dates::Explicit(dates));
    assert_eq!(us.window(), (day("2022-01-03"), day("2022-12-30")));
    assert_eq!(entries(&us), ["2022-03-01 2022-09-01 2022-11-15"]);
    assert_eq!(cash(&us), [(Some(day("2022-03-01")), Some(57))]);
    assert!(us.final_mark());
}

#[test]
fn random_blocks_are_clipped_at_the_final_mark_and_an_empty_block_draws_nothing() {
    // The last block, from Saturday 2022-02-26, holds 2022-02-28 and 2022-03-01.
    let clipped = plan(Market::Us, "2022-01-01", "2022-03-02", random(Interval::Weeks(1), 2, 7));
    assert_eq!(
        entries(&clipped),
        [
            "2022-01-05 2022-01-11 2022-01-20 2022-01-24 2022-01-31 2022-02-11 2022-02-14 2022-02-23 2022-02-28",
            "2022-01-07 2022-01-11 2022-01-17 2022-01-24 2022-02-03 2022-02-10 2022-02-14 2022-02-22 2022-02-28"
        ]
    );
    assert_eq!(cash(&clipped), [(Some(day("2022-01-05")), Some(2)), (Some(day("2022-01-07")), Some(4))]);
    assert_eq!(
        clipped.entry_days().iter().map(Day::to_string).collect::<Vec<_>>().join(" "),
        "2022-01-05 2022-01-07 2022-01-11 2022-01-17 2022-01-20 2022-01-24 2022-01-31 2022-02-03 2022-02-10 \
         2022-02-11 2022-02-14 2022-02-22 2022-02-23 2022-02-28"
    );
    // Here the last block holds no session before the final mark: the
    // second trial draws on from the first trial's eighth draw.
    let empty = plan(Market::Us, "2022-01-01", "2022-02-28", random(Interval::Weeks(1), 2, 7));
    assert_eq!(
        entries(&empty),
        [
            "2022-01-05 2022-01-11 2022-01-20 2022-01-24 2022-01-31 2022-02-11 2022-02-14 2022-02-23",
            "2022-01-07 2022-01-10 2022-01-21 2022-01-25 2022-01-31 2022-02-07 2022-02-17 2022-02-24"
        ]
    );
}

#[test]
fn refused_settings_name_their_place() {
    let refused = |market, start: &str, end: &str, dates| {
        let error = Plan::new(&data(market), &Schedule { start: start.into(), end: end.into(), dates }).unwrap_err();
        (error.place, error.message)
    };
    let year = |dates| refused(Market::Us, "2022-01-01", "2022-12-30", dates);
    for trials in [0, 101] {
        assert_eq!(year(random(Interval::Months(6), trials, 7)), ("trials".into(), "choose 1 to 100 trials".into()));
    }
    let every = year(Dates::Every(Interval::Months(25)));
    assert_eq!(every, ("every".into(), "choose 1 to 104 weeks or 1 to 24 months".into()));
    let (place, message) = year(Dates::Explicit(vec!["2022-03-12".into()]));
    assert_eq!(place, "dates");
    assert!(message.contains("2022-03-11") && message.contains("2022-03-14"), "{message}");
    let decreasing = year(Dates::Explicit(vec!["2022-09-01".into(), "2022-03-01".into()]));
    assert_eq!(decreasing, ("dates".into(), "2022-03-01 is not after the date before it, 2022-09-01".into()));
    let late = refused(Market::Us, "2022-01-01", "2023-07-05", Dates::Every(Interval::Months(1)));
    assert_eq!(late, ("end".into(), "the end must be on or before the last session, 2023-06-30".into()));
    let backwards = refused(Market::Us, "2022-12-30", "2022-01-01", Dates::Every(Interval::Months(1)));
    assert_eq!(backwards, ("end".into(), "the end must be after the start".into()));
}

#[test]
fn a_schedule_reads_back_from_its_json() {
    let schedule =
        Schedule { start: "2013-01-01".into(), end: "2026-10-21".into(), dates: random(Interval::Months(3), 24, 2607948532) };
    let text = serde_json::to_string(&schedule).unwrap();
    assert_eq!(
        text,
        r#"{"start":"2013-01-01","end":"2026-10-21","random":{"every":{"months":3},"trials":24,"seed":2607948532}}"#
    );
    assert_eq!(serde_json::from_str::<Schedule>(&text).unwrap(), schedule);
}
