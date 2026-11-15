//! [`PyJson`]: a JSON value as Python's `json` module reads and writes it,
//! so that a raw file written here has the bytes the old updater wrote for
//! the same provider replies: `json.dumps(json.loads(reply))`.

use std::collections::HashMap;
use std::fmt::Write;

use crate::Day;

/// Containers nested deeper than this are refused, as preparation's reader
/// (`serde_json`) refuses them.
const DEPTH: usize = 128;

/// A value as `json.loads` reads it:
/// - an object keeps its keys in order; a repeated key keeps its first
///   place and its last value;
/// - an integer is exact, of any length (`-0` is `0`);
/// - a number with a fraction or an exponent is a binary64 float.
///
/// [`parse`](Self::parse) refuses what preparation's reader refuses: NaN,
/// Infinity, numbers beyond the binary64 range (integers included), lone
/// surrogates, a byte-order mark, text that is not UTF-8 and nesting deeper
/// than 128. So every value it gives can be written back and read by
/// `bt data prepare`.
///
/// `==` is Python's: `1 == 1.0`, `true == 1`, an integer equals a float
/// only when exactly equal, and objects compare without order.
#[derive(Clone, Debug)]
pub enum PyJson {
    Null,
    Bool(bool),
    Int(Int),
    Float(f64),
    Str(String),
    List(Vec<PyJson>),
    Object(Object),
}

/// An exact integer.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Int(Digits);

#[derive(Clone, Debug, PartialEq, Eq)]
enum Digits {
    Small(i64),
    /// Decimal text, `-` for a negative value, beyond the `i64` range.
    Big(Box<str>),
}

impl Int {
    /// Python's `float(int)`: the nearest binary64, ties to even. Finite,
    /// since [`PyJson::parse`] refuses larger integers.
    pub fn to_f64(&self) -> f64 {
        match &self.0 {
            Digits::Small(i) => *i as f64,
            Digits::Big(text) => text.parse().expect("integer digits"),
        }
    }

    /// Whether the integer equals the float exactly.
    fn equals(&self, x: f64) -> bool {
        if !x.is_finite() || x.fract() != 0.0 {
            return false;
        }
        match &self.0 {
            // Every i64 lies in [-2^63, 2^63); a float there converts exactly.
            Digits::Small(i) => (-9.223_372_036_854_775_808e18..9.223_372_036_854_775_808e18).contains(&x) && x as i64 == *i,
            // Rust writes a float with precision 0 as its exact integer digits.
            Digits::Big(text) => format!("{x:.0}") == **text,
        }
    }

    fn write(&self, out: &mut String) {
        match &self.0 {
            Digits::Small(i) => write!(out, "{i}").unwrap(),
            Digits::Big(text) => out.push_str(text),
        }
    }
}

impl From<i64> for PyJson {
    fn from(i: i64) -> PyJson {
        PyJson::Int(Int(Digits::Small(i)))
    }
}

impl From<bool> for PyJson {
    fn from(b: bool) -> PyJson {
        PyJson::Bool(b)
    }
}

impl From<&str> for PyJson {
    fn from(text: &str) -> PyJson {
        PyJson::Str(text.to_string())
    }
}

/// An object: its keys in order, each once.
#[derive(Clone, Debug, Default)]
pub struct Object(Vec<(String, PyJson)>);

impl Object {
    pub fn new() -> Object {
        Object(Vec::new())
    }

    pub fn get(&self, key: &str) -> Option<&PyJson> {
        self.0.iter().find(|(k, _)| k == key).map(|(_, v)| v)
    }

    /// Python's `d[key] = value`: an existing key keeps its place.
    pub fn insert(&mut self, key: &str, value: PyJson) {
        match self.0.iter_mut().find(|(k, _)| k == key) {
            Some((_, v)) => *v = value,
            None => self.0.push((key.to_string(), value)),
        }
    }

    pub fn iter(&self) -> impl Iterator<Item = (&str, &PyJson)> {
        self.0.iter().map(|(k, v)| (k.as_str(), v))
    }

    pub fn len(&self) -> usize {
        self.0.len()
    }

    pub fn is_empty(&self) -> bool {
        self.0.is_empty()
    }

    /// The pairs as read, a repeated key in its first place with its last value.
    fn from_pairs(pairs: Vec<(String, PyJson)>) -> Object {
        let mut object = Object(Vec::with_capacity(pairs.len()));
        let mut places: HashMap<String, usize> = HashMap::with_capacity(pairs.len());
        for (key, value) in pairs {
            match places.get(&key) {
                Some(&at) => object.0[at].1 = value,
                None => {
                    places.insert(key.clone(), object.0.len());
                    object.0.push((key, value));
                }
            }
        }
        object
    }
}

impl PartialEq for Object {
    fn eq(&self, other: &Object) -> bool {
        self.len() == other.len() && self.iter().all(|(k, v)| other.get(k) == Some(v))
    }
}

impl PartialEq for PyJson {
    fn eq(&self, other: &PyJson) -> bool {
        match (self, other) {
            (PyJson::Null, PyJson::Null) => true,
            (PyJson::Bool(a), PyJson::Bool(b)) => a == b,
            // A boolean is the integer 1 or 0.
            (PyJson::Bool(a), b) => &PyJson::from(i64::from(*a)) == b,
            (a, PyJson::Bool(b)) => a == &PyJson::from(i64::from(*b)),
            (PyJson::Int(a), PyJson::Int(b)) => a == b,
            (PyJson::Int(a), PyJson::Float(b)) | (PyJson::Float(b), PyJson::Int(a)) => a.equals(*b),
            (PyJson::Float(a), PyJson::Float(b)) => a == b,
            (PyJson::Str(a), PyJson::Str(b)) => a == b,
            (PyJson::List(a), PyJson::List(b)) => a == b,
            (PyJson::Object(a), PyJson::Object(b)) => a == b,
            _ => false,
        }
    }
}

impl PyJson {
    /// `json.loads(bytes)`, refusing the forms the type's comment names. The
    /// error says what is wrong and where.
    pub fn parse(bytes: &[u8]) -> Result<PyJson, String> {
        if bytes.starts_with(b"\xef\xbb\xbf") {
            return Err("a byte-order mark".to_string());
        }
        let text = std::str::from_utf8(bytes).map_err(|e| format!("not UTF-8 at byte {}", e.valid_up_to()))?;
        let mut parser = Parser { text: text.as_bytes(), at: 0 };
        parser.space();
        let value = parser.value(0)?;
        parser.space();
        if parser.at < parser.text.len() {
            return Err(parser.error("extra data"));
        }
        Ok(value)
    }

    /// `json.dumps(value)`: `", "` and `": "` separators, keys in order,
    /// floats as `repr`, text with ASCII escapes.
    pub fn to_text(&self) -> String {
        let mut out = String::new();
        self.write(&mut out, false);
        out
    }

    /// `json.dumps(value, sort_keys=True)`: [`to_text`](Self::to_text) with
    /// the keys of every object in code point order.
    pub fn sorted_text(&self) -> String {
        let mut out = String::new();
        self.write(&mut out, true);
        out
    }

    /// Python's `value.get(key)` of an object; `None` for other values too.
    pub fn get(&self, key: &str) -> Option<&PyJson> {
        match self {
            PyJson::Object(object) => object.get(key),
            _ => None,
        }
    }

    pub fn as_str(&self) -> Option<&str> {
        match self {
            PyJson::Str(text) => Some(text),
            _ => None,
        }
    }

    pub fn as_list(&self) -> Option<&[PyJson]> {
        match self {
            PyJson::List(items) => Some(items),
            _ => None,
        }
    }

    pub fn as_object(&self) -> Option<&Object> {
        match self {
            PyJson::Object(object) => Some(object),
            _ => None,
        }
    }

    /// Python's truth value: `null`, `false`, zero, `""`, `[]` and `{}` are false.
    pub fn truthy(&self) -> bool {
        match self {
            PyJson::Null => false,
            PyJson::Bool(b) => *b,
            PyJson::Int(i) => i.0 != Digits::Small(0),
            PyJson::Float(x) => *x != 0.0,
            PyJson::Str(text) => !text.is_empty(),
            PyJson::List(items) => !items.is_empty(),
            PyJson::Object(object) => !object.is_empty(),
        }
    }

    /// The old updater's number reader (`rules.num`) of a field: a number,
    /// a boolean as 1 or 0, or a text that Python's `float()` reads; `None`
    /// for a missing field, `null`, `""`, a container, or a value that is
    /// not finite. Not ported: underscores between digits and non-ASCII
    /// digits in a text.
    pub fn number(value: Option<&PyJson>) -> Option<f64> {
        let x = match value? {
            PyJson::Bool(b) => f64::from(u8::from(*b)),
            PyJson::Int(i) => i.to_f64(),
            PyJson::Float(x) => *x,
            PyJson::Str(text) => text.trim().parse().ok()?,
            PyJson::Null | PyJson::List(_) | PyJson::Object(_) => return None,
        };
        x.is_finite().then_some(x)
    }

    /// The old updater's date reader (`rules.parse_day`) of a field, on the
    /// form the provider sends: a text whose first ten characters are
    /// `YYYY-MM-DD`. Other values are `None`.
    pub fn day(value: Option<&PyJson>) -> Option<Day> {
        super::day_prefix(value?.as_str()?)
    }

    fn write(&self, out: &mut String, sorted: bool) {
        match self {
            PyJson::Null => out.push_str("null"),
            PyJson::Bool(true) => out.push_str("true"),
            PyJson::Bool(false) => out.push_str("false"),
            PyJson::Int(i) => i.write(out),
            PyJson::Float(x) => out.push_str(&numbers::float_repr(*x)),
            PyJson::Str(text) => write_text(text, out),
            PyJson::List(items) => {
                out.push('[');
                for (i, item) in items.iter().enumerate() {
                    if i > 0 {
                        out.push_str(", ");
                    }
                    item.write(out, sorted);
                }
                out.push(']');
            }
            PyJson::Object(object) => {
                let mut pairs: Vec<&(String, PyJson)> = object.0.iter().collect();
                if sorted {
                    pairs.sort_unstable_by(|a, b| a.0.cmp(&b.0));
                }
                out.push('{');
                for (i, (key, value)) in pairs.into_iter().enumerate() {
                    if i > 0 {
                        out.push_str(", ");
                    }
                    write_text(key, out);
                    out.push_str(": ");
                    value.write(out, sorted);
                }
                out.push('}');
            }
        }
    }
}

/// A text as `json.dumps` writes it with `ensure_ascii`: printable ASCII as
/// is, `"` and `\` escaped, the five short escapes, and every other
/// character as `\u` and four lowercase hex digits, beyond U+FFFF as a
/// surrogate pair.
fn write_text(text: &str, out: &mut String) {
    out.push('"');
    for c in text.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{8}' => out.push_str("\\b"),
            '\u{c}' => out.push_str("\\f"),
            ' '..='~' => out.push(c),
            _ => {
                let mut units = [0u16; 2];
                for unit in c.encode_utf16(&mut units) {
                    write!(out, "\\u{unit:04x}").unwrap();
                }
            }
        }
    }
    out.push('"');
}

struct Parser<'a> {
    text: &'a [u8],
    at: usize,
}

impl Parser<'_> {
    fn error(&self, what: &str) -> String {
        format!("{what} at byte {}", self.at)
    }

    fn space(&mut self) {
        while let Some(b' ' | b'\t' | b'\n' | b'\r') = self.text.get(self.at) {
            self.at += 1;
        }
    }

    fn literal(&mut self, word: &str, value: PyJson) -> Result<PyJson, String> {
        if self.text[self.at..].starts_with(word.as_bytes()) {
            self.at += word.len();
            Ok(value)
        } else {
            Err(self.error("not JSON"))
        }
    }

    fn value(&mut self, depth: usize) -> Result<PyJson, String> {
        match self.text.get(self.at) {
            Some(b'{') => self.object(depth + 1),
            Some(b'[') => self.list(depth + 1),
            Some(b'"') => Ok(PyJson::Str(self.string()?)),
            Some(b't') => self.literal("true", PyJson::Bool(true)),
            Some(b'f') => self.literal("false", PyJson::Bool(false)),
            Some(b'n') => self.literal("null", PyJson::Null),
            Some(b'-' | b'0'..=b'9') => self.number(),
            Some(b'N' | b'I') => Err(self.error("a number that is not finite")),
            _ => Err(self.error("not JSON")),
        }
    }

    fn list(&mut self, depth: usize) -> Result<PyJson, String> {
        if depth >= DEPTH {
            return Err(self.error("nesting too deep"));
        }
        self.at += 1;
        let mut items = Vec::new();
        self.space();
        if self.text.get(self.at) == Some(&b']') {
            self.at += 1;
            return Ok(PyJson::List(items));
        }
        loop {
            self.space();
            items.push(self.value(depth)?);
            self.space();
            match self.text.get(self.at) {
                Some(b',') => self.at += 1,
                Some(b']') => {
                    self.at += 1;
                    return Ok(PyJson::List(items));
                }
                _ => return Err(self.error("expected , or ]")),
            }
        }
    }

    fn object(&mut self, depth: usize) -> Result<PyJson, String> {
        if depth >= DEPTH {
            return Err(self.error("nesting too deep"));
        }
        self.at += 1;
        let mut pairs = Vec::new();
        self.space();
        if self.text.get(self.at) == Some(&b'}') {
            self.at += 1;
            return Ok(PyJson::Object(Object::new()));
        }
        loop {
            self.space();
            if self.text.get(self.at) != Some(&b'"') {
                return Err(self.error("expected a key"));
            }
            let key = self.string()?;
            self.space();
            if self.text.get(self.at) != Some(&b':') {
                return Err(self.error("expected :"));
            }
            self.at += 1;
            self.space();
            pairs.push((key, self.value(depth)?));
            self.space();
            match self.text.get(self.at) {
                Some(b',') => self.at += 1,
                Some(b'}') => {
                    self.at += 1;
                    return Ok(PyJson::Object(Object::from_pairs(pairs)));
                }
                _ => return Err(self.error("expected , or }")),
            }
        }
    }

    /// `-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][-+]?[0-9]+)?`: an integer without
    /// a fraction or exponent, otherwise a float.
    fn number(&mut self) -> Result<PyJson, String> {
        let start = self.at;
        let digits = |p: &mut Self| {
            let from = p.at;
            while p.text.get(p.at).is_some_and(u8::is_ascii_digit) {
                p.at += 1;
            }
            p.at > from
        };
        if self.text[self.at] == b'-' {
            self.at += 1;
            if self.text.get(self.at) == Some(&b'I') {
                return Err(self.error("a number that is not finite"));
            }
        }
        match self.text.get(self.at) {
            Some(b'0') => self.at += 1,
            Some(b'1'..=b'9') => {
                digits(self);
            }
            _ => return Err(self.error("not a number")),
        }
        let mut float = false;
        if self.text.get(self.at) == Some(&b'.') {
            self.at += 1;
            if !digits(self) {
                return Err(self.error("not a number"));
            }
            float = true;
        }
        if let Some(b'e' | b'E') = self.text.get(self.at) {
            self.at += 1;
            if let Some(b'+' | b'-') = self.text.get(self.at) {
                self.at += 1;
            }
            if !digits(self) {
                return Err(self.error("not a number"));
            }
            float = true;
        }
        let text = std::str::from_utf8(&self.text[start..self.at]).unwrap();
        if float {
            let x: f64 = text.parse().unwrap();
            if x.is_infinite() {
                return Err(self.error("a number beyond the binary64 range"));
            }
            return Ok(PyJson::Float(x));
        }
        if let Ok(i) = text.parse::<i64>() {
            return Ok(PyJson::from(i));
        }
        if text.parse::<f64>().unwrap().is_infinite() {
            return Err(self.error("a number beyond the binary64 range"));
        }
        Ok(PyJson::Int(Int(Digits::Big(text.into()))))
    }

    fn string(&mut self) -> Result<String, String> {
        self.at += 1;
        let mut out = String::new();
        loop {
            let from = self.at;
            while let Some(&b) = self.text.get(self.at)
                && b != b'"'
                && b != b'\\'
                && b >= 0x20
            {
                self.at += 1;
            }
            // The text is UTF-8 and the scan stops only at ASCII bytes.
            out.push_str(std::str::from_utf8(&self.text[from..self.at]).unwrap());
            match self.text.get(self.at) {
                Some(b'"') => {
                    self.at += 1;
                    return Ok(out);
                }
                Some(b'\\') => {
                    self.at += 1;
                    let escaped = match self.text.get(self.at) {
                        Some(b'"') => '"',
                        Some(b'\\') => '\\',
                        Some(b'/') => '/',
                        Some(b'b') => '\u{8}',
                        Some(b'f') => '\u{c}',
                        Some(b'n') => '\n',
                        Some(b'r') => '\r',
                        Some(b't') => '\t',
                        Some(b'u') => {
                            self.at += 1;
                            let unit = self.hex()?;
                            let code = match unit {
                                0xd800..=0xdbff if self.text[self.at..].starts_with(b"\\u") => {
                                    self.at += 2;
                                    let low = self.hex()?;
                                    if !(0xdc00..=0xdfff).contains(&low) {
                                        return Err(self.error("a lone surrogate"));
                                    }
                                    0x10000 + ((unit - 0xd800) << 10) + (low - 0xdc00)
                                }
                                0xd800..=0xdfff => return Err(self.error("a lone surrogate")),
                                _ => unit,
                            };
                            out.push(char::from_u32(code).unwrap());
                            continue;
                        }
                        _ => return Err(self.error("an invalid escape")),
                    };
                    self.at += 1;
                    out.push(escaped);
                }
                Some(_) => return Err(self.error("a control character in a text")),
                None => return Err(self.error("an unterminated text")),
            }
        }
    }

    /// Four hex digits.
    fn hex(&mut self) -> Result<u32, String> {
        let digits = self.text.get(self.at..self.at + 4).ok_or_else(|| self.error("an invalid escape"))?;
        if !digits.iter().all(u8::is_ascii_hexdigit) {
            return Err(self.error("an invalid escape"));
        }
        self.at += 4;
        Ok(u32::from_str_radix(std::str::from_utf8(digits).unwrap(), 16).unwrap())
    }
}
