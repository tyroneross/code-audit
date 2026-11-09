//! Equations: every real root of a polynomial, one root of any other equation inside a
//! bracket, and systems of linear equations.
//!
//! Polynomial roots are isolated exactly. The polynomial is reduced to its square-free part,
//! Sturm's theorem counts the distinct real roots in an interval from sign changes of a
//! remainder sequence, and bisection on exact rationals narrows each root. No root is missed
//! and a repeated root is reported once. (Floating-point root finders were measured first:
//! the `roots` crate's Sturm and eigenvalue routines missed repeated roots and one panicked,
//! so they are not used. Its bracketed Brent solver is used for equations that are not
//! polynomials.)

use super::poly::{eliminate, linear, polynomial, reported, unknowns, with_constants_folded, Poly, Solution};
use super::{as_exact, as_float, eval, list, nearest, object, parse, quoted, relation, shown, to_float, Names, Node, Outcome, Value};
use num_bigint::BigInt;
use num_integer::Integer;
use num_rational::BigRational;
use num_traits::{One, Signed, Zero};
use roots::{find_root_brent, Convergency};
use std::cell::RefCell;
use std::collections::BTreeSet;
use std::rc::Rc;

/// Highest degree whose roots are isolated, and the most work one polynomial may ask for
/// (degree squared times the bits of its largest integer coefficient).
const MAX_ROOT_DEGREE: usize = 32;
const MAX_ROOT_WORK: u64 = 200_000;
const MAX_EQUATIONS: usize = 32;
/// Enough for bisection alone to walk from 1 down to the smallest float, as a flat root at zero needs.
const BRENT_STEPS: usize = 2200;
/// At a crossing, the value at the root is at most this fraction of the value a step away on either side.
const CROSSING: f64 = 1e-3;
/// Bisection steps for a single root of a long polynomial; enough for a rate as small as 2**-300.
const MAX_SINGLE_STEPS: u64 = 480;

/// Integer coefficients, lowest power first, the highest not zero.
type Ints = Vec<BigInt>;

fn trimmed(mut c: Ints) -> Ints {
    while c.last().is_some_and(Zero::is_zero) {
        c.pop();
    }
    c
}

/// The same polynomial divided by the positive common divisor of its coefficients, so signs are unchanged.
fn primitive(c: Ints) -> Ints {
    let c = trimmed(c);
    let content = c.iter().fold(BigInt::zero(), |divisor, value| divisor.gcd(value));
    if content.is_zero() || content.is_one() {
        return c;
    }
    c.into_iter().map(|value| value / &content).collect()
}

fn integral(p: &Poly) -> Ints {
    let common = p.c.iter().fold(BigInt::one(), |multiple, value| multiple.lcm(value.denom()));
    primitive(p.c.iter().map(|value| (value * BigRational::from_integer(common.clone())).to_integer()).collect())
}

fn derivative(c: &Ints) -> Ints {
    c.iter().enumerate().skip(1).map(|(power, value)| value * BigInt::from(power)).collect()
}

/// A positive multiple of the remainder of a divided by b.
fn remainder(a: &Ints, b: &Ints) -> Ints {
    let mut rest = a.clone();
    while rest.len() >= b.len() {
        let (Some(lead), Some(top)) = (b.last(), rest.last().cloned()) else { break };
        let shift = rest.len() - b.len();
        // rest = |lead| x rest - sign(lead) x top x b x name**shift: the top term cancels and the factor is positive.
        let (size, signed) = (lead.abs(), if lead.is_negative() { -top } else { top });
        for value in rest.iter_mut() {
            *value *= &size;
        }
        for (index, value) in b.iter().enumerate() {
            rest[index + shift] -= &signed * value;
        }
        rest = primitive(rest);
    }
    rest
}

fn common_divisor(mut a: Ints, mut b: Ints) -> Ints {
    while !b.is_empty() {
        let rest = remainder(&a, &b);
        a = std::mem::replace(&mut b, rest);
    }
    primitive(a)
}

/// a divided by b when b divides a exactly.
fn quotient(a: &Ints, b: &Ints) -> Option<Ints> {
    let lead = b.last()?;
    let mut rest = a.clone();
    let mut result = vec![BigInt::zero(); a.len().checked_sub(b.len())? + 1];
    while rest.len() >= b.len() && !rest.is_empty() {
        let shift = rest.len() - b.len();
        let (factor, left_over) = rest.last()?.div_rem(lead);
        if !left_over.is_zero() {
            return None;
        }
        for (index, value) in b.iter().enumerate() {
            rest[index + shift] -= &factor * value;
        }
        result[shift] = factor;
        rest = trimmed(rest);
    }
    rest.is_empty().then(|| trimmed(result))
}

/// Sign of the polynomial at x = n/d, from the integer sum of c[i] x n**i x d**(degree - i).
fn sign_at(c: &Ints, x: &BigRational) -> i32 {
    let (mut sum, mut scale) = (BigInt::zero(), BigInt::one());
    for value in c.iter().rev() {
        sum = sum * x.numer() + value * &scale;
        scale *= x.denom();
    }
    if sum.is_zero() { 0 } else if sum.is_negative() { -1 } else { 1 }
}

/// Sturm's sequence: the polynomial, its derivative, then each negated remainder.
fn sturm(q: &Ints) -> Vec<Ints> {
    let mut chain = vec![q.clone(), primitive(derivative(q))];
    loop {
        let rest = remainder(&chain[chain.len() - 2], &chain[chain.len() - 1]);
        if rest.is_empty() {
            return chain;
        }
        chain.push(rest.into_iter().map(|value| -value).collect());
    }
}

/// Sign changes along the sequence at x. The count at a minus the count at b is the number
/// of distinct real roots between them, when neither end is a root.
fn variations(chain: &[Ints], x: &BigRational) -> usize {
    let signs: Vec<i32> = chain.iter().map(|p| sign_at(p, x)).filter(|sign| *sign != 0).collect();
    signs.windows(2).filter(|pair| pair[0] != pair[1]).count()
}

/// A point strictly between a and b that is not a root, the midpoint when possible.
fn split(q: &Ints, a: &BigRational, b: &BigRational) -> Outcome<BigRational> {
    for parts in 2..(q.len() as i64 + 3) {
        for step in 1..parts {
            let point = a + (b - a) * BigRational::new(BigInt::from(step), BigInt::from(parts));
            if sign_at(q, &point) != 0 {
                return Ok(point);
            }
        }
    }
    Err("root isolation failed: no split point".into())
}

pub(super) enum Root {
    Exact(BigRational),
    Near(f64),
}

/// The float nearest an exact root. A root too small or too large for a float is refused:
/// rounding it to 0.0 or infinity would report a number that is not a root.
fn near(value: &BigRational) -> Outcome<f64> {
    nearest(value).map_err(|error| format!("a root cannot be written as a float: {error}"))
}

impl Root {
    fn float(&self) -> f64 {
        match self {
            Root::Exact(value) => to_float(value).unwrap_or(if value.is_negative() { f64::NEG_INFINITY } else { f64::INFINITY }),
            Root::Near(value) => *value,
        }
    }

    pub fn value(&self) -> Outcome<Value> {
        match self {
            Root::Exact(value) => super::exact(value.clone()),
            Root::Near(value) => super::float(*value),
        }
    }
}

/// The single root of q strictly between a and b, where q changes sign.
fn refine(q: &Ints, mut a: BigRational, mut b: BigRational, steps: u64) -> Outcome<Root> {
    let two = BigRational::from_integer(BigInt::from(2));
    let precision = BigRational::from_integer(BigInt::one() << 62);
    let low_sign = sign_at(q, &a);
    let mut narrowed = false;
    for _ in 0..steps {
        let middle = (&a + &b) / &two;
        match sign_at(q, &middle) {
            0 => return Ok(Root::Exact(middle)),
            sign if sign == low_sign => a = middle,
            _ => b = middle,
        }
        // Zero is never a root here, so both ends end up on one side of it and relative width is defined.
        if a.is_positive() == b.is_positive() && !a.is_zero() && !b.is_zero() && (&b - &a) * &precision <= a.abs().min(b.abs()) {
            narrowed = true;
            break;
        }
    }
    if !narrowed {
        return Err("a root could not be narrowed to float precision within the step budget".into());
    }
    let middle = (&a + &b) / &two;
    // A rational root has a denominator that divides the leading coefficient, so it is the
    // nearest multiple of 1/lead; substituting it decides the matter exactly.
    if let Some(lead) = q.last().map(|lead| BigRational::from_integer(lead.clone())) {
        let candidate = (&middle * &lead).round() / &lead;
        if candidate > a && candidate < b && sign_at(q, &candidate) == 0 {
            return Ok(Root::Exact(candidate));
        }
    }
    Ok(Root::Near(near(&middle)?))
}

/// Where roots are wanted: between two exact bounds, either of which may be absent.
pub(super) struct Span<'a> {
    pub low: Option<&'a BigRational>,
    pub high: Option<&'a BigRational>,
    /// Whether a root exactly at a bound counts.
    pub closed: bool,
}

pub(super) const EVERYWHERE: Span = Span { low: None, high: None, closed: true };

impl Span<'_> {
    fn holds(&self, value: &BigRational) -> bool {
        let above = self.low.is_none_or(|low| if self.closed { value >= low } else { value > low });
        above && self.high.is_none_or(|high| if self.closed { value <= high } else { value < high })
    }

    fn strictly_holds(&self, value: &BigRational) -> bool {
        self.low.is_none_or(|low| value > low) && self.high.is_none_or(|high| value < high)
    }
}

/// A power of two that every root is smaller than in size: it exceeds 1 + max|c[i]| / |lead|.
/// Also the bisection steps that are always enough to reach float precision from it.
fn reach(q: &Ints) -> (BigRational, u64) {
    let lead_bits = q.last().map_or(1, BigInt::bits);
    let widest = q.iter().map(BigInt::bits).max().unwrap_or(1);
    (BigRational::from_integer(BigInt::one() << (widest.saturating_sub(lead_bits) + 2) as usize), 2 * (widest + lead_bits) + 80)
}

/// Floats for roots when a coefficient came from a float, exact order, and a refusal when two
/// distinct roots would print as the same float.
fn presented(mut found: Vec<Root>, inexact: bool) -> Outcome<Vec<Root>> {
    if inexact {
        // An exact-looking root would overstate what is known.
        found = found.into_iter().map(|root| match root { Root::Exact(value) => near(&value).map(Root::Near), other => Ok(other) }).collect::<Outcome<Vec<_>>>()?;
    }
    let place = |root: &Root| match root {
        Root::Exact(value) => value.clone(),
        Root::Near(value) => BigRational::from_float(*value).unwrap_or_default(),
    };
    found.sort_by_cached_key(place);
    if let Some(pair) = found.windows(2).find(|pair| pair[0].float() == pair[1].float() && !matches!((&pair[0], &pair[1]), (Root::Exact(_), Root::Exact(_)))) {
        return Err(format!("two distinct roots near {:?} are closer together than floats can tell apart; rescale the equation", pair[0].float()));
    }
    Ok(found)
}

/// Every distinct real root of p inside `span`, in ascending order. The bounds are applied
/// exactly, inside the isolation: a root is in or out by the sign of the polynomial at the
/// bound, never by comparing a rounded root with it.
pub(super) fn real_roots(p: &Poly, span: &Span) -> Outcome<Vec<Root>> {
    let mut c = integral(p);
    let degree = c.len().saturating_sub(1);
    let bits = c.iter().map(BigInt::bits).max().unwrap_or(0);
    if degree > MAX_ROOT_DEGREE {
        return Err(format!("roots are found for polynomials up to degree {MAX_ROOT_DEGREE}; this one has degree {degree}"));
    }
    if degree > 1 && (degree * degree) as u64 * bits > MAX_ROOT_WORK {
        return Err(format!("coefficients of {bits} bits are too large to isolate the roots of a degree {degree} polynomial"));
    }
    let mut found = Vec::new();
    let zeros = c.iter().take_while(|value| value.is_zero()).count();
    if zeros > 0 && degree > 0 {
        c.drain(..zeros);
        if span.holds(&BigRational::zero()) {
            found.push(Root::Exact(BigRational::zero()));
        }
    }
    if c.len() > 2 {
        let repeated = common_divisor(c.clone(), derivative(&c));
        c = if repeated.len() > 1 { quotient(&c, &repeated).ok_or("root isolation failed: inexact division")? } else { c };
        // A root exactly at a bound is settled here and divided out, so neither end of the
        // interval below is a root and Sturm's count applies.
        for end in [span.low, span.high].into_iter().flatten() {
            if c.len() > 1 && sign_at(&c, end) == 0 {
                if span.closed {
                    found.push(Root::Exact(end.clone()));
                }
                c = quotient(&c, &vec![-end.numer().clone(), end.denom().clone()]).ok_or("root isolation failed: inexact division")?;
            }
        }
        if c.len() > 2 {
            let chain = sturm(&c);
            let (bound, steps) = reach(&c);
            let low = span.low.filter(|low| **low > -bound.clone()).cloned().unwrap_or_else(|| -bound.clone());
            let high = span.high.filter(|high| **high < bound).cloned().unwrap_or(bound);
            let mut pending = if low < high { vec![(low, high)] } else { Vec::new() };
            while let Some((a, b)) = pending.pop() {
                match variations(&chain, &a).saturating_sub(variations(&chain, &b)) {
                    0 => {}
                    1 => found.push(refine(&c, a, b, steps)?),
                    _ => {
                        let middle = split(&c, &a, &b)?;
                        pending.push((a, middle.clone()));
                        pending.push((middle, b));
                    }
                }
            }
            return presented(found, p.inexact);
        }
        // Dividing out the bounds left one root: it is strictly between them or outside.
        if c.len() == 2 {
            let root = BigRational::new(-c[0].clone(), c[1].clone());
            if span.strictly_holds(&root) {
                found.push(Root::Exact(root));
            }
        }
    } else if c.len() == 2 {
        let root = BigRational::new(-c[0].clone(), c[1].clone());
        if span.holds(&root) {
            found.push(Root::Exact(root));
        }
    }
    presented(found, p.inexact)
}

/// The one root above `above` of a polynomial known to have exactly one there and to be
/// non-zero at `above` (Descartes' rule of signs gives this for cash flows whose sign changes
/// once). Exact bisection, with no limit on the degree.
pub(super) fn single_root_above(p: &Poly, above: &BigRational) -> Outcome<Root> {
    let c = integral(p);
    if c.first().is_some_and(Zero::is_zero) && above.is_negative() {
        return Ok(Root::Exact(BigRational::zero()));
    }
    let (bound, steps) = reach(&c);
    if c.len() < 2 || *above >= bound || sign_at(&c, above) == 0 || sign_at(&c, above) == sign_at(&c, &bound) {
        return Err("no single root above the bound".into());
    }
    let root = refine(&c, above.clone(), bound, steps.min(MAX_SINGLE_STEPS))?;
    Ok(presented(vec![root], p.inexact)?.remove(0))
}

/// Stops Brent's method when the bracket is as narrow as floats allow.
pub(super) struct Narrow;

impl Convergency<f64> for Narrow {
    fn is_root_found(&mut self, y: f64) -> bool {
        y == 0.0
    }
    fn is_converged(&mut self, x1: f64, x2: f64) -> bool {
        (x1 - x2).abs() <= 4.0 * f64::EPSILON * x1.abs().max(x2.abs()).max(f64::MIN_POSITIVE)
    }
    fn is_iteration_limit_reached(&mut self, iter: usize) -> bool {
        iter >= BRENT_STEPS
    }
}

/// The expression as a function of one name; the first evaluation error is kept in `failure`.
pub(super) fn function<'a>(node: &'a Node, name: &'a str, names: Names<'a>, failure: &'a RefCell<Option<String>>) -> impl Fn(f64) -> f64 + 'a {
    move |x| {
        let at = |found: &str| if found == name { Some(Value::Float(x)) } else { names(found) };
        match eval(node, &at).and_then(|value| as_float(&value)) {
            Ok(y) => y,
            Err(error) => {
                failure.borrow_mut().get_or_insert(format!("at {name} = {x:?}: {error}"));
                f64::NAN
            }
        }
    }
}

fn solution(values: &[(&str, &Value)], exact: bool, residual: Option<f64>) -> String {
    let pairs: Vec<(&str, String)> = values.iter().map(|(name, value)| (*name, shown(value))).collect();
    let mut fields = vec![("values", object(&pairs)), ("exact", exact.to_string())];
    if let Some(residual) = residual {
        fields.push(("residual", format!("{residual:?}")));
    }
    object(&fields)
}

fn report(free: &[String], method: &str, solutions: &[String], note: Option<&str>) -> String {
    let mut fields = vec![
        ("unknowns", list(&free.iter().map(|name| quoted(name)).collect::<Vec<_>>())),
        ("method", quoted(method)),
        ("solutions", list(solutions)),
    ];
    if let Some(note) = note {
        fields.push(("note", quoted(note)));
    }
    object(&fields)
}

/// One equation in one name: the difference of its two sides is zero.
fn one(difference: &Rc<Node>, name: &str, between: Option<(Value, Value)>, names: Names) -> Outcome<String> {
    let free = [name.to_string()];
    if let Some(p) = polynomial(difference, name, names)? {
        if p.degree() == 0 {
            let note = if p.c.is_empty() { "every value satisfies the equation" } else { "no value satisfies the equation" };
            return Ok(report(&free, "the name cancels out", &[], Some(note)));
        }
        let mut solutions = Vec::new();
        // --between is applied exactly, inside the root isolation.
        let range = between.as_ref().map(|(low, high)| Ok::<_, String>((as_exact(low)?, as_exact(high)?))).transpose()?;
        let span = range.as_ref().map_or(EVERYWHERE, |(low, high)| Span { low: Some(low), high: Some(high), closed: true });
        for root in real_roots(&p, &span)? {
            let value = root.value()?;
            let residual = match &root {
                Root::Exact(_) => None,
                Root::Near(x) => to_float(&p.at(&as_exact(&Value::Float(*x))?)).ok(), // omitted when outside float range
            };
            solutions.push(solution(&[(name, &value)], matches!(root, Root::Exact(_)), residual));
        }
        let method = format!("polynomial of degree {}: every distinct real root, isolated exactly by Sturm's theorem", p.degree());
        let note = solutions.is_empty().then_some(if range.is_some() { "no real root between the bounds" } else { "no real root" });
        return Ok(report(&free, &method, &solutions, note));
    }
    let (low, high) = between.ok_or(format!("this equation is not a polynomial in {name}: give --between LOW HIGH, two values where its sides differ in opposite directions"))?;
    let (low, high) = (as_float(&low)?, as_float(&high)?);
    if low >= high {
        return Err("the --between bounds are closer together than floats can tell apart; this equation is solved in floats".into());
    }
    let failure = RefCell::new(None);
    let folded = with_constants_folded(difference, name, names);
    let f = function(&folded, name, names, &failure);
    let (at_low, at_high) = (f(low), f(high));
    if let Some(error) = failure.borrow_mut().take() {
        return Err(format!("cannot evaluate the equation {error}"));
    }
    let root = if at_low == 0.0 {
        low
    } else if at_high == 0.0 {
        high
    } else if (at_low < 0.0) == (at_high < 0.0) {
        return Err(format!("left minus right is {at_low:?} at {low:?} and {at_high:?} at {high:?}: the same sign, so --between does not bracket a root"));
    } else {
        let found = find_root_brent(low, high, &f, &mut Narrow);
        if let Some(error) = failure.borrow_mut().take() {
            return Err(format!("cannot evaluate the equation {error}"));
        }
        found.map_err(|_| format!("the search between {low:?} and {high:?} did not settle on a root within {BRENT_STEPS} steps"))?
    };
    let residual = f(root);
    // Brent's method ends wherever the sign changes, which is also true of a jump (floor,
    // 1/x at 0, tan at pi/2). At a crossing the value at the root is far smaller than the
    // values a short step to either side, which have opposite signs; at a jump it is as
    // large as one of them. The test is a ratio, so scaling the equation does not change it.
    let step = 1e-6 * root.abs().max(high - low);
    // A side that would leave the bracket is not looked at; a root at an end has one neighbour.
    let sides: Vec<f64> = [root - step, root + step].into_iter().filter(|x| *x >= low && *x <= high).map(&f).collect();
    if failure.borrow().is_some() || !residual.is_finite() || sides.is_empty() || sides.iter().any(|side| !side.is_finite()) {
        return Err(format!("left minus right cannot be evaluated all around {name} = {root:?}, so it is not established as a root"));
    }
    if residual == 0.0 && sides.iter().all(|side| *side == 0.0) {
        // Exactly zero beside it too: the expression has underflowed (exp(-x) for large x) or
        // is zero over a stretch, and no single root can be named.
        return Err(format!("left minus right is exactly zero all around {name} = {root:?}: it is too small for floats there or zero over a stretch, so no single root can be named"));
    }
    let smallest = sides.iter().fold(f64::INFINITY, |least, side| least.min(side.abs()));
    let same_side = sides.len() == 2 && (sides[0] < 0.0) == (sides[1] < 0.0);
    if residual.abs() > CROSSING * smallest || same_side {
        return Err(format!("left minus right jumps across zero near {name} = {root:?} without passing through it: a discontinuity, not a root"));
    }
    let method = format!("Brent's method between {low:?} and {high:?}: one root; others may exist");
    Ok(report(&free, &method, &[solution(&[(name, &super::float(root)?)], false, Some(residual))], None))
}

/// Several linear equations in several names, by exact elimination.
fn system(differences: &[Rc<Node>], free: &[String], names: Names) -> Outcome<String> {
    let mut rows = Vec::new();
    let mut inexact = false;
    for difference in differences {
        let form = linear(difference, names)?;
        inexact |= form.inexact;
        let mut row: Vec<BigRational> = free.iter().map(|name| form.terms.get(name).cloned().unwrap_or_default()).collect();
        row.push(-form.constant);
        rows.push(row);
    }
    let method = "linear system: exact Gauss-Jordan elimination, checked by substitution";
    match eliminate(rows.clone(), free.len())? {
        Solution::None => Ok(report(free, method, &[], Some("the equations contradict each other: no solution"))),
        Solution::Many(_) => Ok(report(free, method, &[], Some("the equations do not determine every name: infinitely many solutions"))),
        Solution::Unique(values) => {
            // Substitute back into every equation as given; exact arithmetic makes this a proof.
            let satisfied = rows.iter().all(|row| row[..free.len()].iter().zip(&values).fold(BigRational::zero(), |sum, (a, x)| sum + a * x) == row[free.len()]);
            if !satisfied {
                return Err("the computed solution does not satisfy the equations".into());
            }
            let shown_values = values.iter().map(|value| reported(value, inexact)).collect::<Outcome<Vec<_>>>()?;
            let pairs: Vec<(&str, &Value)> = free.iter().map(String::as_str).zip(&shown_values).collect();
            Ok(report(free, method, &[solution(&pairs, !inexact, None)], None))
        }
    }
}

pub(super) fn solve(equations: &[String], between: Option<&(String, String)>, names: Names) -> Outcome<String> {
    if equations.len() > MAX_EQUATIONS {
        return Err(format!("more than {MAX_EQUATIONS} equations"));
    }
    let mut differences = Vec::new();
    let mut free = BTreeSet::new();
    for equation in equations {
        let (left, _, right) = relation(equation, &["==", "="], "an equation is LEFT == RIGHT, for example \"2*x + 1 == 7\"")?;
        let difference = Rc::new(Node::Binary("-", left, right));
        unknowns(&difference, names, &mut free);
        differences.push(difference);
    }
    let free: Vec<String> = free.into_iter().collect();
    let bounds = match between {
        Some((low, high)) => {
            let (low, high) = (eval(&*parse(low)?, names)?, eval(&*parse(high)?, names)?);
            if super::compare(&low, &high)? != std::cmp::Ordering::Less {
                return Err("--between takes LOW then HIGH, with LOW below HIGH".into());
            }
            Some((low, high))
        }
        None => None,
    };
    match (differences.as_slice(), free.as_slice()) {
        (_, []) => Err("nothing to solve for: every name has a value; use --check to test an equality".into()),
        ([difference], [name]) => one(difference, name, bounds, names),
        _ if bounds.is_some() => Err("--between applies to one equation in one name".into()),
        _ => system(&differences, &free, names),
    }
}
