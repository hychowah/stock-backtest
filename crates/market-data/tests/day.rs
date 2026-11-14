use market_data::Day;

#[test]
fn iso_text_round_trips_and_impossible_dates_are_refused() {
    assert_eq!(Day::parse("1970-01-01"), Some(Day(0)));
    for text in ["0001-01-01", "1996-01-01", "2024-02-29", "9999-12-31"] {
        assert_eq!(Day::parse(text).map(|d| d.to_string()).as_deref(), Some(text));
    }
    assert_eq!(Day::parse("2023-02-29"), None);
    assert_eq!(Day::parse("2023-2-9"), None);
}

#[test]
fn an_anniversary_of_feb_29_is_feb_28_in_a_year_without_it() {
    let leap = Day::parse("2016-02-29").unwrap();
    assert_eq!(leap.anniversary(1).to_string(), "2015-02-28");
    assert_eq!(leap.anniversary(4).to_string(), "2012-02-29");
}

#[test]
fn adding_months_clamps_to_the_month_end() {
    let day = |text| Day::parse(text).unwrap();
    assert_eq!(day("2024-03-31").add_months(-1), Some(day("2024-02-29")));
    assert_eq!(day("2024-01-15").add_months(-13), Some(day("2022-12-15")));
    assert_eq!(day("2023-01-31").add_months(1), Some(day("2023-02-28")));
    assert_eq!(day("2023-01-31").add_months(13), Some(day("2024-02-29")));
}
