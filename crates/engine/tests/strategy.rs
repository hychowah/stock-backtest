//! Strategy files: name resolution, the canonical form and identity, and the
//! place and message of refused files.

use engine::names::Field;
use engine::strategy::{Compare, Step, Test};
use engine::{Error, Source, Strategy};
use market_data::builtins::BUILTINS;
use std::path::PathBuf;

/// Writes `json` to a file `name` in a new folder and reads it; returns the
/// file's path too.
fn read(name: &str, json: &str) -> (PathBuf, Result<Strategy, Error>) {
    let folder = tempfile::tempdir().unwrap();
    let path = folder.path().join(name);
    std::fs::write(&path, json).unwrap();
    let strategy = Strategy::read(&path);
    (path, strategy)
}

fn builtin(id: &str) -> Source {
    Source::Builtin(BUILTINS.iter().position(|b| b.id == id).unwrap())
}

/// Each step's source, and its stored threshold or rank range.
fn steps(strategy: &Strategy) -> Vec<(Source, String)> {
    strategy.sleeves()[0]
        .steps
        .iter()
        .map(|step| match step {
            Step::Filter { source, test: Test::Number(compare, threshold) } => (*source, format!("{compare:?} {:?}", threshold.stored)),
            Step::Filter { source, test } => (*source, format!("{test:?}")),
            Step::Rank { source, order, from, to } => (*source, format!("{order:?} {from}-{to}")),
        })
        .collect()
}

fn one_sleeve(steps: &str) -> String {
    format!(r#"{{"sleeves": [{{"steps": [{steps}]}}]}}"#)
}

#[test]
fn hong_kong_floors_read_the_dollar_fields_and_the_linked_yield() {
    let (_, strategy) = read(
        "hk.json",
        &one_sleeve(
            r#"{"filter": "Market cap in dollars", "op": ">=", "value": "100000000"},
               {"filter": "Enterprise value in dollars", "op": ">=", "value": "50000000"},
               {"filter": "EBITDA yield", "op": ">=", "value": "0"},
               {"rank": "EBITDA yield", "order": "highest", "from": 1, "to": 50},
               {"filter": "Market cap", "op": ">=", "value": "100"}"#,
        ),
    );
    let yield_lane = builtin("metric:ev_ebitda:yield");
    assert_eq!(
        steps(&strategy.unwrap()),
        [
            (Source::Field(Field::MarketCap), "AtLeast 100000000.0".to_string()),
            (Source::Field(Field::EnterpriseValue), "AtLeast 50000000.0".to_string()),
            (yield_lane, "AtLeast 0.0".to_string()),
            (yield_lane, "Highest 1-50".to_string()),
            // The built-in market cap is stored in $ million.
            (builtin("filter:market_cap"), "AtLeast 100.0".to_string()),
        ]
    );
}

#[test]
fn a_linked_name_reads_its_stored_lane_in_display_units() {
    let (_, strategy) = read("roe.json", &one_sleeve(r#"{"filter": "ROE", "op": ">", "value": "15"}, {"rank": "ROE", "order": "lowest", "from": 1, "to": 5}"#));
    let strategy = strategy.unwrap();
    assert_eq!(steps(&strategy)[0], (builtin("filter:roe"), "Greater 15.0".to_string()));
    assert!(matches!(&strategy.sleeves()[0].steps[0], Step::Filter { test: Test::Number(Compare::Greater, _), .. }));
}

#[test]
fn a_step_only_name_reads_its_lane_and_an_input_needs_a_formula() {
    let (_, strategy) = read("pe.json", &one_sleeve(r#"{"rank": "P/E 5-year average", "order": "lowest", "from": 1, "to": 5}"#));
    assert_eq!(steps(&strategy.unwrap()), [(builtin("filter:pe_avg_5y"), "Lowest 1-5".to_string())]);
    let (path, refused) = read("revenue.json", &one_sleeve(r#"{"rank": "Revenue", "order": "highest", "from": 1, "to": 5}"#));
    let error = refused.unwrap_err();
    assert_eq!(error.place, format!("{}: sleeves[1].steps[1]", path.display()));
    assert_eq!(error.message, r#""Revenue" is read with a formula, and this program does not read formulas yet"#);
}

#[test]
fn spellings_of_the_same_strategy_have_one_canonical_form_and_identity() {
    let listed = r#"{"sleeves": [
        {"name": "Value", "steps": [
            {"filter": "Market cap in dollars", "op": ">=", "value": "100000000"},
            {"filter": "Sector", "op": "is not", "value": "Utilities"},
            {"rank": "EBITDA yield", "order": "highest", "from": 1, "to": 50}]},
        {"name": "Margin", "steps": [
            {"filter": "Dividend yield", "op": "<", "value": "7.5"},
            {"rank": "Net margin", "order": "highest", "from": 2, "to": 4}]}]}"#;
    let respelled = r#"{"sleeves": [
        {"steps": [
            {"value": 1e8, "op": ">=", "filter": "market  cap IN dollars"},
            {"filter": " sector", "op": "is not", "value": "Utilities"},
            {"to": 50, "from": 1, "order": "highest", "rank": "ebitda   YIELD"}], "name": "Value"},
        {"name": "Margin", "steps": [
            {"filter": "DIVIDEND YIELD", "op": "<", "value": "007.50"},
            {"rank": "net margin", "order": "highest", "from": 2, "to": 4}]}]}"#;
    let (_, a) = read("a.json", listed);
    let (_, b) = read("b.json", respelled);
    let (a, b) = (a.unwrap(), b.unwrap());
    assert_eq!(
        a.canonical(),
        concat!(
            r#"{"sleeves":[{"name":"Value","steps":[{"filter":"Market cap in dollars","op":">=","value":"100000000"},"#,
            r#"{"filter":"Sector","op":"is not","value":"Utilities"},{"rank":"EBITDA yield","order":"highest","from":1,"to":50}]},"#,
            r#"{"name":"Margin","steps":[{"filter":"Dividend yield","op":"<","value":"7.5"},"#,
            r#"{"rank":"Net margin","order":"highest","from":2,"to":4}]}]}"#
        )
    );
    assert_eq!(b.canonical(), a.canonical());
    assert_eq!(b.identity(), a.identity());
    assert_eq!(a.identity().len(), 64);
}

#[test]
fn refused_files_name_the_place_and_the_cause() {
    let rank = r#"{"rank": "P/B", "order": "lowest", "from": 1, "to": 5}"#;
    let cases = [
        (
            one_sleeve(r#"{"rank": "P/E 4-year average", "order": "highest", "from": 1, "to": 5}"#),
            "sleeves[1].steps[1]",
            r#""P/E 4-year average" is not a known name; did you mean "P/E 3-year average", "P/E 5-year average", "P/S 3-year average"?"#,
        ),
        (
            one_sleeve(&format!(r#"{{"filter": "Sector", "op": ">", "value": "Technology"}}, {rank}"#)),
            "sleeves[1].steps[1]",
            "Sector is text: compare it with is or is not",
        ),
        (
            one_sleeve(&format!(r#"{rank}, {{"filter": "ROE", "op": ">", "value": "fifteen"}}"#)),
            "sleeves[1].steps[2]",
            r#"threshold: "fifteen" is not a decimal number"#,
        ),
        (one_sleeve(&vec![rank; 51].join(",")), "", "has 51 steps across its sleeves; the most is 50"),
        (
            format!(
                r#"{{"sleeves": [{{"name": "A", "steps": [{rank}]}}, {{"name": "B", "steps": [{{"filter": "ROE", "op": ">", "value": "15"}}]}}]}}"#
            ),
            "sleeves[2]",
            "needs a Rank step",
        ),
        // Valid JSON with a lone surrogate escape, in a threshold and in a key.
        (
            one_sleeve(&format!(r#"{rank}, {{"filter": "ROE", "op": ">", "value": "\ud800"}}"#)),
            "sleeves[1].steps[2]",
            "the threshold must be a JSON string",
        ),
        (one_sleeve(&format!(r#"{rank}, {{"\ud800": 1}}"#)), "sleeves[1].steps[2]", "must be a JSON object"),
        (
            one_sleeve(r#"{"rank": "P/B", "order": "lowest", "from": 1, "to": 5001}"#),
            "sleeves[1].steps[1]",
            "from and to are whole numbers from 1 to 5000",
        ),
    ];
    for (json, place, message) in cases {
        let (path, refused) = read("refused.json", &json);
        let error = refused.unwrap_err();
        let file = path.display().to_string();
        assert_eq!(error.place, if place.is_empty() { file } else { format!("{file}: {place}") });
        assert_eq!(error.message, message);
    }
}
