#!/usr/bin/env python3
"""Evaluate arithmetic so a reported number comes from a computation, not from a model's mental arithmetic.

  calc.py EXPRESSION [EXPRESSION ...] [--check "LEFT == RIGHT" ...] [--tolerance 1e-9]

The same calculator is built into the analyzer binary and starts several times faster: when
runtime/complexity is built, run `code-audit-complexity calc ...` with the same arguments. This script needs no
build and is the fallback. calc_vectors.json is run against both, so they give the same answers.

  calc.py "99 + 124 + 89 + 10" "round(100 * 21 / 47, 1)"
  calc.py --check "10**2 * (1 - 0.5)**3 + 10 == 22.5"

Expressions use numbers, + - * / // % **, parentheses, comparisons and the functions listed by --help.
Nothing else is accepted: no names, attributes, calls to other functions, strings or imports, so an expression
copied from a repository under review cannot run code. Integers and fractions stay exact (1/3 + 1/6 is 1/2);
a float in the expression or sqrt/log makes the result a float. An exact value larger than 4096 bits (about
1,230 digits) is refused before it is computed, and an expression is at most 2000 characters and 256 parts. round follows Python: a tie goes to the even digit, and a float is rounded
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
import sys

BINARY = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
          ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod}
UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
COMPARE = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt, ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge}
# Standard-library arithmetic only: fractions for exact values, math and statistics for the rest.
FUNCTIONS = {"abs": abs, "round": lambda *arguments: rounded(*arguments), "min": lambda *values: extreme(min, values),
             "max": lambda *values: extreme(max, values), "sum": lambda *values: total(*values), "sqrt": lambda value: square_root(value),
             "floor": math.floor, "ceil": math.ceil, "log": lambda *arguments: log(*arguments),
             "log2": lambda value: log_to(value, math.log(2), math.log2), "log10": lambda value: log_to(value, math.log(10), math.log10),
             "mean": lambda *values: mean(*values), "median": lambda *values: median(*values),
             "stdev": lambda *values: deviation(True, values), "pstdev": lambda *values: deviation(False, values)}
# Size budget for every exact value, so 9**9**9 or a nested power cannot exhaust memory. 4096 bits is about 1,230
# digits: far beyond any review arithmetic, and below the 4,300 digits at which Python refuses to print an integer,
# so every permitted result can be written and read back as JSON.
MAX_BITS = 4096
MAX_ROUND_DIGITS = 60
# Input budget: review arithmetic is a line or two. With at most this many numbers and operations, evaluation depth
# and work are bounded, and each operation is bounded by MAX_BITS.
MAX_CHARS = 2000
MAX_NODES = 256
TOLERANCE = 1e-9
# How far apart the results at the two floats around an exact operand may be before the result is refused.
SENSITIVE = 1e-9
# This script is the arithmetic fallback. Names, equations, calculus, finance functions and linear programs exist
# only in the analyzer binary, which is built on exact rationals and checked against independent methods.
BINARY_ONLY = {"--set", "--solve", "--between", "--derivative", "--at", "--integral", "--from", "--to", "--expand", "--maximize", "--minimize",
               "--subject", "--integer", "--var"}
BINARY_ONLY_MESSAGE = ("names, equations, derivatives, integrals, finance functions and linear programs need the analyzer binary: "
                       "build runtime/complexity (cargo build --release) and run `code-audit-complexity calc --help`")


def bits(value):
    """Storage size of an exact value: the longer of its numerator and denominator, in bits."""
    return max(value.numerator.bit_length(), value.denominator.bit_length()) if isinstance(value, Fraction) else 0


def bounded(value):
    """Every exact value as a Fraction within the size budget. Floor division, floor and ceil return int, which
    would otherwise skip the budget and turn a later division into a float."""
    if isinstance(value, complex):  # a negative base with a fractional exponent
        raise ValueError("result is not a real number")
    if isinstance(value, float) and not math.isfinite(value):  # refused where it arises: min, max and median would hide it
        raise ValueError("result is not a finite real number")
    if isinstance(value, int) and not isinstance(value, bool):
        value = Fraction(value)
    if bits(value) > MAX_BITS:
        raise ValueError(f"exact result is larger than {MAX_BITS} bits; use a float (write 2.0 for 2) or a smaller expression")
    return value



def approximate(value):
    """The float for a value that has to become one. A non-zero exact value below about 2e-308 would become 0.0
    (or a float with few digits left) and what followed would be a wrong number, not a rounded one, so it is
    refused. The analyzer binary's calc applies the same rule (nearest)."""
    if isinstance(value, float):
        return value
    result = float(value)  # OverflowError when it is too large, reported as outside float range
    if value != 0 and abs(result) < sys.float_info.min:
        raise ValueError("an exact value is too small for a float; keep the arithmetic exact or rescale")
    return result


def combined(operation, left, right):
    """left operation right. An exact value beside a float is combined exactly, on the float's own value, and
    rounded once at the end. Rounding the exact operand first loses what a later subtraction needs:
    (1 + 1/2**60) - 1.0 is 2**-60, not 0.0. The analyzer binary's calc does the same."""
    if isinstance(left, float) != isinstance(right, float):
        return approximate(Fraction(operation(Fraction(left), Fraction(right))))
    return operation(left, right)


def other_side(value, nearest):
    """The float on the other side of an exact value from its nearest float; None when the value is that float
    (or was a float to begin with)."""
    if isinstance(value, float) or Fraction(nearest) == value:
        return None
    return math.nextafter(nearest, math.inf if Fraction(nearest) < value else -math.inf)


def steady(result, other):
    """An exact operand that is not itself a float lies between two floats. When the operation gives those two
    materially different results, its value at the exact operand is not known from floats at all (a base next to
    1 raised to a huge power), and it is refused instead of reporting the result at one of them."""
    if not (isinstance(other, float) and abs(result - other) <= SENSITIVE * max(abs(result), abs(other))):
        raise ValueError("this power depends on digits of an exact value that a float cannot hold; rescale, or keep the arithmetic exact")


def power(left, right):
    if isinstance(left, Fraction) and isinstance(right, Fraction):
        if right.denominator == 1:
            if max(abs(left.numerator), left.denominator) == 1:
                # 0, 1 and -1 do not grow, whatever the exponent; Python would try to convert a huge exponent.
                if left == 0:
                    if right < 0:
                        raise ZeroDivisionError
                    return Fraction(0 if right else 1)
                return Fraction(-1 if left < 0 and right.numerator % 2 else 1)
            # Checked before computing: the result has about exponent x log2(base) bits.
            if abs(right.numerator) * math.log2(max(abs(left.numerator), left.denominator)) + 1 > MAX_BITS:
                raise ValueError(f"exact power would exceed {MAX_BITS} bits; use a float base (write 2.0 for 2) or a smaller exponent")
            return operator.pow(left, right)
    elif isinstance(left, float) and isinstance(right, float):
        return operator.pow(left, right)
    base, exponent = approximate(left), approximate(right)  # a fractional power, or one float operand: not exact
    if base < 0 and other_side(right, exponent) is not None:
        # The sign of a negative base's power turns on whether the exponent is odd, even or not whole, and the
        # float nearest this exponent is a different number.
        raise ValueError("a negative base needs an exponent that a float holds exactly; this exact exponent is not one")
    result = operator.pow(base, exponent)
    if isinstance(result, float) and base != 0 and abs(result) < sys.float_info.min:
        # A power of a non-zero base is never zero: this one is too small for a float.
        raise ValueError("this power is too small for a float; keep the arithmetic exact or rescale")
    if isinstance(result, float):
        for moved in ((other_side(left, base), exponent), (base, other_side(right, exponent))):
            if None not in moved:
                try:
                    steady(result, operator.pow(*moved))
                except (OverflowError, ZeroDivisionError):
                    steady(result, None)
    return result


def total(*values):
    """Sum that checks the size budget after every addition, so many large fractions cannot build a huge denominator."""
    result = Fraction(0)
    for value in values:
        result = bounded(combined(operator.add, result, value))
    return result


def mean(*values):
    if not values:
        raise ValueError("mean needs at least one value")
    return bounded(combined(operator.truediv, total(*values), Fraction(len(values))))


def median(*values):
    if not values:
        raise ValueError("median needs at least one value")
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return bounded(combined(operator.truediv, bounded(combined(operator.add, ordered[middle - 1], ordered[middle])), Fraction(2)))


def square_root(value):
    """An exact argument goes straight to the correctly rounded square root of the ratio, so its size never passes
    through a float first: sqrt(1/2**2000) is 2**-1000, not 0.0."""
    if isinstance(value, Fraction):
        if value < 0:
            raise ValueError("sqrt is not defined for a negative value")
        return root_of_ratio(value.numerator, value.denominator) if value else 0.0
    return math.sqrt(value)


def near_one(value):
    return isinstance(value, Fraction) and value > 0 and abs(value - 1) < Fraction(1, 2)


def natural_log(value):
    """An exact value near 1 becomes 1.0 as a float and its logarithm 0.0, so the part beyond 1 is taken exactly
    and given to log1p instead."""
    if near_one(value):
        return math.log1p(approximate(value - 1))
    return math.log(approximate(value))


def log(value, base=None):
    return natural_log(value) if base is None else natural_log(value) / natural_log(base)


def log_to(value, base_log, plain):
    return natural_log(value) / base_log if near_one(value) else plain(approximate(value))


def root_of_ratio(n, d):
    """The float nearest the square root of n/d. CPython's statistics._float_sqrt_of_frac: an integer square root
    kept to 109 bits and rounded to odd, so the single final rounding is correct and a tiny or huge ratio never
    passes through a float."""
    def rounded_to_odd(n, d):
        root = math.isqrt(n // d)
        return root | (root * root * d != n)
    q = (n.bit_length() - d.bit_length() - 109) // 2
    result = float(rounded_to_odd(n, d << 2 * q) << q) if q >= 0 else rounded_to_odd(n << -2 * q, d) / (1 << -q)
    if abs(result) < sys.float_info.min:  # the same strict rule as approximate()
        raise ValueError("an exact value is too small for a float; keep the arithmetic exact or rescale")
    return result


def deviation(sample, values):
    """Standard deviation with every exact step (mean, squared distances, variance) inside the size budget;
    the analyzer binary's calc takes the same steps, so both refuse the same inputs."""
    if len(values) < 1 + sample:
        raise ValueError(f"needs at least {1 + sample} values")
    data = [bounded(Fraction(value)) for value in values]
    centre = mean(*data)
    squares = Fraction(0)
    for value in data:
        distance = bounded(value - centre)
        squares = bounded(squares + bounded(distance * distance))
    variance = bounded(squares / (len(data) - sample))
    return root_of_ratio(variance.numerator, variance.denominator) if variance else 0.0


def rounded(value, digits=None):
    """round(x) is a whole number, exact for a float too; round(x, n) keeps the kind of x."""
    if digits is None:
        return round(value)
    if not isinstance(digits, Fraction) or digits.denominator != 1 or abs(digits) > MAX_ROUND_DIGITS:
        raise ValueError(f"round takes a whole number of digits between -{MAX_ROUND_DIGITS} and {MAX_ROUND_DIGITS}")
    return round(value, int(digits))


def extreme(pick, values):
    if not values:
        raise ValueError("needs at least one value")
    return pick(values)


def number(node):
    """Value of one expression node; integers become exact fractions so division does not lose precision."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return bounded(node.value)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
        return bounded(power(number(node.left), number(node.right)))
    if isinstance(node, ast.BinOp) and type(node.op) in BINARY:
        # Both operands are within the budget, so the product is at most twice it before this check.
        return bounded(combined(BINARY[type(node.op)], number(node.left), number(node.right)))
    if isinstance(node, ast.UnaryOp) and type(node.op) in UNARY:
        return UNARY[type(node.op)](number(node.operand))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FUNCTIONS and not node.keywords:
        try:
            result = FUNCTIONS[node.func.id](*(number(argument) for argument in node.args))
        except TypeError as error:  # wrong argument count or kind
            raise ValueError(f"{node.func.id}: {error}") from None
        return bounded(result)
    raise ValueError(f"only numbers, arithmetic operators and {sorted(FUNCTIONS)} are accepted here; {BINARY_ONLY_MESSAGE}")


def parse(expression):
    """The expression's syntax tree, refused when it is not arithmetic or is larger than the input budget."""
    if len(expression) > MAX_CHARS:
        raise ValueError(f"expression is longer than {MAX_CHARS} characters")
    try:
        tree = ast.parse(expression.strip(), mode="eval").body
    except SyntaxError as error:
        raise ValueError(f"not an arithmetic expression: {error.msg}") from None
    except (ValueError, RecursionError, MemoryError) as error:  # an integer literal too long to read, or nesting too deep
        raise ValueError(f"not an arithmetic expression: {error}") from None
    # A part is one number or one operation; the analyzer binary's calc counts the same way.
    if sum(isinstance(node, (ast.Constant, ast.BinOp, ast.UnaryOp, ast.Call, ast.Compare)) for node in ast.walk(tree)) > MAX_NODES:
        raise ValueError(f"expression has more than {MAX_NODES} parts")
    return tree


def value_of(node):
    """Value of a parsed expression: an exact int or Fraction when the inputs allow it, otherwise a finite float.
    The one place errors are translated, so no arithmetic failure leaves this module as anything but ValueError."""
    try:
        value = number(node)
    except ZeroDivisionError:
        raise ValueError("division by zero") from None
    except OverflowError:
        raise ValueError("result is outside float range") from None
    except (ArithmeticError, TypeError, RecursionError, MemoryError) as error:
        raise ValueError(f"cannot evaluate: {error or type(error).__name__}") from None
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("result is not a finite real number")
    return int(value) if isinstance(value, Fraction) and value.denominator == 1 else value


def evaluate(expression):
    return value_of(parse(expression))


def check(expression, tolerance=TOLERANCE):
    """(passed, left value, right value) for a single comparison `LEFT op RIGHT`."""
    node = parse(expression)
    if not (isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in COMPARE):
        raise ValueError("a check is one comparison, for example \"2 + 2 == 4\"")
    left, right = value_of(node.left), value_of(node.comparators[0])
    inexact = isinstance(left, float) or isinstance(right, float)
    try:
        if inexact and isinstance(node.ops[0], (ast.Eq, ast.NotEq)):
            equal = math.isclose(approximate(left), approximate(right), rel_tol=tolerance, abs_tol=tolerance)
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
    # An expression may begin with a minus sign ("-5 + 3"); a leading space stops argparse reading it as an option.
    options = {"--check", "--tolerance", "-h", "--help"}
    argv = sys.argv[1:] if argv is None else list(argv)
    if BINARY_ONLY & set(argv):
        print(json.dumps({"schema": "code-audit.calc.v1", "status": "invalid", "error": BINARY_ONLY_MESSAGE}))
        return 2
    args = parser.parse_args([argument if not argument.startswith("-") or argument.split("=")[0] in options else " " + argument
                              for argument in argv])
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
