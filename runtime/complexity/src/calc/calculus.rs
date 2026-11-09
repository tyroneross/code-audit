//! Derivatives, integrals and polynomial expansion.
//!
//! A polynomial is handled exactly by the power rule. Any other expression is differentiated
//! by the standard rules (sum, product, quotient, chain) and the value is cross-checked
//! against a central difference; it is integrated numerically by the `quadrature` crate's
//! double exponential rule, which reports its own error estimate.

use super::poly::{mentions, polynomial, reported, unknowns, with_constants_folded, Poly};
use super::solve::function;
use super::{as_exact, as_float, binary, eval, float, list, object, parse, quoted, shown, text, Names, Node, Outcome, Value};
use num_bigint::BigInt;
use num_rational::BigRational;
use num_traits::Signed;
use std::cell::RefCell;
use std::collections::BTreeSet;
use std::rc::Rc;
use std::time::{Duration, Instant};

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
/// The scan before integrating: about this many part evaluations in all, so between MIN_SCAN and
/// MAX_SCAN evenly spaced points depending on the expression's length, and the most rough
/// stretches worth cutting at.
const SCAN_WORK: usize = 8_000_000;
const MIN_SCAN: usize = 4096;
const MAX_SCAN: usize = 1 << 20;
const MAX_STRETCHES: usize = 256;
/// Wall-clock budget for one numeric integral; past it the result is reported as not converged.
const TIME_BUDGET: Duration = Duration::from_secs(3);
/// The fewest floats a range must span at its larger end for sampling to mean anything.
const MIN_RANGE_FLOATS: f64 = 67_108_864.0;
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

/// The expression as a plain float function of `name`, for scanning only. It rounds where
/// the calculator proper is exact and returns NaN where that would refuse, so it decides where
/// to look closely and never supplies a reported number. `None` when a part has no float form.
fn scanner(node: &Node, name: &str, names: Names) -> Option<Box<dyn Fn(f64) -> f64>> {
    let part = |inner: &Node| scanner(inner, name, names);
    Some(match node {
        Node::Number(value) => {
            let constant = as_float(value).ok()?;
            Box::new(move |_| constant)
        }
        Node::Name(found) if found == name => Box::new(|x| x),
        Node::Name(found) => {
            let constant = as_float(&names(found)?).ok()?;
            Box::new(move |_| constant)
        }
        Node::Negate(inner) => {
            let inner = part(inner)?;
            Box::new(move |x| -inner(x))
        }
        Node::Binary(op, left, right) => {
            let (left, right) = (part(left)?, part(right)?);
            match *op {
                "+" => Box::new(move |x| left(x) + right(x)),
                "-" => Box::new(move |x| left(x) - right(x)),
                "*" => Box::new(move |x| left(x) * right(x)),
                "/" => Box::new(move |x| left(x) / right(x)),
                "**" => Box::new(move |x| left(x).powf(right(x))),
                _ => return None,
            }
        }
        Node::Call(function, arguments) => {
            let [inner] = arguments.as_slice() else { return None };
            let inner = part(inner)?;
            let apply: fn(f64) -> f64 = match function.as_str() {
                "sqrt" => f64::sqrt,
                "exp" => f64::exp,
                "log" => f64::ln,
                "log2" => f64::log2,
                "log10" => f64::log10,
                "sin" => f64::sin,
                "cos" => f64::cos,
                "tan" => f64::tan,
                "abs" => f64::abs,
                _ => return None,
            };
            Box::new(move |x| apply(inner(x)))
        }
    })
}

/// Places inside the range where evenly spaced samples show the integrand bending faster
/// than a smooth function of the panel's width would: the ends of each such stretch. A peak
/// or step wider than the sample spacing shows up here even when it falls between the
/// quadrature rule's own points.
fn rough_stretches(scan: &dyn Fn(f64) -> f64, low: f64, high: f64, points: usize, late: &dyn Fn() -> bool) -> Vec<f64> {
    let at = |index: usize| low + (high - low) * index as f64 / points as f64;
    let mut values = Vec::with_capacity(points + 1);
    for index in 0..=points {
        if index % 1024 == 0 && late() {
            return Vec::new(); // out of time: integrate without the scan's cuts
        }
        values.push(scan(at(index)));
    }
    let scale = values.iter().filter(|value| value.is_finite()).fold(0.0_f64, |largest, value| largest.max(value.abs()));
    // The bend of a smooth feature as wide as a panel, measured over one sample spacing.
    let allowed = (PANELS as f64 * 2.0 / points as f64).powi(2) * scale;
    let bends = |index: usize| {
        let (before, here, after) = (values[index - 1], values[index], values[index + 1]);
        !(before.is_finite() && here.is_finite() && after.is_finite()) || (before - 2.0 * here + after).abs() > allowed
    };
    let mut ends = Vec::new();
    let mut open: Option<usize> = None;
    let mut flagged = 0;
    for index in 1..points {
        match (bends(index), open) {
            (true, None) => open = Some(index - 1),
            (false, Some(start)) => {
                ends.extend([at(start), at(index)]);
                open = None;
            }
            _ => {}
        }
        flagged += bends(index) as usize;
    }
    if let Some(start) = open {
        ends.extend([at(start), high]);
    }
    // Rough nearly everywhere (a fast oscillation, or a coarse scan): the stretches say nothing the panels do not.
    if ends.len() > 2 * MAX_STRETCHES || flagged * 5 > points { Vec::new() } else { ends }
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
/// panels (evenly, and at `cuts`, the ends of the stretches the scan found rough) and each
/// panel is accepted only when it agrees with the sum of its two halves; a panel that does
/// not is halved again. A feature narrower than the scan's spacing can still be missed: no
/// finite sampling can exclude that, and the report states the spacing.
fn area(f: &dyn Fn(f64) -> f64, low: f64, high: f64, cuts: &[f64], failed: &dyn Fn() -> bool) -> Area {
    let mut result = Area { value: 0.0, error: 0.0, evaluations: 0, settled: true };
    if low >= high || low.is_nan() || high.is_nan() {
        return result;
    }
    let piece = |from: f64, to: f64, evaluations: &mut u64| {
        let part = quadrature::integrate(f, from, to, INTEGRAL_TARGET);
        *evaluations += part.num_function_evaluations as u64;
        part.integral
    };
    let mut edges: Vec<f64> = (0..=PANELS).map(|panel| if panel == PANELS { high } else { low + (high - low) * panel as f64 / PANELS as f64 }).collect();
    edges.extend(cuts.iter().filter(|cut| **cut > low && **cut < high));
    edges.sort_by(f64::total_cmp);
    edges.dedup();
    // (from, to, estimate, depth)
    let mut pending = Vec::new();
    let mut scale = 0.0;
    for pair in edges.windows(2) {
        let whole = piece(pair[0], pair[1], &mut result.evaluations);
        scale += whole.abs();
        pending.push((pair[0], pair[1], whole, 0));
    }
    while let Some((from, to, whole, depth)) = pending.pop() {
        if failed() {
            // Stopped early (out of time, or a point that cannot be evaluated): what is left
            // keeps its unrefined estimate and the result is marked as not settled.
            result.value += whole + pending.iter().map(|panel| panel.2).sum::<f64>();
            result.settled = false;
            break;
        }
        let middle = 0.5 * (from + to);
        let (left, right) = (piece(from, middle, &mut result.evaluations), piece(middle, to, &mut result.evaluations));
        let gap = (whole - (left + right)).abs();
        // The total of the pieces' sizes, kept current, is what "small" is measured against.
        scale += left.abs() + right.abs() - whole.abs();
        if !(from < middle && middle < to) {
            // No float lies between the ends, so the "halves" are the panel itself and their
            // agreement with it says nothing.
            result.value += whole;
            result.settled = false;
        } else if gap <= PANEL_AGREEMENT * scale.max(f64::MIN_POSITIVE) || gap == 0.0 {
            result.value += left + right;
            result.error += gap;
        } else if depth >= MAX_HALVINGS || result.evaluations > MAX_EVALUATIONS {
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
        // The rules can give a formula defined where the expression is not (1/x for log(x) at
        // -1), so the expression itself must have a value at the point.
        eval(&node, &|found| if found == name { Some(at.clone()) } else { names(found) })
            .map_err(|error| format!("the expression has no value at {name} = {}, so it has no derivative there: {error}", text(&Node::Number(at.clone()))))?;
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
        } else {
            fields.push(("central_difference", "null".into()));
            fields.push(("agrees", "null".into()));
            fields.push(("note", quoted("the expression has no value just to one side of this point (the edge of its domain), so the value is the rules' result without the cross-check")));
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
    // The integral runs between the floats nearest the bounds. When the bounds are close
    // together those floats can span a different width (1 to 1 + 3/10**16 becomes 1 to
    // 1 + 2**-52, a quarter narrower), so the float width must match the exact width.
    let exact_width = as_exact(&high)? - as_exact(&low)?;
    let float_width = BigRational::from_float(b).unwrap_or_default() - BigRational::from_float(a).unwrap_or_default();
    let allowed = exact_width.abs() / BigRational::from_integer(BigInt::from(1_000_000_000u64));
    if (float_width - &exact_width).abs() > allowed {
        return Err("--from and --to are too close together for floats to hold the width of the range; a numeric integral would run over a different range".into());
    }
    // Sampling needs room: a range only a few floats wide puts every sample on the same handful
    // of points.
    let largest = a.abs().max(b.abs());
    if (b - a).abs() < MIN_RANGE_FLOATS * (largest.next_up() - largest) {
        return Err("--from and --to are only a few floats apart, too close for a numeric integral to sample between them".into());
    }
    let node = with_constants_folded(&node, &name, names);
    let deadline = Instant::now() + TIME_BUDGET;
    let failure = RefCell::new(None);
    let f = function(&node, &name, names, &failure);
    let (from, to) = (a.min(b), a.max(b));
    // Scan first, with a fast float form of the integrand when it has one; the scan only
    // chooses where the panels are cut, and its own failures (a point outside a domain) are
    // read as roughness.
    let fast = scanner(&node, &name, names);
    let points = if fast.is_some() { (SCAN_WORK / size(&node, usize::MAX).max(1)).clamp(MIN_SCAN, MAX_SCAN) } else { MIN_SCAN };
    let ignored = RefCell::new(None);
    let slow = function(&node, &name, names, &ignored);
    let late = || Instant::now() > deadline;
    let cuts = match &fast {
        Some(fast) => rough_stretches(fast, from, to, points, &late),
        None => rough_stretches(&slow, from, to, points, &late),
    };
    let result = area(&f, from, to, &cuts, &|| failure.borrow().is_some() || late());
    if let Some(error) = failure.borrow_mut().take() {
        return Err(format!("the integrand cannot be evaluated {error}"));
    }
    let value = if a <= b { result.value } else { -result.value };
    let converged = result.settled && result.error.is_finite() && result.error <= INTEGRAL_ACCEPTED * value.abs().max(1.0);
    fields.push(("value", shown(&float(value)?)));
    fields.push(("error_estimate", if result.error.is_finite() { format!("{:?}", result.error) } else { "null".into() }));
    fields.push(("evaluations", result.evaluations.to_string()));
    fields.push(("converged", converged.to_string()));
    fields.push(("scan_points", points.to_string()));
    fields.push(("method", quoted("double exponential (tanh-sinh) quadrature on panels cut where a scan found the integrand rough, each halved until whole and halves agree; a feature narrower than the range divided by scan_points can be missed")));
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
