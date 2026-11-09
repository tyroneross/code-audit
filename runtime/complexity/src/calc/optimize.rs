//! Small linear programs: a linear objective under linear constraints, with whole-number
//! names when asked.
//!
//! The `microlp` crate (a simplex solver with branch and bound) finds the optimum in floats.
//! The answer is then rebuilt exactly: the constraints that hold with equality at the
//! optimum are solved as an exact linear system, the result is substituted into every
//! constraint, and for a program without whole-number names the optimality conditions are
//! checked exactly (the objective must be a combination, with the right signs, of the
//! constraints that bind). An answer that passes is reported as exact and proved; any other
//! is reported as the solver's float answer and marked as such.

use super::poly::{eliminate, linear, nearest, reported, Linear, Solution};
use super::{list, object, quoted, relation, shown, to_float, Names, Outcome, Value};
use microlp::{ComparisonOp, Error, OptimizationDirection, Problem};
use num_rational::BigRational;
use num_bigint::BigInt;
use num_integer::Integer;
use num_traits::{One, Signed, Zero};
use std::collections::BTreeSet;
use std::time::Duration;

const MAX_NAMES: usize = 64;
const MAX_CONSTRAINTS: usize = 256;
const TIME_LIMIT: Duration = Duration::from_secs(5);
/// How close to equality a constraint must be at the float optimum to count as binding.
const BINDING: f64 = 1e-7;
/// Choices of binding constraints tried when more bind than there are names.
const MAX_PROOF_ATTEMPTS: usize = 2000;
const ROUNDED: &str = "a coefficient does not fit a float exactly, so the solver worked on a slightly different program, and its answer could not be proved optimal; use smaller or simpler numbers";
/// The whole numbers the solver can search: comfortably inside 32 bits.
const WHOLE_LOW: f64 = -2_000_000_000.0;
const WHOLE_HIGH: f64 = 2_000_000_000.0;

struct Constraint {
    source: String,
    /// One coefficient per name, in the order of the names.
    row: Vec<BigRational>,
    op: &'static str,
    bound: BigRational,
}

impl Constraint {
    fn value(&self, point: &[BigRational]) -> BigRational {
        self.row.iter().zip(point).fold(BigRational::zero(), |sum, (a, x)| sum + a * x)
    }

    fn holds(&self, point: &[BigRational]) -> bool {
        let value = self.value(point);
        match self.op {
            "<=" => value <= self.bound,
            ">=" => value >= self.bound,
            _ => value == self.bound,
        }
    }
}

/// Coefficients as the solver takes them. One too small or too large for a float is refused,
/// because the solver would otherwise be given a different problem.
fn floats(values: &[BigRational]) -> Outcome<Vec<f64>> {
    values.iter().map(nearest).collect()
}

/// Whether the solver sees this number exactly.
fn kept(value: &BigRational) -> bool {
    nearest(value).is_ok_and(|float| BigRational::from_float(float).as_ref() == Some(value))
}

/// The exact point where the binding constraints meet, when they pin down every name.
fn vertex(binding: &[&Constraint], count: usize) -> Outcome<Option<Vec<BigRational>>> {
    let rows = binding.iter().map(|constraint| constraint.row.iter().cloned().chain([constraint.bound.clone()]).collect()).collect();
    Ok(match eliminate(rows, count)? {
        Solution::Unique(point) => Some(point),
        _ => None,
    })
}

/// Whether the binding constraints prove the point optimal. The point is optimal when the
/// objective is a combination of binding constraints in which every weight pushes the right
/// way (the Karush-Kuhn-Tucker conditions). Each choice of as many binding constraints as
/// names gives one candidate combination by exact elimination; one that passes is a proof.
fn proved(maximize: bool, objective: &[BigRational], binding: &[&Constraint], count: usize) -> Outcome<bool> {
    if binding.len() < count {
        return Ok(false);
    }
    let mut chosen: Vec<usize> = (0..count).collect();
    for _ in 0..MAX_PROOF_ATTEMPTS {
        // Solve sum(weight[i] x chosen[i].row) = objective: one equation per name.
        let rows = (0..count).map(|name| chosen.iter().map(|&index| binding[index].row[name].clone()).chain([objective[name].clone()]).collect()).collect();
        if let Solution::Unique(weights) = eliminate(rows, count)? {
            let right_way = chosen.iter().zip(&weights).all(|(&index, weight)| match (binding[index].op, maximize) {
                ("<=", true) | (">=", false) => !weight.is_negative(),
                (">=", true) | ("<=", false) => !weight.is_positive(),
                _ => true,
            });
            if right_way {
                return Ok(true);
            }
        }
        // The next choice of `count` indices in increasing order, or stop after the last.
        let Some(moving) = (0..count).rev().find(|&slot| chosen[slot] < binding.len() - count + slot) else { return Ok(false) };
        chosen[moving] += 1;
        for slot in moving + 1..count {
            chosen[slot] = chosen[slot - 1] + 1;
        }
    }
    Ok(false)
}

pub(super) fn optimize(maximize: bool, objective: &str, subjects: &[String], integers: &[String], names: Names) -> Outcome<String> {
    if subjects.len() > MAX_CONSTRAINTS {
        return Err(format!("more than {MAX_CONSTRAINTS} constraints"));
    }
    let goal: Linear = linear(&*super::parse(objective)?, names)?;
    if goal.terms.is_empty() {
        return Err("nothing to optimize: the objective holds no name without a value".into());
    }
    let mut forms = Vec::new();
    let mut impossible: Option<String> = None;
    let mut inexact = goal.inexact;
    let mut free: BTreeSet<String> = goal.terms.keys().cloned().collect();
    for subject in subjects {
        let (left, op, right) = relation(subject, &["<=", ">=", "==", "="], "a constraint is LEFT <= RIGHT, LEFT >= RIGHT or LEFT == RIGHT; a strict < or > has no optimum")?;
        let form = linear(&left, names)?.combined(&linear(&right, names)?, -1)?;
        if form.terms.is_empty() {
            // Nothing left to choose: the constraint is simply true (and dropped) or false (no answer exists).
            let holds = match op {
                "<=" => !form.constant.is_positive(),
                ">=" => !form.constant.is_negative(),
                _ => form.constant.is_zero(),
            };
            if !holds {
                impossible.get_or_insert(subject.clone());
            }
            continue;
        }
        inexact |= form.inexact;
        free.extend(form.terms.keys().cloned());
        forms.push((subject.clone(), form, if op == "=" { "==" } else { op }));
    }
    let free: Vec<String> = free.into_iter().collect();
    if free.len() > MAX_NAMES {
        return Err(format!("more than {MAX_NAMES} names"));
    }
    if let Some(stray) = integers.iter().find(|name| !free.contains(name)) {
        return Err(format!("--integer names {stray}, which is not in the objective or a constraint"));
    }
    let row = |form: &Linear| -> Vec<BigRational> { free.iter().map(|name| form.terms.get(name).cloned().unwrap_or_default()).collect() };
    // Each constraint is multiplied through by the common denominator of its numbers (a positive
    // factor, so it is the same constraint): whole-number coefficients reach the solver's floats
    // exactly where a third or a seventh would not.
    let whole = |values: &[BigRational]| BigRational::from_integer(values.iter().fold(BigInt::one(), |multiple, value| multiple.lcm(value.denom())));
    let constraints: Vec<Constraint> = forms
        .iter()
        .map(|(source, form, op)| {
            let (row, bound) = (row(form), -form.constant.clone());
            let factor = whole(&[row.as_slice(), std::slice::from_ref(&bound)].concat());
            Constraint { source: source.clone(), row: row.iter().map(|value| value * &factor).collect(), op, bound: bound * &factor }
        })
        .collect();
    let weights = row(&goal);
    // The objective is scaled the same way for the solver only; reported values use `weights`.
    let goal_factor = whole(&weights);
    let solver_weights: Vec<BigRational> = weights.iter().map(|weight| weight * &goal_factor).collect();

    // The program in the solver's terms: `limits` holds the range of each whole-number name.
    let build = |direction: OptimizationDirection, weights: &[f64], limits: &[Option<(i32, i32)>]| -> Outcome<(Problem, Vec<microlp::Variable>)> {
        let mut problem = Problem::new(direction);
        problem.set_time_limit(TIME_LIMIT);
        let variables: Vec<_> = weights.iter().zip(limits).map(|(weight, limit)| match limit {
            Some(range) => problem.add_integer_var(*weight, *range),
            None => problem.add_var(*weight, (f64::NEG_INFINITY, f64::INFINITY)),
        }).collect();
        for constraint in &constraints {
            let terms: Vec<_> = variables.iter().cloned().zip(floats(&constraint.row)?).filter(|(_, coefficient)| *coefficient != 0.0).collect();
            let op = match constraint.op {
                "<=" => ComparisonOp::Le,
                ">=" => ComparisonOp::Ge,
                _ => ComparisonOp::Eq,
            };
            problem.add_constraint(terms, op, nearest(&constraint.bound)?);
        }
        Ok((problem, variables))
    };
    let direction = ("direction", quoted(if maximize { "maximize" } else { "minimize" }));
    let listed = ("names", list(&free.iter().map(|name| quoted(name)).collect::<Vec<_>>()));
    let without = |outcome: &str, note: &str| Ok(object(&[direction.clone(), listed.clone(), ("outcome", quoted(outcome)), ("note", quoted(note))]));
    if let Some(subject) = impossible {
        return without("infeasible", &format!("the constraint {subject:?} is false whatever the names are"));
    }

    // The solver searches a whole-number name only inside 32-bit limits. Rather than apply
    // limits the caller never wrote, find the range the constraints allow each such name
    // (two small programs per name, without the whole-number rule) and refuse a name the
    // constraints leave open or let pass those limits.
    let mut limits: Vec<Option<(i32, i32)>> = vec![None; free.len()];
    for (index, name) in free.iter().enumerate().filter(|(_, name)| integers.contains(name)) {
        let mut ends = [0.0; 2];
        for (end, direction) in ends.iter_mut().zip([OptimizationDirection::Minimize, OptimizationDirection::Maximize]) {
            let only: Vec<f64> = (0..free.len()).map(|other| (other == index) as u8 as f64).collect();
            let (range, variables) = build(direction, &only, &vec![None; free.len()])?;
            *end = match range.solve() {
                Err(Error::Infeasible) => return without("infeasible", "no values satisfy every constraint"),
                Err(Error::Unbounded) => return Err(format!("the constraints leave the whole-number name {name} without a limit on one side; add one (for example \"{name} >= 0\" and \"{name} <= 1000\")")),
                Err(error) => return Err(format!("the solver failed: {error}")),
                Ok(outcome) => outcome.into_solution().map_err(|_| format!("no answer within {} seconds", TIME_LIMIT.as_secs()))?.var_value(variables[index]),
            };
        }
        let (low, high) = ((ends[0] - 1e-6).floor(), (ends[1] + 1e-6).ceil());
        if !(low >= WHOLE_LOW && high <= WHOLE_HIGH) {
            return Err(format!("the whole-number name {name} can reach {low:?} to {high:?}; the solver handles whole numbers between {WHOLE_LOW:?} and {WHOLE_HIGH:?}"));
        }
        limits[index] = Some((low as i32, high as i32));
    }
    let (problem, variables) = build(if maximize { OptimizationDirection::Maximize } else { OptimizationDirection::Minimize }, &floats(&solver_weights)?, &limits)?;
    let solved = match problem.solve() {
        Err(Error::Infeasible) => return without("infeasible", "no values satisfy every constraint"),
        Err(Error::Unbounded) => return without("unbounded", "the objective improves without limit; a name is unbounded unless a constraint bounds it, so add \"x >= 0\" when a quantity cannot be negative"),
        Err(error) => return Err(format!("the solver failed: {error}")),
        Ok(outcome) => outcome.into_solution().map_err(|_| format!("no answer within {} seconds", TIME_LIMIT.as_secs()))?,
    };
    let found: Vec<f64> = variables.iter().map(|variable| solved.var_value(*variable)).collect();
    if found.iter().any(|value| !value.is_finite()) {
        return Err("the solver returned a value that is not finite".into());
    }

    // Rebuild the answer exactly from the constraints that bind at the float optimum.
    let binds = |constraint: &Constraint| -> Outcome<bool> {
        let (row, bound) = (floats(&constraint.row)?, to_float(&constraint.bound)?);
        let value: f64 = row.iter().zip(&found).map(|(a, x)| a * x).sum();
        let scale = row.iter().zip(&found).fold(bound.abs().max(1.0), |scale, (a, x)| scale.max((a * x).abs()));
        Ok((value - bound).abs() <= BINDING * scale)
    };
    let mut binding = Vec::new();
    for constraint in &constraints {
        if binds(constraint)? {
            binding.push(constraint);
        }
    }
    let whole = |value: f64| BigRational::from_float(value.round()).unwrap_or_default();
    let candidate = if inexact {
        None
    } else if let Some(point) = vertex(&binding, free.len())? {
        Some(point)
    } else if integers.len() == free.len() {
        Some(found.iter().map(|value| whole(*value)).collect()) // every name is a whole number: round the float answer
    } else {
        None
    };
    let integral = |point: &[BigRational]| free.iter().zip(point).all(|(name, value)| !integers.contains(name) || value.is_integer());
    let float_goal = solved.objective() / nearest(&goal_factor)? + to_float(&goal.constant)?;
    let exact_point = candidate.filter(|point| {
        let goal_value = weights.iter().zip(point).fold(goal.constant.clone(), |sum, (weight, x)| sum + weight * x);
        let near = to_float(&goal_value).is_ok_and(|value| (value - float_goal).abs() <= 1e-6 * float_goal.abs().max(1.0));
        near && integral(point) && constraints.iter().all(|constraint| constraint.holds(point))
    });

    // The solver works in floats. When a coefficient does not fit one exactly it solved a
    // slightly different program, so its answer stands only if it is then proved exactly.
    let rounded = !solver_weights.iter().chain(constraints.iter().flat_map(|constraint| constraint.row.iter().chain([&constraint.bound]))).all(kept);
    let binding_sources: Vec<String> = binding.iter().map(|constraint| quoted(&constraint.source)).collect();
    let mut fields = vec![direction, listed, ("outcome", quoted("optimal"))];
    match exact_point {
        Some(point) => {
            let goal_value = weights.iter().zip(&point).fold(goal.constant.clone(), |sum, (weight, x)| sum + weight * x);
            let is_proved = integers.is_empty() && proved(maximize, &weights, &binding, free.len())?;
            let values = free.iter().zip(&point).map(|(name, value)| reported(value, false).map(|value| (name.as_str(), shown(&value)))).collect::<Outcome<Vec<_>>>()?;
            fields.push(("objective", shown(&reported(&goal_value, false)?)));
            fields.push(("values", object(&values)));
            fields.push(("exact", "true".into()));
            fields.push(("proved_optimal", is_proved.to_string()));
            if rounded && !is_proved {
                return Err(ROUNDED.into());
            }
            fields.push(("note", quoted(if is_proved {
                "values satisfy every constraint exactly, and the optimality conditions hold exactly"
            } else {
                "values satisfy every constraint exactly; that no better point exists rests on the solver"
            })));
        }
        None if rounded => return Err(ROUNDED.into()),
        None => {
            let values: Vec<(&str, String)> = free.iter().zip(&found).map(|(name, value)| (name.as_str(), shown(&Value::Float(*value)))).collect();
            fields.push(("objective", shown(&super::float(float_goal)?)));
            fields.push(("values", object(&values)));
            fields.push(("exact", "false".into()));
            fields.push(("proved_optimal", "false".into()));
            fields.push(("note", quoted("the solver's floating-point answer; it could not be rebuilt exactly")));
        }
    }
    fields.push(("binding", list(&binding_sources)));
    Ok(object(&fields))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn whole(value: i64) -> BigRational {
        BigRational::from_integer(BigInt::from(value))
    }

    fn constraint(row: [i64; 2], op: &'static str, bound: i64) -> Constraint {
        Constraint { source: String::new(), row: row.iter().map(|value| whole(*value)).collect(), op, bound: whole(bound) }
    }

    // The command line only ever hands `proved` a point the solver called optimal, so the
    // refusals are tested here: a corner that is not the optimum must not be proved.
    #[test]
    fn a_corner_that_is_not_optimal_is_not_proved() {
        let objective = [whole(1), whole(1)];
        let (x_low, y_low) = (constraint([1, 0], ">=", 0), constraint([0, 1], ">=", 0));
        let (x_high, y_high) = (constraint([1, 0], "<=", 4), constraint([0, 1], "<=", 3));
        // Maximizing x + y on the box: (4, 3) is optimal, (0, 0) is the worst corner and (4, 0) is neither.
        assert!(proved(true, &objective, &[&x_high, &y_high], 2).unwrap());
        assert!(!proved(true, &objective, &[&x_low, &y_low], 2).unwrap());
        assert!(!proved(true, &objective, &[&x_high, &y_low], 2).unwrap());
        // Minimizing reverses it.
        assert!(proved(false, &objective, &[&x_low, &y_low], 2).unwrap());
        assert!(!proved(false, &objective, &[&x_high, &y_high], 2).unwrap());
        // x - y: an upper limit on y, or a lower limit on y, holds the objective back in one direction only.
        let mixed = [whole(1), whole(-1)];
        assert!(!proved(true, &mixed, &[&x_high, &y_high], 2).unwrap());
        assert!(proved(true, &mixed, &[&x_high, &y_low], 2).unwrap());
        assert!(!proved(false, &mixed, &[&x_low, &y_low], 2).unwrap());
        assert!(proved(false, &mixed, &[&x_low, &y_high], 2).unwrap());
    }

    #[test]
    fn too_few_binding_constraints_prove_nothing_and_an_equality_takes_either_sign() {
        let objective = [whole(1), whole(1)];
        let x_high = constraint([1, 0], "<=", 4);
        assert!(!proved(true, &objective, &[&x_high], 2).unwrap());
        // On the line x + y == 5 every point has the same objective, so any corner on it is optimal either way.
        let (line, y_low) = (constraint([1, 1], "==", 5), constraint([0, 1], ">=", 0));
        assert!(proved(true, &objective, &[&line, &y_low], 2).unwrap());
        assert!(proved(false, &objective, &[&line, &y_low], 2).unwrap());
    }

    #[test]
    fn a_degenerate_corner_is_proved_by_one_valid_choice() {
        // Three constraints meet at (3, 1); only some pairs give weights of the right sign.
        let objective = [whole(3), whole(2)];
        let binding = [constraint([1, 1], "<=", 4), constraint([1, 3], "<=", 6), constraint([1, 0], "<=", 3)];
        assert!(proved(true, &objective, &binding.iter().collect::<Vec<_>>(), 2).unwrap());
    }

    #[test]
    fn a_point_is_checked_against_every_constraint() {
        let inside = [whole(1), whole(1)];
        let outside = [whole(5), whole(1)];
        let x_high = constraint([1, 0], "<=", 4);
        assert!(x_high.holds(&inside) && !x_high.holds(&outside));
        assert!(constraint([1, 1], "==", 2).holds(&inside) && !constraint([1, 1], "==", 3).holds(&inside));
        assert!(constraint([0, 1], ">=", 1).holds(&inside) && !constraint([0, 1], ">=", 2).holds(&inside));
    }
}
