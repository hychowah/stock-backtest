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
            Step::Filter { source, test: Test::Number(compare, threshold) } => (source.clone(), format!("{compare:?} {:?}", threshold.stored)),
            Step::Filter { source, test } => (source.clone(), format!("{test:?}")),
            Step::Rank { source, order, from, to } => (source.clone(), format!("{order:?} {from}-{to}")),
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
            (yield_lane.clone(), "AtLeast 0.0".to_string()),
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
fn a_step_only_name_reads_its_lane_and_an_input_reads_its_formula() {
    let (_, strategy) = read(
        "names.json",
        &one_sleeve(
            r#"{"rank": "P/E 5-year average", "order": "lowest", "from": 1, "to": 5},
               {"filter": "revenue", "op": ">", "value": "100"},
               {"filter": "Price/sales", "op": "<", "value": "3"},
               {"filter": "[Price/sales]", "op": "<", "value": "3"}"#,
        ),
    );
    let strategy = strategy.unwrap();
    let found = steps(&strategy);
    assert_eq!(found[0], (builtin("filter:pe_avg_5y"), "Lowest 1-5".to_string()));
    // A whole input or measure reads its formula in the list's display; as
    // other text it shows in its unit's default display (percent here).
    let shown: Vec<(String, &str, String)> = found[1..]
        .iter()
        .map(|(source, stored)| {
            let Source::Formula(formula) = source else { panic!("a formula") };
            (formula.text().to_string(), formula.display(), stored.clone())
        })
        .collect();
    assert_eq!(
        shown,
        [
            ("Revenue".to_string(), "usd_million", "Greater 100000000.0".to_string()),
            ("Price/sales".to_string(), "multiple", "Less 3.0".to_string()),
            ("Price/sales".to_string(), "percent", "Less 0.03".to_string()),
        ]
    );
    assert!(strategy.canonical().contains(r#"{"filter":"Price/sales","op":"<","value":"3"},{"filter":"(Price/sales)""#));
}

#[test]
fn variables_and_formula_steps_print_canonically() {
    let written = r#"{"variables": {
        " Debt to EV ": {"formula": "total debt/positive( enterprise value )", "display": "multiple"},
        "Doubled": {"formula": "[Debt to EV]*2"}},
      "sleeves": [{"steps": [
        {"filter": "debt  to EV", "op": "<", "value": "1.5"},
        {"filter": "revenue-cost of revenue", "op": ">", "value": 100},
        {"filter": "[ROE]", "op": ">", "value": "15"},
        {"filter": "ROE", "op": ">", "value": "15"},
        {"rank": "Doubled", "order": "lowest", "from": 1, "to": 5}]}]}"#;
    let (_, strategy) = read("variables.json", written);
    let strategy = strategy.unwrap();
    let canonical = concat!(
        r#"{"variables":{"Debt to EV":{"formula":"Total debt / positive(Enterprise value)","display":"multiple"},"#,
        r#""Doubled":{"formula":"Debt to EV * 2","display":"percent"}},"sleeves":[{"steps":["#,
        r#"{"filter":"Debt to EV","op":"<","value":"1.5"},{"filter":"Revenue - Cost of revenue","op":">","value":"100"},"#,
        r#"{"filter":"(ROE)","op":">","value":"15"},{"filter":"ROE","op":">","value":"15"},"#,
        r#"{"rank":"Doubled","order":"lowest","from":1,"to":5}]}]}"#
    );
    assert_eq!(strategy.canonical(), canonical);
    let stored: Vec<String> = steps(&strategy).into_iter().map(|(_, stored)| stored).collect();
    assert_eq!(stored, ["Less 1.5", "Greater 100000000.0", "Greater 0.15", "Greater 15.0", "Lowest 1-5"]);
    let names: Vec<_> = strategy.variables().iter().map(|v| v.name().unwrap()).collect();
    assert_eq!(names, ["Debt to EV", "Doubled"]);
    let (_, again) = read("again.json", canonical);
    let again = again.unwrap();
    assert_eq!((again.canonical(), again.identity()), (strategy.canonical(), strategy.identity()));
}

#[test]
fn the_fictional_strategy_files_read_and_their_canonical_forms_read_again() {
    let cases = format!("{}/../../fixtures/fictional/cases", env!("CARGO_MANIFEST_DIR"));
    let mut count = 0;
    for kind in std::fs::read_dir(cases).unwrap() {
        for case in std::fs::read_dir(kind.unwrap().path()).unwrap() {
            let path = case.unwrap().path().join("strategy.json");
            let strategy = Strategy::read(&path).unwrap_or_else(|e| panic!("{e}"));
            let (_, again) = read("again.json", strategy.canonical());
            let again = again.unwrap_or_else(|e| panic!("{}: {e}", path.display()));
            assert_eq!((again.canonical(), again.identity()), (strategy.canonical(), strategy.identity()), "{}", path.display());
            count += 1;
        }
    }
    assert!(count > 0);
}

#[test]
fn formula_faults_name_the_variable_or_step_and_the_characters() {
    let rank = r#"{"rank": "P/B", "order": "lowest", "from": 1, "to": 5}"#;
    let with = |variables: &str, steps: &str| format!(r#"{{"variables": {{{variables}}}, "sleeves": [{{"steps": [{steps}]}}]}}"#);
    let cases = [
        (
            with(r#""Debt to EV": {"formula": "Total debt / Enterprse value"}"#, rank),
            r#"variables."Debt to EV", characters 14–28"#,
            "“Enterprse value” is not an input or a saved variable. Did you mean “Enterprise value”?",
        ),
        (
            with(r#""A": {"formula": "B * 2"}, "B": {"formula": "Revenue"}"#, rank),
            r#"variables."A", character 1"#,
            "“B” is not an input or a saved variable.",
        ),
        (
            with(r#""A": {"formula": "Revenue", "display": "percent"}"#, rank),
            r#"variables."A".display"#,
            r#""percent" is not a display of USD: use usd, usd_million"#,
        ),
        (with(r#""A": {"formula": "Revenue + 1"}"#, rank), r#"variables."A", characters 1–11"#, ""),
        (with(r#"" ": {"formula": "Revenue"}"#, rank), r#"variables." ""#, "a variable name is not empty"),
        (with("", &format!(r#"{{"filter": "Revenue +", "op": ">", "value": "1"}}, {rank}"#)), "sleeves[1].steps[1], character 10", "A value is missing at the end."),
        (
            with("", &format!(r#"{rank}, {{"rank": "average(P/E, 3 years)", "order": "lowest", "from": 1, "to": 5}}"#)),
            "sleeves[1].steps[2], characters 1–21",
            "",
        ),
    ];
    for (json, place, message) in cases {
        let (path, refused) = read("formula.json", &json);
        let error = refused.unwrap_err();
        assert_eq!(error.place, format!("{}: {place}", path.display()));
        if !message.is_empty() {
            assert_eq!(error.message, message);
        }
    }
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
            "sleeves[1].steps[1], character 5",
            "Put +, -, * or / between two values.",
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
