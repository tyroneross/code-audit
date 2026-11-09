#!/usr/bin/env python3
"""Evaluate arithmetic so a reported number comes from a computation, not from a model's mental arithmetic.

  calc.py EXPRESSION [EXPRESSION ...] [--check "LEFT == RIGHT" ...] [--tolerance 1e-9]

  calc.py "99 + 124 + 89 + 10" "round(100 * 21 / 47, 1)"
  calc.py --check "10**2 * (1 - 0.5)**3 + 10 == 22.5"

Expressions use numbers, + - * / // % **, parentheses, comparisons and the functions listed by --help.
Nothing else is accepted: no names, attributes, calls to other functions, strings or imports, so an expression
copied from a repository under review cannot run code. Integers and fractions stay exact (1/3 + 1/6 is 1/2);
a float in the expression or sqrt/log makes the result a float. An exact value larger than 4096 bits (about
1,230 digits) is refused before it is computed. round follows Python: a tie goes to the even digit, and a float is rounded
as the binary value it holds. mean and median of exact values are exact; stdev and pstdev return floats. --check passes when both sides are equal, or
within --tolerance when either side is a float.

Exit: 0 every expression evaluated and every check passed; 1 a check failed; 2 an expression is invalid.
"""
import argparse
import ast
from fractions import Fraction
import json
import math
import operator
import statistics
import sys

BINARY = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
          ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod}
UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
COMPARE = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt, ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge}
# Standard-library arithmetic only: fractions for exact values, math and statistics for the rest.
FUNCTIONS = {"abs": abs, "round": lambda *arguments: rounded(*arguments), "min": min, "max": max, "sum": lambda *values: sum(values), "sqrt": math.sqrt,
             "floor": math.floor, "ceil": math.ceil, "log": math.log, "log2": math.log2, "log10": math.log10,
             "mean": lambda *values: statistics.mean(values), "median": lambda *values: statistics.median(values),
             "stdev": lambda *values: statistics.stdev(values), "pstdev": lambda *values: statistics.pstdev(values)}
# Size budget for every exact value, so 9**9**9 or a nested power cannot exhaust memory. 4096 bits is about 1,230
# digits: far beyond any review arithmetic, and below the 4,300 digits at which Python refuses to print an integer,
# so every permitted result can be written and read back as JSON.
MAX_BITS = 4096
MAX_ROUND_DIGITS = 60
TOLERANCE = 1e-9


def bits(value):
    """Storage size of an exact value: the longer of its numerator and denominator, in bits."""
    return max(value.numerator.bit_length(), value.denominator.bit_length()) if isinstance(value, Fraction) else 0


def bounded(value):
    """Every exact value as a Fraction within the size budget. Floor division, floor and ceil return int, which
    would otherwise skip the budget and turn a later division into a float."""
    if isinstance(value, int) and not isinstance(value, bool):
        value = Fraction(value)
    if bits(value) > MAX_BITS:
        raise ValueError(f"exact result is larger than {MAX_BITS} bits; use a float (write 2.0 for 2) or a smaller expression")
    return value



def power(left, right):
    if isinstance(left, Fraction) and isinstance(right, Fraction):
        if right.denominator != 1:
            left, right = float(left), float(right)  # a fractional power is not exact
        # Checked before computing: the result has about exponent x log2(base) bits.
        elif abs(right.numerator) * math.log2(max(abs(left.numerator), left.denominator)) + 1 > MAX_BITS:
            raise ValueError(f"exact power would exceed {MAX_BITS} bits; use a float base (write 2.0 for 2) or a smaller exponent")
    return operator.pow(left, right)


def rounded(value, digits=Fraction(0)):
    if not isinstance(digits, Fraction) or digits.denominator != 1 or abs(digits) > MAX_ROUND_DIGITS:
        raise ValueError(f"round takes a whole number of digits between -{MAX_ROUND_DIGITS} and {MAX_ROUND_DIGITS}")
    return round(value, int(digits))


def number(node):
    """Value of one expression node; integers become exact fractions so division does not lose precision."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return bounded(node.value)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
        return bounded(power(number(node.left), number(node.right)))
    if isinstance(node, ast.BinOp) and type(node.op) in BINARY:
        # Both operands are within the budget, so the product is at most twice it before this check.
        return bounded(BINARY[type(node.op)](number(node.left), number(node.right)))
    if isinstance(node, ast.UnaryOp) and type(node.op) in UNARY:
        return UNARY[type(node.op)](number(node.operand))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FUNCTIONS and not node.keywords:
        try:
            result = FUNCTIONS[node.func.id](*(number(argument) for argument in node.args))
        except (TypeError, statistics.StatisticsError) as error:
            raise ValueError(f"{node.func.id}: {error}") from None
        return bounded(result)
    raise ValueError(f"only numbers, arithmetic operators and {sorted(FUNCTIONS)} are accepted")


def parse(expression):
    try:
        return ast.parse(expression.strip(), mode="eval").body
    except SyntaxError as error:
        raise ValueError(f"not an arithmetic expression: {error.msg}") from None
    except (ValueError, RecursionError, MemoryError) as error:  # an integer literal too long to read, or nesting too deep
        raise ValueError(f"not an arithmetic expression: {error}") from None


def evaluate(expression):
    """Exact int or Fraction when the inputs allow it, otherwise a float."""
    try:
        value = number(parse(expression))
    except ZeroDivisionError:
        raise ValueError("division by zero") from None
    except OverflowError:
        raise ValueError("result is outside float range") from None
    except RecursionError:
        raise ValueError("expression is nested too deeply") from None
    if isinstance(value, complex) or (isinstance(value, float) and not math.isfinite(value)):
        raise ValueError("result is not a finite real number")
    return int(value) if isinstance(value, Fraction) and value.denominator == 1 else value


def check(expression, tolerance=TOLERANCE):
    """(passed, left value, right value) for a single comparison `LEFT op RIGHT`."""
    node = parse(expression)
    if not (isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in COMPARE):
        raise ValueError("a check is one comparison, for example \"2 + 2 == 4\"")
    left, right = evaluate(ast.unparse(node.left)), evaluate(ast.unparse(node.comparators[0]))
    approximate = isinstance(left, float) or isinstance(right, float)
    try:
        if approximate and isinstance(node.ops[0], (ast.Eq, ast.NotEq)):
            equal = math.isclose(left, right, rel_tol=tolerance, abs_tol=tolerance)
            return equal == isinstance(node.ops[0], ast.Eq), left, right
        return COMPARE[type(node.ops[0])](left, right), left, right
    except OverflowError:
        raise ValueError("a side is outside float range; compare exact values") from None


def shown(value):
    """JSON form: integers and floats as numbers, an exact fraction as text with its decimal value beside it
    (null when the fraction is outside float range)."""
    if not isinstance(value, Fraction):
        return value
    try:
        return {"exact": str(value), "decimal": float(value)}
    except OverflowError:
        return {"exact": str(value), "decimal": None}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__ + "\nFunctions: " + ", ".join(sorted(FUNCTIONS)), formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("expressions", nargs="*", help="arithmetic expressions to evaluate")
    parser.add_argument("--check", action="append", default=[], metavar="COMPARISON", help="a comparison that must hold; repeatable")
    parser.add_argument("--tolerance", type=float, default=TOLERANCE, help=f"relative and absolute tolerance for float equality (default: {TOLERANCE})")
    args = parser.parse_args(argv)
    if not args.expressions and not args.check:
        parser.error("give at least one expression or --check")
    results, checks, status = [], [], 0
    try:
        for expression in args.expressions:
            results.append({"expression": expression, "value": shown(evaluate(expression))})
        for expression in args.check:
            passed, left, right = check(expression, args.tolerance)
            checks.append({"check": expression, "passed": passed, "left": shown(left), "right": shown(right)})
            status = status if passed else 1
    except ValueError as error:
        print(json.dumps({"schema": "code-audit.calc.v1", "status": "invalid", "error": str(error)}))
        return 2
    print(json.dumps({"schema": "code-audit.calc.v1", "status": "failed" if status else "ok", "results": results, "checks": checks}, indent=2))
    return status


if __name__ == "__main__":
    sys.exit(main())
