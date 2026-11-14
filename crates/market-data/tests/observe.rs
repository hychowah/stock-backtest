//! Formula observations on the fictional raw cache equal the oracle's. The
//! expected numbers come from the oracle on the same raw, prepared at the
//! same as-of time: `columns.Formulas._observation` at a root (the stored
//! dated book's row) or at an `at` context of that root.

use market_data::commands::{self, Home, PrepareRequest};
use market_data::parameters::PARAMETERS;
use market_data::{At, Candidate, CompanyId, Day, Market, MarketData, Parameter, Screen};
use std::path::Path;

fn prepared() -> (tempfile::TempDir, Home) {
    let dir = tempfile::tempdir().unwrap();
    let raw = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../fixtures/fictional/raw");
    std::os::unix::fs::symlink(raw.canonicalize().unwrap(), dir.path().join("raw")).unwrap();
    let home = Home::new(dir.path());
    let as_of = chrono::DateTime::parse_from_rfc3339("2023-06-30T07:30:00+00:00").unwrap();
    commands::prepare(&home, &PrepareRequest { as_of }).unwrap();
    (dir, home)
}

fn company(data: &MarketData, symbol: &str) -> CompanyId {
    let companies = data.companies();
    companies.ids().find(|&c| companies.symbol(c) == symbol).unwrap()
}

fn day(text: &str) -> Day {
    Day::parse(text).unwrap()
}

fn parameter(id: &str) -> Parameter {
    *PARAMETERS.iter().find(|p| p.id == id).unwrap()
}

/// The candidate of `symbol` on the dated screen of `root`.
fn candidate(data: &MarketData, symbol: &str, root: &str) -> Candidate {
    let c = company(data, symbol);
    data.candidates(day(root), Screen::Dated).into_iter().find(|x| x.company == c).unwrap()
}

fn bits(values: Option<Vec<f64>>) -> Option<Vec<u64>> {
    values.map(|v| v.iter().map(|x| x.to_bits()).collect())
}

#[test]
fn annual_inputs_read_years_of_the_fiscal_spine_in_usd_at_the_days_fx() {
    let (_dir, home) = prepared();
    let us = MarketData::open(&home, Market::Us).unwrap();
    let us_observer = us.observer();
    let qab = candidate(&us, "QAB", "2022-08-05");
    let revenue = us_observer.observe(At::Root(&qab, day("2022-08-05")), parameter("annual.revenue"), 4);
    assert_eq!(bits(revenue), Some(vec![0x41dd844870400000, 0x41df58c5c3000000, 0x41e0bd3a80400000, 0x41e24bc138c00000]));

    // The same four fiscal years, converted from HKD at each day's FX; share counts are not converted.
    let hk = MarketData::open(&home, Market::Hk).unwrap();
    let hk_observer = hk.observer();
    let root = candidate(&hk, "0101.HK", "2021-09-24");
    let at_root = At::Root(&root, day("2021-09-24"));
    let earlier = At::Dated(root.company, day("2021-06-24"));
    let revenue = parameter("annual.revenue");
    assert_eq!(bits(hk_observer.observe(at_root, revenue, 4)), Some(vec![0x41e5bfe806f0c48b, 0x41e6f7b58858c5db, 0x41e77ef14285d080, 0x41e8dbcf1ffc8f7a]));
    assert_eq!(bits(hk_observer.observe(earlier, revenue, 4)), Some(vec![0x41e5c84132ef4c53, 0x41e7008662d631cb, 0x41e787f6055dac3b, 0x41e8e559cb508e83]));
    let shares = hk_observer.observe(at_root, parameter("annual.weighted_average_basic_shares"), 2);
    assert_eq!(bits(shares), Some(vec![0x41cad27480000000; 2]));
}

#[test]
fn owner_values_are_the_candidates_at_a_root_and_recalculated_in_a_shifted_context() {
    let (_dir, home) = prepared();
    let hk = MarketData::open(&home, Market::Hk).unwrap();
    let hk_observer = hk.observer();
    let root = candidate(&hk, "0101.HK", "2021-09-24");
    let roe = parameter("owner.roe");
    assert_eq!(bits(hk_observer.observe(At::Root(&root, day("2021-09-24")), roe, 1)), Some(vec![0x3fd843de5d32b73b]));
    assert_eq!(bits(hk_observer.observe(At::Dated(root.company, day("2021-06-24")), roe, 1)), Some(vec![0x3fd843de5d32b73c]));

    // Valued on its own day, a candidate keeps its market cap and EV.
    let us = MarketData::open(&home, Market::Us).unwrap();
    let us_observer = us.observer();
    let qab = candidate(&us, "QAB", "2022-08-05");
    for (id, root, same_day, earlier) in [
        ("owner.market_cap", 0x4214b1a15c000000, 0x4214b1a15c000000, 0x42138f85c7ffffff),
        ("market.enterprise_value", 0x4214771558140000, 0x4214771558140000, 0x421354f9c413ffff),
    ] {
        let p = parameter(id);
        assert_eq!(bits(us_observer.observe(At::Root(&qab, day("2022-08-05")), p, 1)), Some(vec![root]), "{id}");
        assert_eq!(bits(us_observer.observe(At::Dated(qab.company, day("2022-08-05")), p, 1)), Some(vec![same_day]), "{id}");
        assert_eq!(bits(us_observer.observe(At::Dated(qab.company, day("2022-05-05")), p, 1)), Some(vec![earlier]), "{id}");
    }
}

#[test]
fn prices_read_the_last_session_and_treasury_the_last_treasury_day() {
    let (_dir, home) = prepared();
    // 2021-10-01 is a Hong Kong holiday: 2021-10-02 reads the session of
    // 2021-09-30, its close in USD at that day's FX, and the Treasury day
    // before 2021-10-02.
    let hk = MarketData::open(&home, Market::Hk).unwrap();
    let hk_observer = hk.observer();
    let at = At::Dated(company(&hk, "0101.HK"), day("2021-10-02"));
    assert_eq!(bits(hk_observer.observe(at, parameter("market.adjusted_price"), 1)), Some(vec![0x4040f391df2c773e]));
    assert_eq!(bits(hk_observer.observe(at, parameter("market.volume"), 1)), Some(vec![0x40fd4c0000000000]));
    assert_eq!(bits(hk_observer.observe(at, parameter("treasury.us_3m"), 1)), Some(vec![0x3f92bd3c36113405]));

    let us = MarketData::open(&home, Market::Us).unwrap();

    let us_observer = us.observer();
    let qab = candidate(&us, "QAB", "2022-08-05");
    let at = At::Root(&qab, day("2022-08-05"));
    assert_eq!(bits(us_observer.observe(at, parameter("market.adjusted_price"), 1)), Some(vec![0x4067254c985f06f7]));
    assert_eq!(bits(us_observer.observe(at, parameter("treasury.us_10y"), 1)), Some(vec![0x3f8b089a02752546]));
}

#[test]
fn report_ebitda_has_the_selected_reports_ebitda_of_each_year() {
    let (_dir, home) = prepared();
    let us = MarketData::open(&home, Market::Us).unwrap();
    let us_observer = us.observer();
    let qab = candidate(&us, "QAB", "2022-08-05");
    let ebitda = us_observer.observe(At::Root(&qab, day("2022-08-05")), parameter("annual.report_ebitda"), 3);
    assert_eq!(bits(ebitda), Some(vec![0x41baf54dea000000, 0x41be4c437c000000, 0x41c1906792800000]));
    let hk = MarketData::open(&home, Market::Hk).unwrap();
    let hk_observer = hk.observer();
    let root = candidate(&hk, "0101.HK", "2021-09-24");
    let ebitda = hk_observer.observe(At::Root(&root, day("2021-09-24")), parameter("annual.report_ebitda"), 3);
    assert_eq!(bits(ebitda), Some(vec![0x41d06bfdf4b2874a, 0x41d262b14410b4d2, 0x41d2554f27948e2b]));
}

#[test]
fn a_value_the_oracle_does_not_have_is_none() {
    let (_dir, home) = prepared();
    let us = MarketData::open(&home, Market::Us).unwrap();
    let us_observer = us.observer();
    let qab = candidate(&us, "QAB", "2022-08-05");
    let at = At::Root(&qab, day("2022-08-05"));
    // Ten years reach before QAB's first statement; it has no equity a year before its report.
    assert_eq!(us_observer.observe(at, parameter("annual.revenue"), 10), None);
    assert_eq!(us_observer.observe(at, parameter("owner.roe"), 1), None);
}
