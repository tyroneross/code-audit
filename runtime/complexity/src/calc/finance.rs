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
use super::solve::{real_roots, single_root_above, Root, Span};
use super::{as_exact, as_float, binary, float, integer, is_zero, negate, other_side, power, steady, Outcome, Value};
use num_bigint::BigInt;
use num_rational::BigRational;
use num_traits::{One, Signed, ToPrimitive, Zero};

const RATE_STEPS: usize = 100;
const RATE_TOLERANCE: f64 = 1e-12;
const MAX_FLOWS: usize = 240;
/// rate(): exact polishing steps, and the longest term whose equation is evaluated exactly.
const RATE_POLISH: usize = 12;
const MAX_EXACT_RATE_PERIODS: i32 = 1200;
/// fv, pv and pmt are exact while periods times the bits of the rate stays under this, which
/// bounds the size of (1 + rate)**nper.
const MAX_EXACT_GROWTH_BITS: u64 = 200_000;
/// The relative rounding error a float amount may carry after a few operations.
const FLOAT_NOISE: f64 = 8.0 * f64::EPSILON;
/// Up to this many periods every real root is isolated exactly, so a rational rate is reported exactly.
const MAX_EXACT_PERIODS: usize = 32;

fn whole(value: i64) -> Outcome<Value> {
    integer(BigInt::from(value))
}

fn add(a: &Value, b: &Value) -> Outcome<Value> {
    binary("+", a.clone(), b.clone())
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

/// log(1 + beyond) for beyond above -1. A float goes to log1p, which keeps the digits of a
/// small one. An exact value is added to 1 exactly first, so one next to -1 (a rate of
/// -1 + 1/10**16) or next to 0 keeps its digits too.
fn log_one_plus(beyond: &Value) -> Outcome<f64> {
    match beyond {
        Value::Float(float) if *float > -1.0 => Ok(float.ln_1p()),
        Value::Exact(_) => super::natural_log(&add(&whole(1)?, beyond)?),
        _ => Err("log is not defined for this value".into()),
    }
}

#[derive(Clone, Copy)]
enum Wanted {
    Future,
    Present,
    Payment,
}

/// fv, pv or pmt from the other values of the time-value equation.
///
/// A whole number of periods is the usual case, and there the equation is a ratio of
/// polynomials in the rate: it is evaluated in exact rationals, on the inputs' own values
/// (a float input is the exact number that float is), and rounded once at the end if any
/// input was a float. Nothing cancels and no digit is lost on the way.
///
/// A fractional (or very long) term has no such form. It is computed in floats through
/// log1p and expm1, which avoid the subtraction in (1 + rate)**nper - 1, and the last step,
/// a sum of two amounts, is refused when it leaves a difference too small for the floats
/// that made it.
fn time_value(wanted: Wanted, rate: &Value, nper: &Value, pmt: &Value, pv: &Value, fv: &Value, when: &Value) -> Outcome<Value> {
    let approximate = [rate, nper, pmt, pv, fv].into_iter().any(|value| matches!(value, Value::Float(_)));
    let one = BigRational::one();
    let (exact_rate, periods) = (as_exact(rate)?, as_exact(nper)?);
    let whole_periods = periods.is_integer().then(|| periods.to_integer().to_i32()).flatten();
    let rate_bits = exact_rate.numer().bits().max(exact_rate.denom().bits());
    if let Some(n) = whole_periods.filter(|n| n.unsigned_abs() as u64 * rate_bits <= MAX_EXACT_GROWTH_BITS) {
        let (w, p, x, y) = (as_exact(when)?, as_exact(pmt)?, as_exact(pv)?, as_exact(fv)?);
        let base = &one + &exact_rate;
        if base.is_zero() && n < 0 {
            return Err("division by zero".into());
        }
        let grown = base.pow(n);
        let factor = if exact_rate.is_zero() { periods } else { (&one + &exact_rate * &w) * (&grown - &one) / &exact_rate };
        let result = match wanted {
            Wanted::Future => -(&x * &grown + &p * &factor),
            Wanted::Present if grown.is_zero() => return Err("division by zero".into()),
            Wanted::Present => -(&y + &p * &factor) / &grown,
            Wanted::Payment if factor.is_zero() => return Err("division by zero".into()),
            Wanted::Payment => -(&y + &x * &grown) / &factor,
        };
        return if approximate { float(super::nearest(&result)?) } else { super::exact(result) };
    }
    if whole_periods.is_some() && !approximate {
        return Err("the exact result would be too large to hold; write the rate as a float (0.05 for 5/100) for a float result".into());
    }
    let (r, n, p, x, y) = (as_float(rate)?, as_float(nper)?, as_float(pmt)?, as_float(pv)?, as_float(fv)?);
    if r <= -1.0 {
        return Err("a rate at or below -100% needs a whole number of periods".into());
    }
    // grown = (1 + rate)**nper, less_one = grown - 1 without the subtraction, and the payment
    // factor (1 + rate*when)*less_one/rate, which is nper when the rate is 0.
    let (grown, less_one, factor) = if r == 0.0 {
        (1.0, 0.0, n)
    } else {
        let log_growth = n * log_one_plus(rate)?;
        // 1 + rate*when is taken exactly before it becomes a float: at a rate next to -1 it is next to zero.
        let lead = as_float(&add(&whole(1)?, &mul(rate, when)?)?)?;
        (log_growth.exp(), log_growth.exp_m1(), lead * log_growth.exp_m1() / r)
    };
    // The answer is minus a sum of two amounts over a divisor. For pmt the sum is written as
    // (fv + pv) + pv*(grown - 1), with fv + pv taken exactly, so opposite fv and pv do not cancel.
    let (terms, divisor) = match wanted {
        Wanted::Future => ([x * grown, p * factor], 1.0),
        Wanted::Present => ([y, p * factor], grown),
        Wanted::Payment => ([as_float(&add(fv, pv)?)?, x * less_one], factor),
    };
    let sum = terms[0] + terms[1];
    if terms[0].abs().max(terms[1].abs()) * FLOAT_NOISE > super::SENSITIVE * sum.abs() {
        return Err("the result is a small difference of large amounts, which floats cannot hold for a fractional number of periods; use a whole number of periods (computed exactly) or smaller amounts".into());
    }
    if divisor == 0.0 {
        return Err("division by zero".into());
    }
    float(-sum / divisor)
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

/// The time-value equation's left side at rate r, and its slope, in floats (n periods,
/// payment p, present value x, future value y, timing w).
fn rate_residual(r: f64, [n, p, x, y, w]: [f64; 5]) -> f64 {
    y + (r + 1.0).powf(n) * x + p * ((r + 1.0).powf(n) - 1.0) * (r * w + 1.0) / r
}

fn rate_slope(r: f64, [n, p, x, _, w]: [f64; 5]) -> f64 {
    let (t1, t2) = ((r + 1.0).powf(n), (r + 1.0).powf(n - 1.0));
    n * t2 * x - p * (t1 - 1.0) * (r * w + 1.0) / (r * r) + n * p * t2 * (r * w + 1.0) / r + p * (t1 - 1.0) * w / r
}

/// numpy-financial's Newton iteration, started at 10%; `None` when it does not settle.
fn newton_rate(inputs: [f64; 5]) -> Option<f64> {
    let mut r: f64 = 0.1;
    for _ in 0..RATE_STEPS {
        let next = r - rate_residual(r, inputs) / rate_slope(r, inputs);
        if !next.is_finite() {
            return None;
        }
        let settled = (next - r).abs() < RATE_TOLERANCE;
        r = next;
        if settled {
            return Some(r);
        }
    }
    None
}

/// The rate per period.
fn rate(nper: &Value, pmt: &Value, pv: &Value, fv: &Value, when: &Value) -> Outcome<Value> {
    // A rate of zero satisfies the equation exactly when fv + pv + pmt*nper is zero, and the
    // iteration divides by the rate, so it is decided first.
    if is_zero(&add(&add(fv, pv)?, &mul(pmt, nper)?)?) {
        return whole(0);
    }
    let inputs = [as_float(nper)?, as_float(pmt)?, as_float(pv)?, as_float(fv)?, as_float(when)?];
    let unsettled = || Err("rate: the iteration did not settle on a rate; check the signs (cash paid out is negative)".to_string());
    let Some(mut r) = newton_rate(inputs) else { return unsettled() };
    // The floats may have rounded the inputs (a future value of 1 + 2**-60 is 1.0). With a
    // whole number of periods the equation can be evaluated exactly, so the rate is polished
    // and confirmed there: each step moves by the exact residual over the slope, and the
    // rate is accepted once that step is below one part in 10**12.
    let periods = match nper {
        Value::Exact(count) if count.is_integer() => count.to_integer().to_i32().filter(|count| count.abs() <= MAX_EXACT_RATE_PERIODS),
        _ => None,
    };
    let Some(periods) = periods else {
        // A fractional or very long term has no exact form. The float answer is accepted when
        // it satisfies the float equation and does not move when an input that is not itself
        // a float is replaced by the float on its other side.
        let [n, p, x, y, _] = inputs;
        let scale = y.abs().max(x.abs()).max((p * n).abs()).max(1.0);
        if rate_residual(r, inputs).abs() > 1e-7 * scale {
            return unsettled();
        }
        // The equation's left side is only known to float noise times the amounts in it. That
        // noise over the slope is how far the rate could be off; it must be below one part in 10**9.
        if FLOAT_NOISE * scale / rate_slope(r, inputs).abs() > super::SENSITIVE * r.abs() {
            return Err("rate: the amounts are too large beside their difference for floats to fix the rate with a fractional number of periods; use a whole number of periods".into());
        }
        for (index, value) in [nper, pmt, pv, fv].into_iter().enumerate() {
            if let Some(nearby) = other_side(value, inputs[index]) {
                let mut moved = inputs;
                moved[index] = nearby;
                let Some(other) = newton_rate(moved) else { return unsettled() };
                steady("rate", r, other)?;
            }
        }
        return float(r);
    };
    let (exact_pmt, exact_pv, exact_fv, exact_when) = (as_exact(pmt)?, as_exact(pv)?, as_exact(fv)?, as_exact(when)?);
    let one = BigRational::one();
    for _ in 0..RATE_POLISH {
        let Some(rate) = BigRational::from_float(r).filter(|rate| !rate.is_zero() && *rate > -one.clone()) else { return unsettled() };
        let grown = (&one + &rate).pow(periods);
        let residual = &exact_fv + &exact_pv * &grown + &exact_pmt * (&one + &rate * &exact_when) / &rate * (&grown - &one);
        let step = super::to_float(&residual)? / rate_slope(r, inputs);
        if !step.is_finite() {
            return unsettled();
        }
        if step.abs() <= 1e-12 * r.abs() {
            return float(r);
        }
        r -= step;
    }
    unsettled()
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
    // With g = 1 + rate, sum(flow[t] / g**t) = 0 is the polynomial sum(flow[t] * g**(n - t)) = 0.
    // It is rewritten in the rate itself before the roots are found, so a rate near zero is
    // located as a small number and not as the difference of two numbers near one.
    let in_rate = Poly::new(exact_flows.iter().rev().cloned().collect(), inexact).shifted_by_one();
    let floor = -BigRational::one();
    let rates = if changes == 1 {
        vec![single_root_above(&in_rate, &floor).map_err(|error| format!("irr: {error}"))?]
    } else if exact_flows.len() - 1 > MAX_EXACT_PERIODS {
        return Err(format!("irr: these flows change sign {changes} times, so several rates may exist; all of them are found only up to {MAX_EXACT_PERIODS} periods"));
    } else {
        real_roots(&in_rate, &Span { low: Some(&floor), high: None, closed: false })?
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
    // (received / paid)**(1/(n - 1)) * (1 + reinvest) - 1, taken through logarithms: the
    // ratio stays exact until its logarithm, and expm1 gives the final "minus one" without
    // subtracting two numbers that may both be near 1.
    let sized = |value: Value| if matches!(&value, Value::Exact(r) if r.is_negative()) || matches!(&value, Value::Float(f) if *f < 0.0) { negate(value) } else { value };
    let ratio = div(&sized(present(reinvest, &received)?), &sized(present(finance, &paid)?))?;
    let carried = super::natural_log(&add(&whole(1)?, reinvest)?).map_err(|_| "mirr: the reinvestment rate must be above -100%".to_string())?;
    float((super::natural_log(&ratio)? / (flows.len() as f64 - 1.0) + carried).exp_m1())
}

/// A finance function by name, or `None` when the name is not one.
pub(super) fn call(name: &str, values: &[Value]) -> Option<Outcome<Value>> {
    let zero = whole(0);
    let result = match (name, values) {
        ("fv", [rate, nper, pmt, pv, rest @ ..]) if rest.len() <= 1 => (|| time_value(Wanted::Future, rate, nper, pmt, pv, &zero.clone()?, &timing(rest.first())?))(),
        ("pv", [rate, nper, pmt, rest @ ..]) if rest.len() <= 2 => {
            (|| time_value(Wanted::Present, rate, nper, pmt, &zero.clone()?, rest.first().unwrap_or(&zero.clone()?), &timing(rest.get(1))?))()
        }
        ("pmt", [rate, nper, pv, rest @ ..]) if rest.len() <= 2 => {
            (|| time_value(Wanted::Payment, rate, nper, &zero.clone()?, pv, rest.first().unwrap_or(&zero.clone()?), &timing(rest.get(1))?))()
        }
        ("nper", [rate, pmt, pv, rest @ ..]) if rest.len() <= 2 => (|| {
            let (fv, when) = (rest.first().cloned().unwrap_or(zero.clone()?), timing(rest.get(1))?);
            if is_zero(rate) {
                return div(&negate(add(&fv, pv)?), pmt);
            }
            // nper = log((-fv + z) / (pv + z)) / log(1 + rate), with z = pmt*(1 + rate*when)/rate.
            // The ratio is 1 - (fv + pv)/(pv + z), so log1p takes the part after the 1 directly and
            // a small rate, where the ratio is close to 1, keeps its digits.
            let z = div(&mul(pmt, &add(&whole(1)?, &mul(rate, &when)?)?)?, rate)?;
            let beyond_one = negate(div(&add(&fv, pv)?, &add(pv, &z)?)?);
            if as_float(&beyond_one)? <= -1.0 || as_float(rate)? <= -1.0 {
                return Err("nper: these payments never reach the future value; check the signs (cash paid out is negative)".into());
            }
            float(log_one_plus(&beyond_one)? / log_one_plus(rate)?)
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
