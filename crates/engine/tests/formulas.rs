//! Formula text against the oracle: the vectors in fixtures/formulas/,
//! written by proof/formula_vectors.py from the Python product's formula
//! editor. Each case must give the same canonical text, tree, unit and
//! display, or the same error code (and the same characters for an error of
//! the text).

use engine::formula::{Formula, Node, Op, Stat};
use serde::Deserialize;
use serde_json::{Value, json};
use std::collections::BTreeMap;
use std::sync::Arc;

#[derive(Deserialize)]
struct Vectors {
    libraries: BTreeMap<String, Vec<(String, String, Option<String>)>>,
    cases: Vec<Case>,
}

#[derive(Deserialize)]
struct Case {
    text: String,
    library: Option<String>,
    /// A library variable's own case: read with the variables before it.
    before: Option<String>,
    display: Option<String>,
    result: Option<Expected>,
    error: Option<Refusal>,
}

#[derive(Deserialize, Debug)]
struct Expected {
    text: String,
    tree: Value,
    unit: String,
    display: String,
}

#[derive(Deserialize, Debug)]
struct Refusal {
    code: String,
    start: Option<usize>,
    end: Option<usize>,
}

/// The tree as the vectors write it.
fn dump(node: &Node) -> Value {
    match node {
        Node::Parameter(p) => json!({"op": "parameter", "id": p.id}),
        Node::Constant { value, unit } => json!({"op": "constant", "value": value, "unit": unit.id()}),
        Node::Neg(arg) => json!({"op": "neg", "arg": dump(arg)}),
        Node::Binary { op, left, right } => {
            let op = match op {
                Op::Add => "add",
                Op::Sub => "sub",
                Op::Mul => "mul",
                Op::Div => "div",
                Op::PositiveDiv => "positive_div",
            };
            json!({"op": op, "left": dump(left), "right": dump(right)})
        }
        Node::Annual { stat, count, parameter } => {
            let stat = match stat {
                Stat::Mean => "mean",
                Stat::Min => "min",
                Stat::Max => "max",
                Stat::Growth => "growth",
                Stat::Cagr => "cagr",
            };
            json!({"op": "annual", "stat": stat, "count": count, "parameter": parameter.id})
        }
        Node::Lookback { months, arg } => json!({"op": "lookback", "months": months, "arg": dump(arg)}),
        Node::At { date, arg } => json!({"op": "at", "date": date.to_string(), "arg": dump(arg)}),
        Node::Measure(m) => json!({"op": "ref", "measure": m.key, "tree": dump(m.tree())}),
        Node::Variable(f) => json!({"op": "ref", "variable": f.name()}),
    }
}

/// Reads `text` as the file's variable or step formula with `earlier`.
fn read(text: &str, display: Option<&str>, earlier: &[Arc<Formula>]) -> Result<Formula, engine::formula::Fault> {
    let formula = Formula::read(text, earlier)?;
    Ok(match display {
        Some(display) => formula.shown_in(display).expect("a display that suits the unit"),
        None => formula,
    })
}

#[test]
fn formula_text_reads_and_prints_as_the_oracle_does() {
    let path = format!("{}/../../fixtures/formulas/vectors.json", env!("CARGO_MANIFEST_DIR"));
    let vectors: Vectors = serde_json::from_str(&std::fs::read_to_string(&path).unwrap()).unwrap();
    // Each library's variables, and those before each variable; a refused
    // variable is left out, as the oracle's editor leaves it out.
    let mut libraries = BTreeMap::new();
    let mut before = BTreeMap::new();
    for (name, variables) in &vectors.libraries {
        let mut defined: Vec<Arc<Formula>> = Vec::new();
        for (variable, text, display) in variables {
            before.insert((name.clone(), variable.clone()), defined.clone());
            if let Ok(formula) = read(text, display.as_deref(), &defined) {
                defined.push(Arc::new(formula.named(variable)));
            }
        }
        libraries.insert(name.clone(), defined);
    }
    let mut failures = Vec::new();
    for case in &vectors.cases {
        let earlier = match (&case.library, &case.before) {
            (Some(library), Some(variable)) => before[&(library.clone(), variable.clone())].clone(),
            (Some(library), None) => libraries[library].clone(),
            _ => Vec::new(),
        };
        let found = read(&case.text, case.display.as_deref(), &earlier);
        let same = match (&found, &case.result, &case.error) {
            (Ok(f), Some(e), None) => f.text() == e.text && dump(f.tree()) == e.tree && f.unit().id() == e.unit && f.display() == e.display,
            (Err(fault), None, Some(e)) => {
                fault.code == e.code && e.start.is_none_or(|s| s == fault.start) && e.end.is_none_or(|end| end == fault.end)
            }
            _ => false,
        };
        if !same {
            let found = match &found {
                Ok(f) => format!("{} {} {} {}", f.text(), dump(f.tree()), f.unit().id(), f.display()),
                Err(fault) => format!("{fault:?}"),
            };
            failures.push(format!("{:?}: expected {:?} {:?}, found {found}", case.text, case.result, case.error));
        }
    }
    assert!(failures.is_empty(), "{} of {} vectors differ:\n{}", failures.len(), vectors.cases.len(), failures.join("\n"));
}

#[test]
fn a_field_or_a_name_the_oracle_does_not_list_is_step_only_inside_a_formula() {
    for (text, start, end) in [("Sector", 0, 6), ("2 * Market cap in dollars", 4, 25), ("[Free cash flow] / 2", 0, 16)] {
        let fault = Formula::read(text, &[]).unwrap_err();
        assert_eq!((fault.code, fault.start, fault.end), ("STEP_ONLY", start, end), "{text}");
    }
}

#[test]
fn very_long_or_deep_texts_are_refused() {
    let long = vec!["Revenue"; 20_000].join(" + ");
    let deep = format!("{}Revenue{}", "(".repeat(10_000), ")".repeat(10_000));
    let negated = format!("{}Revenue", "-".repeat(20_000));
    for text in [long, deep, negated] {
        assert_eq!(Formula::read(&text, &[]).unwrap_err().code, "DEFINITION_LIMIT");
    }
}
