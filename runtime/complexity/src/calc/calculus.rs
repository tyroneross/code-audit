//! Derivatives, integrals and polynomial expansion.
//!
//! A polynomial is handled exactly by the power rule. Any other expression is differentiated
//! by the standard rules (sum, product, quotient, chain) and the value is cross-checked
//! against a central difference; it is integrated numerically by the `quadrature` crate's
//! double exponential rule, which reports its own error estimate.

use super::poly::{mentions, polynomial, reported, unknowns, Poly};
use super::solve::function;
use super::{as_exact, as_float, binary, eval, float, list, object, parse, quoted, shown, text, Names, Node, Outcome, Value};
use num_bigint::BigInt;
use num_rational::BigRational;
use std::cell::RefCell;
use std::collections::BTreeSet;
use std::rc::Rc;

/// A derivative larger than this many parts is evaluated but not printed.
const MAX_PRINTED_PARTS: usize = 400;
const INTEGRAL_TARGET: f64 = 1e-12;
const INTEGRAL_ACCEPTED: f64 = 1e-7;
/// Panels the range starts with, how closely a panel must match its halves relative to the
/// total, and the limits on halving and on evaluations.
const PANELS: usize = 32;
const PANEL_AGREEMENT: f64 = 1e-11;
const MAX_HALVINGS: u32 = 48;
const MAX_EVALUATIONS: u64 = 400_000;
const DERIVATIVE_AGREEMENT: f64 = 1e-5;

/// The name the command is about: `--var`, or the only name without a value, or x.
fn variable(node: &Node, wanted: Option<&str>, names: Names) -> Outcome<String> {
    if let Some(name) = wanted {
        if names(name).is_some() {
            return Err(format!("{name} already has a value, so nothing varies with it; drop its --set or choose another --var"));
        }
        return Ok(name.to_string());
    }
    let mut free = BTreeSet::new();
    unknowns(node, names, &mut free);
    match free.len() {
        0 => Ok("x".into()),
        1 => Ok(free.into_iter().next().unwrap_or_default()),
        _ => Err(format!("several names have no value ({}): say which one varies with --var", free.into_iter().collect::<Vec<_>>().join(", "))),
    }
}

fn number(value: i64) -> Rc<Node> {
    Rc::new(Node::Number(Value::Exact(BigRational::from_integer(BigInt::from(value)))))
}

fn is(node: &Node, value: i64) -> bool {
    matches!(node, Node::Number(Value::Exact(r)) if *r == BigRational::from_integer(BigInt::from(value)))
}

/// `left op right`, with the identities that keep a derivative readable (0 + a, 1 * a, a ** 1)
/// and two exact numbers folded into one.
fn join(op: &'static str, left: Rc<Node>, right: Rc<Node>) -> Rc<Node> {
    if let (Node::Number(a @ Value::Exact(_)), Node::Number(b @ Value::Exact(_))) = (&*left, &*right) {
        let folded = if op == "**" { super::power(a.clone(), b.clone()) } else { binary(op, a.clone(), b.clone()) };
        if let Ok(value @ Value::Exact(_)) = folded {
            return Rc::new(Node::Number(value));
        }
    }
    match op {
        "+" if is(&left, 0) => right,
        "+" | "-" if is(&right, 0) => left,
        "-" if is(&left, 0) => negated(right),
        "*" if is(&left, 0) || is(&right, 0) => number(0),
        "*" if is(&left, 1) => right,
        "*" | "/" | "**" if is(&right, 1) => left,
        "/" if is(&left, 0) => number(0),
        "**" if is(&right, 0) => number(1),
        _ => Rc::new(Node::Binary(op, left, right)),
    }
}

fn negated(node: Rc<Node>) -> Rc<Node> {
    match &*node {
        Node::Number(value @ Value::Exact(_)) => Rc::new(Node::Number(super::negate(value.clone()))),
        Node::Negate(inner) => inner.clone(),
        _ => Rc::new(Node::Negate(node)),
    }
}

fn apply(name: &str, argument: Rc<Node>) -> Rc<Node> {
    Rc::new(Node::Call(name.to_string(), vec![argument]))
}

/// The derivative with respect to `name`, by the differentiation rules.
fn differentiated(node: &Rc<Node>, name: &str) -> Outcome<Rc<Node>> {
    if !mentions(node, name) {
        return Ok(number(0));
    }
    let d = |part: &Rc<Node>| differentiated(part, name);
    Ok(match &**node {
        Node::Number(_) => number(0),
        Node::Name(_) => number(1),
        Node::Negate(inner) => negated(d(inner)?),
        Node::Binary(op @ ("+" | "-"), left, right) => join(op, d(left)?, d(right)?),
        Node::Binary("*", left, right) => join("+", join("*", d(left)?, right.clone()), join("*", left.clone(), d(right)?)),
        Node::Binary("/", left, right) if !mentions(right, name) => join("/", d(left)?, right.clone()),
        Node::Binary("/", left, right) => {
            let top = join("-", join("*", d(left)?, right.clone()), join("*", left.clone(), d(right)?));
            join("/", top, join("**", right.clone(), number(2)))
        }
        // u ** n: n * u ** (n - 1) * u'
        Node::Binary("**", base, exponent) if !mentions(exponent, name) => {
            let lowered = join("**", base.clone(), join("-", exponent.clone(), number(1)));
            join("*", join("*", exponent.clone(), lowered), d(base)?)
        }
        // a ** v: a ** v * log(a) * v'
        Node::Binary("**", base, exponent) if !mentions(base, name) => join("*", join("*", node.clone(), apply("log", base.clone())), d(exponent)?),
        // u ** v: u ** v * (v' * log(u) + v * u' / u)
        Node::Binary("**", base, exponent) => {
            let inner = join("+", join("*", d(exponent)?, apply("log", base.clone())), join("/", join("*", exponent.clone(), d(base)?), base.clone()));
            join("*", node.clone(), inner)
        }
        Node::Binary(op, ..) => return Err(format!("{op} has no derivative rule")),
        Node::Call(function, arguments) => {
            let (inner, base) = match arguments.as_slice() {
                [inner] => (inner, None),
                [inner, base] if function == "log" && !mentions(base, name) => (inner, Some(base)),
                _ => return Err(format!("{function} with these arguments has no derivative rule")),
            };
            let slope = d(inner)?;
            let over_log = |base: Rc<Node>| join("/", slope.clone(), join("*", inner.clone(), apply("log", base)));
            match (function.as_str(), base) {
                ("log", Some(base)) => over_log(base.clone()),
                ("log", None) => join("/", slope, inner.clone()),
                ("log2", _) => over_log(number(2)),
                ("log10", _) => over_log(number(10)),
                ("sqrt", _) => join("/", slope, join("*", number(2), node.clone())),
                ("exp", _) => join("*", node.clone(), slope),
                ("sin", _) => join("*", apply("cos", inner.clone()), slope),
                ("cos", _) => negated(join("*", apply("sin", inner.clone()), slope)),
                ("tan", _) => join("/", slope, join("**", apply("cos", inner.clone()), number(2))),
                _ => return Err(format!("{function} has no derivative rule; the rules cover + - * / **, sqrt, exp, log, log2, log10, sin, cos and tan")),
            }
        }
    })
}

/// Parts in the expression when printed, stopping once it passes `limit`.
fn size(node: &Node, limit: usize) -> usize {
    match node {
        Node::Number(_) | Node::Name(_) => 1,
        Node::Negate(inner) => 1 + size(inner, limit),
        Node::Binary(_, left, right) => {
            let left = 1 + size(left, limit);
            if left > limit { left } else { left + size(right, limit) }
        }
        Node::Call(_, arguments) => arguments.iter().fold(1, |total, argument| if total > limit { total } else { total + size(argument, limit) }),
    }
}

/// Whether a float enters the expression, as a literal or through a name (pi and e are floats).
fn approximate(node: &Node, names: Names) -> bool {
    match node {
        Node::Number(value) => matches!(value, Value::Float(_)),
        Node::Name(name) => matches!(names(name), Some(Value::Float(_))),
        Node::Negate(inner) => approximate(inner, names),
        Node::Binary(_, left, right) => approximate(left, names) || approximate(right, names),
        Node::Call(_, arguments) => arguments.iter().any(|argument| approximate(argument, names)),
    }
}

struct Area {
    value: f64,
    /// Sum over the panels of the difference between a panel and its two halves.
    error: f64,
    evaluations: u64,
    /// Every panel agreed with its halves inside the depth and evaluation budgets.
    settled: bool,
}

/// The integral of f from low to high. One pass of a quadrature rule reports a small error
/// for a function with a narrow peak between its sample points, so the range is cut into
/// panels and each panel is accepted only when it agrees with the sum of its two halves;
/// a panel that does not is halved again. A feature much narrower than a panel's sample
/// spacing can still be missed: no finite sampling can exclude that.
fn area(f: &dyn Fn(f64) -> f64, low: f64, high: f64, failed: &dyn Fn() -> bool) -> Area {
    let mut result = Area { value: 0.0, error: 0.0, evaluations: 0, settled: true };
    if low >= high || low.is_nan() || high.is_nan() {
        return result;
    }
    let piece = |from: f64, to: f64, evaluations: &mut u64| {
        let part = quadrature::integrate(f, from, to, INTEGRAL_TARGET);
        *evaluations += part.num_function_evaluations as u64;
        part.integral
    };
    // (from, to, estimate, depth)
    let mut pending = Vec::new();
    let mut scale = 0.0;
    for panel in 0..PANELS {
        let from = low + (high - low) * panel as f64 / PANELS as f64;
        let to = if panel + 1 == PANELS { high } else { low + (high - low) * (panel + 1) as f64 / PANELS as f64 };
        let whole = piece(from, to, &mut result.evaluations);
        scale += whole.abs();
        pending.push((from, to, whole, 0));
    }
    while let Some((from, to, whole, depth)) = pending.pop() {
        if failed() {
            result.settled = false;
            break;
        }
        let middle = 0.5 * (from + to);
        let (left, right) = (piece(from, middle, &mut result.evaluations), piece(middle, to, &mut result.evaluations));
        let gap = (whole - (left + right)).abs();
        // The total of the pieces' sizes, kept current, is what "small" is measured against.
        scale += left.abs() + right.abs() - whole.abs();
        if gap <= PANEL_AGREEMENT * scale.max(f64::MIN_POSITIVE) || gap == 0.0 {
            result.value += left + right;
            result.error += gap;
        } else if depth >= MAX_HALVINGS || result.evaluations > MAX_EVALUATIONS || !(from < middle && middle < to) {
            result.value += left + right;
            result.error += gap;
            result.settled = false;
        } else {
            pending.push((from, middle, left, depth + 1));
            pending.push((middle, to, right, depth + 1));
        }
    }
    result
}

fn point(source: &str, names: Names) -> Outcome<Value> {
    eval(&*parse(source)?, names)
}

pub(super) fn derivative(expression: &str, wanted: Option<&str>, at: Option<&str>, names: Names) -> Outcome<String> {
    let node = parse(expression)?;
    let name = variable(&node, wanted, names)?;
    let at = at.map(|source| point(source, names)).transpose()?;
    let mut fields = vec![("of", quoted(expression)), ("variable", quoted(&name))];
    if let Some(p) = polynomial(&node, &name, names)? {
        let slope = p.derivative();
        fields.push(("expression", quoted(&slope.text(&name))));
        fields.push(("method", quoted("power rule, exact")));
        if let Some(at) = &at {
            fields.push(("at", shown(at)));
            fields.push(("value", shown(&reported(&slope.at(&as_exact(at)?), slope.inexact || matches!(at, Value::Float(_)))?)));
        }
        return Ok(object(&fields));
    }
    let slope = differentiated(&node, &name)?;
    let printed = if size(&slope, MAX_PRINTED_PARTS) > MAX_PRINTED_PARTS { "null".to_string() } else { quoted(&text(&slope)) };
    fields.push(("expression", printed));
    fields.push(("method", quoted("differentiation rules")));
    if let Some(at) = &at {
        let x = as_float(at)?;
        let value = eval(&slope, &|found| if found == name { Some(at.clone()) } else { names(found) })?;
        // The rules drop terms such as 0 * f, so a float in the expression may not reach the value: mark it here.
        let value = if matches!(value, Value::Exact(_)) && approximate(&node, names) { float(as_float(&value)?)? } else { value };
        fields.push(("at", shown(at)));
        fields.push(("value", shown(&value)));
        // An independent check: the slope between two nearby points. It is skipped where the
        // expression cannot be evaluated on both sides (the edge of a domain).
        let failure = RefCell::new(None);
        let f = function(&node, &name, names, &failure);
        let step = 1e-5 * x.abs().max(1.0);
        let nearby = (f(x + step) - f(x - step)) / (2.0 * step);
        if failure.borrow().is_none() && nearby.is_finite() {
            let exact_slope = as_float(&value)?;
            let agrees = (exact_slope - nearby).abs() <= DERIVATIVE_AGREEMENT * exact_slope.abs().max(nearby.abs()).max(1.0);
            fields.push(("central_difference", format!("{nearby:?}")));
            fields.push(("agrees", agrees.to_string()));
        }
    }
    Ok(object(&fields))
}

/// The report and whether the value is established (false when numeric integration did not converge).
pub(super) fn integral(expression: &str, wanted: Option<&str>, from: Option<&str>, to: Option<&str>, names: Names) -> Outcome<(String, bool)> {
    let node = parse(expression)?;
    let name = variable(&node, wanted, names)?;
    let bounds = match (from, to) {
        (Some(from), Some(to)) => Some((point(from, names)?, point(to, names)?)),
        (None, None) => None,
        _ => return Err("give both --from and --to, or neither for the antiderivative of a polynomial".into()),
    };
    let mut fields = vec![("of", quoted(expression)), ("variable", quoted(&name))];
    let range = |fields: &mut Vec<(&'static str, String)>, low: &Value, high: &Value| {
        fields.push(("from", shown(low)));
        fields.push(("to", shown(high)));
    };
    if let Some(p) = polynomial(&node, &name, names)? {
        let area: Poly = p.antiderivative();
        fields.push(("antiderivative", quoted(&area.text(&name))));
        fields.push(("method", quoted("power rule, exact")));
        if let Some((low, high)) = &bounds {
            range(&mut fields, low, high);
            let inexact = area.inexact || matches!(low, Value::Float(_)) || matches!(high, Value::Float(_));
            fields.push(("value", shown(&reported(&(area.at(&as_exact(high)?) - area.at(&as_exact(low)?)), inexact)?)));
        }
        return Ok((object(&fields), true));
    }
    let (low, high) = bounds.ok_or("only a polynomial has its antiderivative written out: give --from and --to for a numeric integral")?;
    range(&mut fields, &low, &high);
    let (a, b) = (as_float(&low)?, as_float(&high)?);
    let failure = RefCell::new(None);
    let f = function(&node, &name, names, &failure);
    let result = area(&f, a.min(b), a.max(b), &|| failure.borrow().is_some());
    if let Some(error) = failure.borrow_mut().take() {
        return Err(format!("the integrand cannot be evaluated {error}"));
    }
    let value = if a <= b { result.value } else { -result.value };
    let converged = result.settled && result.error.is_finite() && result.error <= INTEGRAL_ACCEPTED * value.abs().max(1.0);
    fields.push(("value", shown(&float(value)?)));
    fields.push(("error_estimate", if result.error.is_finite() { format!("{:?}", result.error) } else { "null".into() }));
    fields.push(("evaluations", result.evaluations.to_string()));
    fields.push(("converged", converged.to_string()));
    fields.push(("method", quoted("double exponential (tanh-sinh) quadrature on panels, each halved until whole and halves agree")));
    Ok((object(&fields), converged))
}

pub(super) fn expand(expression: &str, wanted: Option<&str>, names: Names) -> Outcome<String> {
    let node = parse(expression)?;
    let name = variable(&node, wanted, names)?;
    let p = polynomial(&node, &name, names)?.ok_or(format!("not a polynomial in {name}: only sums, products and whole-number powers of {name} are expanded"))?;
    let coefficients = p.c.iter().map(|c| reported(c, p.inexact).map(|value| shown(&value))).collect::<Outcome<Vec<_>>>()?;
    Ok(object(&[
        ("of", quoted(expression)),
        ("variable", quoted(&name)),
        ("polynomial", quoted(&p.text(&name))),
        ("degree", p.degree().to_string()),
        ("coefficients_low_to_high", list(&coefficients)),
    ]))
}
