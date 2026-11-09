//! Local, approximate solutions of small rational arithmetic systems.

use super::poly::{polynomial, unknowns};
use super::{
    as_exact, as_float, binary, eval, exact, negate, parse, power, relation, Names, Node, Outcome,
    Value,
};
use num_rational::BigRational;
use num_traits::Signed;
use serde_json::{json, Value as Json};
use std::collections::{BTreeMap, BTreeSet};
use std::rc::Rc;

const MAX_VARIABLES: usize = 6;
const MAX_ITERATIONS: usize = 30;
const MAX_EVALUATIONS: usize = 800;
const MAX_BACKTRACKS: usize = 12;
const MIN_RECIPROCAL_CONDITION: f64 = 1e-8;
const MAX_DIFFERENCE_SENSITIVITY: f64 = 0.05;
type Matrix = Vec<Vec<f64>>;

struct Difference {
    central: Matrix,
    side_disagreement: f64,
}

struct Equation<'a> {
    source: &'a str,
    left: Rc<Node>,
    right: Rc<Node>,
}

struct Problem<'a> {
    equations: Vec<Equation<'a>>,
    variables: Vec<String>,
    names: Names<'a>,
    evaluations: usize,
}

#[derive(Clone, Copy)]
struct Residual {
    raw: f64,
    scale: f64,
}

struct ExactResidual {
    raw: BigRational,
    scale: BigRational,
}

impl Problem<'_> {
    fn value(&self, name: &str, point: &[f64]) -> Option<Value> {
        self.variables
            .binary_search_by(|variable| variable.as_str().cmp(name))
            .ok()
            .map(|index| Value::Float(point[index]))
            .or_else(|| (self.names)(name))
    }

    fn evaluate(&mut self, point: &[f64]) -> Outcome<Vec<Residual>> {
        if self.evaluations == MAX_EVALUATIONS {
            return Err("evaluation budget exhausted".into());
        }
        self.evaluations += 1;
        let at = |name: &str| self.value(name, point);
        self.equations
            .iter()
            .map(|equation| {
                let left = eval(&equation.left, &at)?;
                let right = eval(&equation.right, &at)?;
                let scale = as_float(&left)?.abs().max(as_float(&right)?.abs()).max(1.0);
                let raw = as_float(&binary("-", left, right)?)?;
                Ok(Residual { raw, scale })
            })
            .collect()
    }

    fn excluded_quadratic(&self) -> Option<&str> {
        self.equations.iter().find_map(|equation| {
            let difference = Node::Binary("-", equation.left.clone(), equation.right.clone());
            let mut variables = BTreeSet::new();
            unknowns(&difference, self.names, &mut variables);
            if variables.len() != 1 {
                return None;
            }
            // Optional exact exclusion. Unsupported or over-budget polynomial construction
            // carries no evidence; the numerical candidate still has its normal checks.
            let poly = polynomial(&difference, variables.first()?, self.names).ok()??;
            let [c, b, a] = poly.c.as_slice() else {
                return None;
            };
            let discriminant = b * b - a * c * num_bigint::BigInt::from(4);
            (!poly.inexact && discriminant.is_negative()).then_some(equation.source)
        })
    }

    fn substitute(&mut self, point: &[f64]) -> Outcome<Vec<ExactResidual>> {
        if self.evaluations == MAX_EVALUATIONS {
            return Err("evaluation budget exhausted".into());
        }
        self.evaluations += 1;
        let at = |name: &str| self.value(name, point);
        self.equations
            .iter()
            .map(|equation| {
                let left = recompute(&equation.left, &at)?;
                let right = recompute(&equation.right, &at)?;
                let scale = as_exact(&left)?
                    .abs()
                    .max(as_exact(&right)?.abs())
                    .max(BigRational::from_integer(1.into()));
                let raw = as_exact(&binary("-", left, right)?)?;
                Ok(ExactResidual { raw, scale })
            })
            .collect()
    }

    // Approximate derivatives in coordinates scaled by max(1, |x_j|), with equation
    // scales fixed at the center of the stencil.
    fn difference(
        &mut self,
        point: &[f64],
        residuals: &[Residual],
        step: f64,
    ) -> Outcome<Difference> {
        let n = point.len();
        let mut central = vec![vec![0.0; n]; n];
        let mut side_errors = vec![0.0; n];
        for (column, &coordinate) in point.iter().enumerate() {
            let scale = coordinate.abs().max(1.0);
            let mut probe = point.to_vec();
            probe[column] = coordinate + step * scale;
            if !probe[column].is_finite() {
                return Err("a Jacobian probe is outside the finite float range".into());
            }
            let upper = probe[column];
            let positive = self.evaluate(&probe)?;
            probe[column] = coordinate - step * scale;
            if !probe[column].is_finite() {
                return Err("a Jacobian probe is outside the finite float range".into());
            }
            let negative = self.evaluate(&probe)?;
            let right_width = (upper - coordinate) / scale;
            let left_width = (coordinate - probe[column]) / scale;
            for (row, original) in residuals.iter().enumerate() {
                let center = original.raw / original.scale;
                let right = positive[row].raw / original.scale;
                let left = negative[row].raw / original.scale;
                let slope = (right - left) / (right_width + left_width);
                let one_sided_gap =
                    ((right - center) / right_width - (center - left) / left_width).abs();
                if !slope.is_finite() || !one_sided_gap.is_finite() {
                    return Err("a Jacobian entry is outside the finite float range".into());
                }
                central[row][column] = slope;
                side_errors[row] += one_sided_gap;
            }
        }
        Ok(Difference {
            central,
            side_disagreement: magnitude(side_errors.into_iter()),
        })
    }
}

fn rational_arithmetic(node: &Node, names: Names) -> bool {
    match node {
        Node::Number(_) | Node::Name(_) => true,
        Node::Negate(inner) => rational_arithmetic(inner, names),
        Node::Binary("**", base, exponent) => {
            let mut free = BTreeSet::new();
            unknowns(exponent, names, &mut free);
            free.is_empty()
                && rational_arithmetic(base, names)
                && rational_arithmetic(exponent, names)
                && matches!(eval(exponent, names), Ok(Value::Exact(value)) if value.is_integer())
        }
        Node::Binary(op, a, b) => {
            matches!(*op, "+" | "-" | "*" | "/")
                && rational_arithmetic(a, names)
                && rational_arithmetic(b, names)
        }
        Node::Call(..) => false,
    }
}

// Exact substitution keeps exact literals and interprets finite floating leaves as their
// stored binary rationals. All accepted operations on those values stay rational.
fn recompute(node: &Node, names: Names) -> Outcome<Value> {
    let part = |node: &Node| recompute(node, names);
    match node {
        Node::Number(value) => exact(as_exact(value)?),
        Node::Name(name) => exact(as_exact(
            &names(name).ok_or_else(|| format!("{name} has no value"))?,
        )?),
        Node::Negate(inner) => Ok(negate(part(inner)?)),
        Node::Binary("**", base, exponent) => power(part(base)?, part(exponent)?),
        Node::Binary(op, left, right) => binary(op, part(left)?, part(right)?),
        Node::Call(..) => Err("a function has no rational substitution rule".into()),
    }
}

fn newton_step(inverse: &Matrix, residuals: &[f64]) -> Vec<f64> {
    inverse
        .iter()
        .map(|row| -row.iter().zip(residuals).map(|(a, b)| a * b).sum::<f64>())
        .collect()
}

fn magnitude(values: impl Iterator<Item = f64>) -> f64 {
    values.map(f64::abs).fold(0.0, f64::max)
}

fn matrix_norm(matrix: &Matrix) -> f64 {
    magnitude(matrix.iter().map(|row| row.iter().map(|x| x.abs()).sum()))
}

fn inverse(matrix: &Matrix) -> Option<Matrix> {
    let n = matrix.len();
    let mut rows: Matrix = matrix
        .iter()
        .enumerate()
        .map(|(i, row)| {
            row.iter()
                .copied()
                .chain((0..n).map(|j| f64::from(i == j)))
                .collect()
        })
        .collect();
    for column in 0..n {
        let pivot =
            (column..n).max_by(|&a, &b| rows[a][column].abs().total_cmp(&rows[b][column].abs()))?;
        rows.swap(pivot, column);
        let divisor = rows[column][column];
        if divisor == 0.0 || !divisor.is_finite() {
            return None;
        }
        for value in &mut rows[column] {
            *value /= divisor;
        }
        let reduced = rows[column].clone();
        for (index, row) in rows.iter_mut().enumerate() {
            if index == column {
                continue;
            }
            let factor = row[column];
            for (value, pivot) in row.iter_mut().zip(&reduced) {
                *value -= factor * pivot;
            }
        }
    }
    rows.iter()
        .flatten()
        .all(|x| x.is_finite())
        .then(|| rows.into_iter().map(|row| row[n..].to_vec()).collect())
}

struct Search {
    point: Vec<f64>,
    residuals: Option<Vec<Residual>>,
    jacobian: Json,
    substitution: Option<Vec<ExactResidual>>,
    iterations: usize,
    reason: String,
    converged: bool,
}

fn search(problem: &mut Problem<'_>, mut result: Search, tolerance: f64) -> Search {
    result.reason = "iteration budget exhausted".into();
    while let Some(residuals) = &result.residuals {
        let center = &result.point;
        let h = f64::EPSILON.cbrt();
        let pair = problem
            .difference(center, residuals, h)
            .and_then(|coarse| Ok((coarse, problem.difference(center, residuals, h / 2.0)?)));
        let (coarse, fine) = match pair {
            Ok(pair) => pair,
            Err(error) => {
                result.reason = format!("could not estimate the local Jacobian: {error}");
                break;
            }
        };
        let Some(inverse) = inverse(&fine.central) else {
            result.jacobian = json!({"reciprocal_condition_estimate": 0.0});
            result.reason = "local Jacobian is singular or its inverse is unrepresentable".into();
            break;
        };
        let inverse_norm = matrix_norm(&inverse);
        let reciprocal_condition = 1.0 / (matrix_norm(&fine.central) * inverse_norm);
        let difference_norm = magnitude(
            coarse
                .central
                .iter()
                .zip(&fine.central)
                .map(|(a, b)| a.iter().zip(b).map(|(x, y)| (x - y).abs()).sum()),
        );
        let sensitivity = difference_norm * inverse_norm;
        let side_sensitivity = fine.side_disagreement * inverse_norm;
        let scaled: Vec<f64> = residuals.iter().map(|r| r.raw / r.scale).collect();
        let delta = newton_step(&inverse, &scaled);
        let correction = magnitude(delta.iter().copied());
        result.jacobian = json!({
            "reciprocal_condition_estimate": reciprocal_condition,
            "difference_sensitivity": sensitivity,
            "one_sided_sensitivity": side_sensitivity,
            "scaled_step": correction,
        });
        if !(reciprocal_condition >= MIN_RECIPROCAL_CONDITION
            && sensitivity <= MAX_DIFFERENCE_SENSITIVITY
            && side_sensitivity <= MAX_DIFFERENCE_SENSITIVITY
            && delta.iter().all(|x| x.is_finite()))
        {
            result.reason =
                "local Jacobian is ill-conditioned or its local slope estimates disagree".into();
            break;
        }
        let merit = magnitude(scaled.iter().copied());
        if merit <= tolerance && correction <= tolerance {
            if let Some(equation) = problem.excluded_quadratic() {
                result.reason = format!("an exact quadratic has no real solution: {equation}");
                break;
            }
            let verification = problem.substitute(center).and_then(|exact| {
                let exact_tolerance = as_exact(&Value::Float(tolerance))?;
                if exact
                    .iter()
                    .any(|value| value.raw.abs() > &value.scale * &exact_tolerance)
                {
                    return Ok((exact, false));
                }
                // The inverse was calculated using the floating-point equation scales,
                // so the independently computed residual must use those same units here.
                let scaled = exact
                    .iter()
                    .zip(residuals)
                    .map(|(value, original)| {
                        let scale = as_exact(&Value::Float(original.scale))?;
                        as_float(&Value::Exact(&value.raw / scale))
                    })
                    .collect::<Outcome<Vec<_>>>()?;
                let delta = newton_step(&inverse, &scaled);
                let passed = delta.iter().all(|x| x.is_finite())
                    && magnitude(delta.into_iter()) <= tolerance;
                Ok((exact, passed))
            });
            match verification {
                Ok((exact, passed)) => {
                    result.substitution = Some(exact);
                    result.converged = passed;
                    result.reason = if passed {
                        "local candidate passed scaled residual and Newton correction checks".into()
                    } else {
                        "independent rational substitution did not meet residual or correction tolerance".into()
                    };
                }
                Err(error) => {
                    result.reason = format!("could not verify candidate by substitution: {error}")
                }
            }
            break;
        }
        if result.iterations == MAX_ITERATIONS {
            break;
        }

        // Compare trials at the current equation scales so changing a scale alone
        // cannot make the residual look smaller.
        let mut next = None;
        for backtrack in 0..MAX_BACKTRACKS {
            let damping = 0.5_f64.powi(backtrack as i32);
            let point: Vec<f64> = center
                .iter()
                .zip(&delta)
                .map(|(&x, &d)| (damping * d).mul_add(x.abs().max(1.0), x))
                .collect();
            if !point.iter().all(|x| x.is_finite()) || point == *center {
                continue;
            }
            if let Ok(trial) = problem.evaluate(&point) {
                let trial_merit = magnitude(
                    trial
                        .iter()
                        .zip(residuals)
                        .map(|(r, old)| r.raw / old.scale),
                );
                if trial_merit < merit {
                    next = Some((point, trial));
                    break;
                }
            }
        }
        let Some((point, residuals)) = next else {
            result.reason = if problem.evaluations == MAX_EVALUATIONS {
                "evaluation budget exhausted".into()
            } else {
                "damped step did not find a finite point with smaller residual".into()
            };
            break;
        };
        result.point = point;
        result.residuals = Some(residuals);
        result.iterations += 1;
    }
    result
}

pub(super) fn solve(
    equations: &[String],
    starts: &[String],
    tolerance: f64,
    names: Names,
) -> Outcome<(String, bool)> {
    if !(2..=MAX_VARIABLES).contains(&equations.len()) || starts.len() != equations.len() {
        return Err(format!(
            "a nonlinear solve needs 2 to {MAX_VARIABLES} equations and one --start per unknown"
        ));
    }
    if !(0.0..=0.01).contains(&tolerance) {
        return Err("nonlinear --tolerance must be between 0 and 0.01".into());
    }
    let mut variables = BTreeSet::new();
    let equations = equations
        .iter()
        .map(|source| {
            let (left, _, right) = relation(
                source,
                &["=", "=="],
                "a nonlinear equation is LEFT == RIGHT",
            )?;
            if !rational_arithmetic(&left, names) || !rational_arithmetic(&right, names) {
                return Err("nonlinear solve accepts rational arithmetic and fixed exact integer powers only".into());
            }
            unknowns(&left, names, &mut variables);
            unknowns(&right, names, &mut variables);
            Ok(Equation {
                source,
                left,
                right,
            })
        })
        .collect::<Outcome<Vec<_>>>()?;
    if variables.len() != equations.len() {
        return Err("nonlinear solve needs as many unknowns as equations".into());
    }
    let mut initial = BTreeMap::new();
    for assignment in starts {
        let (name, expression) = assignment
            .split_once('=')
            .ok_or("--start takes NAME=EXPRESSION")?;
        let name = name.trim();
        if !variables.contains(name) || initial.contains_key(name) {
            return Err(format!(
                "--start name {name:?} must be an unknown and occur only once"
            ));
        }
        let expression = parse(expression)?;
        if !rational_arithmetic(&expression, names) {
            return Err(
                "--start accepts rational arithmetic and fixed exact integer powers only".into(),
            );
        }
        initial.insert(name, as_float(&eval(&expression, names)?)?);
    }
    let variables: Vec<String> = variables.into_iter().collect();
    let start: Vec<f64> = variables
        .iter()
        .map(|name| initial[name.as_str()])
        .collect();
    let mut problem = Problem {
        equations,
        variables,
        names,
        evaluations: 0,
    };
    let mut result = Search {
        point: start.clone(),
        residuals: None,
        jacobian: Json::Null,
        substitution: None,
        iterations: 0,
        reason: String::new(),
        converged: false,
    };
    match problem.evaluate(&start) {
        Ok(residuals) => {
            result.residuals = Some(residuals);
            result = search(&mut problem, result, tolerance);
        }
        Err(error) => result.reason = format!("could not evaluate the starting point: {error}"),
    }

    let point = |values: &[f64]| {
        problem
            .variables
            .iter()
            .cloned()
            .zip(values.iter().copied())
            .collect::<BTreeMap<_, _>>()
    };
    let solutions = if result.converged {
        vec![json!({
            "values": point(&result.point),
            "exact": false,
            "evidence": "residual-tested local candidate",
        })]
    } else {
        Vec::new()
    };
    let residuals = result.residuals.as_ref().map(|values| {
        problem
            .equations
            .iter()
            .zip(values)
            .enumerate()
            .map(|(index, (eq, value))| {
                let exact = result.substitution.as_ref().map(|rows| &rows[index]);
                json!({
                    "equation": eq.source,
                    "residual": value.raw,
                    "scale": value.scale,
                    "scaled_residual": value.raw / value.scale,
                    "recomputed_residual": exact.map(|value| value.raw.to_string()),
                    "recomputed_scale": exact.map(|value| value.scale.to_string()),
                })
            })
            .collect::<Vec<_>>()
    });
    Ok((
        json!({
            "method": "damped Newton with pivoting and two central difference scales",
            "scope": "local",
            "existence_certified": false,
            "unknowns": problem.variables,
            "starts": point(&start),
            "converged": result.converged,
            "reason": result.reason,
            "iterations": result.iterations,
            "evaluations": problem.evaluations,
            "tolerance": tolerance,
            "jacobian": result.jacobian,
            "last_point": point(&result.point),
            "residuals": residuals,
            "solutions": solutions,
        })
        .to_string(),
        result.converged,
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn run(equations: &[&str], start: &[&str]) -> (Json, bool) {
        let strings = |items: &[&str]| items.iter().map(|s| s.to_string()).collect::<Vec<_>>();
        let (report, established) =
            solve(&strings(equations), &strings(start), 1e-9, &|_| None).unwrap();
        (serde_json::from_str(&report).unwrap(), established)
    }

    #[test]
    fn substitutes_local_candidates_from_distinct_starts() {
        let equations = ["x**2 + y**2 = 2", "x = y"];
        for (start, expected) in [(["x=2", "y=3"], 1.0), (["x=-2", "y=-3"], -1.0)] {
            let (report, established) = run(&equations, &start);
            assert!(established, "{report}");
            assert_eq!(report["scope"], "local");
            assert_eq!(report["solutions"][0]["exact"], false);
            let answer = report["solutions"][0]["values"]["x"].as_f64().unwrap();
            assert!((answer - expected).abs() <= 1e-9, "{report}");
            assert!(report["residuals"]
                .as_array()
                .unwrap()
                .iter()
                .all(|row| { row["scaled_residual"].as_f64().unwrap().abs() <= 1e-9 }));
        }
    }

    #[test]
    fn small_residual_alone_does_not_stop_a_well_conditioned_step() {
        let (report, established) = run(
            &["x/100000 + y**2/100 = 0", "y = 0"],
            &["x=1/100000", "y=0"],
        );
        assert!(established, "{report}");
        assert!(report["iterations"].as_u64().unwrap() > 0, "{report}");
        assert!(
            report["solutions"][0]["values"]["x"]
                .as_f64()
                .unwrap()
                .abs()
                <= 1e-9
        );
    }

    #[test]
    fn solves_a_system_with_a_fixed_integer_power_expression() {
        let (report, established) = solve(
            &["x**(degree-1) = y".into(), "x = 2".into()],
            &["x=1".into(), "y=1".into()],
            1e-9,
            &|name| (name == "degree").then(|| Value::Exact(BigRational::from_integer(4.into()))),
        )
        .unwrap();
        assert!(established, "{report}");
        let report: Json = serde_json::from_str(&report).unwrap();
        let values = &report["solutions"][0]["values"];
        assert!(
            (values["x"].as_f64().unwrap() - 2.0).abs() <= 1e-9,
            "{report}"
        );
        assert!(
            (values["y"].as_f64().unwrap() - 8.0).abs() <= 1e-9,
            "{report}"
        );
    }

    #[test]
    fn refuses_small_residual_at_poorly_conditioned_point() {
        let (report, established) =
            run(&["x+y-2 = 0", "x+y-2+(x-1)**3/10**12 = 0"], &["x=0", "y=2"]);
        assert!(!established, "{report}");
        assert_eq!(report["solutions"], json!([]));
        assert!(
            report["reason"].as_str().unwrap().contains("Jacobian"),
            "{report}"
        );
        assert!(report["residuals"][1]["residual"].as_f64().unwrap().abs() < 1e-9);
    }

    #[test]
    fn refuses_a_small_positive_minimum_with_disagreeing_local_slopes() {
        let (report, established) = run(
            &["(x-1/1000000000)**2+1/10**20 = 0", "y/10**9 = 0"],
            &["x=0", "y=0"],
        );
        assert!(!established, "{report}");
        assert_eq!(report["solutions"], json!([]));
        assert!(
            report["jacobian"]["one_sided_sensitivity"]
                .as_f64()
                .unwrap()
                > 1.0
        );
    }

    #[test]
    fn exact_quadratic_exclusion_blocks_a_false_candidate_at_loose_tolerance() {
        let (report, established) = solve(
            &["(x-1/100)**2+1/10**8 = 0".into(), "y = 0".into()],
            &["x=0".into(), "y=0".into()],
            0.01,
            &|_| None,
        )
        .unwrap();
        assert!(!established, "{report}");
        let report: Json = serde_json::from_str(&report).unwrap();
        assert_eq!(report["solutions"], json!([]));
        assert!(report["reason"]
            .as_str()
            .unwrap()
            .contains("quadratic has no real solution"));
    }

    #[test]
    fn independent_substitution_refuses_cancellation() {
        let (report, established) = run(&["((x+2**55)-2**55)+x = 1", "y = 0"], &["x=1", "y=0"]);
        assert!(!established, "{report}");
        assert_eq!(report["solutions"], json!([]));
        assert_eq!(report["residuals"][0]["residual"], 0.0);
        assert_eq!(report["residuals"][0]["recomputed_residual"], "1");
        assert!(
            report["reason"].as_str().unwrap().contains("substitution"),
            "{report}"
        );
    }

    #[test]
    fn refuses_rounded_primitives_and_powers_without_fixed_exact_integer_exponents() {
        for equation in [
            "10**20*(exp(1)-6121026514868073/2251799813685248)+x=0",
            "((sin(x)+10**20)-10**20)+x = 1",
            "x**(1/2) = y",
            "x**y = 1",
            "x**2.0 = y",
        ] {
            let error = solve(
                &[equation.into(), "y = 0".into()],
                &["x=1".into(), "y=0".into()],
                1e-9,
                &|_| None,
            )
            .unwrap_err();
            assert!(
                error.contains("fixed exact integer powers"),
                "{equation}: {error}"
            );
        }
    }

    #[test]
    fn refuses_a_singular_root_and_inconsistent_system() {
        for equations in [["x**3 = 0", "y = 0"], ["x**2 + 1 = 0", "y = 0"]] {
            let (report, established) = run(&equations, &["x=0", "y=0"]);
            assert!(!established, "{report}");
            assert_eq!(report["solutions"], json!([]));
        }
    }

    #[test]
    fn refuses_nonsmooth_inputs_and_reports_domain_failures() {
        assert!(solve(
            &["abs(x) = y".into(), "y = 1".into()],
            &["x=0".into(), "y=0".into()],
            1e-9,
            &|_| None
        )
        .is_err());
        let (report, established) = run(&["1/x=y", "y=0"], &["x=0", "y=0"]);
        assert!(!established, "{report}");
        assert_eq!(report["residuals"], Json::Null);
        assert!(report["reason"]
            .as_str()
            .unwrap()
            .contains("starting point"));
    }
}
