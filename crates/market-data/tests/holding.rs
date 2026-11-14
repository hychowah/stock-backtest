//! A holding's exit and the closes of its daily path, on the fictional raw
//! cache, equal the oracle's. The expected numbers come from the oracle on
//! the same raw, prepared at the same as-of time: `books.close` with
//! `BookFacts.usd_price` as its lookup (as `schedules` calls it), and the
//! closes that `curves.holding` reads. Each entry is
//! `BookFacts.usd_price(symbol, day, True, 4)`, the dated screen's entry.

use market_data::commands::{self, Home, PrepareRequest};
use market_data::{CompanyId, Day, Exit, ExitStatus, Market, MarketData, MissingExitPrice};
use std::path::Path;

fn prepared(market: Market) -> (tempfile::TempDir, MarketData) {
    let dir = tempfile::tempdir().unwrap();
    let raw = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../fixtures/fictional/raw");
    std::os::unix::fs::symlink(raw.canonicalize().unwrap(), dir.path().join("raw")).unwrap();
    let home = Home::new(dir.path());
    let as_of = chrono::DateTime::parse_from_rfc3339("2023-06-30T07:30:00+00:00").unwrap();
    commands::prepare(&home, &PrepareRequest { as_of }).unwrap();
    let data = MarketData::open(&home, market).unwrap();
    (dir, data)
}

fn company(data: &MarketData, symbol: &str) -> CompanyId {
    let companies = data.companies();
    companies.ids().find(|&c| companies.symbol(c) == symbol).unwrap()
}

fn day(text: &str) -> Day {
    Day::parse(text).unwrap()
}

#[test]
fn an_exit_takes_the_close_within_10_days_else_the_last_available_price() {
    // QDL's prices stop on 2022-08-12, 10 days before 2022-08-22.
    let (_dir, data) = prepared(Market::Us);
    let qdl = company(&data, "QDL");
    let entry = (day("2022-06-01"), f64::from_bits(0x4046ef7ced916873));
    let return_value = f64::from_bits(0xbf829e2690551900);
    let scheduled = Exit { day: day("2022-08-12"), return_value, status: ExitStatus::Scheduled };
    assert_eq!(data.exit(qdl, entry, day("2022-08-22")), Ok(scheduled));
    let last = Exit { status: ExitStatus::LastAvailable, ..scheduled };
    assert_eq!(data.exit(qdl, entry, day("2022-08-23")), Ok(last));
}

#[test]
fn a_foreign_exit_close_converts_at_the_fx_of_its_own_day() {
    // 2021-10-01 is a Hong Kong holiday, so the exit close is of 2021-09-30.
    let (_dir, hk) = prepared(Market::Hk);
    let entry = (day("2021-09-20"), f64::from_bits(0x40408cfbe69cac43));
    let exit = Exit { day: day("2021-09-30"), return_value: f64::from_bits(0x3f98cb074daf2040), status: ExitStatus::Scheduled };
    assert_eq!(hk.exit(company(&hk, "0101.HK"), entry, day("2021-10-01")), Ok(exit));

    // 2022-05-04 is a Tokyo holiday, so the exit close is of 2022-05-02.
    let (_dir, jp) = prepared(Market::Jp);
    let t7101 = company(&jp, "7101.T");
    let entry = (day("2022-04-11"), f64::from_bits(0x4045939c181aa0c3));
    let exit = Exit { day: day("2022-05-02"), return_value: f64::from_bits(0x3fb3393dbeb1eb20), status: ExitStatus::Scheduled };
    assert_eq!(jp.exit(t7101, entry, day("2022-05-04")), Ok(exit));

    // USDJPY has no fixing from 2021-06-21 to 2021-07-02: the close of
    // 2021-07-01 has no FX, and the oracle's run stops.
    let entry = (day("2021-06-01"), f64::from_bits(0x4040aafa630bef43));
    assert_eq!(jp.exit(t7101, entry, day("2021-07-01")), Err(MissingExitPrice));
}

#[test]
fn a_foreign_path_reads_local_sessions_and_leaves_out_closes_without_fx() {
    // 2021-10-01, a Hong Kong holiday, has a saved price row but no session.
    let (_dir, hk) = prepared(Market::Hk);
    let closes = hk.usd_closes(company(&hk, "0101.HK"), day("2021-09-27"), day("2021-10-08"));
    let expected = [
        ("2021-09-27", 0x4040c11bf5e6ce6e),
        ("2021-09-28", 0x4040b1a16dc2d5a7),
        ("2021-09-29", 0x4040a161fca8e5f7),
        ("2021-09-30", 0x4040f391df2c773e),
        ("2021-10-04", 0x404125a122bdddb8),
        ("2021-10-05", 0x4040daf455d9ca4f),
        ("2021-10-06", 0x40412ac80225f2a0),
        ("2021-10-07", 0x40414594dba03a8d),
        ("2021-10-08", 0x40419ee5b47a8fcb),
    ];
    assert_eq!(closes, expected.map(|(d, bits)| (day(d), f64::from_bits(bits))));

    // The closes of 2021-06-28 to 2021-07-05 fall in the USDJPY gap.
    let (_dir, jp) = prepared(Market::Jp);
    let closes = jp.usd_closes(company(&jp, "7101.T"), day("2021-06-14"), day("2021-07-09"));
    let expected = [
        ("2021-06-14", 0x40409b1e29a5a42a),
        ("2021-06-15", 0x4040b14b84c3e5be),
        ("2021-06-16", 0x4040cce71421e2ce),
        ("2021-06-17", 0x404101827ef36ed3),
        ("2021-06-18", 0x404128b7a5035983),
        ("2021-06-21", 0x4040dc88cd21ca42),
        ("2021-06-22", 0x4040d6ec4555c203),
        ("2021-06-23", 0x4040ee33b0cc28d3),
        ("2021-06-24", 0x40409a8d44d1c586),
        ("2021-06-25", 0x4040ee49a3d24982),
        ("2021-07-06", 0x40403c1be7e42d71),
        ("2021-07-07", 0x40405ba84a02f50b),
        ("2021-07-08", 0x403ffdcaac5e36ff),
        ("2021-07-09", 0x403ffb569ec8831b),
    ];
    assert_eq!(closes, expected.map(|(d, bits)| (day(d), f64::from_bits(bits))));
}
