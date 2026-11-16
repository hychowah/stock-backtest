//! `Plan` gives the expected trade dates on the fictional data: the dates
//! that the Python product that this program replaced planned on the same
//! sessions.

use engine::{Plan, Schedule};
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

/// A schedule of the window from `start` to `end`; `dates` sets its other
/// keys.
fn schedule(start: &str, end: &str, dates: impl FnOnce(&mut Schedule)) -> Schedule {
    let mut schedule = Schedule { start: start.into(), end: end.into(), every: None, trials: None, seed: None, dates: None };
    dates(&mut schedule);
    schedule
}

fn plan(market: Market, start: &str, end: &str, dates: impl FnOnce(&mut Schedule)) -> Plan {
    Plan::new(&data(market), &schedule(start, end, dates)).unwrap()
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

fn every(every: &str) -> impl FnOnce(&mut Schedule) {
    move |s| s.every = Some(every.into())
}

fn random(every: &str, trials: u32, seed: u32) -> impl FnOnce(&mut Schedule) {
    move |s| (s.every, s.trials, s.seed) = (Some(every.into()), Some(trials), Some(seed))
}

fn dates(dates: &[&str]) -> impl FnOnce(&mut Schedule) {
    let dates = dates.iter().map(|d| d.to_string()).collect();
    move |s| s.dates = Some(dates)
}

#[test]
fn the_fictional_tests_trade_on_the_expected_dates() {
    let us = plan(Market::Us, "2021-07-01", "2023-06-28", random("6m", 3, 20210701));
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

    let hk = plan(Market::Hk, "2021-07-01", "2023-06-28", random("6m", 2, 852));
    assert_eq!(hk.window(), (day("2021-07-01"), day("2023-06-28")));
    assert_eq!(entries(&hk), ["2021-07-21 2022-03-23 2022-12-27 2023-03-23", "2021-11-10 2022-05-23 2022-09-26 2023-03-15"]);
    assert_eq!(cash(&hk), [(Some(day("2021-07-21")), Some(20)), (Some(day("2021-11-10")), Some(132))]);

    let jp = plan(Market::Jp, "2021-07-01", "2023-06-28", every("1m"));
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
    let us = plan(Market::Us, "2022-01-03", "2022-03-28", every("2w"));
    assert_eq!(entries(&us), ["2022-01-03 2022-01-17 2022-01-31 2022-02-14 2022-02-28 2022-03-14"]);
    assert!(!us.final_mark());
    // 2022-02-10 is no Hong Kong session and rolls to 2022-02-14.
    let hk = plan(Market::Hk, "2022-01-27", "2022-03-01", every("1w"));
    assert_eq!(entries(&hk), ["2022-01-27 2022-02-03 2022-02-14 2022-02-17 2022-02-24"]);
    assert!(hk.final_mark());
}

#[test]
fn month_targets_keep_the_start_day_or_the_month_end() {
    // 2022-04-30 rolls to 2022-05-02; the next target is still 2022-05-31.
    let jp = plan(Market::Jp, "2022-01-31", "2022-12-30", every("1m"));
    assert_eq!(
        entries(&jp),
        ["2022-01-31 2022-02-28 2022-03-31 2022-05-02 2022-05-31 2022-06-30 2022-08-01 2022-08-31 2022-09-30 \
          2022-10-31 2022-11-30"]
    );
}

#[test]
fn explicit_dates_hold_cash_from_the_window_start_until_the_first_trade() {
    let us = plan(Market::Us, "2022-01-01", "2022-12-30", dates(&["2022-03-01", "2022-09-01", "2022-11-15"]));
    assert_eq!(us.window(), (day("2022-01-03"), day("2022-12-30")));
    assert_eq!(entries(&us), ["2022-03-01 2022-09-01 2022-11-15"]);
    assert_eq!(cash(&us), [(Some(day("2022-03-01")), Some(57))]);
    assert!(us.final_mark());
}

#[test]
fn random_blocks_are_clipped_at_the_final_mark_and_an_empty_block_draws_nothing() {
    // The last block, from Saturday 2022-02-26, holds 2022-02-28 and 2022-03-01.
    let clipped = plan(Market::Us, "2022-01-01", "2022-03-02", random("1w", 2, 7));
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
    let empty = plan(Market::Us, "2022-01-01", "2022-02-28", random("1w", 2, 7));
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
    fn refused(market: Market, start: &str, end: &str, dates: impl FnOnce(&mut Schedule)) -> (String, String) {
        let error = Plan::new(&data(market), &schedule(start, end, dates)).unwrap_err();
        (error.place, error.message)
    }
    fn year(dates: impl FnOnce(&mut Schedule)) -> (String, String) {
        refused(Market::Us, "2022-01-01", "2022-12-30", dates)
    }
    assert_eq!(year(random("6m", 0, 7)), ("trials".into(), "choose at least 1 trial".into()));
    assert_eq!(plan(Market::Us, "2022-01-01", "2022-12-30", random("6m", 101, 7)).trials().len(), 101);
    assert_eq!(year(every("25m")), ("every".into(), "choose 1 to 104 weeks or 1 to 24 months".into()));
    let (place, message) = year(dates(&["2022-03-12"]));
    assert_eq!(place, "dates");
    assert!(message.contains("2022-03-11") && message.contains("2022-03-14"), "{message}");
    let decreasing = year(dates(&["2022-09-01", "2022-03-01"]));
    assert_eq!(decreasing, ("dates".into(), "2022-03-01 is not after the date before it, 2022-09-01".into()));
    let late = refused(Market::Us, "2022-01-01", "2023-07-05", every("1m"));
    assert_eq!(late, ("end".into(), "the end must be on or before the last session, 2023-06-30".into()));
    let backwards = refused(Market::Us, "2022-12-30", "2022-01-01", every("1m"));
    assert_eq!(backwards, ("end".into(), "the end must be after the start".into()));
}

#[test]
fn a_schedule_that_combines_its_keys_wrongly_names_the_key_at_fault() {
    fn keys(every: Option<&str>, trials: Option<u32>, seed: Option<u32>, dates: Option<&[&str]>) -> (String, String) {
        let error = Plan::new(&data(Market::Us), &schedule("2022-01-01", "2022-12-30", |s| {
            (s.every, s.trials, s.seed) = (every.map(String::from), trials, seed);
            s.dates = dates.map(|d| d.iter().map(|d| d.to_string()).collect());
        }))
        .unwrap_err();
        (error.place, error.message)
    }
    let error = |place: &str, message: &str| (place.to_string(), message.to_string());
    let one = Some(&["2022-03-01"][..]);
    let dates = error("dates", "dates cannot be combined with every or trials");
    assert_eq!(keys(Some("3m"), None, None, one), dates);
    assert_eq!(keys(None, Some(2), Some(7), one), dates);
    assert_eq!(keys(None, Some(2), Some(7), None), error("trials", "trials need every: a random trial trades once in every interval"));
    let seed = error("seed", "a seed is only for random trials: give trials too");
    assert_eq!(keys(Some("3m"), None, Some(1), None), seed);
    assert_eq!(keys(None, None, Some(1), one), seed);
    assert_eq!(keys(None, None, Some(1), None), seed);
    assert_eq!(keys(None, None, None, None), error("every", "choose a schedule: every, every with trials, or dates"));
    let interval = r#""3x" is not an interval: use N weeks (Nw) or N months (Nm), such as 13w or 3m"#;
    assert_eq!(keys(Some("3x"), None, None, None), error("every", interval));
    // A seed is drawn before the check, never inside it.
    assert_eq!(keys(Some("3m"), Some(2), None, None), error("seed", "a random schedule needs its seed drawn first"));
}

#[test]
fn a_schedule_reads_back_from_its_flat_json() {
    let schedule = schedule("2013-01-01", "2026-10-21", random("3m", 24, 2607948532));
    let text = serde_json::to_string(&schedule).unwrap();
    assert_eq!(text, r#"{"start":"2013-01-01","end":"2026-10-21","every":"3m","trials":24,"seed":2607948532}"#);
    assert_eq!(serde_json::from_str::<Schedule>(&text).unwrap(), schedule);
}
