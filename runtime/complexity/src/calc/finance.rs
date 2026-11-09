//! Time value of money, with the formulas and conventions of numpy-financial (BSD-3-Clause,
//! https://github.com/numpy/numpy-financial at 031ed55): cash paid out is negative, cash
//! received is positive, and `when` is 0 for payments at the end of a period or 1 for the
//! beginning. Every function solves
//!
//!   fv + pv*(1 + rate)**nper + pmt*(1 + rate*when)/rate*((1 + rate)**nper - 1) == 0
//!
//! or, when rate is 0,  fv + pv + pmt*nper == 0.
//!
//! The formulas run on the calculator's own values, so exact inputs (a rate written 5/100)
//! give exact results and a float input gives a float.

use super::poly::Poly;
use super::solve::{real_roots, Narrow, Root};
use super::{as_exact, as_float, binary, float, integer, is_zero, negate, power, Outcome, Value};
use num_bigint::BigInt;
use num_rational::BigRational;
use num_traits::{One, Signed, Zero};
use roots::find_root_brent;

const RATE_STEPS: usize = 100;
const RATE_TOLERANCE: f64 = 1e-12;
const MAX_FLOWS: usize = 240;
/// Up to this many periods every real root is isolated exactly, so a rational rate is reported exactly.
const MAX_EXACT_PERIODS: usize = 32;

fn whole(value: i64) -> Outcome<Value> {
    integer(BigInt::from(value))
}

fn add(a: &Value, b: &Value) -> Outcome<Value> {
    binary("+", a.clone(), b.clone())
}

fn sub(a: &Value, b: &Value) -> Outcome<Value> {
    binary("-", a.clone(), b.clone())
}

fn mul(a: &Value, b: &Value) -> Outcome<Value> {
    binary("*", a.clone(), b.clone())
}

fn div(a: &Value, b: &Value) -> Outcome<Value> {
    binary("/", a.clone(), b.clone())
}

/// 0 (end of period) or 1 (beginning), and nothing else.
fn timing(value: Option<&Value>) -> Outcome<Value> {
    match value {
        None => whole(0),
        Some(Value::Exact(r)) if r.is_zero() || r.is_one() => Ok(Value::Exact(r.clone())),
        Some(_) => Err("when is 0 (payments at the end of each period) or 1 (at the beginning)".into()),
    }
}

/// (1 + rate)**nper, and the payment factor (1 + rate*when)*(that - 1)/rate, which is nper when rate is 0.
fn growth(rate: &Value, nper: &Value, when: &Value) -> Outcome<(Value, Value)> {
    let grown = power(add(&whole(1)?, rate)?, nper.clone())?;
    let factor = if is_zero(rate) {
        nper.clone()
    } else {
        div(&mul(&add(&whole(1)?, &mul(rate, when)?)?, &sub(&grown, &whole(1)?)?)?, rate)?
    };
    Ok((grown, factor))
}

/// The net present value of flows at times 0, 1, 2, ...
fn present(rate: &Value, flows: &[Value]) -> Outcome<Value> {
    let base = add(&whole(1)?, rate)?;
    if is_zero(&base) {
        return Err("a rate of -1 loses everything each period: the present value is undefined".into());
    }
    let mut total = whole(0)?;
    for (period, flow) in flows.iter().enumerate() {
        total = add(&total, &div(flow, &power(base.clone(), whole(period as i64)?)?)?)?;
    }
    Ok(total)
}

/// The rate per period, by the Newton iteration numpy-financial uses, started at 10%.
fn rate(nper: &Value, pmt: &Value, pv: &Value, fv: &Value, when: &Value) -> Outcome<Value> {
    // A rate of zero satisfies the equation exactly when fv + pv + pmt*nper is zero, and the
    // iteration below divides by the rate, so it is decided first.
    if is_zero(&add(&add(fv, pv)?, &mul(pmt, nper)?)?) {
        return whole(0);
    }
    let (n, p, x, y, w) = (as_float(nper)?, as_float(pmt)?, as_float(pv)?, as_float(fv)?, as_float(when)?);
    let g = |r: f64| y + (r + 1.0).powf(n) * x + p * ((r + 1.0).powf(n) - 1.0) * (r * w + 1.0) / r;
    let mut r: f64 = 0.1;
    for _ in 0..RATE_STEPS {
        let (t1, t2) = ((r + 1.0).powf(n), (r + 1.0).powf(n - 1.0));
        let slope = n * t2 * x - p * (t1 - 1.0) * (r * w + 1.0) / (r * r) + n * p * t2 * (r * w + 1.0) / r + p * (t1 - 1.0) * w / r;
        let next = r - g(r) / slope;
        if !next.is_finite() {
            break;
        }
        let moved = (next - r).abs();
        r = next;
        if moved < RATE_TOLERANCE {
            // The answer is accepted only if it satisfies the equation it came from.
            let scale = y.abs().max(x.abs()).max((p * n).abs()).max(1.0);
            if g(r).abs() <= 1e-7 * scale {
                return float(r);
            }
            break;
        }
    }
    Err("rate: the iteration did not settle on a rate; check the signs (cash paid out is negative)".into())
}

/// The one growth factor g = 1 + rate above zero at which the flows' present value is zero,
/// for flows whose sign changes once. Bracketed between powers of two, then Brent's method.
fn only_growth(flows: &[Value]) -> Outcome<f64> {
    let amounts = flows.iter().map(as_float).collect::<Outcome<Vec<_>>>()?;
    // Present value per unit of g**0 for g >= 1, and of g**n below 1: the same sign, and neither overflows.
    let f = |g: f64| {
        if g >= 1.0 { amounts.iter().rev().fold(0.0, |sum, amount| sum / g + amount) } else { amounts.iter().fold(0.0, |sum, amount| sum * g + amount) }
    };
    let grid: Vec<f64> = (-40..=40).map(|power| 2f64.powi(power)).collect();
    let bracket = grid.windows(2).find(|pair| (f(pair[0]) < 0.0) != (f(pair[1]) < 0.0) || f(pair[1]) == 0.0);
    let pair = bracket.ok_or("irr: no rate between -100% and a trillion-fold brings the net present value to zero")?;
    find_root_brent(pair[0], pair[1], &f, &mut Narrow).map_err(|error| format!("irr: {error}"))
}

/// The internal rate of return: the rate at which the flows' net present value is zero.
fn irr(flows: &[Value]) -> Outcome<Value> {
    if flows.len() < 2 || flows.len() > MAX_FLOWS {
        return Err(format!("irr takes between 2 and {MAX_FLOWS} cash flows"));
    }
    let exact_flows = flows.iter().map(as_exact).collect::<Outcome<Vec<_>>>()?;
    if !(exact_flows.iter().any(Signed::is_positive) && exact_flows.iter().any(Signed::is_negative)) {
        return Err("irr needs at least one cash flow paid out (negative) and one received (positive)".into());
    }
    // With g = 1 + rate, sum(flow[t] / g**t) = 0 is the polynomial sum(flow[t] * g**(n - t)) = 0.
    let inexact = flows.iter().any(|flow| matches!(flow, Value::Float(_)));
    let p = Poly::new(exact_flows.iter().rev().cloned().collect(), inexact);
    let one = BigRational::one();
    // One change of sign along the flows means exactly one positive root (Descartes' rule of
    // signs), which a bracketed search finds at any length; several changes need every root.
    let signs: Vec<bool> = exact_flows.iter().filter(|flow| !flow.is_zero()).map(Signed::is_positive).collect();
    let changes = signs.windows(2).filter(|pair| pair[0] != pair[1]).count();
    let growths = if changes == 1 && p.degree() > MAX_EXACT_PERIODS { vec![Root::Near(only_growth(flows)?)] } else { real_roots(&p, true)? };
    let rates: Vec<Root> = growths
        .into_iter()
        .map(|root| match root {
            Root::Exact(g) => Root::Exact(g - &one),
            Root::Near(g) => Root::Near(g - 1.0),
        })
        .collect();
    let size = |root: &Root| root.value().and_then(|value| as_float(&value)).map(f64::abs).unwrap_or(f64::INFINITY);
    let positive = |root: &Root| matches!(root, Root::Exact(r) if !r.is_negative()) || matches!(root, Root::Near(r) if *r >= 0.0);
    // numpy-financial's choice among several rates: the non-negative ones when the signs
    // are mixed, then the one closest to zero.
    let mixed = rates.iter().any(positive) && !rates.iter().all(positive);
    let chosen = rates.iter().filter(|root| !mixed || positive(root)).min_by(|a, b| size(a).total_cmp(&size(b)));
    chosen.ok_or("irr: no rate above -100% brings the net present value to zero".to_string())?.value()
}

/// The modified internal rate of return: outflows financed at one rate, inflows reinvested at another.
fn mirr(finance: &Value, reinvest: &Value, flows: &[Value]) -> Outcome<Value> {
    if flows.len() < 2 {
        return Err("mirr takes a finance rate, a reinvestment rate and at least two cash flows".into());
    }
    let zero = whole(0)?;
    let keep = |wanted: fn(&BigRational) -> bool| -> Outcome<Vec<Value>> {
        flows.iter().map(|flow| Ok(if wanted(&as_exact(flow)?) { flow.clone() } else { zero.clone() })).collect()
    };
    let (received, paid) = (keep(Signed::is_positive)?, keep(Signed::is_negative)?);
    if received.iter().all(is_zero) || paid.iter().all(is_zero) {
        return Err("mirr needs at least one cash flow paid out (negative) and one received (positive)".into());
    }
    let top = as_float(&present(reinvest, &received)?)?.abs();
    let bottom = as_float(&present(finance, &paid)?)?.abs();
    float((top / bottom).powf(1.0 / (flows.len() as f64 - 1.0)) * (1.0 + as_float(reinvest)?) - 1.0)
}

/// A finance function by name, or `None` when the name is not one.
pub(super) fn call(name: &str, values: &[Value]) -> Option<Outcome<Value>> {
    let zero = whole(0);
    let result = match (name, values) {
        ("fv", [rate, nper, pmt, pv, rest @ ..]) if rest.len() <= 1 => (|| {
            let (grown, factor) = growth(rate, nper, &timing(rest.first())?)?;
            Ok(negate(add(&mul(pv, &grown)?, &mul(pmt, &factor)?)?))
        })(),
        ("pv", [rate, nper, pmt, rest @ ..]) if rest.len() <= 2 => (|| {
            let (grown, factor) = growth(rate, nper, &timing(rest.get(1))?)?;
            div(&negate(add(rest.first().unwrap_or(&zero.clone()?), &mul(pmt, &factor)?)?), &grown)
        })(),
        ("pmt", [rate, nper, pv, rest @ ..]) if rest.len() <= 2 => (|| {
            let (grown, factor) = growth(rate, nper, &timing(rest.get(1))?)?;
            div(&negate(add(rest.first().unwrap_or(&zero.clone()?), &mul(pv, &grown)?)?), &factor)
        })(),
        ("nper", [rate, pmt, pv, rest @ ..]) if rest.len() <= 2 => (|| {
            let (fv, when) = (rest.first().cloned().unwrap_or(zero.clone()?), timing(rest.get(1))?);
            if is_zero(rate) {
                return div(&negate(add(&fv, pv)?), pmt);
            }
            // nper = log((-fv + z) / (pv + z)) / log(1 + rate), with z = pmt*(1 + rate*when)/rate
            let z = div(&mul(pmt, &add(&whole(1)?, &mul(rate, &when)?)?)?, rate)?;
            let ratio = as_float(&div(&sub(&z, &fv)?, &add(pv, &z)?)?)?;
            let base = 1.0 + as_float(rate)?;
            if ratio <= 0.0 || base <= 0.0 {
                return Err("nper: these payments never reach the future value; check the signs (cash paid out is negative)".into());
            }
            float(ratio.ln() / base.ln())
        })(),
        ("rate", [nper, pmt, pv, fv, rest @ ..]) if rest.len() <= 1 => timing(rest.first()).and_then(|when| rate(nper, pmt, pv, fv, &when)),
        ("npv", [rate, flows @ ..]) if !flows.is_empty() => present(rate, flows),
        ("irr", flows) => irr(flows),
        ("mirr", [finance, reinvest, flows @ ..]) => mirr(finance, reinvest, flows),
        ("fv" | "pv" | "pmt" | "nper" | "rate" | "npv" | "mirr", _) => Err(format!("{name}: wrong number of values; see --help for its arguments")),
        _ => return None,
    };
    Some(result)
}
