//! Strategy files: their JSON shape, the checks that need no market data, the
//! canonical form and the identity.
//!
//! ```json
//! {"sleeves": [{"name": "Value", "steps": [
//!   {"filter": "Market cap in dollars", "op": ">=", "value": "100000000"},
//!   {"rank": "EBITDA yield", "order": "highest", "from": 1, "to": 50}]}]}
//! ```
//!
//! - A strategy is one or more sleeves of ordered Filter and Rank steps, 50
//!   steps at most across its sleeves. Each sleeve has a Rank step, and a
//!   name when there are two or more.
//! - A filter compares its source with `<`, `<=`, `>` or `>=` and a decimal
//!   threshold (a JSON string, or a JSON number read as its literal text) in
//!   the source's display unit; Sector and Exchange take `is` or `is not` and
//!   a text.
//! - A rank orders by its source, `highest` or `lowest` first, and keeps the
//!   positions `from` to `to`, whole numbers with 1 ≤ from ≤ to ≤ 5000.
//! - `variables` maps a variable's name to `{"formula": TEXT, "display"?:
//!   DISPLAY}`. A name is not empty and must not reuse a name of the list
//!   or another variable's. A formula ([`crate::formula`]) can name
//!   the variables above it; `display` must be one of its unit's displays,
//!   and is the unit's default when absent.
//! - A source that is one whole name reads, as [`crate::names`] says, a
//!   built-in's stored lane, a field, a file variable, or a formula of an
//!   input or measure in the list's display. Any other source is formula
//!   text, shown in the default display of its unit.
//! - The canonical form is compact JSON: each name as the list spells it,
//!   each formula as its canonical text, each threshold as its decimal text
//!   expanded without an exponent, the keys in the order above, the
//!   variables in file order, each with its display. A formula step whose
//!   text would read as a whole name of another meaning is printed in
//!   parentheses.

use crate::Error;
use crate::formula::Formula;
use crate::names::{self, Field, Kind};
use market_data::builtins::BUILTINS;
use serde::de::{Deserializer, MapAccess, Visitor};
use serde::ser::{SerializeMap, Serializer};
use serde::{Deserialize, Serialize};
use serde_json::value::RawValue;
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::path::Path;
use std::sync::Arc;

/// The most steps a strategy has across its sleeves.
const MAX_STEPS: usize = 50;
/// The highest rank a Rank step keeps.
const MAX_RANK: u32 = 5000;
/// The longest threshold text, and the longest decimal it expands to
/// (`definitions.CEILINGS` literal and expanded_literal).
pub(crate) const MAX_LITERAL: usize = 64;
const MAX_EXPANDED: usize = 1024;

/// A checked strategy file.
#[derive(Debug)]
pub struct Strategy {
    variables: Vec<Arc<Formula>>,
    sleeves: Vec<Sleeve>,
    canonical: String,
}

/// One chain of steps.
#[derive(Debug)]
pub struct Sleeve {
    /// Present when the file names the sleeve; a strategy of two or more
    /// sleeves names each one.
    pub name: Option<String>,
    pub steps: Vec<Step>,
}

#[derive(Debug)]
pub enum Step {
    Filter { source: Source, test: Test },
    Rank { source: Source, order: Order, from: u32, to: u32 },
}

impl Step {
    pub fn source(&self) -> &Source {
        match self {
            Step::Filter { source, .. } | Step::Rank { source, .. } => source,
        }
    }
}

/// What a step reads for each candidate.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Source {
    /// A built-in's stored lane, by its position in [`BUILTINS`].
    Builtin(usize),
    Field(Field),
    /// A formula (a file variable when it is [named](Formula::name)), whose
    /// values are in its unit.
    Formula(Arc<Formula>),
}

impl Source {
    /// The list's name of a built-in or field, the variable's name, or the
    /// formula's canonical text.
    pub fn label(&self) -> &str {
        match self {
            &Source::Builtin(index) => names::of_builtin(index).name,
            &Source::Field(field) => names::of_field(field).name,
            Source::Formula(formula) => formula.name().unwrap_or(formula.text()),
        }
    }

    /// The display its threshold is written in.
    pub fn display(&self) -> &'static str {
        match self {
            &Source::Builtin(index) => BUILTINS[index].display,
            &Source::Field(field) => names::of_field(field).display(),
            Source::Formula(formula) => formula.display(),
        }
    }

    /// The decimal exponent from the source's stored values to its unit.
    pub(crate) fn scale(&self) -> i32 {
        match *self {
            Source::Builtin(index) => BUILTINS[index].scale,
            Source::Field(_) | Source::Formula(_) => 0,
        }
    }
}

/// A filter's comparison.
#[derive(Debug)]
pub enum Test {
    /// The source's value `<`, `<=`, `>` or `>=` the threshold.
    Number(Compare, Threshold),
    /// A text field equal to the text.
    Is(String),
    /// A text field not equal to the text.
    IsNot(String),
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Compare {
    Less,
    AtMost,
    Greater,
    AtLeast,
}

impl Compare {
    pub fn holds(self, value: f64, threshold: f64) -> bool {
        match self {
            Compare::Less => value < threshold,
            Compare::AtMost => value <= threshold,
            Compare::Greater => value > threshold,
            Compare::AtLeast => value >= threshold,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Order {
    Highest,
    Lowest,
}

/// A filter's threshold (`strategy_requests._quantity`).
#[derive(Debug)]
pub struct Threshold {
    /// The decimal text in the display unit, expanded without an exponent,
    /// as the canonical form prints it.
    pub text: String,
    /// The threshold in the source's stored units, which a filter compares
    /// with.
    pub stored: f64,
}

impl Threshold {
    /// Reads decimal `text` in unit `display` for a source whose stored
    /// values are `10 ** scale` of its unit. The text is scaled to the
    /// unit and then to the stored units by moving its decimal exponent,
    /// and read as binary64 once at each step; neither may overflow, or
    /// underflow to zero from a value that is not zero. `display` is a
    /// display or unit name that `definitions.normalize_quantity` knows.
    pub fn new(text: &str, display: &str, scale: i32) -> Result<Threshold, String> {
        let shift = match display {
            "scalar" | "number" | "multiple" | "USD" | "usd" | "USD/share" | "usd_per_share" | "share" | "shares" => 0,
            "percent" | "percentage_points" => -2,
            "usd_million" => 6,
            _ => panic!("unknown display {display}"),
        };
        let out_of_range = || format!("{text:?} is too large or too small for this source");
        let expanded = expand(text, MAX_LITERAL).ok_or_else(|| format!("{text:?} is not a decimal number"))?;
        let canonical = expand(&scaled(&expanded, shift), MAX_EXPANDED).ok_or_else(out_of_range)?;
        let read = |exponent: i32| -> Option<f64> {
            let value: f64 = format!("{canonical}e{exponent}").parse().expect("an expanded decimal");
            (value.is_finite() && (value != 0.0 || canonical == "0")).then_some(value)
        };
        read(0).ok_or_else(out_of_range)?;
        let stored = read(-scale).ok_or_else(out_of_range)?;
        Ok(Threshold { text: expanded, stored })
    }
}

/// `definitions._decimal(value)` (not normalized, no binary64 check): the
/// decimal text without an exponent, leading or trailing zeros, a `+` sign
/// or the sign of zero; `None` when `value` is not a decimal of 1 to
/// `max_length` characters, its exponent exceeds 2048 or the result exceeds
/// [`MAX_EXPANDED`] characters.
pub(crate) fn expand(value: &str, max_length: usize) -> Option<String> {
    if !(1..=max_length).contains(&value.chars().count()) {
        return None;
    }
    let b = value.as_bytes();
    let digits_from = |start: usize| start + b[start..].iter().take_while(|c| c.is_ascii_digit()).count();
    let negative = b[0] == b'-';
    let mut i = usize::from(matches!(b[0], b'-' | b'+'));
    let end = digits_from(i);
    let integer = &value[i..end];
    i = end;
    let fraction = if b.get(i) == Some(&b'.') {
        let end = digits_from(i + 1);
        let fraction = &value[i + 1..end];
        i = end;
        fraction
    } else {
        ""
    };
    if integer.is_empty() && fraction.is_empty() {
        return None;
    }
    let mut exponent = 0i64;
    if matches!(b.get(i), Some(b'e' | b'E')) {
        let start = i + 1;
        let digits = start + usize::from(matches!(b.get(start), Some(b'+' | b'-')));
        let end = digits_from(digits);
        if end == digits {
            return None;
        }
        let significant = value[digits..end].trim_start_matches('0');
        if significant.len() > 4 {
            return None;
        }
        exponent = value[start..end].parse().expect("at most four digits");
        if exponent.abs() > 2048 {
            return None;
        }
        i = end;
    }
    if i != b.len() {
        return None;
    }
    let all = format!("{integer}{fraction}");
    let digits = all.trim_start_matches('0');
    if digits.is_empty() {
        return Some("0".to_string());
    }
    let trimmed = digits.trim_end_matches('0');
    let power = exponent - fraction.len() as i64 + (digits.len() - trimmed.len()) as i64;
    let length = trimmed.len() as i64;
    let point = length + power;
    let unsigned = if power >= 0 {
        point
    } else if point > 0 {
        length + 1
    } else {
        2 - point + length
    };
    if unsigned + i64::from(negative) > MAX_EXPANDED as i64 {
        return None;
    }
    let body = if power >= 0 {
        format!("{trimmed}{}", "0".repeat(power as usize))
    } else if point > 0 {
        format!("{}.{}", &trimmed[..point as usize], &trimmed[point as usize..])
    } else {
        format!("0.{}{trimmed}", "0".repeat(-point as usize))
    };
    Some(if negative { format!("-{body}") } else { body })
}

/// `format(Decimal(text).scaleb(shift), 'f')` for an expanded decimal `text`:
/// the coefficient keeps its trailing zeros, and a zero with a positive
/// exponent is `0`.
fn scaled(text: &str, shift: i32) -> String {
    let (sign, unsigned) = text.strip_prefix('-').map_or(("", text), |rest| ("-", rest));
    let (integer, fraction) = unsigned.split_once('.').unwrap_or((unsigned, ""));
    let all = format!("{integer}{fraction}");
    let coefficient = match all.trim_start_matches('0') {
        "" => "0",
        digits => digits,
    };
    let mut exponent = -(fraction.len() as i64) + i64::from(shift);
    if coefficient == "0" && exponent > 0 {
        exponent = 0;
    }
    let dot = exponent + coefficient.len() as i64;
    let (int_part, frac_part) = if dot < 0 {
        ("0".to_string(), format!("{}{coefficient}", "0".repeat(-dot as usize)))
    } else if dot as usize > coefficient.len() {
        (format!("{coefficient}{}", "0".repeat(dot as usize - coefficient.len())), String::new())
    } else {
        let (a, b) = coefficient.split_at(dot as usize);
        (if a.is_empty() { "0".to_string() } else { a.to_string() }, b.to_string())
    };
    if frac_part.is_empty() { format!("{sign}{int_part}") } else { format!("{sign}{int_part}.{frac_part}") }
}

impl Strategy {
    /// Reads and checks a strategy file. Checks everything that needs no
    /// market data. An error names the file and the step or variable, and
    /// the characters of a formula at fault.
    pub fn read(path: &Path) -> Result<Strategy, Error> {
        let file = path.display().to_string();
        let text = std::fs::read_to_string(path).map_err(|_| Error::new("the strategy file cannot be read as text", &file))?;
        Reader { file }.strategy(&text)
    }

    pub fn sleeves(&self) -> &[Sleeve] {
        &self.sleeves
    }

    /// The file's variables, in file order.
    pub fn variables(&self) -> &[Arc<Formula>] {
        &self.variables
    }

    /// The canonical form: compact JSON that names each source as the list
    /// spells it and prints each formula in its canonical text.
    pub fn canonical(&self) -> &str {
        &self.canonical
    }

    /// The SHA-256 of the canonical form, in lower-case hex.
    pub fn identity(&self) -> String {
        Sha256::digest(self.canonical.as_bytes()).iter().map(|b| format!("{b:02x}")).collect()
    }
}

#[derive(Serialize)]
struct CanonicalFile<'a> {
    #[serde(skip_serializing_if = "<[_]>::is_empty")]
    #[serde(serialize_with = "canonical_variables")]
    variables: &'a [Arc<Formula>],
    sleeves: Vec<CanonicalSleeve<'a>>,
}

/// The variables as a JSON object in file order.
fn canonical_variables<S: Serializer>(variables: &&[Arc<Formula>], serializer: S) -> Result<S::Ok, S::Error> {
    #[derive(Serialize)]
    struct Variable<'a> {
        formula: &'a str,
        display: &'a str,
    }
    let mut map = serializer.serialize_map(Some(variables.len()))?;
    for formula in variables.iter() {
        let name = formula.name().expect("a variable has a name");
        map.serialize_entry(name, &Variable { formula: formula.text(), display: formula.display() })?;
    }
    map.end()
}

#[derive(Serialize)]
struct CanonicalSleeve<'a> {
    #[serde(skip_serializing_if = "Option::is_none")]
    name: Option<&'a str>,
    steps: Vec<CanonicalStep<'a>>,
}

#[derive(Serialize)]
#[serde(untagged)]
enum CanonicalStep<'a> {
    Filter { filter: String, op: &'static str, value: &'a str },
    Rank { rank: String, order: &'static str, from: u32, to: u32 },
}

fn canonical<'a>(sleeves: &'a [Sleeve], variables: &'a [Arc<Formula>]) -> String {
    let step = |step: &'a Step| -> CanonicalStep<'a> {
        match step {
            Step::Filter { source, test } => {
                let (op, value) = match test {
                    Test::Number(Compare::Less, threshold) => ("<", &threshold.text),
                    Test::Number(Compare::AtMost, threshold) => ("<=", &threshold.text),
                    Test::Number(Compare::Greater, threshold) => (">", &threshold.text),
                    Test::Number(Compare::AtLeast, threshold) => (">=", &threshold.text),
                    Test::Is(text) => ("is", text),
                    Test::IsNot(text) => ("is not", text),
                };
                CanonicalStep::Filter { filter: written(source, variables), op, value }
            }
            &Step::Rank { ref source, order, from, to } => {
                let order = if order == Order::Highest { "highest" } else { "lowest" };
                CanonicalStep::Rank { rank: written(source, variables), order, from, to }
            }
        }
    };
    let file = CanonicalFile {
        variables,
        sleeves: sleeves
            .iter()
            .map(|s| CanonicalSleeve { name: s.name.as_deref(), steps: s.steps.iter().map(step).collect() })
            .collect(),
    };
    serde_json::to_string(&file).expect("a strategy serializes")
}

/// The source that `text` names as one whole name of the list or of a file
/// variable, if it is one.
fn whole(text: &str, variables: &[Arc<Formula>]) -> Option<Source> {
    if let Some(name) = names::find(text) {
        return Some(match name.kind {
            Kind::Builtin { .. } => Source::Builtin(name.builtin().expect("a built-in name")),
            Kind::Field(field) => Source::Field(field),
            Kind::Input { display, .. } | Kind::Measure { display, .. } => {
                let formula = Formula::read(name.name, &[]).expect("a listed name reads as a formula");
                Source::Formula(Arc::new(formula.shown_in(display).expect("the list's display suits its unit")))
            }
        });
    }
    let key = names::key(text);
    variables.iter().find(|v| v.name().is_some_and(|name| names::key(name) == key)).map(|v| Source::Formula(v.clone()))
}

/// How the canonical form writes a step's source: its name, or a formula's
/// canonical text, in parentheses while that would read as a whole name of
/// another meaning (`(ROE)` is the formula of `owner.roe`, `ROE` the lane).
fn written(source: &Source, variables: &[Arc<Formula>]) -> String {
    let mut text = source.label().to_string();
    if matches!(source, Source::Formula(formula) if formula.name().is_none()) {
        while whole(&text, variables).is_some_and(|other| other != *source) {
            text = format!("({text})");
        }
    }
    text
}

/// A JSON object's entries in file order.
struct Ordered<'a>(Vec<(String, &'a RawValue)>);

impl<'de> Deserialize<'de> for Ordered<'de> {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        struct Entries;
        impl<'de> Visitor<'de> for Entries {
            type Value = Ordered<'de>;
            fn expecting(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
                f.write_str("a JSON object")
            }
            fn visit_map<M: MapAccess<'de>>(self, mut map: M) -> Result<Ordered<'de>, M::Error> {
                let mut entries = Vec::new();
                while let Some(entry) = map.next_entry()? {
                    entries.push(entry);
                }
                Ok(Ordered(entries))
            }
        }
        deserializer.deserialize_map(Entries)
    }
}

/// Reads one file; `file` is its path as errors name it.
struct Reader {
    file: String,
}

type Object<'a> = BTreeMap<String, &'a RawValue>;

impl Reader {
    fn fail<T>(&self, place: &str, message: impl Into<String>) -> Result<T, Error> {
        let place = if place.is_empty() { self.file.clone() } else { format!("{}: {place}", self.file) };
        Err(Error::new(message, place))
    }

    fn strategy(&self, text: &str) -> Result<Strategy, Error> {
        let root: &RawValue = match serde_json::from_str(text) {
            Ok(root) => root,
            Err(e) => return self.fail("", format!("is not JSON (line {}, column {})", e.line(), e.column())),
        };
        let root = self.object(root, "", &["sleeves"], &["variables"])?;
        let variables = match root.get("variables") {
            Some(raw) => self.variables(raw)?,
            None => Vec::new(),
        };
        let listed = self.list(root["sleeves"], "sleeves", "a list of sleeves")?;
        if listed.is_empty() {
            return self.fail("sleeves", "needs at least one sleeve");
        }
        let several = listed.len() > 1;
        let mut raw_sleeves = Vec::new();
        for (n, raw) in listed.iter().enumerate() {
            let place = format!("sleeves[{}]", n + 1);
            let sleeve = self.object(raw, &place, &["steps"], &["name"])?;
            let name = match sleeve.get("name") {
                Some(raw) => {
                    let name = self.string(raw, &format!("{place}.name"), "the sleeve's name")?;
                    if name.is_empty() {
                        return self.fail(&format!("{place}.name"), "a sleeve name is not empty");
                    }
                    Some(name)
                }
                None if several => return self.fail(&place, "needs a name, because the strategy has several sleeves"),
                None => None,
            };
            raw_sleeves.push((place.clone(), name, self.list(sleeve["steps"], &format!("{place}.steps"), "a list of steps")?));
        }
        let count: usize = raw_sleeves.iter().map(|(_, _, steps)| steps.len()).sum();
        if count > MAX_STEPS {
            return self.fail("", format!("has {count} steps across its sleeves; the most is {MAX_STEPS}"));
        }
        let mut sleeves = Vec::new();
        for (place, name, raw_steps) in raw_sleeves {
            let steps = raw_steps
                .iter()
                .enumerate()
                .map(|(m, raw)| self.step(raw, &format!("{place}.steps[{}]", m + 1), &variables))
                .collect::<Result<Vec<_>, _>>()?;
            if !steps.iter().any(|s| matches!(s, Step::Rank { .. })) {
                return self.fail(&place, "needs a Rank step");
            }
            sleeves.push(Sleeve { name, steps });
        }
        let canonical = canonical(&sleeves, &variables);
        Ok(Strategy { variables, sleeves, canonical })
    }

    /// The file's variables in file order, each read with the ones above it.
    fn variables(&self, raw: &RawValue) -> Result<Vec<Arc<Formula>>, Error> {
        let Ok(Ordered(entries)) = serde_json::from_str(raw.get()) else {
            return self.fail("variables", "must be a JSON object");
        };
        let mut variables: Vec<Arc<Formula>> = Vec::new();
        for (written, raw) in entries {
            let place = format!("variables.{written:?}");
            let name = written.trim();
            if name.is_empty() {
                return self.fail(&place, "a variable name is not empty");
            }
            if let Some(listed) = names::find(name) {
                return self.fail(&place, format!("a variable cannot reuse the name {:?}", listed.name));
            }
            if let Some(other) = variables.iter().filter_map(|v| v.name()).find(|v| names::key(v) == names::key(name)) {
                return self.fail(&place, format!("is the same name as the variable {other:?}"));
            }
            let fields = self.object(raw, &place, &["formula"], &["display"])?;
            let text = self.string(fields["formula"], &format!("{place}.formula"), "the formula text")?;
            let formula = Formula::read(&text, &variables).or_else(|fault| self.fail(&format!("{place}, {}", fault.place()), fault.message))?;
            let formula = match fields.get("display") {
                Some(raw) => {
                    let place = format!("{place}.display");
                    let display = self.string(raw, &place, "a display name")?;
                    let unit = formula.unit();
                    formula.shown_in(&display).map_or_else(
                        || self.fail(&place, format!("{display:?} is not a display of {}: use {}", unit.id(), unit.displays().join(", "))),
                        Ok,
                    )?
                }
                None => formula,
            };
            variables.push(Arc::new(formula.named(name)));
        }
        Ok(variables)
    }

    fn step(&self, raw: &RawValue, place: &str, variables: &[Arc<Formula>]) -> Result<Step, Error> {
        let fields = self.any_object(raw, place)?;
        if fields.contains_key("filter") {
            self.keys(&fields, place, &["filter", "op", "value"], &[])?;
            let text = self.string(fields["filter"], place, "the filter's source")?;
            let source = self.source(&text, place, variables)?;
            let op = self.string(fields["op"], place, "the comparison")?;
            let text_field = matches!(source, Source::Field(field) if field.is_text());
            let compare = match op.as_str() {
                "<" => Some(Compare::Less),
                "<=" => Some(Compare::AtMost),
                ">" => Some(Compare::Greater),
                ">=" => Some(Compare::AtLeast),
                "is" | "is not" => None,
                _ => return self.fail(place, format!("{op:?} is not a comparison: use <, <=, >, >=, is or is not")),
            };
            let name = source.label();
            let test = match compare {
                Some(_) if text_field => return self.fail(place, format!("{name} is text: compare it with is or is not")),
                None if !text_field => return self.fail(place, format!("{op} compares Sector or Exchange only; {name} is a number")),
                Some(compare) => {
                    let value = fields["value"];
                    let text = match value.get().trim_start().as_bytes().first() {
                        Some(b'"') => self.string(value, place, "the threshold")?,
                        Some(b'-' | b'0'..=b'9') => value.get().trim().to_string(),
                        _ => return self.fail(place, "the threshold is decimal text or a JSON number"),
                    };
                    let threshold = Threshold::new(&text, source.display(), source.scale())
                        .or_else(|message| self.fail(place, format!("threshold: {message}")))?;
                    Test::Number(compare, threshold)
                }
                None => {
                    let value = self.string(fields["value"], place, "the text to compare with")?;
                    if op == "is" { Test::Is(value) } else { Test::IsNot(value) }
                }
            };
            return Ok(Step::Filter { source, test });
        }
        if fields.contains_key("rank") {
            self.keys(&fields, place, &["rank", "order", "from", "to"], &[])?;
            let text = self.string(fields["rank"], place, "the rank's source")?;
            let source = self.source(&text, place, variables)?;
            if matches!(source, Source::Field(field) if field.is_text()) {
                return self.fail(place, format!("{} is text and cannot rank", source.label()));
            }
            let order = match self.string(fields["order"], place, "the order")?.as_str() {
                "highest" => Order::Highest,
                "lowest" => Order::Lowest,
                other => return self.fail(place, format!("{other:?} is not an order: use highest or lowest")),
            };
            let rank = |key: &str| serde_json::from_str::<u32>(fields[key].get()).ok().filter(|r| (1..=MAX_RANK).contains(r));
            let (Some(from), Some(to)) = (rank("from"), rank("to")) else {
                return self.fail(place, format!("from and to are whole numbers from 1 to {MAX_RANK}"));
            };
            if from > to {
                return self.fail(place, "from is at most to");
            }
            return Ok(Step::Rank { source, order, from, to });
        }
        self.fail(place, "a step has the keys filter, op and value, or rank, order, from and to")
    }

    /// The source one step names: a whole name, else formula text.
    fn source(&self, text: &str, place: &str, variables: &[Arc<Formula>]) -> Result<Source, Error> {
        if let Some(source) = whole(text, variables) {
            return Ok(source);
        }
        match Formula::read(text, variables) {
            Ok(formula) => Ok(Source::Formula(Arc::new(formula))),
            Err(fault) => self.fail(&format!("{place}, {}", fault.place()), fault.message),
        }
    }

    /// A JSON object with the `required` keys and no keys outside
    /// `required` and `optional`.
    fn object<'a>(&self, raw: &'a RawValue, place: &str, required: &[&str], optional: &[&str]) -> Result<Object<'a>, Error> {
        let object = self.any_object(raw, place)?;
        self.keys(&object, place, required, optional)?;
        Ok(object)
    }

    /// A JSON object with any keys.
    fn any_object<'a>(&self, raw: &'a RawValue, place: &str) -> Result<Object<'a>, Error> {
        if !raw.get().trim_start().starts_with('{') {
            return self.fail(place, "must be a JSON object");
        }
        serde_json::from_str(raw.get()).or_else(|_| self.fail(place, "must be a JSON object"))
    }

    /// Checks that `object` has the `required` keys and no keys outside
    /// `required` and `optional`.
    fn keys(&self, object: &Object<'_>, place: &str, required: &[&str], optional: &[&str]) -> Result<(), Error> {
        if let Some(missing) = required.iter().find(|k| !object.contains_key(**k)) {
            return self.fail(place, format!("needs the key {missing:?}"));
        }
        if let Some(unknown) = object.keys().find(|k| !required.contains(&k.as_str()) && !optional.contains(&k.as_str())) {
            let keys: Vec<&str> = required.iter().chain(optional).copied().collect();
            return self.fail(place, format!("has the unknown key {unknown:?}; the keys are {}", keys.join(", ")));
        }
        Ok(())
    }

    fn list<'a>(&self, raw: &'a RawValue, place: &str, what: &str) -> Result<Vec<&'a RawValue>, Error> {
        if !raw.get().trim_start().starts_with('[') {
            return self.fail(place, format!("must be {what}"));
        }
        Ok(serde_json::from_str(raw.get()).expect("a JSON list"))
    }

    fn string(&self, raw: &RawValue, place: &str, what: &str) -> Result<String, Error> {
        serde_json::from_str(raw.get()).or_else(|_| self.fail(place, format!("{what} must be a JSON string")))
    }
}
