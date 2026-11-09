//! Exact finite-domain checks for ordered piecewise-affine rules.

use super::poly::{held, unknowns};
use super::{
    exact, list, object, parse, quoted, relation, round_half_even, shown, to_float, Names, Node,
    Outcome, Value, COMPARISONS,
};
use num_rational::BigRational as Rat;
use num_traits::{One, Zero};
use std::cell::Cell;
use std::cmp::Ordering;
use std::collections::BTreeSet;
use std::rc::Rc;

const MAX_PIECES: usize = 32;
const MAX_CUTS: usize = 128;
const MAX_NODES: usize = 100_000;
const MAX_TEXT_BYTES: usize = 16_384;

#[derive(Clone)]
struct Affine {
    slope: Rat,
    offset: Rat,
}

impl Affine {
    fn constant(offset: Rat) -> Self {
        Self {
            slope: Rat::zero(),
            offset,
        }
    }

    fn at(&self, x: &Rat) -> Outcome<Rat> {
        held(&self.slope * x + &self.offset)
    }

    fn combine(&self, other: &Self, subtract: bool) -> Outcome<Self> {
        let combine = |a: &Rat, b: &Rat| held(if subtract { a - b } else { a + b });
        Ok(Self {
            slope: combine(&self.slope, &other.slope)?,
            offset: combine(&self.offset, &other.offset)?,
        })
    }

    fn scale(&self, factor: &Rat) -> Outcome<Self> {
        Ok(Self {
            slope: held(&self.slope * factor)?,
            offset: held(&self.offset * factor)?,
        })
    }
}

/// A cell is either a singleton or an open interval. Splits always insert the exact boundary
/// as its own cell, so rounding ties and ordered branches use the rule at the boundary itself.
struct Span {
    low: Rat,
    high: Rat,
}

impl Span {
    fn point(x: Rat) -> Self {
        Self {
            low: x.clone(),
            high: x,
        }
    }

    fn is_point(&self) -> bool {
        self.low == self.high
    }

    fn sample(&self) -> Outcome<Rat> {
        held((&self.low + &self.high) / Rat::from_integer(2.into()))
    }
}

enum Refine {
    Cut(Rat),
    Invalid(String),
}

impl From<String> for Refine {
    fn from(error: String) -> Self {
        Self::Invalid(error)
    }
}

type Refined<T> = Result<T, Refine>;

struct Evaluator<'a> {
    span: &'a Span,
    sample: &'a Rat,
    names: Names<'a>,
    budget: &'a Cell<usize>,
}

impl Evaluator<'_> {
    /// The sign stays constant on the open cell unless the exact zero lies inside it.
    fn split_at_zero(&self, affine: &Affine) -> Refined<()> {
        if !affine.slope.is_zero() {
            let zero = -&affine.offset / &affine.slope;
            if self.span.low < zero && zero < self.span.high {
                return Err(Refine::Cut(held(zero)?));
            }
        }
        Ok(())
    }

    fn comparison(&self, difference: &Affine, op: &str) -> Refined<bool> {
        self.split_at_zero(difference)?;
        let order = difference.at(self.sample)?.cmp(&Rat::zero());
        Ok(match op {
            "==" => order == Ordering::Equal,
            "!=" => order != Ordering::Equal,
            "<" => order == Ordering::Less,
            "<=" => order != Ordering::Greater,
            ">" => order == Ordering::Greater,
            ">=" => order != Ordering::Less,
            _ => unreachable!("comparison token validated by parser"),
        })
    }

    fn discrete(&self, form: &Affine, op: &str) -> Refined<Affine> {
        // floor and ceil change at integers. Half-even round changes at half-integers.
        let shift = if op == "round" {
            Rat::new(1.into(), 2.into())
        } else {
            Rat::zero()
        };
        if !form.slope.is_zero() {
            let low = form.at(&self.span.low)?;
            let high = form.at(&self.span.high)?;
            let first = (low.min(high) - &shift).floor() + Rat::one() + shift;
            let threshold = form.combine(&Affine::constant(first), true)?;
            self.split_at_zero(&threshold)?;
        }
        let at = form.at(self.sample)?;
        let rounded = match op {
            "floor" => at.floor(),
            "ceil" => at.ceil(),
            "round" => Rat::from_integer(round_half_even(&at)),
            _ => unreachable!("discrete operation selected by evaluator"),
        };
        Ok(Affine::constant(held(rounded)?))
    }

    fn binary(&self, op: &str, left: Affine, right: Affine) -> Refined<Affine> {
        let left_constant = left.slope.is_zero();
        let right_constant = right.slope.is_zero();
        Ok(match op {
            "+" | "-" => left.combine(&right, op == "-")?,
            "*" if left_constant => right.scale(&left.offset)?,
            "*" if right_constant => left.scale(&right.offset)?,
            "/" | "//" | "%" if right_constant => {
                if right.offset.is_zero() {
                    return Err("division by zero in a reachable piece".to_string().into());
                }
                let quotient = left.scale(&right.offset.recip())?;
                match op {
                    "//" => self.discrete(&quotient, "floor")?,
                    "%" => left.combine(&self.discrete(&quotient, "floor")?.scale(&right.offset)?, true)?,
                    _ => quotient,
                }
            }
            "**" if left_constant && right_constant => {
                let result = super::power(Value::Exact(left.offset), Value::Exact(right.offset))?;
                Affine::constant(exact_value(result)?)
            }
            _ => return Err(format!("operator {op} needs piecewise-affine operands with a constant multiplier or divisor").into()),
        })
    }

    fn call(&self, op: &str, arguments: &[Rc<Node>]) -> Refined<Affine> {
        match (op, arguments) {
            ("abs", [argument]) => {
                let form = self.form(argument)?;
                if self.comparison(&form, "<")? {
                    Ok(form.scale(&-Rat::one())?)
                } else {
                    Ok(form)
                }
            }
            ("floor" | "ceil" | "round", [argument]) => self.discrete(&self.form(argument)?, op),
            ("min" | "max", [first, rest @ ..]) => {
                let mut best = self.form(first)?;
                for argument in rest {
                    let form = self.form(argument)?;
                    let compare = if op == "min" { "<" } else { ">" };
                    if self.comparison(&form.combine(&best, true)?, compare)? {
                        best = form;
                    }
                }
                Ok(best)
            }
            _ => Err(format!("unsupported piecewise function or arity: {op}").into()),
        }
    }

    fn form(&self, node: &Node) -> Refined<Affine> {
        let remaining = self
            .budget
            .get()
            .checked_sub(1)
            .ok_or("piecewise expression work limit exceeded".to_string())?;
        self.budget.set(remaining);
        Ok(match node {
            Node::Number(value) => Affine::constant(exact_value(value.clone())?),
            Node::Name(name) => match (self.names)(name) {
                Some(value) => Affine::constant(exact_value(value)?),
                None => Affine {
                    slope: Rat::one(),
                    offset: Rat::zero(),
                },
            },
            Node::Negate(inner) => self.form(inner)?.scale(&-Rat::one())?,
            Node::Binary(op, left, right) => {
                self.binary(op, self.form(left)?, self.form(right)?)?
            }
            Node::Call(op, arguments) => self.call(op, arguments)?,
        })
    }
}

fn exact_value(value: Value) -> Outcome<Rat> {
    match value {
        Value::Exact(rational) => Ok(rational),
        Value::Float(_) => Err("piecewise solving requires exact numbers; write integers or fractions instead of floats".into()),
    }
}

struct Condition {
    left: Rc<Node>,
    op: &'static str,
    right: Rc<Node>,
}

struct Piece {
    condition: Option<Condition>,
    formula: Rc<Node>,
}

fn pieces(sources: &[String], names: Names) -> Outcome<(Vec<Piece>, Option<String>)> {
    let mut variables = BTreeSet::new();
    let mut pieces = Vec::new();
    for (index, source) in sources.iter().enumerate() {
        let (guard, formula) = source
            .split_once(':')
            .ok_or("a piece is CONDITION: EXPRESSION or else: EXPRESSION")?;
        let condition = if guard.trim() == "else" {
            if index + 1 != sources.len() {
                return Err("else must be the last piece".into());
            }
            None
        } else {
            let (left, op, right) = relation(
                guard,
                &COMPARISONS,
                "a piece condition is a single comparison such as x < 3",
            )?;
            unknowns(&left, names, &mut variables);
            unknowns(&right, names, &mut variables);
            Some(Condition { left, op, right })
        };
        let formula = parse(formula)?;
        unknowns(&formula, names, &mut variables);
        pieces.push(Piece { condition, formula });
    }
    if variables.len() > 1 {
        return Err("piecewise solving supports one unknown; bind other names with --set".into());
    }
    Ok((pieces, variables.into_iter().next()))
}

fn constant(node: &Node, names: Names, budget: &Cell<usize>) -> Outcome<Rat> {
    let mut variables = BTreeSet::new();
    unknowns(node, names, &mut variables);
    if !variables.is_empty() {
        return Err("piecewise bounds and target must be exact constants".into());
    }
    let sample = Rat::zero();
    let span = Span::point(sample.clone());
    let evaluator = Evaluator {
        span: &span,
        sample: &sample,
        names,
        budget,
    };
    match evaluator.form(node) {
        Ok(form) => Ok(form.offset),
        Err(Refine::Invalid(error)) => Err(error),
        Err(Refine::Cut(_)) => unreachable!("a singleton cannot be subdivided"),
    }
}

struct Witness {
    piece: Option<usize>,
    value: Option<Rat>,
    matches: bool,
}

fn examine(
    evaluator: &Evaluator<'_>,
    pieces: &[Piece],
    op: &str,
    target: &Rat,
) -> Refined<Witness> {
    for (index, piece) in pieces.iter().enumerate() {
        if let Some(guard) = &piece.condition {
            let difference = evaluator
                .form(&guard.left)?
                .combine(&evaluator.form(&guard.right)?, true)?;
            if !evaluator.comparison(&difference, guard.op)? {
                continue;
            }
        }
        let form = evaluator.form(&piece.formula)?;
        let matches =
            evaluator.comparison(&form.combine(&Affine::constant(target.clone()), true)?, op)?;
        let value = Some(form.at(evaluator.sample)?);
        return Ok(Witness {
            piece: Some(index + 1),
            value,
            matches,
        });
    }
    Ok(Witness {
        piece: None,
        value: None,
        matches: false,
    })
}

struct Interval<'a> {
    low: &'a Rat,
    high: &'a Rat,
    low_closed: bool,
    high_closed: bool,
}

fn number(value: &Rat) -> Outcome<String> {
    Ok(shown(&exact(value.clone())?))
}

fn merged_cells(
    cells: &[(Span, Rat, Witness)],
    include: impl Fn(&Witness) -> bool,
) -> Outcome<String> {
    let mut intervals: Vec<Interval<'_>> = Vec::new();
    for (span, _, _) in cells.iter().filter(|(_, _, witness)| include(witness)) {
        let closed = span.is_point();
        if let Some(previous) = intervals.last_mut() {
            if previous.high == &span.low && (previous.high_closed || closed) {
                previous.high = &span.high;
                previous.high_closed = closed;
                continue;
            }
        }
        intervals.push(Interval {
            low: &span.low,
            high: &span.high,
            low_closed: closed,
            high_closed: closed,
        });
    }
    let items = intervals
        .iter()
        .map(|i| {
            Ok(object(&[
                ("low", number(i.low)?),
                ("high", number(i.high)?),
                ("low_closed", i.low_closed.to_string()),
                ("high_closed", i.high_closed.to_string()),
            ]))
        })
        .collect::<Outcome<Vec<_>>>()?;
    Ok(list(&items))
}

fn witness_json(sample: &Rat, witness: &Witness) -> Outcome<String> {
    let null = || "null".to_string();
    Ok(object(&[
        ("input", number(sample)?),
        (
            "piece",
            witness.piece.map_or_else(null, |index| index.to_string()),
        ),
        (
            "value",
            witness
                .value
                .as_ref()
                .map(number)
                .transpose()?
                .unwrap_or_else(null),
        ),
        (
            "matches",
            witness
                .piece
                .map_or_else(null, |_| witness.matches.to_string()),
        ),
    ]))
}

/// Candidate inputs for replay in a binary64 implementation. The exact witnesses remain
/// independent of target arithmetic, and an unrepresentable cut has no floating-point "at".
fn float_inputs(cut: &Rat, low: &Rat, high: &Rat) -> String {
    let probes = to_float(cut)
        .ok()
        .and_then(|float| {
            let represented = Rat::from_float(float)?;
            Some(match represented.cmp(cut) {
                Ordering::Less => [Some(float), None, Some(float.next_up())],
                Ordering::Equal => [Some(float.next_down()), Some(float), Some(float.next_up())],
                Ordering::Greater => [Some(float.next_down()), None, Some(float)],
            })
        })
        .unwrap_or([None; 3]);
    let input = |value: Option<f64>, side: Ordering| {
        value
            .filter(|&float| {
                Rat::from_float(float)
                    .is_some_and(|x| low <= &x && &x <= high && x.cmp(cut) == side)
            })
            .map_or_else(|| "null".to_string(), |float| format!("{float:?}"))
    };
    object(&[
        ("below", input(probes[0], Ordering::Less)),
        ("at", input(probes[1], Ordering::Equal)),
        ("above", input(probes[2], Ordering::Greater)),
    ])
}

pub(super) fn solve(
    sources: &[String],
    target: &str,
    bounds: &(String, String),
    names: Names,
) -> Outcome<String> {
    if sources.is_empty() || sources.len() > MAX_PIECES {
        return Err(format!("piecewise solving needs 1 to {MAX_PIECES} pieces"));
    }
    let size = sources.iter().map(String::len).sum::<usize>()
        + target.len()
        + bounds.0.len()
        + bounds.1.len();
    if size > MAX_TEXT_BYTES {
        return Err(format!(
            "piecewise expressions exceed {MAX_TEXT_BYTES} bytes"
        ));
    }
    let (pieces, variable) = pieces(sources, names)?;
    let budget = Cell::new(MAX_NODES);
    let (op, rhs) = COMPARISONS
        .into_iter()
        .find_map(|op| target.trim_start().strip_prefix(op).map(|rhs| (op, rhs)))
        .ok_or("a piecewise target starts with a comparison such as >= 3")?;
    let target = constant(parse(rhs)?.as_ref(), names, &budget)?;
    let low = constant(parse(&bounds.0)?.as_ref(), names, &budget)?;
    let high = constant(parse(&bounds.1)?.as_ref(), names, &budget)?;
    if low >= high {
        return Err("piecewise --between bounds must be in strictly increasing order".into());
    }

    let mut pending = vec![
        Span::point(high.clone()),
        Span {
            low: low.clone(),
            high: high.clone(),
        },
        Span::point(low.clone()),
    ];
    let mut cells = Vec::new();
    let mut cuts = 0;
    while let Some(span) = pending.pop() {
        let sample = span.sample()?;
        let evaluator = Evaluator {
            span: &span,
            sample: &sample,
            names,
            budget: &budget,
        };
        match examine(&evaluator, &pieces, op, &target) {
            Ok(witness) => cells.push((span, sample, witness)),
            Err(Refine::Invalid(error)) => return Err(error),
            Err(Refine::Cut(cut)) => {
                cuts += 1;
                if cuts > MAX_CUTS {
                    return Err(format!(
                        "piecewise split limit of {MAX_CUTS} exceeded; narrow --between"
                    ));
                }
                pending.push(Span {
                    low: cut.clone(),
                    high: span.high,
                });
                pending.push(Span::point(cut.clone()));
                pending.push(Span {
                    low: span.low,
                    high: cut,
                });
            }
        }
    }

    let witnesses = cells
        .iter()
        .map(|(_, sample, witness)| witness_json(sample, witness))
        .collect::<Outcome<Vec<_>>>()?;
    let mut boundaries = Vec::new();
    for (index, (_, sample, _)) in cells
        .iter()
        .enumerate()
        .filter(|(_, (span, _, _))| span.is_point())
    {
        let adjacent = |i: Option<usize>| {
            i.and_then(|i| witnesses.get(i))
                .map_or("null", String::as_str)
                .to_owned()
        };
        boundaries.push(object(&[
            ("input", number(sample)?),
            ("below", adjacent(index.checked_sub(1))),
            ("at", witnesses[index].clone()),
            ("above", adjacent(Some(index + 1))),
            ("f64_inputs", float_inputs(sample, &low, &high)),
        ]));
    }
    Ok(object(&[
        (
            "variable",
            variable.as_deref().map_or_else(|| "null".into(), quoted),
        ),
        ("exact", "true".into()),
        ("solutions", merged_cells(&cells, |w| w.matches)?),
        ("gaps", merged_cells(&cells, |w| w.piece.is_none())?),
        ("witnesses", list(&witnesses)),
        ("boundaries", list(&boundaries)),
    ]))
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::{json, Value as Json};

    fn run(pieces: &[&str], target: &str, low: &str, high: &str) -> Json {
        let pieces = pieces
            .iter()
            .map(|piece| (*piece).to_string())
            .collect::<Vec<_>>();
        serde_json::from_str(
            &solve(&pieces, target, &(low.into(), high.into()), &|_| None).unwrap(),
        )
        .unwrap()
    }

    #[test]
    fn first_match_owns_the_boundary_and_gaps_are_visible() {
        let report = run(&["x <= 1: x", "x >= 2: 1"], "== 1", "0", "3");
        assert_eq!(
            report["solutions"],
            json!([
                {"low":1,"high":1,"low_closed":true,"high_closed":true},
                {"low":2,"high":3,"low_closed":true,"high_closed":true}
            ])
        );
        assert_eq!(
            report["gaps"],
            json!([{"low":1,"high":2,"low_closed":false,"high_closed":false}])
        );
        let overlap = run(&["x <= 1: 1", "x >= 1: 2"], "== 1", "0", "3");
        assert_eq!(overlap["boundaries"][1]["at"]["piece"], 1);
        assert_eq!(overlap["boundaries"][1]["above"]["piece"], 2);
    }

    #[test]
    fn strict_guard_leaves_the_boundary_to_the_next_piece() {
        let report = run(&["x < 4: 3", "else: 4"], "== 3", "2", "5");
        assert_eq!(
            report["solutions"],
            json!([{"low":2,"high":4,"low_closed":true,"high_closed":false}])
        );
        assert_eq!(report["boundaries"][1]["at"]["piece"], 2);
    }

    #[test]
    fn clamping_and_discrete_intervals_are_exact() {
        let clamp = run(&["else: min(3,max(0,x))"], ">= 3", "-1", "4");
        assert_eq!(
            clamp["solutions"],
            json!([{"low":3,"high":4,"low_closed":true,"high_closed":true}])
        );
        let floor = run(&["else: floor(x)"], "== 3", "2", "5");
        assert_eq!(
            floor["solutions"],
            json!([{"low":3,"high":4,"low_closed":true,"high_closed":false}])
        );
        let ceil = run(&["else: ceil(-x)"], "== 2", "-3", "0");
        assert_eq!(
            ceil["solutions"],
            json!([{"low":-2,"high":-1,"low_closed":true,"high_closed":false}])
        );
    }

    #[test]
    fn rounding_ties_and_negative_remainders_use_exact_calculator_semantics() {
        let round = run(&["else: round(x)"], "== 2", "1", "3");
        let interval = &round["solutions"][0];
        assert_eq!(interval["low"]["exact"], "3/2");
        assert_eq!(interval["high"]["exact"], "5/2");
        assert_eq!(interval["low_closed"], true);
        assert_eq!(interval["high_closed"], true);
        let modulo = run(&["else: x % 3"], "== 2", "-2", "0");
        assert_eq!(
            modulo["solutions"],
            json!([{"low":-1,"high":-1,"low_closed":true,"high_closed":true}])
        );
    }

    #[test]
    fn float_probes_bracket_the_exact_boundary_and_stay_in_domain() {
        let report = run(&["x <= 1/3: 0", "else: 1"], "== 1", "0", "1");
        let edges = &report["boundaries"];
        let probe = &edges[1]["f64_inputs"];
        let below = probe["below"].as_f64().unwrap();
        let above = probe["above"].as_f64().unwrap();
        let boundary = Rat::new(1.into(), 3.into());
        assert!(Rat::from_float(below).unwrap() < boundary);
        assert!(boundary < Rat::from_float(above).unwrap());
        assert_eq!(below.next_up(), above);
        assert!(probe["at"].is_null());
        assert!(edges[0]["f64_inputs"]["below"].is_null());
        assert!(edges[2]["f64_inputs"]["above"].is_null());
        assert_eq!(edges[2]["f64_inputs"]["at"], 1.0);
    }

    #[test]
    fn unsupported_or_unbounded_work_is_refused() {
        for (rule, low, high) in [
            ("else: x*y", "0", "2"),
            ("else: x*1.5", "0", "2"),
            ("else: x^2", "0", "2"),
            ("else: x*x", "0", "2"),
            ("else: floor(x)", "0", "200"),
            ("else: x", "2", "2"),
            ("else: x/0", "0", "2"),
        ] {
            assert!(
                solve(&[rule.into()], "== 1", &(low.into(), high.into()), &|_| {
                    None
                })
                .is_err(),
                "{rule}"
            );
        }
        assert!(solve(
            &["else: x".into()],
            "+ 1 > 1",
            &("0".into(), "2".into()),
            &|_| None
        )
        .is_err());
    }
}
