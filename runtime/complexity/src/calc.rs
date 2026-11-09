//! `code-audit-complexity calc`: exact arithmetic, so a reported number comes from a
//! computation and not from a model's mental arithmetic.
//!
//! This is the fast form of `skills/code-principles/scripts/calc.py` and follows the same
//! rules; `calc_vectors.json` beside that script is run against both so they cannot drift.
//!
//! Accepted: numbers, `+ - * / // % **`, parentheses, and the functions in `call`. Nothing
//! else parses, so an expression copied from a repository under review cannot run code.
//! Integers and fractions stay exact; a float literal, `sqrt`, `log` or a fractional power
//! makes the result a float. Semantics follow Python: `//` and `%` floor, `**` binds tighter
//! than a leading minus and associates to the right, `round` sends a tie to the even digit.
//!
//! Budgets: an expression is at most `MAX_CHARS` characters and `MAX_PARTS` numbers and
//! operations, and every exact value is at most `MAX_BITS` bits, checked before a power is
//! computed. Work and memory are therefore bounded for any input.

use num_bigint::BigInt;
use num_integer::Integer;
use num_rational::BigRational;
use num_traits::{One, Signed, ToPrimitive, Zero};
use std::cmp::Ordering;

const MAX_BITS: u64 = 4096;
const MAX_ROUND_DIGITS: i64 = 60;
const MAX_CHARS: usize = 2000;
const MAX_PARTS: usize = 256;
const MAX_NESTING: usize = 200;
const TOLERANCE: f64 = 1e-9;
const COMPARISONS: [&str; 6] = ["==", "!=", "<=", ">=", "<", ">"];

#[derive(Clone, Debug)]
enum Value {
    Exact(BigRational),
    Float(f64),
}

type Outcome<T> = Result<T, String>;

fn exact(value: BigRational) -> Outcome<Value> {
    if value.numer().bits().max(value.denom().bits()) > MAX_BITS {
        return Err(format!("exact result is larger than {MAX_BITS} bits; use a float (write 2.0 for 2) or a smaller expression"));
    }
    Ok(Value::Exact(value))
}

/// The only way a float value is made, so infinity and not-a-number never reach an operation.
fn float(value: f64) -> Outcome<Value> {
    if value.is_finite() { Ok(Value::Float(value)) } else { Err("result is not a finite real number".into()) }
}

fn integer(value: BigInt) -> Outcome<Value> {
    exact(BigRational::from_integer(value))
}

/// The float nearest an exact value; an error when it is outside float range.
fn to_float(value: &BigRational) -> Outcome<f64> {
    match value.to_f64() {
        Some(f) if f.is_finite() => Ok(f),
        _ => Err("exact value is outside float range".into()),
    }
}

fn as_float(value: &Value) -> Outcome<f64> {
    match value {
        Value::Exact(r) => to_float(r),
        Value::Float(f) => Ok(*f),
    }
}

/// The exact value a finite float holds.
fn as_exact(value: &Value) -> Outcome<BigRational> {
    match value {
        Value::Exact(r) => Ok(r.clone()),
        Value::Float(f) => BigRational::from_float(*f).ok_or_else(|| "value is not a finite real number".to_string()),
    }
}

fn is_zero(value: &Value) -> bool {
    match value {
        Value::Exact(r) => r.is_zero(),
        Value::Float(f) => *f == 0.0,
    }
}

/// Numeric order of two values, exact when both are finite.
fn compare(a: &Value, b: &Value) -> Outcome<Ordering> {
    match (as_exact(a), as_exact(b)) {
        (Ok(x), Ok(y)) => Ok(x.cmp(&y)),
        _ => as_float(a)?.partial_cmp(&as_float(b)?).ok_or_else(|| "values cannot be ordered".to_string()),
    }
}

fn floor_div_float(a: f64, b: f64) -> (f64, f64) {
    // Python's float divmod: the remainder takes the sign of the divisor.
    let mut remainder = a % b;
    let mut quotient = (a - remainder) / b;
    if remainder != 0.0 {
        if (b < 0.0) != (remainder < 0.0) {
            remainder += b;
            quotient -= 1.0;
        }
    } else {
        remainder = 0.0_f64.copysign(b);
    }
    let floored = if quotient != 0.0 {
        let f = quotient.floor();
        if quotient - f > 0.5 { f + 1.0 } else { f }
    } else {
        0.0_f64.copysign(a / b)
    };
    (floored, remainder)
}

fn binary(op: &str, a: Value, b: Value) -> Outcome<Value> {
    if matches!(op, "/" | "//" | "%") && is_zero(&b) {
        return Err("division by zero".into());
    }
    if let (Value::Exact(x), Value::Exact(y)) = (&a, &b) {
        return match op {
            "+" => exact(x + y),
            "-" => exact(x - y),
            "*" => exact(x * y),
            "/" => exact(x / y),
            "//" => exact((x / y).floor()),
            "%" => exact(x - y * (x / y).floor()),
            _ => Err(format!("unknown operator {op}")),
        };
    }
    let (x, y) = (as_float(&a)?, as_float(&b)?);
    float(match op {
        "+" => x + y,
        "-" => x - y,
        "*" => x * y,
        "/" => x / y,
        "//" => floor_div_float(x, y).0,
        "%" => floor_div_float(x, y).1,
        _ => return Err(format!("unknown operator {op}")),
    })
}

/// log2 of a positive integer of any size.
fn log2(value: &BigInt) -> f64 {
    let bits = value.bits();
    if bits <= 512 {
        return value.to_f64().unwrap_or(f64::INFINITY).log2();
    }
    let shift = bits - 64;
    (value >> shift).to_f64().unwrap_or(f64::INFINITY).log2() + shift as f64
}

fn power(base: Value, exponent: Value) -> Outcome<Value> {
    if let (Value::Exact(b), Value::Exact(e)) = (&base, &exponent) {
        if e.is_integer() {
            let e = e.to_integer();
            let magnitude = b.numer().abs().max(b.denom().clone());
            if b.is_zero() && e.is_negative() {
                return Err("division by zero".into());
            }
            if magnitude.is_one() || b.is_zero() {
                // 0, 1 and -1: no growth, whatever the exponent.
                let negative = b.is_negative() && e.is_odd();
                let one = if b.is_zero() && !e.is_zero() { BigInt::zero() } else { BigInt::one() };
                return integer(if negative { -one } else { one });
            }
            // Checked before computing: the result has about exponent x log2(base) bits.
            let size = e.abs().to_f64().unwrap_or(f64::INFINITY) * log2(&magnitude) + 1.0;
            if size > MAX_BITS as f64 {
                return Err(format!("exact power would exceed {MAX_BITS} bits; use a float base (write 2.0 for 2) or a smaller exponent"));
            }
            let n = e.abs().to_u32().ok_or("exponent is too large")?;
            let (numer, denom) = (b.numer().pow(n), b.denom().pow(n));
            return exact(if e.is_negative() { BigRational::new(denom, numer) } else { BigRational::new(numer, denom) });
        }
    }
    let (b, e) = (as_float(&base)?, as_float(&exponent)?);
    let result = b.powf(e);
    if result.is_nan() && !b.is_nan() && !e.is_nan() {
        return Err("result is not a real number".into());
    }
    if result.is_infinite() && b.is_finite() && e.is_finite() {
        return Err(if b == 0.0 { "division by zero".into() } else { "result is outside float range".to_string() });
    }
    float(result)
}

fn negate(value: Value) -> Value {
    match value {
        Value::Exact(r) => Value::Exact(-r),
        Value::Float(f) => Value::Float(-f),
    }
}

/// Round to the nearest integer, a tie going to the even one.
fn round_half_even(value: &BigRational) -> BigInt {
    let floor = value.floor().to_integer();
    let half = BigRational::new(BigInt::one(), BigInt::from(2));
    match (value - BigRational::from_integer(floor.clone())).cmp(&half) {
        Ordering::Less => floor,
        Ordering::Greater => floor + 1,
        Ordering::Equal => if floor.is_even() { floor } else { floor + 1 },
    }
}

fn round(arguments: &[Value]) -> Outcome<Value> {
    let (value, digits) = match arguments {
        [value] => (value, None),
        [value, Value::Exact(d)] if d.is_integer() && d.to_integer().abs() <= BigInt::from(MAX_ROUND_DIGITS) => (value, d.to_integer().to_i64()),
        _ => return Err(format!("round takes a value and a whole number of digits between -{MAX_ROUND_DIGITS} and {MAX_ROUND_DIGITS}")),
    };
    let source = as_exact(value)?;
    let Some(digits) = digits else { return integer(round_half_even(&source)) };
    let scale = BigRational::from_integer(BigInt::from(10).pow(digits.unsigned_abs() as u32));
    let scaled = if digits >= 0 { &source * &scale } else { &source / &scale };
    let rounded = BigRational::from_integer(round_half_even(&scaled));
    let result = if digits >= 0 { rounded / scale } else { rounded * scale };
    match value {
        Value::Exact(_) => exact(result),
        Value::Float(_) => float(to_float(&result)?),
    }
}

fn total(values: &[Value]) -> Outcome<Value> {
    // The size budget is checked after every addition, so many large fractions cannot build a huge denominator.
    values.iter().try_fold(Value::Exact(BigRational::zero()), |sum, value| binary("+", sum, value.clone()))
}

fn count(values: &[Value]) -> Value {
    Value::Exact(BigRational::from_integer(BigInt::from(values.len())))
}

fn sorted(values: &[Value]) -> Outcome<Vec<Value>> {
    let mut failure = None;
    let mut ordered = values.to_vec();
    ordered.sort_by(|a, b| compare(a, b).unwrap_or_else(|e| {
        failure = Some(e);
        Ordering::Equal
    }));
    failure.map_or(Ok(ordered), Err)
}

/// The float nearest the square root of n/d, for positive n and d. CPython's
/// `statistics._float_sqrt_of_frac`: an integer square root kept to 109 bits and rounded to odd,
/// so the one final rounding is correct and a tiny or huge ratio never passes through a float.
fn float_sqrt_of_ratio(n: &BigInt, d: &BigInt) -> Outcome<f64> {
    const WIDTH: i64 = 2 * 53 + 3;
    let q = (n.bits() as i64 - d.bits() as i64 - WIDTH).div_euclid(2);
    let rounded_to_odd = |n: BigInt, d: BigInt| {
        let root = (&n / &d).sqrt();
        let inexact = &root * &root * &d != n;
        root | BigInt::from(inexact as u8)
    };
    let ratio = if q >= 0 {
        BigRational::from_integer(rounded_to_odd(n.clone(), d << (2 * q) as usize) << q as usize)
    } else {
        BigRational::new(rounded_to_odd(n << (-2 * q) as usize, d.clone()), BigInt::one() << (-q) as usize)
    };
    to_float(&ratio)
}

/// Standard deviation from the exact variance, like Python's statistics module. Each exact
/// step is held to the size budget, so many large fractions cannot build a huge denominator.
fn deviation(values: &[Value], sample: bool) -> Outcome<Value> {
    let needed = if sample { 2 } else { 1 };
    if values.len() < needed {
        return Err(format!("needs at least {needed} values"));
    }
    let data = values.iter().map(|value| as_exact(value).and_then(exact)).collect::<Outcome<Vec<_>>>()?;
    let mean = binary("/", total(&data)?, count(&data))?;
    let mut squares = Value::Exact(BigRational::zero());
    for value in &data {
        let distance = binary("-", value.clone(), mean.clone())?;
        squares = binary("+", squares, binary("*", distance.clone(), distance)?)?;
    }
    let divisor = integer(BigInt::from(data.len() - sample as usize))?;
    let Value::Exact(variance) = binary("/", squares, divisor)? else { return Err("variance is not exact".into()) };
    if variance.is_zero() {
        return float(0.0);
    }
    float(float_sqrt_of_ratio(variance.numer(), variance.denom())?)
}

fn real(name: &str, arguments: &[Value], f: impl Fn(f64) -> f64, domain: impl Fn(f64) -> bool) -> Outcome<Value> {
    let [value] = arguments else { return Err(format!("{name} takes one value")) };
    let x = as_float(value)?;
    if !domain(x) {
        return Err(format!("{name} is not defined for this value"));
    }
    float(f(x))
}

fn call(name: &str, arguments: Vec<Value>) -> Outcome<Value> {
    let values = arguments.as_slice();
    match name {
        "abs" => match values {
            [Value::Exact(r)] => Ok(Value::Exact(r.abs())),
            [Value::Float(f)] => Ok(Value::Float(f.abs())),
            _ => Err("abs takes one value".into()),
        },
        "round" => round(values),
        "min" | "max" => {
            let mut best = values.first().ok_or(format!("{name} needs at least one value"))?;
            let wanted = if name == "min" { Ordering::Less } else { Ordering::Greater };
            for value in &values[1..] {
                if compare(value, best)? == wanted {
                    best = value;
                }
            }
            Ok(best.clone())
        }
        "sum" => total(values),
        "mean" => {
            if values.is_empty() {
                return Err("mean needs at least one value".into());
            }
            binary("/", total(values)?, count(values))
        }
        "median" => {
            let ordered = sorted(values)?;
            let middle = ordered.len() / 2;
            match ordered.len() {
                0 => Err("median needs at least one value".into()),
                n if n % 2 == 1 => Ok(ordered[middle].clone()),
                _ => binary("/", binary("+", ordered[middle - 1].clone(), ordered[middle].clone())?, integer(BigInt::from(2))?),
            }
        }
        "stdev" => deviation(values, true),
        "pstdev" => deviation(values, false),
        "sqrt" => real(name, values, f64::sqrt, |x| x >= 0.0),
        "log2" => real(name, values, f64::log2, |x| x > 0.0),
        "log10" => real(name, values, f64::log10, |x| x > 0.0),
        "log" => match values {
            [_] => real(name, values, f64::ln, |x| x > 0.0),
            [value, base] => {
                let (x, b) = (as_float(value)?, as_float(base)?);
                if x <= 0.0 || b <= 0.0 || b == 1.0 {
                    return Err("log is not defined for these values".into());
                }
                float(x.ln() / b.ln())
            }
            _ => Err("log takes a value and an optional base".into()),
        },
        "floor" | "ceil" => {
            let [value] = values else { return Err(format!("{name} takes one value")) };
            let source = as_exact(value)?;
            integer(if name == "floor" { source.floor().to_integer() } else { source.ceil().to_integer() })
        }
        _ => Err(format!("unknown function {name}; only numbers, arithmetic operators and numeric functions are accepted")),
    }
}

#[derive(Clone, Debug, PartialEq)]
enum Token {
    Number(String),
    Name(String),
    Symbol(&'static str),
}

const SYMBOLS: [&str; 15] = ["**", "//", "==", "!=", "<=", ">=", "+", "-", "*", "/", "%", "(", ")", ",", "<"];

fn tokens(source: &str) -> Outcome<Vec<Token>> {
    let chars: Vec<char> = source.chars().collect();
    let mut out = Vec::new();
    let mut i = 0;
    while i < chars.len() {
        let c = chars[i];
        if c.is_whitespace() {
            i += 1;
        } else if c.is_ascii_digit() || (c == '.' && chars.get(i + 1).is_some_and(|d| d.is_ascii_digit())) {
            let start = i;
            while i < chars.len() {
                let d = chars[i];
                let exponent_sign = (d == '+' || d == '-') && matches!(chars[i - 1], 'e' | 'E') && !chars[start..i].iter().any(|x| matches!(x, 'x' | 'X'));
                if d.is_ascii_alphanumeric() || d == '.' || d == '_' || (i > start && exponent_sign) {
                    i += 1;
                } else {
                    break;
                }
            }
            out.push(Token::Number(chars[start..i].iter().collect()));
        } else if c.is_ascii_alphabetic() || c == '_' {
            let start = i;
            while i < chars.len() && (chars[i].is_ascii_alphanumeric() || chars[i] == '_') {
                i += 1;
            }
            out.push(Token::Name(chars[start..i].iter().collect()));
        } else {
            let rest: String = chars[i..].iter().take(2).collect();
            let symbol = SYMBOLS.iter().chain([">"].iter()).find(|s| rest.starts_with(**s)).ok_or_else(|| format!("not an arithmetic expression: unexpected {c:?}"))?;
            out.push(Token::Symbol(symbol));
            i += symbol.len();
        }
    }
    Ok(out)
}

/// A Python numeric literal: decimal, hex, octal or binary integer, or a decimal float.
fn literal(text: &str) -> Outcome<Value> {
    let invalid = || format!("not a number: {text}");
    let plain = text.replace('_', "");
    if text.starts_with('_') || text.ends_with('_') || text.contains("__") {
        return Err(invalid());
    }
    let lower = plain.to_ascii_lowercase();
    for (prefix, radix) in [("0x", 16), ("0o", 8), ("0b", 2)] {
        if let Some(digits) = lower.strip_prefix(prefix) {
            return integer(BigInt::parse_bytes(digits.as_bytes(), radix).ok_or_else(invalid)?);
        }
    }
    if lower.bytes().all(|b| b.is_ascii_digit()) {
        if lower.len() > 1 && lower.starts_with('0') && lower.bytes().any(|b| b != b'0') {
            return Err(invalid()); // Python rejects a leading zero on a decimal integer
        }
        return integer(BigInt::parse_bytes(lower.as_bytes(), 10).ok_or_else(invalid)?);
    }
    if lower.bytes().all(|b| b.is_ascii_digit() || matches!(b, b'.' | b'e' | b'+' | b'-')) {
        return float(lower.parse::<f64>().map_err(|_| invalid())?);
    }
    Err(invalid())
}

struct Parser {
    tokens: Vec<Token>,
    at: usize,
    parts: usize,
    nesting: usize,
}

impl Parser {
    fn new(source: &str) -> Outcome<Parser> {
        if source.chars().count() > MAX_CHARS {
            return Err(format!("expression is longer than {MAX_CHARS} characters"));
        }
        Ok(Parser { tokens: tokens(source)?, at: 0, parts: 0, nesting: 0 })
    }

    fn symbol(&self) -> Option<&'static str> {
        match self.tokens.get(self.at) {
            Some(Token::Symbol(s)) => Some(s),
            _ => None,
        }
    }

    fn take(&mut self, symbol: &str) -> bool {
        let found = self.symbol() == Some(symbol);
        self.at += found as usize;
        found
    }

    fn expect(&mut self, symbol: &str) -> Outcome<()> {
        if self.take(symbol) { Ok(()) } else { Err(format!("not an arithmetic expression: expected {symbol}")) }
    }

    /// One number or operation; the count bounds the work an expression can ask for.
    fn part(&mut self) -> Outcome<()> {
        self.parts += 1;
        if self.parts > MAX_PARTS { Err(format!("expression has more than {MAX_PARTS} parts")) } else { Ok(()) }
    }

    fn enter(&mut self) -> Outcome<()> {
        self.nesting += 1;
        if self.nesting > MAX_NESTING { Err("not an arithmetic expression: too many nested parentheses".into()) } else { Ok(()) }
    }

    fn finished(&self) -> Outcome<()> {
        if self.at == self.tokens.len() { Ok(()) } else { Err("not an arithmetic expression: unexpected text after the expression".into()) }
    }

    fn sum(&mut self) -> Outcome<Value> {
        let mut value = self.term()?;
        while let Some(op @ ("+" | "-")) = self.symbol() {
            self.at += 1;
            self.part()?;
            let right = self.term()?;
            value = binary(op, value, right)?;
        }
        Ok(value)
    }

    fn term(&mut self) -> Outcome<Value> {
        let mut value = self.factor()?;
        while let Some(op @ ("*" | "/" | "//" | "%")) = self.symbol() {
            self.at += 1;
            self.part()?;
            let right = self.factor()?;
            value = binary(op, value, right)?;
        }
        Ok(value)
    }

    fn factor(&mut self) -> Outcome<Value> {
        // A chain of signs is read in a loop, not by recursion, so its length cannot exhaust the stack.
        let mut negative = false;
        while let Some(op @ ("+" | "-")) = self.symbol() {
            self.at += 1;
            self.part()?;
            negative ^= op == "-";
        }
        let value = self.power()?;
        Ok(if negative { negate(value) } else { value })
    }

    fn power(&mut self) -> Outcome<Value> {
        let base = self.atom()?;
        if !self.take("**") {
            return Ok(base);
        }
        self.part()?;
        self.enter()?;
        let exponent = self.factor()?;
        self.nesting -= 1;
        power(base, exponent)
    }

    fn atom(&mut self) -> Outcome<Value> {
        match self.tokens.get(self.at).cloned() {
            Some(Token::Number(text)) => {
                self.at += 1;
                self.part()?;
                literal(&text)
            }
            Some(Token::Name(name)) => {
                self.at += 1;
                self.part()?;
                self.expect("(")?;
                self.enter()?;
                let mut arguments = Vec::new();
                while !self.take(")") {
                    if !arguments.is_empty() {
                        self.expect(",")?;
                        if self.take(")") {
                            break;
                        }
                    }
                    arguments.push(self.sum()?);
                }
                self.nesting -= 1;
                call(&name, arguments)
            }
            Some(Token::Symbol("(")) => {
                self.at += 1;
                self.enter()?;
                let value = self.sum()?;
                self.expect(")")?;
                self.nesting -= 1;
                Ok(value)
            }
            _ => Err("not an arithmetic expression: expected a number".into()),
        }
    }
}

fn finite(value: Value) -> Outcome<Value> {
    match value {
        Value::Float(f) if !f.is_finite() => Err("result is not a finite real number".into()),
        other => Ok(other),
    }
}

fn evaluate(source: &str) -> Outcome<Value> {
    let mut parser = Parser::new(source)?;
    let value = parser.sum()?;
    parser.finished()?;
    finite(value)
}

/// (passed, left, right) for one comparison `LEFT op RIGHT`.
fn check(source: &str, tolerance: f64) -> Outcome<(bool, Value, Value)> {
    let usage = "a check is one comparison, for example \"2 + 2 == 4\"";
    let mut parser = Parser::new(source)?;
    let left = finite(parser.sum()?)?;
    let op = parser.symbol().filter(|s| COMPARISONS.contains(s)).ok_or(usage)?;
    parser.at += 1;
    parser.part()?;
    let right = finite(parser.sum()?)?;
    parser.finished().map_err(|_| usage.to_string())?;
    let approximate = matches!(left, Value::Float(_)) || matches!(right, Value::Float(_));
    let passed = if approximate && matches!(op, "==" | "!=") {
        let (a, b) = (as_float(&left).map_err(|_| "a side is outside float range; compare exact values")?,
                      as_float(&right).map_err(|_| "a side is outside float range; compare exact values")?);
        let close = (a - b).abs() <= (tolerance * a.abs().max(b.abs())).max(tolerance);
        close == (op == "==")
    } else {
        let order = compare(&left, &right)?;
        match op {
            "==" => order == Ordering::Equal,
            "!=" => order != Ordering::Equal,
            "<" => order == Ordering::Less,
            "<=" => order != Ordering::Greater,
            ">" => order == Ordering::Greater,
            _ => order != Ordering::Less,
        }
    };
    Ok((passed, left, right))
}

/// JSON form: an integer or float as a number, an exact fraction as text with its decimal
/// beside it (null when the fraction is outside float range).
fn shown(value: &Value) -> String {
    match value {
        Value::Exact(r) if r.is_integer() => r.to_integer().to_string(),
        Value::Exact(r) => {
            let decimal = to_float(r).map_or("null".to_string(), |f| format!("{f:?}"));
            format!("{{\"exact\": \"{r}\", \"decimal\": {decimal}}}")
        }
        Value::Float(f) => format!("{f:?}"),
    }
}

fn quoted(text: &str) -> String {
    serde_json::to_string(text).unwrap_or_else(|_| "\"\"".into())
}

const HELP: &str = "usage: code-audit-complexity calc EXPRESSION [EXPRESSION ...] [--check \"LEFT == RIGHT\" ...] [--tolerance 1e-9]\n\n\
Evaluates arithmetic exactly: numbers, + - * / // % **, parentheses and the functions abs, round, min, max, sum,\n\
mean, median, stdev, pstdev, sqrt, floor, ceil, log, log2, log10. Nothing else is accepted.\n\
Exit: 0 every expression evaluated and every check passed; 1 a check failed; 2 an expression is invalid.";

/// Run the subcommand; returns the process exit status.
pub fn run(arguments: &[String]) -> i32 {
    let (mut expressions, mut checks, mut tolerance) = (Vec::new(), Vec::new(), TOLERANCE);
    let invalid = |error: String| {
        println!("{{\"schema\": \"code-audit.calc.v1\", \"status\": \"invalid\", \"error\": {}}}", quoted(&error));
        2
    };
    let mut iter = arguments.iter();
    while let Some(argument) = iter.next() {
        match argument.as_str() {
            "-h" | "--help" => {
                println!("{HELP}");
                return 0;
            }
            "--check" => match iter.next() {
                Some(value) => checks.push(value.clone()),
                None => return invalid("--check needs a comparison".into()),
            },
            "--tolerance" => match iter.next().and_then(|v| v.parse::<f64>().ok()).filter(|t| t.is_finite() && *t >= 0.0) {
                Some(value) => tolerance = value,
                None => return invalid("--tolerance needs a non-negative number".into()),
            },
            other => expressions.push(other.to_string()),
        }
    }
    if expressions.is_empty() && checks.is_empty() {
        return invalid("give at least one expression or --check".into());
    }
    let (mut results, mut verdicts, mut status) = (Vec::new(), Vec::new(), 0);
    for expression in &expressions {
        match evaluate(expression) {
            Ok(value) => results.push(format!("{{\"expression\": {}, \"value\": {}}}", quoted(expression), shown(&value))),
            Err(error) => return invalid(error),
        }
    }
    for expression in &checks {
        match check(expression, tolerance) {
            Ok((passed, left, right)) => {
                verdicts.push(format!("{{\"check\": {}, \"passed\": {passed}, \"left\": {}, \"right\": {}}}", quoted(expression), shown(&left), shown(&right)));
                status = status.max(!passed as i32);
            }
            Err(error) => return invalid(error),
        }
    }
    println!("{{\"schema\": \"code-audit.calc.v1\", \"status\": \"{}\", \"results\": [{}], \"checks\": [{}]}}",
             if status == 0 { "ok" } else { "failed" }, results.join(", "), verdicts.join(", "));
    status
}
