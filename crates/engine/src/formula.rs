//! Formulas: the text a strategy file writes for a variable or a step.
//!
//! [`Formula::read`] accepts and refuses exactly what the Python product's
//! formula editor does (`formula_text.from_text`, then the checks of
//! `variable_authoring.validate`, catalog 4), with the file's earlier
//! variables as its saved variables. A caller gets the checked tree
//! ([`Node`]), its unit and display, and its canonical text: the tree
//! printed as the product's `to_text` prints it, which reads back to the
//! same tree. A refusal is a [`Fault`] with the product's error code and the
//! characters at fault.

use crate::names::{self, Kind, NAMES};
use crate::strategy::{MAX_LITERAL, expand};
use market_data::Day;
use market_data::parameters::{PARAMETERS, Parameter};
use std::sync::{Arc, LazyLock, OnceLock};

/// A checked formula.
#[derive(Debug)]
pub struct Formula {
    tree: Node,
    unit: Unit,
    display: &'static str,
    text: String,
    name: Option<String>,
    /// Its nodes, and its levels once references are expanded.
    nodes: usize,
    expanded: usize,
    /// 1, plus the levels of the definitions it refers to.
    dependency: usize,
}

/// A formula's tree, as the oracle stores it (catalog 4).
#[derive(Debug)]
pub enum Node {
    /// The value of a parameter at the context.
    Parameter(Parameter),
    /// A decimal constant: its text expanded without an exponent.
    Constant { value: String, unit: Unit },
    Neg(Box<Node>),
    Binary { op: Op, left: Box<Node>, right: Box<Node> },
    /// A statistic of the `count` latest yearly values of an `annual.`
    /// parameter; growth and CAGR count `years + 1` values.
    Annual { stat: Stat, count: u32, parameter: Parameter },
    /// `arg` at the context moved `months` calendar months back.
    Lookback { months: u32, arg: Box<Node> },
    /// `arg` at the context of `date`.
    At { date: Day, arg: Box<Node> },
    /// A named measure: its tree, at the same context.
    Measure(&'static Measure),
    /// A file variable: its formula, at the same context.
    Variable(Arc<Formula>),
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Op {
    Add,
    Sub,
    Mul,
    Div,
    /// Division by a value above zero only.
    PositiveDiv,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Stat {
    Mean,
    Min,
    Max,
    Growth,
    Cagr,
}

/// Each statistic, the function word that names it, and whether it reads
/// `years + 1` yearly values (a change across the years).
const STATS: [(Stat, &str, bool); 5] = [
    (Stat::Mean, "average", false),
    (Stat::Min, "min", false),
    (Stat::Max, "max", false),
    (Stat::Growth, "growth", true),
    (Stat::Cagr, "cagr", true),
];

/// The functions that are not statistics.
const OTHER_FUNCTIONS: [&str; 3] = ["ago", "at", "positive"];

/// A unit of the formula catalog.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Unit {
    Scalar,
    Usd,
    UsdPerShare,
    Share,
}

const UNITS: [Unit; 4] = [Unit::Scalar, Unit::Usd, Unit::UsdPerShare, Unit::Share];

impl Unit {
    /// `scalar`, `USD`, `USD/share` or `share`.
    pub fn id(self) -> &'static str {
        match self {
            Unit::Scalar => "scalar",
            Unit::Usd => "USD",
            Unit::UsdPerShare => "USD/share",
            Unit::Share => "share",
        }
    }

    /// The unit of a parameter of [`PARAMETERS`].
    fn of(id: &str) -> Unit {
        UNITS.into_iter().find(|u| u.id() == id).expect("a known unit")
    }

    /// The displays a threshold of this unit can be written in.
    pub fn displays(self) -> &'static [&'static str] {
        match self {
            Unit::Scalar => &["number", "multiple", "percent", "percentage_points"],
            Unit::Usd => &["usd", "usd_million"],
            Unit::UsdPerShare => &["usd_per_share"],
            Unit::Share => &["shares"],
        }
    }

    /// The display of a formula that names none (`vocabulary.DISPLAYS`).
    fn default_display(self) -> &'static str {
        match self {
            Unit::Scalar => "percent",
            Unit::Usd => "usd_million",
            Unit::UsdPerShare => "usd_per_share",
            Unit::Share => "shares",
        }
    }

    /// The exponents of US dollars and shares.
    fn dimensions(self) -> (i32, i32) {
        match self {
            Unit::Scalar => (0, 0),
            Unit::Usd => (1, 0),
            Unit::UsdPerShare => (1, -1),
            Unit::Share => (0, 1),
        }
    }
}

/// A formula reading that failed: the oracle's error code, a message, and
/// the characters `[start, end)` of the fault, counted from 0.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Fault {
    /// SYNTAX, UNKNOWN_NAME, STEP_ONLY and BAD_ARGUMENT come from the text;
    /// UNSUPPORTED_OPERATION, INVALID_SHAPE, INVALID_DATE, INVALID_LITERAL,
    /// UNIT_MISMATCH, UNSUPPORTED_OUTPUT_UNIT and DEFINITION_LIMIT from the
    /// checks of the tree, whose range is the part of the text at fault.
    pub code: &'static str,
    pub message: String,
    pub start: usize,
    pub end: usize,
}

impl Fault {
    /// `characters 12–15`, counted from 1, or `character 4`.
    pub fn place(&self) -> String {
        if self.end > self.start + 1 {
            format!("characters {}–{}", self.start + 1, self.end)
        } else {
            format!("character {}", self.start + 1)
        }
    }
}

impl Formula {
    /// Reads formula text. `earlier` are the file's variables defined before
    /// it, each [`named`](Self::named); a name of the list wins over a
    /// variable's. The display is the default of the formula's unit.
    pub fn read(text: &str, earlier: &[Arc<Formula>]) -> Result<Formula, Fault> {
        let mut reader = Reader::new(text, earlier);
        if reader.text.iter().all(|&c| space(c)) {
            return Err(fault("SYNTAX", 0, reader.text.len(), "Type a formula."));
        }
        let root = reader.sum()?;
        if let Some(c) = reader.peek() {
            let message = if c == ')' { "This ) has no matching (." } else { "Put +, -, * or / between two values." };
            return Err(fault("SYNTAX", reader.at, reader.at + 1, message));
        }
        reader.check(root)
    }

    /// The same formula shown in `display`, or `None` when that is not a
    /// display of its unit.
    pub fn shown_in(self, display: &str) -> Option<Formula> {
        let display = self.unit.displays().iter().find(|&&d| d == display)?;
        Some(Formula { display, ..self })
    }

    /// The same formula as the file variable `name`, which other formulas
    /// refer to by that name.
    pub fn named(self, name: &str) -> Formula {
        Formula { name: Some(name.to_string()), ..self }
    }

    pub fn tree(&self) -> &Node {
        &self.tree
    }

    pub fn unit(&self) -> Unit {
        self.unit
    }

    /// The display its threshold is written in.
    pub fn display(&self) -> &'static str {
        self.display
    }

    /// The canonical text: the tree printed as the oracle's `to_text` does,
    /// each name as the list spells it.
    pub fn text(&self) -> &str {
        &self.text
    }

    /// The file variable's name, when it is one.
    pub fn name(&self) -> Option<&str> {
        self.name.as_deref()
    }
}

/// Two formulas are the same when they print the same, show the same and
/// are the same variable or none.
impl PartialEq for Formula {
    fn eq(&self, other: &Formula) -> bool {
        (&self.text, self.display, &self.name) == (&other.text, other.display, &other.name)
    }
}

impl Eq for Formula {}

/// A named measure of `measures.py` that a formula can reach: the eight
/// compound measures of the list, and the two single-parameter measures they
/// refer to. It prints as its name in the list.
#[derive(Debug)]
pub struct Measure {
    pub key: &'static str,
    built: OnceLock<Built>,
}

#[derive(Debug)]
struct Built {
    tree: Node,
    unit: Unit,
    nodes: usize,
    expanded: usize,
    dependency: usize,
}

static MEASURES: [Measure; 10] = [
    Measure::new("gross_profit"),
    Measure::new("gross_margin"),
    Measure::new("operating_cash_flow_plus_capex"),
    Measure::new("total_debt"),
    Measure::new("net_debt"),
    Measure::new("working_capital"),
    Measure::new("tangible_book_equity"),
    Measure::new("market_cap"),
    Measure::new("price_sales"),
    Measure::new("debt_assets"),
];

impl Measure {
    const fn new(key: &'static str) -> Measure {
        Measure { key, built: OnceLock::new() }
    }

    /// The measure of `measures.py` with this key.
    pub fn of(key: &str) -> &'static Measure {
        MEASURES.iter().find(|m| m.key == key).expect("a known measure")
    }

    pub fn tree(&self) -> &Node {
        &self.built().tree
    }

    pub fn unit(&self) -> Unit {
        self.built().unit
    }

    /// The name it prints as: the list's name of the measure, or of the
    /// parameter a single-parameter measure reads.
    pub fn name(&self) -> &'static str {
        match self.tree() {
            Node::Parameter(p) => term_name(p.id),
            _ => NAMES.iter().find(|n| matches!(n.kind, Kind::Measure { measure, .. } if measure == self.key)).expect("a listed measure").name,
        }
    }

    fn built(&self) -> &Built {
        self.built.get_or_init(|| {
            use Op::*;
            let p = |id| Part::leaf(Node::Parameter(parameter(id)), 0, 0, Unit::of(parameter(id).unit));
            let m = |key| Part::measure(Measure::of(key), 0, 0);
            let both = |op, left: Part, right: Part| Part::binary(op, left, right).0;
            let root = match self.key {
                "gross_profit" => both(Sub, p("annual.revenue"), p("annual.cost_of_revenue")),
                "gross_margin" => both(PositiveDiv, m("gross_profit"), p("annual.revenue")),
                "operating_cash_flow_plus_capex" => both(Add, p("annual.operating_cash_flow"), p("annual.capital_expenditure")),
                "total_debt" => p("annual.total_debt"),
                "net_debt" => both(Sub, m("total_debt"), p("annual.cash_and_equivalents")),
                "working_capital" => both(Sub, p("annual.current_assets"), p("annual.current_liabilities")),
                "tangible_book_equity" => {
                    both(Sub, both(Sub, p("annual.equity"), p("annual.goodwill")), p("annual.intangible_assets"))
                }
                "market_cap" => p("owner.market_cap"),
                "price_sales" => both(PositiveDiv, m("market_cap"), p("annual.revenue")),
                "debt_assets" => both(PositiveDiv, m("total_debt"), p("annual.total_assets")),
                key => unreachable!("no measure {key}"),
            };
            let mut closure = Closure::default();
            closure.of(&root.node);
            Built {
                unit: unit_of(root.dimensions).expect("a measure has a unit"),
                nodes: root.nodes,
                expanded: root.expanded,
                dependency: 1 + closure.dependency,
                tree: root.node,
            }
        })
    }
}

/// The parameter with this id.
fn parameter(id: &str) -> Parameter {
    *PARAMETERS.iter().find(|p| p.id == id).expect("a formula parameter")
}

/// The list's name whose formula term is the parameter `id`.
fn term_name(id: &str) -> &'static str {
    let named = |n: &&names::Name| match n.kind {
        Kind::Input { parameter, .. } => parameter == id,
        Kind::Builtin { term, .. } => term == Some(id),
        _ => false,
    };
    NAMES.iter().find(named).expect("a parameter with a name").name
}

fn fault(code: &'static str, start: usize, end: usize, message: impl Into<String>) -> Fault {
    Fault { code, message: message.into(), start, end }
}

/// The unit with these exponents of US dollars and shares, if any.
fn unit_of(dimensions: (i32, i32)) -> Option<Unit> {
    UNITS.into_iter().find(|u| u.dimensions() == dimensions)
}

/// Python's `str.isspace`, which `\s`, `split` and `strip` use.
fn space(c: char) -> bool {
    c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c)
}

/// A character of `\w`.
fn word(c: char) -> bool {
    c.is_alphanumeric() || c == '_'
}

/// Whether a name starts as a bare word (`[^\W\d_]`).
fn starts_bare(c: char) -> bool {
    word(c) && !c.is_numeric() && c != '_'
}

/// How a name is typed: bare when it starts with a letter, else in brackets.
fn spelling(name: &str) -> String {
    if name.chars().next().is_some_and(starts_bare) { name.to_string() } else { format!("[{}]", name.replace(']', "]]")) }
}

/// Two characters equal ignoring case, as a regular expression with
/// IGNORECASE compares them.
fn same_letter(a: char, b: char) -> bool {
    let lower = |c: char| {
        let mut lower = c.to_lowercase();
        match (lower.next(), lower.next()) {
            (Some(l), None) => l,
            _ => c,
        }
    };
    a == b || lower(a) == lower(b)
}

/// A parsed piece of formula: its node, the characters it spans, and what
/// the checks need.
struct Part {
    node: Node,
    start: usize,
    end: usize,
    dimensions: (i32, i32),
    nodes: usize,
    depth: usize,
    expanded: usize,
    /// `positive(x)`, which only the bottom of a division takes.
    positive: bool,
}

impl Part {
    fn leaf(node: Node, start: usize, end: usize, unit: Unit) -> Part {
        Part { node, start, end, dimensions: unit.dimensions(), nodes: 1, depth: 1, expanded: 1, positive: false }
    }

    fn measure(measure: &'static Measure, start: usize, end: usize) -> Part {
        let built = measure.built();
        Part { expanded: 1 + built.expanded, ..Part::leaf(Node::Measure(measure), start, end, built.unit) }
    }

    fn variable(formula: &Arc<Formula>, start: usize, end: usize) -> Part {
        Part { expanded: 1 + formula.expanded, ..Part::leaf(Node::Variable(formula.clone()), start, end, formula.unit) }
    }

    /// One node over `arg`, with the same unit.
    fn over(arg: Part, start: usize, end: usize, node: impl FnOnce(Box<Node>) -> Node) -> Part {
        Part {
            node: node(Box::new(arg.node)),
            start,
            end,
            dimensions: arg.dimensions,
            nodes: 1 + arg.nodes,
            depth: 1 + arg.depth,
            expanded: 1 + arg.expanded,
            positive: false,
        }
        .bounded()
    }

    /// A part deeper than a formula may be is refused after reading; it
    /// keeps only its counts, so that no tree is too deep to drop.
    fn bounded(mut self) -> Part {
        if self.depth > MAX_DEPTH {
            self.node = Node::Constant { value: String::new(), unit: Unit::Scalar };
        }
        self
    }

    /// Joins two parts; also gives the fault of adding or subtracting
    /// different units.
    fn binary(op: Op, left: Part, right: Part) -> (Part, Option<Fault>) {
        let (start, end) = (left.start, right.end);
        let (l, r) = (left.dimensions, right.dimensions);
        let mut mismatch = None;
        let dimensions = match op {
            Op::Add | Op::Sub => {
                if l != r {
                    mismatch = Some(fault("UNIT_MISMATCH", start, end, "Only values of the same unit can be added or subtracted."));
                }
                l
            }
            Op::Mul => (l.0 + r.0, l.1 + r.1),
            Op::Div | Op::PositiveDiv => (l.0 - r.0, l.1 - r.1),
        };
        let part = Part {
            dimensions,
            nodes: 1 + left.nodes + right.nodes,
            depth: 1 + left.depth.max(right.depth),
            expanded: 1 + left.expanded.max(right.expanded),
            start,
            end,
            positive: false,
            node: Node::Binary { op, left: Box::new(left.node), right: Box::new(right.node) },
        };
        (part.bounded(), mismatch)
    }
}

/// The definitions a formula refers to, each once, with their nodes and the
/// deepest level of reference among them.
#[derive(Default)]
struct Closure {
    seen: Vec<*const ()>,
    nodes: usize,
    dependency: usize,
}

impl Closure {
    fn of(&mut self, node: &Node) {
        match node {
            Node::Measure(m) => {
                let built = m.built();
                self.add(*m as *const Measure as *const (), built.nodes, built.dependency, &built.tree);
            }
            Node::Variable(f) => self.add(Arc::as_ptr(f) as *const (), f.nodes, f.dependency, &f.tree),
            Node::Neg(arg) | Node::Lookback { arg, .. } | Node::At { arg, .. } => self.of(arg),
            Node::Binary { left, right, .. } => {
                self.of(left);
                self.of(right);
            }
            Node::Parameter(_) | Node::Constant { .. } | Node::Annual { .. } => {}
        }
    }

    fn add(&mut self, identity: *const (), nodes: usize, dependency: usize, tree: &Node) {
        self.dependency = self.dependency.max(dependency);
        if !self.seen.contains(&identity) {
            self.seen.push(identity);
            self.nodes += nodes;
            self.of(tree);
        }
    }
}

const MAX_NODES: usize = 256;
const MAX_DEPTH: usize = 32;
const MAX_DEFINITIONS: usize = 32;
const MAX_DEPENDENCY: usize = 8;
const MAX_MONTHS: u64 = 120;
const MAX_YEARLY: u64 = 10;
/// Brackets and signs nested deeper than this stop the reader. The oracle's
/// reader recurses as this one does and fails at Python's recursion limit,
/// around 240 levels; a formula has at most 32 levels of nodes.
const MAX_NESTING: usize = 128;

/// What a known name reads inside a formula.
enum Term {
    Parameter(Parameter),
    Measure(&'static Measure),
    Variable(Arc<Formula>),
    StepOnly,
}

struct Known {
    label: String,
    key: String,
    /// The characters of `key`, which order the names a position can match.
    length: usize,
    words: Vec<Vec<char>>,
    term: Term,
}

impl Known {
    fn new(label: &str, term: Term) -> Known {
        let key = names::key(label);
        let words = label.split(space).filter(|w| !w.is_empty()).map(|w| w.chars().collect()).collect();
        Known { label: label.to_string(), length: key.chars().count(), key, words, term }
    }
}

/// The list's names as a formula reads them.
static LIST: LazyLock<Vec<Known>> = LazyLock::new(|| {
    let term = |kind: &Kind| match *kind {
        Kind::Input { parameter: id, .. } | Kind::Builtin { term: Some(id), .. } => Term::Parameter(parameter(id)),
        Kind::Measure { measure, .. } => Term::Measure(Measure::of(measure)),
        Kind::Builtin { term: None, .. } | Kind::Field(_) => Term::StepOnly,
    };
    NAMES.iter().map(|name| Known::new(name.name, term(&name.kind))).collect()
});

/// The oracle's `_Reader`: a recursive-descent reader over the characters
/// of the text, whose `peek` skips spaces.
struct Reader {
    text: Vec<char>,
    at: usize,
    /// The file's variables; the list follows them.
    variables: Vec<Known>,
    nesting: usize,
    /// The first fault of the tree's own checks and the first unit fault,
    /// each in the tree's order; the checks after reading report them.
    issue: Option<Fault>,
    mismatch: Option<Fault>,
}

impl Reader {
    fn new(text: &str, earlier: &[Arc<Formula>]) -> Reader {
        let variables = earlier
            .iter()
            .map(|f| (f.name().expect("an earlier variable has a name"), f))
            // A name of the list wins over a variable's (the file refuses such variables).
            .filter(|(name, _)| names::find(name).is_none())
            .map(|(name, f)| Known::new(name, Term::Variable(f.clone())))
            .collect();
        Reader { text: text.chars().collect(), at: 0, variables, nesting: 0, issue: None, mismatch: None }
    }

    /// The names a formula knows: the file's variables, then the list.
    fn known(&self) -> impl Iterator<Item = &Known> {
        self.variables.iter().chain(LIST.iter())
    }

    fn char(&self, at: usize) -> Option<char> {
        self.text.get(at).copied()
    }

    fn peek(&mut self) -> Option<char> {
        while self.char(self.at).is_some_and(space) {
            self.at += 1;
        }
        self.char(self.at)
    }

    fn slice(&self, start: usize, end: usize) -> String {
        self.text[start..end].iter().collect()
    }

    fn nest(&mut self) -> Result<(), Fault> {
        self.nesting += 1;
        if self.nesting > MAX_NESTING {
            return Err(fault("DEFINITION_LIMIT", self.at, self.at + 1, "This formula is nested too deeply."));
        }
        Ok(())
    }

    /// Keeps the first fault of the tree's own checks.
    fn note(&mut self, fault: Fault) {
        self.issue.get_or_insert(fault);
    }

    fn sum(&mut self) -> Result<Part, Fault> {
        self.nest()?;
        let mut part = self.product()?;
        while let Some(c @ ('+' | '-')) = self.peek() {
            self.at += 1;
            let right = self.product()?;
            let (joined, mismatch) = Part::binary(if c == '+' { Op::Add } else { Op::Sub }, part, right);
            if let Some(m) = mismatch {
                self.mismatch.get_or_insert(m);
            }
            part = joined;
        }
        self.nesting -= 1;
        Ok(part)
    }

    fn product(&mut self) -> Result<Part, Fault> {
        let mut part = self.unary(false)?;
        while let Some(c @ ('*' | '/')) = self.peek() {
            self.at += 1;
            let right = self.unary(c == '/')?;
            let op = if right.positive { Op::PositiveDiv } else if c == '*' { Op::Mul } else { Op::Div };
            part = Part::binary(op, part, right).0;
        }
        Ok(part)
    }

    fn unary(&mut self, divisor: bool) -> Result<Part, Fault> {
        if self.peek() == Some('-') && self.number(self.at).is_none() {
            let start = self.at;
            self.at += 1;
            self.nest()?;
            let arg = self.unary(false)?;
            self.nesting -= 1;
            let end = arg.end;
            return Ok(Part::over(arg, start, end, Node::Neg));
        }
        self.primary(divisor)
    }

    fn primary(&mut self, divisor: bool) -> Result<Part, Fault> {
        let c = self.peek();
        let start = self.at;
        if let Some(end) = self.number(start) {
            let literal = self.slice(start, end);
            self.at = end;
            let mut unit = Unit::Scalar;
            if let Some((end, found)) = self.unit_word(end) {
                self.at = end;
                unit = found;
            }
            return Ok(self.constant(&literal, unit, start));
        }
        match c {
            Some('(') => {
                self.at += 1;
                let part = self.sum()?;
                self.close(start)?;
                return Ok(Part { start, end: self.at, ..part });
            }
            Some('[') => {
                let name = self.bracketed()?;
                return self.resolve(&name, start, self.at);
            }
            _ => {}
        }
        if let Some((end, part)) = self.whole_name(start).map(|(end, known)| (end, self.term(known, start, end))) {
            self.at = end;
            return part;
        }
        if let Some(end) = self.bare(start) {
            let mut stop = end;
            while stop > start && self.text[stop - 1] == ' ' {
                stop -= 1;
            }
            self.at = stop;
            let found = self.slice(start, stop);
            if stop == end && self.char(stop) == Some('(') {
                return self.call(&found, start, divisor);
            }
            return self.resolve(&found, start, stop);
        }
        Err(match c {
            None => fault("SYNTAX", start, start, "A value is missing at the end."),
            Some(c) if ")+*/,".contains(c) => fault("SYNTAX", start, start + 1, format!("A value is missing before “{c}”.")),
            Some(c) => fault("SYNTAX", start, start + 1, format!("“{c}” cannot start a value.")),
        })
    }

    /// A constant; its literal is checked as the oracle's definition owner
    /// checks it (`definitions._decimal`).
    fn constant(&mut self, literal: &str, unit: Unit, start: usize) -> Part {
        let end = self.at;
        let value = expand(literal, MAX_LITERAL).filter(|value| {
            let number: f64 = value.parse().expect("an expanded decimal");
            number.is_finite() && (number != 0.0 || value == "0")
        });
        let value = value.unwrap_or_else(|| {
            self.note(fault("INVALID_LITERAL", start, end, format!("{literal} is not a number this program can hold.")));
            literal.to_string()
        });
        Part::leaf(Node::Constant { value, unit }, start, end, unit)
    }

    fn close(&mut self, opening: usize) -> Result<(), Fault> {
        if self.peek() != Some(')') {
            return Err(fault("SYNTAX", opening, opening + 1, "This ( has no matching )."));
        }
        self.at += 1;
        Ok(())
    }

    fn bracketed(&mut self) -> Result<String, Fault> {
        let start = self.at;
        let mut name = String::new();
        let mut at = start + 1;
        loop {
            let Some(end) = (at..self.text.len()).find(|&i| self.text[i] == ']') else {
                return Err(fault("SYNTAX", start, self.text.len(), "This [ has no matching ]."));
            };
            name.push_str(&self.slice(at, end));
            if self.char(end + 1) != Some(']') {
                self.at = end + 1;
                return Ok(name);
            }
            name.push(']');
            at = end + 2;
        }
    }

    /// The known name with this matching form.
    fn resolve(&self, name: &str, start: usize, end: usize) -> Result<Part, Fault> {
        let key = names::key(name);
        match self.known().find(|k| k.key == key) {
            Some(known) => self.term(known, start, end),
            None => {
                let usable = self.known().filter(|k| !matches!(k.term, Term::StepOnly)).map(|k| k.label.as_str());
                let hint = hint(name, usable, "");
                Err(fault("UNKNOWN_NAME", start, end, format!("“{name}” is not an input or a saved variable.{hint}")))
            }
        }
    }

    fn term(&self, known: &Known, start: usize, end: usize) -> Result<Part, Fault> {
        Ok(match &known.term {
            Term::Parameter(p) => Part::leaf(Node::Parameter(*p), start, end, Unit::of(p.unit)),
            Term::Measure(m) => Part::measure(m, start, end),
            Term::Variable(f) => Part::variable(f, start, end),
            Term::StepOnly => {
                return Err(fault("STEP_ONLY", start, end, format!("{} can be a step on its own, not part of a formula.", known.label)));
            }
        })
    }

    fn call(&mut self, word: &str, start: usize, divisor: bool) -> Result<Part, Fault> {
        let function = word.to_lowercase();
        let opening = self.at;
        let stat = STATS.iter().find(|s| s.1 == function).map(|&(stat, _, spread)| (stat, spread));
        if stat.is_none() && !OTHER_FUNCTIONS.contains(&function.as_str()) {
            let hint = hint(&function, STATS.iter().map(|s| s.1).chain(OTHER_FUNCTIONS), "(");
            return Err(fault("UNKNOWN_NAME", start, opening, format!("There is no function called “{word}”.{hint}")));
        }
        self.at += 1;
        if function == "positive" {
            if !divisor {
                let message = "positive( ) can only be the bottom of a division, as in Total debt / positive(Shareholders equity).";
                return Err(fault("BAD_ARGUMENT", start, opening, message));
            }
            let arg = self.sum()?;
            self.close(opening)?;
            return Ok(Part { start, end: self.at, positive: true, ..arg });
        }
        self.peek();
        let first = self.at;
        let arg = self.sum()?;
        if stat.is_some() && !matches!(arg.node, Node::Parameter(_)) {
            return Err(fault("BAD_ARGUMENT", first, self.at, format!("{function} works on one yearly input, such as Revenue.")));
        }
        let part = match (function.as_str(), stat) {
            ("at", _) => {
                let message = "Give a date as year-month-day, as in at(Revenue, 2024-12-31).";
                let text = self.argument(|r, at| r.date(at), message)?;
                self.close(opening)?;
                let date = Day::parse(&text).unwrap_or_else(|| {
                    self.note(fault("INVALID_DATE", start, self.at, format!("{text} is not a date.")));
                    Day(0)
                });
                Part::over(arg, start, self.at, |arg| Node::At { date, arg })
            }
            ("ago", _) => {
                let message = "Give a number of months, as in ago(Revenue, 12 months).";
                let months = self.argument(|r, at| r.period(at, "month"), message)?;
                self.close(opening)?;
                if !(1..=MAX_MONTHS).contains(&months) {
                    self.note(fault("INVALID_SHAPE", start, self.at, format!("ago goes back 1 to {MAX_MONTHS} months.")));
                }
                Part::over(arg, start, self.at, |arg| Node::Lookback { months: months.min(u32::MAX.into()) as u32, arg })
            }
            (_, Some((stat, spread))) => {
                let message = format!("Give a number of years, as in {function}(Revenue, 3 years).");
                let years = self.argument(|r, at| r.period(at, "year"), &message)?;
                self.close(opening)?;
                let Node::Parameter(parameter) = arg.node else { unreachable!("checked above") };
                let count = years.saturating_add(u64::from(spread));
                let minimum = 1 + u64::from(spread);
                if !parameter.id.starts_with("annual.") {
                    let name = term_name(parameter.id);
                    self.note(fault("UNSUPPORTED_OPERATION", start, self.at, format!("{function} needs a yearly input; {name} has one value.")));
                } else if !(minimum..=MAX_YEARLY).contains(&count) {
                    let most = MAX_YEARLY - u64::from(spread);
                    self.note(fault("INVALID_SHAPE", start, self.at, format!("{function} takes 1 to {most} years.")));
                }
                let node = Node::Annual { stat, count: count.min(u32::MAX.into()) as u32, parameter };
                let unit = if spread { Unit::Scalar } else { Unit::of(parameter.unit) };
                Part::leaf(node, start, self.at, unit)
            }
            _ => unreachable!("every function is read above"),
        };
        Ok(part)
    }

    /// `, VALUE` read by `read`, or the fault `message` up to the next `)`.
    fn argument<T>(&mut self, read: impl Fn(&Reader, usize) -> Option<(usize, T)>, message: &str) -> Result<T, Fault> {
        let start = self.at;
        if self.peek() == Some(',') {
            self.at += 1;
            self.peek();
            if let Some((end, value)) = read(self, self.at) {
                self.at = end;
                return Ok(value);
            }
        }
        let stop = (start..self.text.len()).find(|&i| self.text[i] == ')').unwrap_or(self.text.len());
        Err(fault("BAD_ARGUMENT", start, stop, message))
    }

    // The oracle's regular expressions, each matched at a position.

    fn digits(&self, at: usize) -> usize {
        (at..self.text.len()).find(|&i| !self.text[i].is_ascii_digit()).unwrap_or(self.text.len())
    }

    /// `[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?`
    fn number(&self, at: usize) -> Option<usize> {
        let mut i = at + usize::from(matches!(self.char(at), Some('+' | '-')));
        let integer = self.digits(i);
        if integer > i {
            i = integer;
            if self.char(i) == Some('.') {
                i = self.digits(i + 1);
            }
        } else if self.char(i) == Some('.') && self.digits(i + 1) > i + 1 {
            i = self.digits(i + 1);
        } else {
            return None;
        }
        if matches!(self.char(i), Some('e' | 'E')) {
            let sign = i + 1 + usize::from(matches!(self.char(i + 1), Some('+' | '-')));
            let end = self.digits(sign);
            if end > sign {
                i = end;
            }
        }
        Some(i)
    }

    /// Whether the text at `at` is `word`, ignoring case.
    fn word_at(&self, at: usize, word: &str) -> Option<usize> {
        let mut i = at;
        for w in word.chars() {
            if !self.char(i).is_some_and(|c| same_letter(c, w)) {
                return None;
            }
            i += 1;
        }
        Some(i)
    }

    /// Spaces only: ` +` or ` *`.
    fn spaces(&self, at: usize) -> usize {
        (at..self.text.len()).find(|&i| self.text[i] != ' ').unwrap_or(self.text.len())
    }

    /// Not followed by `[\w'.&]`.
    fn ends_word(&self, at: usize) -> bool {
        !self.char(at).is_some_and(|c| word(c) || "'.&".contains(c))
    }

    /// ` *(usd +per +share|usd|shares)(?![\w'.&])`, ignoring case.
    fn unit_word(&self, at: usize) -> Option<(usize, Unit)> {
        let at = self.spaces(at);
        // `word`, after one space or more.
        let then = |i: usize, word: &str| Some(self.spaces(i)).filter(|&j| j > i).and_then(|j| self.word_at(j, word));
        let per_share = self.word_at(at, "usd").and_then(|i| then(i, "per")).and_then(|i| then(i, "share"));
        let choices = [(per_share, Unit::UsdPerShare), (self.word_at(at, "usd"), Unit::Usd), (self.word_at(at, "shares"), Unit::Share)];
        choices.into_iter().find_map(|(end, unit)| end.filter(|&e| self.ends_word(e)).map(|e| (e, unit)))
    }

    /// `([0-9]+) *(years?|months?)(?![\w'.&])`, ignoring case, whose word
    /// is `unit` or its plural: the count.
    fn period(&self, at: usize, unit: &str) -> Option<(usize, u64)> {
        let end = self.digits(at);
        if end == at {
            return None;
        }
        let count = self.slice(at, end).parse().unwrap_or(u64::MAX);
        let word = self.spaces(end);
        let found = ["years", "year", "months", "month"].into_iter().find_map(|w| {
            self.word_at(word, w).filter(|&e| self.ends_word(e)).map(|e| (e, w))
        })?;
        (found.1.trim_end_matches('s') == unit).then_some((found.0, count))
    }

    /// `[0-9]{4}-[0-9]{2}-[0-9]{2}(?![\w-])`
    fn date(&self, at: usize) -> Option<(usize, String)> {
        let shape = "dddd-dd-dd";
        for (i, s) in shape.chars().enumerate() {
            let c = self.char(at + i)?;
            if (s == 'd' && !c.is_ascii_digit()) || (s == '-' && c != '-') {
                return None;
            }
        }
        let end = at + shape.len();
        (!self.char(end).is_some_and(|c| word(c) || c == '-')).then(|| (end, self.slice(at, end)))
    }

    /// `[^\W\d_][\w '.&]*`
    fn bare(&self, at: usize) -> Option<usize> {
        if !self.char(at).is_some_and(starts_bare) {
            return None;
        }
        Some((at + 1..self.text.len()).find(|&i| !(word(self.text[i]) || " '.&".contains(self.text[i]))).unwrap_or(self.text.len()))
    }

    /// The longest whole known name at `at`: its words, ignoring case, with
    /// any spaces between them, not followed by `\w` or `(`. Of two names
    /// of the same length, the first known.
    fn whole_name(&self, at: usize) -> Option<(usize, &Known)> {
        let matches = self.known().filter_map(|known| {
            let mut i = at;
            for (n, w) in known.words.iter().enumerate() {
                if n > 0 {
                    let next = (i..self.text.len()).find(|&j| !space(self.text[j])).unwrap_or(self.text.len());
                    if next == i {
                        return None;
                    }
                    i = next;
                }
                for &c in w {
                    if !self.char(i).is_some_and(|t| same_letter(t, c)) {
                        return None;
                    }
                    i += 1;
                }
            }
            let followed = self.char(i).is_some_and(|c| word(c) || c == '(');
            (!known.words.is_empty() && !followed).then_some((i, known))
        });
        matches.fold(None, |best: Option<(usize, &Known)>, (end, known)| match best {
            Some((_, kept)) if kept.length >= known.length => best,
            _ => Some((end, known)),
        })
    }

    /// The checks of the tree after reading, in the oracle's order: the
    /// formula's size, its own checks, the size of what it refers to, its
    /// units, then its size with what it refers to.
    fn check(self, root: Part) -> Result<Formula, Fault> {
        let whole = |message: &str| fault("DEFINITION_LIMIT", 0, self.text.len(), message);
        if root.nodes > MAX_NODES || root.depth > MAX_DEPTH {
            return Err(whole("This formula is too large: at most 256 parts and 32 levels."));
        }
        if let Some(issue) = self.issue {
            return Err(issue);
        }
        let mut closure = Closure::default();
        closure.of(&root.node);
        let large = |definitions: usize, nodes: usize| definitions > MAX_DEFINITIONS || nodes > MAX_NODES;
        if large(closure.seen.len(), closure.nodes) {
            return Err(whole("The variables and measures this formula uses are too large together."));
        }
        if let Some(mismatch) = self.mismatch {
            return Err(mismatch);
        }
        let Some(unit) = unit_of(root.dimensions) else {
            let message = "This formula gives a unit other than a number, US dollars, US dollars per share or shares.";
            return Err(fault("UNSUPPORTED_OUTPUT_UNIT", 0, self.text.len(), message));
        };
        if large(closure.seen.len() + 1, closure.nodes + root.nodes)
            || 1 + closure.dependency > MAX_DEPENDENCY
            || root.expanded > MAX_DEPTH
        {
            return Err(whole("This formula and the variables and measures it uses are too large together."));
        }
        let mut text = String::new();
        write(&root.node, &mut text);
        Ok(Formula {
            text,
            unit,
            display: unit.default_display(),
            name: None,
            nodes: root.nodes,
            expanded: root.expanded,
            dependency: 1 + closure.dependency,
            tree: root.node,
        })
    }
}

/// `; did you mean …?` with up to three of `known` that look like `text`.
fn hint<'a>(text: &str, known: impl IntoIterator<Item = &'a str>, suffix: &str) -> String {
    let close: Vec<String> = names::suggestions(text, known).iter().map(|n| format!("“{}{suffix}”", spelling(n))).collect();
    if close.is_empty() { String::new() } else { format!(" Did you mean {}?", close.join(", ")) }
}

// Printing (`formula_text._write`).

fn precedence(node: &Node) -> u8 {
    match node {
        Node::Binary { op: Op::Add | Op::Sub, .. } => 1,
        Node::Binary { .. } => 2,
        _ => 3,
    }
}

fn write(node: &Node, out: &mut String) {
    let count = |n: u32, word: &str| format!("{n} {word}{}", if n == 1 { "" } else { "s" });
    match node {
        Node::Parameter(p) => out.push_str(&spelling(term_name(p.id))),
        Node::Measure(m) => out.push_str(&spelling(m.name())),
        Node::Variable(f) => out.push_str(&spelling(f.name().expect("a variable has a name"))),
        Node::Constant { value, unit } => {
            out.push_str(&editable(value));
            out.push_str(match unit {
                Unit::Scalar => "",
                Unit::Usd => " USD",
                Unit::UsdPerShare => " USD per share",
                Unit::Share => " shares",
            });
        }
        Node::Neg(arg) => {
            let grouped = matches!(**arg, Node::Binary { .. } | Node::Constant { .. });
            out.push_str(if grouped { "-(" } else { "-" });
            write(arg, out);
            if grouped {
                out.push(')');
            }
        }
        Node::Annual { stat, count: values, parameter } => {
            let &(_, word, spread) = STATS.iter().find(|s| s.0 == *stat).expect("a statistic");
            let years = values - u32::from(spread);
            out.push_str(&format!("{word}({}, {})", spelling(term_name(parameter.id)), count(years, "year")));
        }
        Node::Lookback { months, arg } => {
            out.push_str("ago(");
            write(arg, out);
            out.push_str(&format!(", {})", count(*months, "month")));
        }
        Node::At { date, arg } => {
            out.push_str("at(");
            write(arg, out);
            out.push_str(&format!(", {date})"));
        }
        Node::Binary { op, left, right } => {
            let own = precedence(node);
            let side = |child: &Node, grouped: bool, out: &mut String| {
                if grouped {
                    out.push('(');
                }
                write(child, out);
                if grouped {
                    out.push(')');
                }
            };
            side(left, precedence(left) < own, out);
            out.push_str(match op {
                Op::Add => " + ",
                Op::Sub => " - ",
                Op::Mul => " * ",
                Op::Div | Op::PositiveDiv => " / ",
            });
            if *op == Op::PositiveDiv {
                out.push_str("positive(");
                write(right, out);
                out.push(')');
            } else {
                side(right, precedence(right) <= own, out);
            }
        }
    }
}

/// A constant as the editor shows it (`definitions.authored_bundle`): the
/// expanded decimal, or with an exponent when that is longer than a
/// literal may be.
fn editable(value: &str) -> String {
    if value.chars().count() <= MAX_LITERAL {
        return value.to_string();
    }
    let (sign, unsigned) = value.strip_prefix('-').map_or(("", value), |rest| ("-", rest));
    let (whole, fraction) = unsigned.split_once('.').unwrap_or((unsigned, ""));
    let all = format!("{whole}{fraction}");
    let digits = all.trim_start_matches('0');
    let significant = digits.trim_end_matches('0');
    let power = (digits.len() - significant.len()) as i64 - fraction.len() as i64;
    let exponent = power + significant.len() as i64 - 1;
    let (first, rest) = significant.split_at(1);
    let rest = if rest.is_empty() { String::new() } else { format!(".{rest}") };
    format!("{sign}{first}{rest}e{exponent}")
}
