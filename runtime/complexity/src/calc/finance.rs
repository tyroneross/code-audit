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
    // In floats, (1 + rate)**nper - 1 subtracts two nearly equal numbers when the rate is small
    // (a rate of 1e-12 loses four digits of the answer). log1p and expm1 give the same
    // quantities without the subtraction. Exact inputs take the exact path below.
    let in_floats = matches!(rate, Value::Float(_)) || !matches!(nper, Value::Exact(periods) if periods.is_integer());
    if let (true, Ok(r), Ok(n), Ok(w)) = (in_floats, as_float(rate), as_float(nper), as_float(when)) {
        if r > -1.0 && r != 0.0 {
            let log_growth = n * r.ln_1p();
            return Ok((float(log_growth.exp())?, float((1.0 + r * w) * log_growth.exp_m1() / r)?));
        }
    }
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

/// The one rate above -100% at which the flows' present value is zero, for flows whose sign
/// changes once. The search runs in u = log(1 + rate), bracketed between powers of two of the
/// growth factor and finished by Brent's method; the rate is expm1(u), which keeps the digits
/// of a rate near zero.
fn only_rate(flows: &[Value]) -> Outcome<f64> {
    let amounts = flows.iter().map(as_float).collect::<Outcome<Vec<_>>>()?;
    let last = (amounts.len() - 1) as f64;
    // Present value times exp(u * periods) when u is negative, so neither form overflows; the sign is the same.
    let f = |u: f64| {
        let weight = |period: f64| if u >= 0.0 { (-u * period).exp() } else { (u * (last - period)).exp() };
        amounts.iter().enumerate().map(|(period, amount)| amount * weight(period as f64)).sum::<f64>()
    };
    let grid: Vec<f64> = (-40..=40).map(|power| power as f64 * std::f64::consts::LN_2).collect();
    let bracket = grid.windows(2).find(|pair| (f(pair[0]) < 0.0) != (f(pair[1]) < 0.0) || f(pair[1]) == 0.0);
    let pair = bracket.ok_or("irr: no rate between -100% and a trillion-fold brings the net present value to zero")?;
    let u = find_root_brent(pair[0], pair[1], &f, &mut Narrow).map_err(|error| format!("irr: {error}"))?;
    Ok(u.exp_m1())
}

/// The internal rate of return: the rate at which the flows' net present value is zero.
fn irr(flows: &[Value]) -> Outcome<Value> {
    if flows.len() < 2 || flows.len() > MAX_FLOWS {
        return Err(format!("irr takes between 2 and {MAX_FLOWS} cash flows"));
    }
    let mut exact_flows = flows.iter().map(as_exact).collect::<Outcome<Vec<_>>>()?;
    if !(exact_flows.iter().any(Signed::is_positive) && exact_flows.iter().any(Signed::is_negative)) {
        return Err("irr needs at least one cash flow paid out (negative) and one received (positive)".into());
    }
    // Flows of zero at the end add nothing (and would put a false root at a rate of -100%).
    while exact_flows.last().is_some_and(Zero::is_zero) {
        exact_flows.pop();
    }
    let inexact = flows.iter().any(|flow| matches!(flow, Value::Float(_)));
    // One change of sign along the flows means exactly one rate above -100% (Descartes' rule of
    // signs), which a bracketed search finds at any length; several changes need every root.
    let signs: Vec<bool> = exact_flows.iter().filter(|flow| !flow.is_zero()).map(Signed::is_positive).collect();
    let changes = signs.windows(2).filter(|pair| pair[0] != pair[1]).count();
    let rates = if changes == 1 && exact_flows.len() - 1 > MAX_EXACT_PERIODS {
        vec![Root::Near(only_rate(&flows[..exact_flows.len()])?)]
    } else {
        // With g = 1 + rate, sum(flow[t] / g**t) = 0 is the polynomial sum(flow[t] * g**(n - t)) = 0.
        // It is rewritten in the rate itself before the roots are found, so a rate near zero
        // is located as a small number and not as the difference of two numbers near one.
        let in_growth = Poly::new(exact_flows.iter().rev().cloned().collect(), inexact);
        real_roots(&in_growth.shifted_by_one()?, Some(&-BigRational::one()))?
    };
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
            // nper = log((-fv + z) / (pv + z)) / log(1 + rate), with z = pmt*(1 + rate*when)/rate.
            // The ratio is 1 - (fv + pv)/(pv + z), so log1p takes the part after the 1 directly and
            // a small rate, where the ratio is close to 1, keeps its digits.
            let z = div(&mul(pmt, &add(&whole(1)?, &mul(rate, &when)?)?)?, rate)?;
            let beyond_one = as_float(&negate(div(&add(&fv, pv)?, &add(pv, &z)?)?))?;
            let r = as_float(rate)?;
            if beyond_one <= -1.0 || r <= -1.0 {
                return Err("nper: these payments never reach the future value; check the signs (cash paid out is negative)".into());
            }
            float(beyond_one.ln_1p() / r.ln_1p())
        })(),
        ("rate", [nper, pmt, pv, fv, rest @ ..]) if rest.len() <= 1 => timing(rest.first()).and_then(|when| rate(nper, pmt, pv, fv, &when)),
        ("npv", [rate, flows @ ..]) if !flows.is_empty() => present(rate, flows),
        ("irr", flows) => irr(flows),
        ("mirr", [finance, reinvest, flows @ ..]) => mirr(finance, reinvest, flows),
        ("fv" | "pv" | "pmt" | "nper" | "rate" | "npv" | "mirr", _) => Err(format!("{name}: wrong number of values; see --help for its arguments")),
        _ => return None,
    };
    // One rule for every function here: a float among the arguments makes the result a float,
    // whichever branch or shortcut produced it.
    let approximate = values.iter().any(|value| matches!(value, Value::Float(_)));
    Some(result.and_then(|value| match value {
        Value::Exact(exact) if approximate => float(super::to_float(&exact)?),
        other => Ok(other),
    }))
}
