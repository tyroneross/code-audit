//! `code-audit-complexity calc`: arithmetic, algebra, calculus, finance and small linear
//! programs, so a reported number comes from a computation and not from a model's mental
//! arithmetic.
//!
//! Plain arithmetic is the fast form of `skills/code-principles/scripts/calc.py` and follows
//! the same rules; `calc_vectors.json` beside that script is run against both so they cannot
//! drift. The rest exists only here: names (`--set`), equations (`--solve`), derivatives,
//! integrals, polynomial expansion, time-value-of-money functions and `--maximize` /
//! `--minimize`.
//!
//! Accepted: numbers, names, `+ - * / // % **`, parentheses, and the functions in `call`.
//! Nothing else parses, so an expression copied from a repository under review cannot run
//! code. Integers and fractions stay exact; a float literal, `sqrt`, `log` or a fractional
//! power makes the result a float. Semantics follow Python: `//` and `%` floor, `**` binds
//! tighter than a leading minus and associates to the right, `round` sends a tie to the even
//! digit.
//!
//! Budgets: an expression is at most `MAX_CHARS` characters and `MAX_PARTS` numbers, names
//! and operations, every exact value is at most `MAX_BITS` bits (checked before a power is
//! computed), and each command caps its own degree, unknowns and iterations. Work and memory
//! are therefore bounded for any input.

mod calculus;
mod finance;
mod nonlinear;
mod optimize;
mod piecewise;
mod poly;
mod solve;

use num_bigint::BigInt;
use num_integer::Integer;
use num_rational::BigRational;
use num_traits::{One, Signed, ToPrimitive, Zero};
use std::cmp::Ordering;
use std::collections::BTreeMap;
use std::rc::Rc;

const MAX_BITS: u64 = 4096;
const MAX_ROUND_DIGITS: i64 = 60;
const MAX_CHARS: usize = 2000;
const MAX_PARTS: usize = 256;
const MAX_NESTING: usize = 200;
const TOLERANCE: f64 = 1e-9;
const COMPARISONS: [&str; 6] = ["==", "!=", "<=", ">=", "<", ">"];
const MAX_NAMES: usize = 64;
const SCHEMA: &str = "code-audit.calc.v1";

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

/// The float for an exact value that has to become one, refused when no float is near it. A
/// non-zero value below about 2e-308 would become 0.0 (or a float with few digits left), and
/// what followed would be a wrong number, not a rounded one: sqrt(1/2**2000) is not zero.
fn nearest(value: &BigRational) -> Outcome<f64> {
    if value.is_zero() {
        return Ok(0.0);
    }
    match to_float(value)? {
        float if float.is_normal() => Ok(float),
        // Below the normal range a float keeps fewer digits; it is still the value itself when
        // the value is one of those floats (a tiny float minus zero, say).
        float if float != 0.0 && BigRational::from_float(float).as_ref() == Some(value) => Ok(float),
        _ => Err(format!("an exact value is too small for a float (about 2**{}); keep the arithmetic exact or rescale", value.numer().bits() as i64 - value.denom().bits() as i64)),
    }
}

/// How far apart the results at the two floats around an exact value may be, relative to
/// their size, before the result is taken to depend on digits a float cannot hold.
const SENSITIVE: f64 = 1e-9;

/// The widest gap between the two floats around an exact argument of sin, cos or tan.
const WAVE_GAP: f64 = 1e-6;

/// The float on the other side of an exact value from its nearest float `float`; `None` when
/// the value is itself that float (or was a float to begin with).
fn other_side(value: &Value, float: f64) -> Option<f64> {
    let Value::Exact(exact) = value else { return None };
    match BigRational::from_float(float)?.cmp(exact) {
        Ordering::Equal => None,
        Ordering::Less => Some(float.next_up()),
        Ordering::Greater => Some(float.next_down()),
    }
}

/// An exact argument that is not itself a float lies between two floats. When a function
/// gives those two materially different results, its value at the exact argument is not
/// known from floats at all (sin(10**30 + 1), or a base next to 1 raised to a huge power),
/// and it is refused instead of reporting the result at one of them.
fn steady(what: &str, result: f64, other: f64) -> Outcome<()> {
    if (result - other).abs() <= SENSITIVE * result.abs().max(other.abs()) {
        return Ok(());
    }
    Err(format!("{what} depends on digits of an exact value that a float cannot hold (the two nearest floats give {result:?} and {other:?}); rescale, or keep the arithmetic exact"))
}

fn as_float(value: &Value) -> Outcome<f64> {
    match value {
        Value::Exact(r) => nearest(r),
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
    if matches!(a, Value::Exact(_)) != matches!(b, Value::Exact(_)) {
        // An exact value beside a float: combined exactly, on the float's own value, and
        // rounded once at the end. Rounding the exact operand first loses what a later
        // subtraction needs: (1 + 1/2**60) - 1.0 is 2**-60, not 0.0.
        let (x, y) = (as_exact(&a)?, as_exact(&b)?);
        return float(nearest(&match op {
            "+" => x + y,
            "-" => x - y,
            "*" => x * y,
            "/" => x / y,
            "//" => (x / y).floor(),
            "%" => &x - &y * (&x / &y).floor(),
            _ => return Err(format!("unknown operator {op}")),
        })?);
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
    if b < 0.0 && other_side(&exponent, e).is_some() {
        // The sign of a negative base's power turns on whether the exponent is odd, even or
        // not whole, and the float nearest this exponent is a different number.
        return Err("a negative base needs an exponent that a float holds exactly; this exact exponent is not one".into());
    }
    let result = b.powf(e);
    if result.is_nan() && !b.is_nan() && !e.is_nan() {
        return Err("result is not a real number".into());
    }
    if result.is_infinite() && b.is_finite() && e.is_finite() {
        return Err(if b == 0.0 { "division by zero".into() } else { "result is outside float range".to_string() });
    }
    if !result.is_normal() && b != 0.0 && (matches!(base, Value::Exact(_)) || other_side(&exponent, e).is_some()) {
        // A power of a non-zero base is never zero: this one is too small for a float. (A float
        // base with an exponent that is itself a float, such as x**3 at a float x, is ordinary
        // float arithmetic and underflows to zero as floats do.)
        return Err("this power is too small for a float (below about 2e-308); keep the arithmetic exact or rescale".into());
    }
    if let Some(nearby) = other_side(&base, b) {
        steady("this power", result, nearby.powf(e))?;
    }
    if let Some(nearby) = other_side(&exponent, e) {
        steady("this power", result, b.powf(nearby))?;
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
    nearest(&ratio)
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

/// Whether an exact value is within one half of 1, where its logarithm needs care.
fn near_one(value: &Value) -> bool {
    let half = BigRational::new(BigInt::one(), BigInt::from(2));
    matches!(value, Value::Exact(r) if r.is_positive() && (r - BigRational::one()).abs() < half)
}

/// The natural logarithm of a positive value. An exact value near 1 becomes 1.0 as a float and
/// its logarithm 0.0, so the part beyond 1 is taken exactly and given to log1p instead.
fn natural_log(value: &Value) -> Outcome<f64> {
    match value {
        Value::Exact(r) if near_one(value) => Ok(nearest(&(r - BigRational::one()))?.ln_1p()),
        _ => match as_float(value)? {
            x if x > 0.0 => Ok(x.ln()),
            _ => Err("log is not defined for this value".into()),
        },
    }
}

fn real(name: &str, arguments: &[Value], f: impl Fn(f64) -> f64, domain: impl Fn(f64) -> bool) -> Outcome<Value> {
    let [value] = arguments else { return Err(format!("{name} takes one value")) };
    let x = as_float(value)?;
    if !domain(x) {
        return Err(format!("{name} is not defined for this value"));
    }
    let result = f(x);
    if let Some(nearby) = other_side(value, x).filter(|nearby| domain(*nearby)) {
        // Agreement at the two floats settles a function that only rises or only falls
        // between them. A wave can agree at both and be anywhere in between when they are
        // many periods apart, so for those the two floats must also be close together: within
        // a millionth, a wave cannot stray from them by more than one part in 10**12.
        if matches!(name, "sin" | "cos" | "tan") && (nearby - x).abs() > WAVE_GAP {
            return Err(format!("{name} of an exact value this large is not known from floats: the two nearest floats are {:e} apart, many of its periods", (nearby - x).abs()));
        }
        steady(name, result, f(nearby))?;
    }
    float(result)
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
        // An exact argument goes straight to the correctly rounded square root of the ratio, so
        // its size never passes through a float first.
        "sqrt" => match values {
            [Value::Exact(r)] if r.is_positive() => float(float_sqrt_of_ratio(r.numer(), r.denom())?),
            _ => real(name, values, f64::sqrt, |x| x >= 0.0),
        },
        // exp is never zero; a float result of 0.0 is an underflow, and reads as a root or a vanishing term.
        "exp" => match real(name, values, f64::exp, |_| true)? {
            Value::Float(0.0) => Err("exp is too small for a float here (below about 1e-308)".into()),
            result => Ok(result),
        },
        "sin" => real(name, values, f64::sin, |_| true),
        "cos" => real(name, values, f64::cos, |_| true),
        "tan" => real(name, values, f64::tan, |_| true),
        "log2" | "log10" => match values {
            [value] if near_one(value) => float(natural_log(value)? / if name == "log2" { std::f64::consts::LN_2 } else { std::f64::consts::LN_10 }),
            _ => real(name, values, if name == "log2" { f64::log2 } else { f64::log10 }, |x| x > 0.0),
        },
        "log" => match values {
            [value] => float(natural_log(value)?),
            [value, base] => {
                let (x, b) = (natural_log(value)?, natural_log(base)?);
                if b == 0.0 {
                    return Err("log is not defined for these values".into());
                }
                float(x / b)
            }
            _ => Err("log takes a value and an optional base".into()),
        },
        "floor" | "ceil" => {
            let [value] = values else { return Err(format!("{name} takes one value")) };
            let source = as_exact(value)?;
            integer(if name == "floor" { source.floor().to_integer() } else { source.ceil().to_integer() })
        }
        _ => finance::call(name, values).unwrap_or_else(|| Err(format!("unknown function {name}; only numbers, names, arithmetic operators and the functions listed by --help are accepted"))),
    }
}

#[derive(Clone, Debug, PartialEq)]
enum Token {
    Number(String),
    Name(String),
    Symbol(&'static str),
}

// A two-character symbol comes before the one-character symbol it starts with.
const SYMBOLS: [&str; 17] = ["**", "//", "==", "!=", "<=", ">=", "+", "-", "*", "/", "%", "(", ")", ",", "<", ">", "="];

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
            let symbol = SYMBOLS.iter().find(|s| rest.starts_with(**s)).ok_or_else(|| format!("not an arithmetic expression: unexpected {c:?}"))?;
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

/// A parsed expression. Parsing and evaluating are separate so an expression that holds a
/// name can be evaluated at many values, differentiated, or read as a polynomial.
#[derive(Clone, Debug)]
enum Node {
    Number(Value),
    Name(String),
    Negate(Rc<Node>),
    Binary(&'static str, Rc<Node>, Rc<Node>),
    Call(String, Vec<Rc<Node>>),
}

/// What a name stands for; `None` when it has no value.
type Names<'a> = &'a dyn Fn(&str) -> Option<Value>;

fn eval(node: &Node, names: Names) -> Outcome<Value> {
    match node {
        Node::Number(value) => Ok(value.clone()),
        Node::Name(name) => names(name).ok_or_else(|| format!("{name} has no value: give --set {name}=VALUE, or find it with --solve")),
        Node::Negate(inner) => Ok(negate(eval(inner, names)?)),
        Node::Binary("**", base, exponent) => power(eval(base, names)?, eval(exponent, names)?),
        Node::Binary(op, left, right) => binary(op, eval(left, names)?, eval(right, names)?),
        Node::Call(name, arguments) => call(name, arguments.iter().map(|argument| eval(argument, names)).collect::<Outcome<Vec<_>>>()?),
    }
}

/// Binding strength of a node's outermost operation, for printing with the fewest parentheses.
fn strength(node: &Node) -> u8 {
    match node {
        Node::Binary("+" | "-", ..) => 1,
        Node::Binary("**", ..) => 4,
        Node::Binary(..) => 2,
        Node::Negate(_) => 3,
        Node::Number(Value::Exact(r)) if !r.is_integer() => 2,
        Node::Number(Value::Exact(r)) if r.is_negative() => 3,
        Node::Number(Value::Float(f)) if *f < 0.0 => 3,
        _ => 5,
    }
}

/// The expression as text that parses back to the same expression.
fn text(node: &Node) -> String {
    let wrap = |inner: &Node, least: u8| if strength(inner) < least { format!("({})", text(inner)) } else { text(inner) };
    match node {
        Node::Number(Value::Exact(r)) => r.to_string(),
        Node::Number(Value::Float(f)) => format!("{f:?}"),
        Node::Name(name) => name.clone(),
        Node::Negate(inner) => format!("-{}", wrap(inner, 3)),
        Node::Binary(op @ ("+" | "-"), left, right) => format!("{} {op} {}", wrap(left, 1), wrap(right, 2)),
        Node::Binary("**", base, exponent) => format!("{}**{}", wrap(base, 5), wrap(exponent, 3)),
        Node::Binary(op, left, right) => format!("{}{op}{}", wrap(left, 2), wrap(right, 3)),
        Node::Call(name, arguments) => format!("{name}({})", arguments.iter().map(|argument| text(argument)).collect::<Vec<_>>().join(", ")),
    }
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

    /// One number, name or operation; the count bounds the work an expression can ask for.
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

    fn sum(&mut self) -> Outcome<Rc<Node>> {
        let mut node = self.term()?;
        while let Some(op @ ("+" | "-")) = self.symbol() {
            self.at += 1;
            self.part()?;
            node = Rc::new(Node::Binary(op, node, self.term()?));
        }
        Ok(node)
    }

    fn term(&mut self) -> Outcome<Rc<Node>> {
        let mut node = self.factor()?;
        while let Some(op @ ("*" | "/" | "//" | "%")) = self.symbol() {
            self.at += 1;
            self.part()?;
            node = Rc::new(Node::Binary(op, node, self.factor()?));
        }
        Ok(node)
    }

    fn factor(&mut self) -> Outcome<Rc<Node>> {
        // A chain of signs is read in a loop, not by recursion, so its length cannot exhaust the stack.
        let mut negative = false;
        while let Some(op @ ("+" | "-")) = self.symbol() {
            self.at += 1;
            self.part()?;
            negative ^= op == "-";
        }
        let node = self.power()?;
        Ok(if negative { Rc::new(Node::Negate(node)) } else { node })
    }

    fn power(&mut self) -> Outcome<Rc<Node>> {
        let base = self.atom()?;
        if !self.take("**") {
            return Ok(base);
        }
        self.part()?;
        self.enter()?;
        let exponent = self.factor()?;
        self.nesting -= 1;
        Ok(Rc::new(Node::Binary("**", base, exponent)))
    }

    fn atom(&mut self) -> Outcome<Rc<Node>> {
        match self.tokens.get(self.at).cloned() {
            Some(Token::Number(text)) => {
                self.at += 1;
                self.part()?;
                Ok(Rc::new(Node::Number(literal(&text)?)))
            }
            Some(Token::Name(name)) => {
                self.at += 1;
                self.part()?;
                if !self.take("(") {
                    return Ok(Rc::new(Node::Name(name)));
                }
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
                Ok(Rc::new(Node::Call(name, arguments)))
            }
            Some(Token::Symbol("(")) => {
                self.at += 1;
                self.enter()?;
                let node = self.sum()?;
                self.expect(")")?;
                self.nesting -= 1;
                Ok(node)
            }
            _ => Err("not an arithmetic expression: expected a number".into()),
        }
    }
}

fn parse(source: &str) -> Outcome<Rc<Node>> {
    let mut parser = Parser::new(source)?;
    let node = parser.sum()?;
    parser.finished()?;
    Ok(node)
}

/// `LEFT op RIGHT` with op one of `allowed`; `usage` is the error when the text is anything else.
fn relation(source: &str, allowed: &[&str], usage: &str) -> Outcome<(Rc<Node>, &'static str, Rc<Node>)> {
    let mut parser = Parser::new(source)?;
    let left = parser.sum()?;
    let op = parser.symbol().filter(|s| allowed.contains(s)).ok_or(usage)?;
    parser.at += 1;
    parser.part()?;
    let right = parser.sum()?;
    parser.finished().map_err(|_| usage.to_string())?;
    Ok((left, op, right))
}

/// (passed, left, right) for one comparison `LEFT op RIGHT`.
fn check(source: &str, tolerance: f64, names: Names) -> Outcome<(bool, Value, Value)> {
    let (left, op, right) = relation(source, &COMPARISONS, "a check is one comparison, for example \"2 + 2 == 4\"")?;
    let (left, right) = (eval(&left, names)?, eval(&right, names)?);
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

/// Names given a value with `--set`, plus the constants `pi` and `e`.
#[derive(Default)]
struct Scope {
    set: BTreeMap<String, Value>,
}

impl Scope {
    fn value(&self, name: &str) -> Option<Value> {
        self.set.get(name).cloned().or(match name {
            "pi" => Some(Value::Float(std::f64::consts::PI)),
            "e" => Some(Value::Float(std::f64::consts::E)),
            _ => None,
        })
    }

    /// Add `NAME=EXPRESSION`; the expression may use the names set before it.
    fn define(&mut self, assignment: &str) -> Outcome<()> {
        let (name, expression) = assignment.split_once('=').ok_or("--set takes NAME=VALUE, for example --set rate=5/100")?;
        let name = name.trim();
        let plain = name.chars().all(|c| c.is_ascii_alphanumeric() || c == '_') && name.chars().next().is_some_and(|c| c.is_ascii_alphabetic() || c == '_');
        if !plain || matches!(name, "pi" | "e") {
            return Err(format!("{name:?} cannot be set: a name is letters, digits and _, and pi and e are constants"));
        }
        if self.set.len() >= MAX_NAMES {
            return Err(format!("more than {MAX_NAMES} names"));
        }
        let value = eval(&*parse(expression)?, &|name| self.value(name))?;
        self.set.insert(name.to_string(), value);
        Ok(())
    }
}

/// JSON form: an integer or float as a number, an exact fraction as text with its decimal
/// beside it (null when no float is near the fraction: too large, or too small to be
/// anything but a misleading 0.0).
fn shown(value: &Value) -> String {
    match value {
        Value::Exact(r) if r.is_integer() => r.to_integer().to_string(),
        Value::Exact(r) => {
            let decimal = nearest(r).map_or("null".to_string(), |f| format!("{f:?}"));
            format!("{{\"exact\": \"{r}\", \"decimal\": {decimal}}}")
        }
        Value::Float(f) => format!("{f:?}"),
    }
}

fn quoted(text: &str) -> String {
    serde_json::to_string(text).unwrap_or_else(|_| "\"\"".into())
}

/// A JSON object from keys and already-encoded values.
fn object(fields: &[(&str, String)]) -> String {
    format!("{{{}}}", fields.iter().map(|(key, value)| format!("{}: {value}", quoted(key))).collect::<Vec<_>>().join(", "))
}

fn list(items: &[String]) -> String {
    format!("[{}]", items.join(", "))
}

const HELP: &str = "usage: code-audit-complexity calc EXPRESSION ... [--check \"LEFT == RIGHT\" ...] [--set NAME=VALUE ...] [--tolerance 1e-9]
       code-audit-complexity calc --solve \"EQUATION\" [--solve \"EQUATION\" ...] [--between LOW HIGH]
       code-audit-complexity calc --solve \"EQUATION\" ... --start NAME=VALUE ... [--tolerance 1e-9]
       code-audit-complexity calc --piece \"GUARD: EXPRESSION\" ... --target \">= VALUE\" --between LOW HIGH
       code-audit-complexity calc --derivative EXPRESSION [--at VALUE] [--var NAME]
       code-audit-complexity calc --integral EXPRESSION [--from LOW --to HIGH] [--var NAME]
       code-audit-complexity calc --expand EXPRESSION [--var NAME]
       code-audit-complexity calc --maximize|--minimize EXPRESSION --subject \"LEFT <= RIGHT\" ... [--integer NAME,NAME]

Arithmetic is exact: numbers, + - * / // % **, parentheses, the constants pi and e, names given with --set, and
  abs round min max sum mean median stdev pstdev sqrt exp log log2 log10 sin cos tan floor ceil.
Finance (cash paid out is negative; `when` is 0 for payments at the end of a period, 1 for the beginning):
  fv(rate, nper, pmt, pv[, when])   pv(rate, nper, pmt[, fv, when])   pmt(rate, nper, pv[, fv, when])
  nper(rate, pmt, pv[, fv, when])   rate(nper, pmt, pv, fv[, when])
  npv(rate, v0, v1, ...)  first value at time 0 (a spreadsheet NPV discounts its first value one period)
  irr(v0, v1, ...)        mirr(finance_rate, reinvest_rate, v0, v1, ...)
--solve      one equation in one name (every real root of a polynomial; other equations need --between), or
             several linear equations in several names, solved exactly.
--start      a named starting value for a local numerical solve of simultaneous rational equations.
--piece      an ordered guarded expression. First matching guard wins. Use \"else: EXPRESSION\" for a fallback.
--target     compare piece outputs with a constant over the exact interval given by --between.
--derivative the derivative by the differentiation rules; a polynomial is exact.
--integral   a polynomial exactly; anything else numerically between --from and --to.
--maximize / --minimize  a linear objective under linear constraints. A name is unbounded unless a constraint
             bounds it, so write \"x >= 0\" when a quantity cannot be negative.
Nothing else is accepted. Exit: 0 computed and every check passed; 1 a check failed or a numeric answer did not
converge; 2 the input is invalid.";

/// What one invocation asks for.
#[derive(Default)]
struct Request {
    expressions: Vec<String>,
    checks: Vec<String>,
    sets: Vec<String>,
    equations: Vec<String>,
    starts: Vec<String>,
    pieces: Vec<String>,
    target: Option<String>,
    between: Option<(String, String)>,
    derivative: Option<String>,
    at: Option<String>,
    integral: Option<String>,
    from: Option<String>,
    to: Option<String>,
    expand: Option<String>,
    objective: Option<(bool, String)>,
    subjects: Vec<String>,
    integers: Vec<String>,
    var: Option<String>,
    tolerance: Option<f64>,
}

fn request(arguments: &[String]) -> Outcome<Option<Request>> {
    let mut wanted = Request::default();
    let mut rest = arguments.iter();
    while let Some(argument) = rest.next() {
        let mut value = |what: &str| rest.next().cloned().ok_or_else(|| format!("{argument} needs {what}"));
        match argument.as_str() {
            "-h" | "--help" => return Ok(None),
            "--check" => wanted.checks.push(value("a comparison")?),
            "--set" => wanted.sets.push(value("NAME=VALUE")?),
            "--solve" => wanted.equations.push(value("an equation")?),
            "--start" => wanted.starts.push(value("NAME=VALUE")?),
            "--piece" => wanted.pieces.push(value("GUARD: EXPRESSION")?),
            "--target" => wanted.target = Some(value("an operator and value")?),
            "--between" => wanted.between = Some((value("two bounds")?, value("two bounds")?)),
            "--derivative" => wanted.derivative = Some(value("an expression")?),
            "--at" => wanted.at = Some(value("a value")?),
            "--integral" => wanted.integral = Some(value("an expression")?),
            "--from" => wanted.from = Some(value("a bound")?),
            "--to" => wanted.to = Some(value("a bound")?),
            "--expand" => wanted.expand = Some(value("an expression")?),
            "--maximize" | "--minimize" => wanted.objective = Some((argument == "--maximize", value("an objective")?)),
            "--subject" => wanted.subjects.push(value("a constraint")?),
            "--integer" => wanted.integers.extend(value("names")?.split(',').map(|name| name.trim().to_string()).filter(|name| !name.is_empty())),
            "--var" => wanted.var = Some(value("a name")?),
            "--tolerance" => {
                wanted.tolerance = Some(value("a number")?.parse::<f64>().ok().filter(|t| t.is_finite() && *t >= 0.0).ok_or("--tolerance needs a non-negative number")?)
            }
            // A misspelt option is words and hyphens only; "--max(0)" and "--5" are arithmetic (a double minus).
            other if other.len() > 2 && other.starts_with("--") && other[2..].chars().all(|c| c.is_ascii_alphabetic() || c == '-') => {
                return Err(format!("unknown option {other}; see --help"))
            }
            other => wanted.expressions.push(other.to_string()),
        }
    }
    Ok(Some(wanted))
}

/// The report's fields and the exit status for one request.
fn answer(wanted: &Request) -> Outcome<(Vec<(&'static str, String)>, i32)> {
    if !wanted.starts.is_empty() && (wanted.equations.is_empty() || wanted.between.is_some()) {
        return Err("--start requires --solve and cannot be combined with --between".into());
    }
    if wanted.target.is_some() && wanted.pieces.is_empty() {
        return Err("--target requires --piece".into());
    }
    if !wanted.pieces.is_empty() && !wanted.equations.is_empty() {
        return Err("--piece and --solve require separate invocations".into());
    }
    let mut scope = Scope::default();
    for assignment in &wanted.sets {
        scope.define(assignment)?;
    }
    let names: Names = &|name| scope.value(name);
    let (mut fields, mut status) = (Vec::new(), 0);
    let mut results = Vec::new();
    for expression in &wanted.expressions {
        results.push(object(&[("expression", quoted(expression)), ("value", shown(&eval(&*parse(expression)?, names)?))]));
    }
    let mut verdicts = Vec::new();
    for expression in &wanted.checks {
        let (passed, left, right) = check(expression, wanted.tolerance.unwrap_or(TOLERANCE), names)?;
        verdicts.push(object(&[("check", quoted(expression)), ("passed", passed.to_string()), ("left", shown(&left)), ("right", shown(&right))]));
        status = status.max(!passed as i32);
    }
    fields.push(("results", list(&results)));
    fields.push(("checks", list(&verdicts)));
    if !wanted.starts.is_empty() {
        let (report, converged) = nonlinear::solve(&wanted.equations, &wanted.starts, wanted.tolerance.unwrap_or(TOLERANCE), names)?;
        fields.push(("solve", report));
        status = status.max(!converged as i32);
    } else if !wanted.equations.is_empty() {
        fields.push(("solve", solve::solve(&wanted.equations, wanted.between.as_ref(), names)?));
    }
    if !wanted.pieces.is_empty() {
        let target = wanted.target.as_deref().ok_or("--piece requires --target")?;
        let bounds = wanted.between.as_ref().ok_or("--piece requires --between LOW HIGH")?;
        fields.push(("piecewise", piecewise::solve(&wanted.pieces, target, bounds, names)?));
    }
    if let Some(expression) = &wanted.derivative {
        fields.push(("derivative", calculus::derivative(expression, wanted.var.as_deref(), wanted.at.as_deref(), names)?));
    }
    if let Some(expression) = &wanted.integral {
        let (report, converged) = calculus::integral(expression, wanted.var.as_deref(), wanted.from.as_deref(), wanted.to.as_deref(), names)?;
        fields.push(("integral", report));
        status = status.max(!converged as i32);
    }
    if let Some(expression) = &wanted.expand {
        fields.push(("expand", calculus::expand(expression, wanted.var.as_deref(), names)?));
    }
    if let Some((maximize, objective)) = &wanted.objective {
        fields.push(("optimize", optimize::optimize(*maximize, objective, &wanted.subjects, &wanted.integers, names)?));
    }
    Ok((fields, status))
}

/// Run the subcommand; returns the process exit status.
pub fn run(arguments: &[String]) -> i32 {
    let invalid = |error: String| {
        println!("{}", object(&[("schema", quoted(SCHEMA)), ("status", quoted("invalid")), ("error", quoted(&error))]));
        2
    };
    let wanted = match request(arguments) {
        Ok(Some(wanted)) => wanted,
        Ok(None) => {
            println!("{HELP}");
            return 0;
        }
        Err(error) => return invalid(error),
    };
    let asks = !wanted.expressions.is_empty() || !wanted.checks.is_empty() || !wanted.equations.is_empty()
        || !wanted.starts.is_empty() || !wanted.pieces.is_empty() || wanted.target.is_some()
        || wanted.derivative.is_some() || wanted.integral.is_some() || wanted.expand.is_some() || wanted.objective.is_some();
    if !asks {
        return invalid("give at least one expression, --check, --solve, --piece, --derivative, --integral, --expand, --maximize or --minimize".into());
    }
    // A fault inside this module or a numeric library becomes a stated refusal, never a crash:
    // the caller always gets one JSON report and exit 0, 1 or 2.
    std::panic::set_hook(Box::new(|_| {}));
    let outcome = std::panic::catch_unwind(|| answer(&wanted)).unwrap_or_else(|_| Err("internal error while computing; nothing is reported".into()));
    match outcome {
        Ok((fields, status)) => {
            let mut report = vec![("schema", quoted(SCHEMA)), ("status", quoted(if status == 0 { "ok" } else { "failed" }))];
            report.extend(fields);
            println!("{}", object(&report));
            status
        }
        Err(error) => invalid(error),
    }
}
