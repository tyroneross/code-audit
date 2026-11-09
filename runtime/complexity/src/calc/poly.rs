//! Exact polynomials in one name and linear forms in several: the algebra that the solver,
//! the calculus commands and the optimizer share.

use super::{as_exact, eval, is_zero, to_float, Names, Node, Outcome, Value, MAX_BITS};
use num_bigint::BigInt;
use num_rational::BigRational;
use num_traits::{One, Signed, ToPrimitive, Zero};
use std::collections::{BTreeMap, BTreeSet};

/// Highest power a polynomial may reach, so `(x + 1)**N` cannot ask for unbounded work.
pub(super) const MAX_DEGREE: usize = 64;

/// An exact value inside the size budget.
pub(super) fn held(value: BigRational) -> Outcome<BigRational> {
    if value.numer().bits().max(value.denom().bits()) > MAX_BITS {
        return Err(format!("exact result is larger than {MAX_BITS} bits; use smaller numbers"));
    }
    Ok(value)
}

/// The float nearest an exact value, refused when no float is near: a value too small or too
/// large would round to 0.0 or infinity, and the report would state a number that is wrong.
pub(super) fn nearest(value: &BigRational) -> Outcome<f64> {
    if value.is_zero() {
        return Ok(0.0);
    }
    match to_float(value) {
        Ok(float) if float.is_normal() => Ok(float),
        _ => Err(format!("a value is outside the range of floats (its size is about 2**{}); rescale the problem", value.numer().bits() as i64 - value.denom().bits() as i64)),
    }
}

/// An exact value for a report: a float when any input was a float, so a float is never
/// presented as an exact fraction.
pub(super) fn reported(value: &BigRational, inexact: bool) -> Outcome<Value> {
    if inexact { super::float(nearest(value)?) } else { super::exact(value.clone()) }
}

/// `c[i]` is the coefficient of the i-th power; the highest coefficient is not zero.
#[derive(Clone, Debug)]
pub(super) struct Poly {
    pub c: Vec<BigRational>,
    /// A coefficient came from a float.
    pub inexact: bool,
}

impl Poly {
    pub fn new(mut c: Vec<BigRational>, inexact: bool) -> Poly {
        while c.last().is_some_and(Zero::is_zero) {
            c.pop();
        }
        Poly { c, inexact }
    }

    fn constant(value: &Value) -> Outcome<Poly> {
        Ok(Poly::new(vec![as_exact(value)?], matches!(value, Value::Float(_))))
    }

    pub fn degree(&self) -> usize {
        self.c.len().saturating_sub(1)
    }

    /// self + sign x other
    fn combined(&self, other: &Poly, sign: i32) -> Outcome<Poly> {
        let zero = BigRational::zero();
        let c = (0..self.c.len().max(other.c.len()))
            .map(|i| {
                let (a, b) = (self.c.get(i).unwrap_or(&zero), other.c.get(i).unwrap_or(&zero));
                held(if sign < 0 { a - b } else { a + b })
            })
            .collect::<Outcome<Vec<_>>>()?;
        Ok(Poly::new(c, self.inexact || other.inexact))
    }

    fn times(&self, other: &Poly) -> Outcome<Poly> {
        if self.c.is_empty() || other.c.is_empty() {
            return Ok(Poly::new(Vec::new(), self.inexact || other.inexact));
        }
        if self.degree() + other.degree() > MAX_DEGREE {
            return Err(format!("polynomial degree is above {MAX_DEGREE}"));
        }
        let mut c = vec![BigRational::zero(); self.c.len() + other.c.len() - 1];
        for (i, a) in self.c.iter().enumerate() {
            for (j, b) in other.c.iter().enumerate() {
                c[i + j] = held(&c[i + j] + a * b)?;
            }
        }
        Ok(Poly::new(c, self.inexact || other.inexact))
    }

    pub fn scaled(&self, factor: &BigRational, inexact: bool) -> Outcome<Poly> {
        Ok(Poly::new(self.c.iter().map(|c| held(c * factor)).collect::<Outcome<Vec<_>>>()?, self.inexact || inexact))
    }

    fn raised(&self, power: usize) -> Outcome<Poly> {
        if power > MAX_DEGREE {
            return Err(format!("a power above {MAX_DEGREE} is not expanded"));
        }
        let mut result = Poly::new(vec![BigRational::one()], self.inexact);
        for _ in 0..power {
            result = result.times(self)?;
        }
        Ok(result)
    }

    /// The value at x by Horner's rule. At most MAX_DEGREE multiplications; the caller holds the result to the budget.
    pub fn at(&self, x: &BigRational) -> BigRational {
        self.c.iter().rev().fold(BigRational::zero(), |sum, c| sum * x + c)
    }

    pub fn derivative(&self) -> Poly {
        Poly::new(self.c.iter().enumerate().skip(1).map(|(power, c)| c * BigRational::from_integer(BigInt::from(power))).collect(), self.inexact)
    }

    pub fn antiderivative(&self) -> Poly {
        let mut c = vec![BigRational::zero()];
        c.extend(self.c.iter().enumerate().map(|(power, c)| c / BigRational::from_integer(BigInt::from(power + 1))));
        Poly::new(c, self.inexact)
    }

    /// Text that parses back to the same polynomial, highest power first.
    pub fn text(&self, name: &str) -> String {
        let mut out = String::new();
        for (power, c) in self.c.iter().enumerate().rev().filter(|(_, c)| !c.is_zero()) {
            match (out.is_empty(), c.is_negative()) {
                (true, true) => out.push('-'),
                (true, false) => {}
                (false, negative) => out.push_str(if negative { " - " } else { " + " }),
            }
            let size = c.abs();
            let coefficient = if self.inexact { format!("{:?}", size.to_f64().unwrap_or(f64::NAN)) } else { size.to_string() };
            let variable = match power {
                0 => String::new(),
                1 => name.to_string(),
                _ => format!("{name}**{power}"),
            };
            out.push_str(&match (power, size.is_one()) {
                (0, _) => coefficient,
                (_, true) => variable,
                _ => format!("{coefficient}*{variable}"),
            });
        }
        if out.is_empty() { "0".into() } else { out }
    }
}

pub(super) fn mentions(node: &Node, name: &str) -> bool {
    match node {
        Node::Number(_) => false,
        Node::Name(found) => found == name,
        Node::Negate(inner) => mentions(inner, name),
        Node::Binary(_, left, right) => mentions(left, name) || mentions(right, name),
        Node::Call(_, arguments) => arguments.iter().any(|argument| mentions(argument, name)),
    }
}

/// The expression as a polynomial in `name`; `None` when it is not one (a root, a quotient by
/// the name, a function of it). Parts that do not hold the name are evaluated as constants.
pub(super) fn polynomial(node: &Node, name: &str, names: Names) -> Outcome<Option<Poly>> {
    if !mentions(node, name) {
        return Poly::constant(&eval(node, names)?).map(Some);
    }
    let both = |left: &Node, right: &Node| -> Outcome<Option<(Poly, Poly)>> {
        Ok(polynomial(left, name, names)?.zip(polynomial(right, name, names)?))
    };
    Ok(match node {
        Node::Name(_) => Some(Poly::new(vec![BigRational::zero(), BigRational::one()], false)),
        Node::Negate(inner) => polynomial(inner, name, names)?.map(|p| p.scaled(&-BigRational::one(), false)).transpose()?,
        Node::Binary("+", left, right) => both(left, right)?.map(|(a, b)| a.combined(&b, 1)).transpose()?,
        Node::Binary("-", left, right) => both(left, right)?.map(|(a, b)| a.combined(&b, -1)).transpose()?,
        Node::Binary("*", left, right) => both(left, right)?.map(|(a, b)| a.times(&b)).transpose()?,
        Node::Binary("/", left, right) if !mentions(right, name) => {
            let divisor = eval(right, names)?;
            if is_zero(&divisor) {
                return Err("division by zero".into());
            }
            let inverse = held(as_exact(&divisor)?.recip())?;
            polynomial(left, name, names)?.map(|p| p.scaled(&inverse, matches!(divisor, Value::Float(_)))).transpose()?
        }
        Node::Binary("**", base, exponent) if !mentions(exponent, name) => match eval(exponent, names)? {
            Value::Exact(power) if power.is_integer() && !power.is_negative() => {
                let power = power.to_integer().to_usize().unwrap_or(usize::MAX);
                polynomial(base, name, names)?.map(|p| p.raised(power)).transpose()?
            }
            _ => None,
        },
        _ => None,
    })
}

/// Names in the expression that have no value: the unknowns.
pub(super) fn unknowns(node: &Node, names: Names, found: &mut BTreeSet<String>) {
    match node {
        Node::Number(_) => {}
        Node::Name(name) => {
            if names(name).is_none() {
                found.insert(name.clone());
            }
        }
        Node::Negate(inner) => unknowns(inner, names, found),
        Node::Binary(_, left, right) => {
            unknowns(left, names, found);
            unknowns(right, names, found);
        }
        Node::Call(_, arguments) => arguments.iter().for_each(|argument| unknowns(argument, names, found)),
    }
}

/// `sum(terms[name] x name) + constant`
#[derive(Clone, Debug, Default)]
pub(super) struct Linear {
    pub terms: BTreeMap<String, BigRational>,
    pub constant: BigRational,
    pub inexact: bool,
}

impl Linear {
    fn scaled(mut self, factor: &BigRational, inexact: bool) -> Outcome<Linear> {
        for coefficient in self.terms.values_mut() {
            *coefficient = held(&*coefficient * factor)?;
        }
        self.constant = held(&self.constant * factor)?;
        self.inexact |= inexact;
        self.terms.retain(|_, coefficient| !coefficient.is_zero());
        Ok(self)
    }

    /// self + sign x other
    pub fn combined(mut self, other: &Linear, sign: i32) -> Outcome<Linear> {
        let signed = |value: &BigRational| if sign < 0 { -value } else { value.clone() };
        for (name, coefficient) in &other.terms {
            let entry = self.terms.entry(name.clone()).or_default();
            *entry = held(&*entry + signed(coefficient))?;
        }
        self.constant = held(&self.constant + signed(&other.constant))?;
        self.inexact |= other.inexact;
        self.terms.retain(|_, coefficient| !coefficient.is_zero());
        Ok(self)
    }
}

/// The expression as a linear form in its unknowns; an error when it is not linear.
pub(super) fn linear(node: &Node, names: Names) -> Outcome<Linear> {
    let mut free = BTreeSet::new();
    unknowns(node, names, &mut free);
    if free.is_empty() {
        let value = eval(node, names)?;
        return Ok(Linear { terms: BTreeMap::new(), constant: as_exact(&value)?, inexact: matches!(value, Value::Float(_)) });
    }
    let not_linear = || format!("not linear in {}: only sums, a constant multiple and division by a constant are accepted", free.iter().cloned().collect::<Vec<_>>().join(", "));
    match node {
        Node::Name(name) => Ok(Linear { terms: BTreeMap::from([(name.clone(), BigRational::one())]), ..Linear::default() }),
        Node::Negate(inner) => linear(inner, names)?.scaled(&-BigRational::one(), false),
        Node::Binary("+", left, right) => linear(left, names)?.combined(&linear(right, names)?, 1),
        Node::Binary("-", left, right) => linear(left, names)?.combined(&linear(right, names)?, -1),
        Node::Binary("*", left, right) => {
            let (a, b) = (linear(left, names)?, linear(right, names)?);
            if a.terms.is_empty() {
                b.scaled(&a.constant, a.inexact)
            } else if b.terms.is_empty() {
                a.scaled(&b.constant, b.inexact)
            } else {
                Err(not_linear())
            }
        }
        Node::Binary("/", left, right) => {
            let divisor = linear(right, names)?;
            if !divisor.terms.is_empty() {
                return Err(not_linear());
            }
            if divisor.constant.is_zero() {
                return Err("division by zero".into());
            }
            linear(left, names)?.scaled(&held(divisor.constant.recip())?, divisor.inexact)
        }
        _ => Err(not_linear()),
    }
}

pub(super) enum Solution {
    Unique(Vec<BigRational>),
    None,
    Many,
}

/// Solve `rows x unknowns = last column` exactly by Gauss-Jordan elimination. Each row holds
/// one coefficient per unknown and then the right-hand side.
pub(super) fn eliminate(mut rows: Vec<Vec<BigRational>>, unknowns: usize) -> Outcome<Solution> {
    let mut rank = 0;
    for column in 0..unknowns {
        let Some(pivot) = (rank..rows.len()).find(|&row| !rows[row][column].is_zero()) else { continue };
        rows.swap(rank, pivot);
        let scale = rows[rank][column].clone();
        for value in rows[rank].iter_mut() {
            *value = held(&*value / &scale)?;
        }
        let pivot_row = rows[rank].clone();
        for (index, row) in rows.iter_mut().enumerate() {
            if index != rank && !row[column].is_zero() {
                let factor = row[column].clone();
                for (value, pivot_value) in row.iter_mut().zip(&pivot_row) {
                    *value = held(&*value - &factor * pivot_value)?;
                }
            }
        }
        rank += 1;
    }
    if rows.iter().any(|row| row[..unknowns].iter().all(Zero::is_zero) && !row[unknowns].is_zero()) {
        return Ok(Solution::None);
    }
    if rank < unknowns {
        return Ok(Solution::Many);
    }
    // Full rank: after Gauss-Jordan the pivot rows are the identity, in order.
    Ok(Solution::Unique(rows[..unknowns].iter().map(|row| row[unknowns].clone()).collect()))
}
