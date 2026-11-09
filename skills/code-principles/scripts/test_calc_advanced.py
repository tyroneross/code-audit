#!/usr/bin/env python3
"""Tests for the analyzer binary's calc beyond plain arithmetic: names, equations, derivatives, integrals,
expansion, finance functions and linear programs.

Three kinds of evidence, kept apart:
- fixed cases whose answers were worked by hand or come from a published example (numpy-financial's documentation);
- comparison with independent methods written here in exact fractions (simulating a loan period by period,
  enumerating the corners of a linear program, a grid search for whole-number programs);
- comparison with SymPy, NumPy and mpmath on seeded random inputs, skipped when they are not installed.
"""
import itertools
import json
import math
import random
import shutil
import subprocess
import time
import unittest
from fractions import Fraction
from pathlib import Path

import complexity

BINARY = complexity.native_binary()
MANIFEST = Path(__file__).resolve().parents[3] / "runtime" / "complexity" / "Cargo.toml"
try:
    import mpmath
    import numpy
    import sympy
    ORACLES = True
except ImportError:  # the random comparisons need them; the fixed cases do not
    ORACLES = False


def calc(*arguments):
    done = subprocess.run([str(BINARY), "calc", *arguments], capture_output=True, text=True, timeout=60)
    return done.returncode, json.loads(done.stdout)


def number(shown):
    """A reported value as a Fraction when exact, else a float."""
    if isinstance(shown, dict):
        return Fraction(shown["exact"])
    return Fraction(shown) if isinstance(shown, int) else shown


def value(expression, *more):
    code, report = calc(expression, *more)
    assert code == 0, report
    return number(report["results"][0]["value"])


def close(a, b, tolerance=1e-9):
    return math.isclose(float(a), float(b), rel_tol=tolerance, abs_tol=tolerance)


@unittest.skipUnless(BINARY, "analyzer binary not built")
class NamesAndFunctionsTests(unittest.TestCase):
    def test_names_are_set_in_order_and_stay_exact(self):
        self.assertEqual(value("price * qty", "--set", "price=19/2", "--set", "qty=4"), 38)
        self.assertEqual(value("total / 3", "--set", "a=1/3", "--set", "total=a + 2/3"), Fraction(1, 3))
        self.assertTrue(close(value("2 * pi"), 2 * math.pi) and close(value("e ** 2"), math.e ** 2))

    def test_a_name_without_a_value_and_a_bad_name_are_refused(self):
        for arguments in (["x + 1"], ["1", "--set", "pi=3"], ["1", "--set", "2x=3"], ["1", "--set", "x"], ["1", "--frobnicate"], ["1", "--set"]):
            code, report = calc(*arguments)
            self.assertEqual((code, report["status"]), (2, "invalid"), arguments)

    def test_an_exact_value_too_small_for_a_float_is_refused_not_zeroed(self):
        self.assertTrue(math.isclose(value("sqrt(1/2**2000)"), 2.0 ** -1000, rel_tol=1e-15))
        self.assertTrue(math.isclose(value("log(1 + 1/2**60)"), 8.673617379884035e-19, rel_tol=1e-15))
        for expression in ("(1/2**2000)**(1/2)", "exp(1/2**2000) - 1", "sin(1/2**2000)", "tiny * 1e300"):
            self.assertEqual(calc(expression, "--set", "tiny=1/2**2000")[0], 2, expression)

    def test_added_functions(self):
        for expression, expected in (("exp(1)", math.e), ("sin(pi/2)", 1.0), ("cos(0)", 1.0), ("tan(pi/4)", 1.0), ("exp(0)", 1.0)):
            self.assertTrue(close(value(expression), expected), expression)
        self.assertEqual(calc("exp(1000)")[0], 2)  # outside float range, refused


@unittest.skipUnless(BINARY, "analyzer binary not built")
class SolveTests(unittest.TestCase):
    def solutions(self, *arguments):
        code, report = calc(*arguments)
        self.assertEqual(code, 0, report)
        return report["solve"]

    def roots(self, equation, *more):
        return [(number(s["values"]["x"]), s["exact"]) for s in self.solutions("--solve", equation, *more)["solutions"]]

    def test_rational_roots_are_exact_and_repeated_roots_appear_once(self):
        self.assertEqual(self.roots("x**2 - 5*x + 6 == 0"), [(2, True), (3, True)])
        self.assertEqual(self.roots("2*x + 1 = 7"), [(3, True)])
        self.assertEqual(self.roots("(3*x - 1)**2 * (x + 4)**3 == 0"), [(-4, True), (Fraction(1, 3), True)])
        self.assertEqual(self.roots("x**3 == x"), [(-1, True), (0, True), (1, True)])

    def test_irrational_roots_are_floats_marked_not_exact(self):
        (low, low_exact), (high, high_exact) = self.roots("x**2 == 2")
        self.assertTrue(close(low, -math.sqrt(2), 1e-15) and close(high, math.sqrt(2), 1e-15))
        self.assertFalse(low_exact or high_exact)
        # x**5 - x - 1 has one real root (no formula in radicals); the plastic-like constant 1.1673039782614187
        self.assertTrue(close(self.roots("x**5 - x - 1 == 0")[0][0], 1.1673039782614187, 1e-15))

    def test_no_real_root_identity_and_contradiction(self):
        self.assertEqual(self.solutions("--solve", "x**2 + 1 == 0")["solutions"], [])
        self.assertIn("every value", self.solutions("--solve", "2*(x + 1) == 2*x + 2")["note"])
        self.assertIn("no value", self.solutions("--solve", "x + 1 == x")["note"])

    def test_float_coefficients_never_report_an_exact_root(self):
        (root, exact), = self.roots("0.5*x == 1")
        self.assertEqual((root, exact), (2.0, False))

    def test_a_root_floats_cannot_hold_or_tell_apart_is_refused_not_rounded(self):
        # The roots are +-sqrt(2) * 2**-1100: rounding them to 0.0 would report a number that is not a root.
        code, report = calc("--solve", "x**2 == 2/2**2200")
        self.assertEqual(code, 2, report)
        self.assertIn("too small for a float", report["error"])
        # Two irrational roots 2**-80 apart share one float.
        code, report = calc("--solve", "(x**2 - 2)*(x**2 - 2 - 1/2**80) == 0")
        self.assertEqual(code, 2, report)
        self.assertIn("closer together than floats", report["error"])
        # Two rational roots that close are both reported, exactly.
        found = self.roots("(x - 1)*(x - 1 - 1/2**70) == 0")
        self.assertEqual(found, [(1, True), (1 + Fraction(1, 2**70), True)])

    def test_a_float_anywhere_in_the_equation_keeps_the_answer_inexact(self):
        for equation in ("(x + 0.0)**0 + x == 1", "x == rate(10.0, -10, 100, 0)", "x + 0.5 - 0.5 == 3", "x*(1 + 0.0) == 3"):
            (root, exact), = self.roots(equation)
            self.assertFalse(exact, equation)
            self.assertIsInstance(root, float, equation)

    def test_linear_systems_are_exact_and_singular_ones_are_named(self):
        solved = self.solutions("--solve", "2*x + 3*y == 7", "--solve", "x - y == 1")
        self.assertEqual({k: number(v) for k, v in solved["solutions"][0]["values"].items()}, {"x": 2, "y": 1})
        solved = self.solutions("--solve", "x + y + z == 6", "--solve", "2*y + 5*z == -4", "--solve", "2*x + 5*y - z == 27")
        self.assertEqual({k: number(v) for k, v in solved["solutions"][0]["values"].items()}, {"x": 5, "y": 3, "z": -2})
        solved = self.solutions("--solve", "x/3 + y/7 == 1", "--solve", "x - y == 1/2")
        self.assertEqual({k: number(v) for k, v in solved["solutions"][0]["values"].items()}, {"x": Fraction(9, 4), "y": Fraction(7, 4)})
        self.assertIn("contradict", self.solutions("--solve", "x + y == 1", "--solve", "x + y == 2")["note"])
        self.assertIn("infinitely many", self.solutions("--solve", "x + y == 1", "--solve", "2*x + 2*y == 2")["note"])
        self.assertEqual(calc("--solve", "x*y == 1", "--solve", "x + y == 2")[0], 2)  # not linear

    def test_a_float_answer_too_small_for_a_float_is_refused(self):
        code, report = calc("--solve", "1e200*x + y == 1e-200", "--solve", "y == 0")  # x is 1e-400
        self.assertEqual(code, 2, report)
        self.assertIn("too small for a float", report["error"])

    def test_other_equations_need_a_bracket_and_a_jump_is_not_a_root(self):
        solved = self.solutions("--solve", "cos(x) == x", "--between", "0", "1")
        self.assertTrue(close(number(solved["solutions"][0]["values"]["x"]), 0.7390851332151607, 1e-15))  # the Dottie number
        self.assertEqual(calc("--solve", "cos(x) == x")[0], 2)  # no bracket
        self.assertEqual(calc("--solve", "cos(x) == x", "--between", "2", "3")[0], 2)  # no sign change
        self.assertEqual(calc("--solve", "tan(x) == 0", "--between", "1", "2")[0], 2)  # the sign changes at a pole
        self.assertEqual(calc("--solve", "1/x == 0", "--between", "-1", "1")[0], 2)

    def test_between_limits_polynomial_roots(self):
        self.assertEqual(self.roots("x**3 == x", "--between", "1/2", "2"), [(1, True)])

    def test_between_is_compared_exactly(self):
        self.assertEqual(self.roots("x == 1 + 1/2**60", "--between", "0", "1"), [])  # just past the upper bound
        self.assertEqual(self.roots("x == 1 + 1/2**60", "--between", "0", "2"), [(1 + Fraction(1, 2**60), True)])
        self.assertEqual(self.roots("x**2 == 4", "--between", "2", "3"), [(2, True)])  # a bound itself counts

    def test_a_bound_beside_an_irrational_root_is_decided_exactly(self):
        # sqrt(2) = 1.41421356237309504880...: the first bound is above it, the second below. The float nearest
        # sqrt(2) is above both, so comparing the rounded root would get the first one wrong.
        self.assertEqual(len(self.roots("x**2 == 2", "--between", "0", "14142135623730951/10000000000000000")), 1)
        self.assertEqual(self.roots("x**2 == 2", "--between", "0", "14142135623730950/10000000000000000"), [])
        self.assertEqual(self.roots("(x - 1)*(x - 2)*(x - 3) == 0", "--between", "1", "3"), [(1, True), (2, True), (3, True)])
        self.assertEqual(self.roots("(x - 1)*(x - 2)*(x**2 - 2) == 0", "--between", "1", "2")[0], (1, True))
        self.assertEqual(len(self.roots("(x - 1)*(x - 2)*(x**2 - 2) == 0", "--between", "1", "2")), 3)

    def test_an_underflow_or_a_flat_zero_is_not_a_root(self):
        self.assertEqual(calc("exp(-1000)")[0], 2)  # exp is never zero; 0.0 would be an underflow
        for arguments in (["--solve", "exp(-x) == 0", "--between", "1000", "1001"], ["--solve", "0*sin(x) == 0", "--between", "1", "2"],
                          ["--solve", "2.0**(-x) == 0", "--between", "2000", "2001"]):
            code, report = calc(*arguments)
            self.assertEqual((code, report["status"]), (2, "invalid"), (arguments, report))

    def test_set_names_are_constants_in_an_equation(self):
        self.assertEqual(self.roots("a*x == b", "--set", "a=4", "--set", "b=10"), [(Fraction(5, 2), True)])
        self.assertEqual(calc("--solve", "2 + 2 == 4")[0], 2)  # nothing to solve for


@unittest.skipUnless(BINARY, "analyzer binary not built")
class CalculusTests(unittest.TestCase):
    def test_polynomial_derivative_and_integral_are_exact(self):
        code, report = calc("--derivative", "x**3 + 2*x", "--at", "2")
        self.assertEqual((code, report["derivative"]["expression"], report["derivative"]["value"]), (0, "3*x**2 + 2", 14))
        code, report = calc("--integral", "x**2", "--from", "0", "--to", "1")
        self.assertEqual((number(report["integral"]["value"]), report["integral"]["antiderivative"]), (Fraction(1, 3), "1/3*x**3"))
        code, report = calc("--integral", "3*t**2 - t/2", "--from", "1", "--to", "-2")  # reversed bounds: (t**3 - t**2/4) from 1 to -2
        self.assertEqual(number(report["integral"]["value"]), Fraction(-39, 4))
        code, report = calc("--integral", "6*x")
        self.assertEqual(report["integral"]["antiderivative"], "3*x**2")

    def test_rule_based_derivative_matches_hand_results_and_its_own_check(self):
        for expression, at, expected in (("sin(x)", "0", 1.0), ("exp(2*x)", "0", 2.0), ("log(x)", "4", 0.25), ("sqrt(x)", "4", 0.25),
                                         ("x**x", "1", 1.0), ("2**x", "0", math.log(2)), ("tan(x)", "0", 1.0), ("1/x", "2", -0.25),
                                         ("log(x, 10)", "1", 1 / math.log(10)), ("cos(x)**2", "pi/4", -1.0), ("log2(x)", "1", 1 / math.log(2))):
            code, report = calc("--derivative", expression, "--at", at)
            self.assertEqual(code, 0, report)
            self.assertTrue(close(number(report["derivative"]["value"]), expected), (expression, report))
            self.assertTrue(report["derivative"]["agrees"], (expression, report))

    def test_a_float_dropped_by_a_rule_still_marks_the_value(self):
        code, report = calc("--derivative", "0*exp(0.5*x) + sin(x)*0 + x", "--at", "2")  # the rules reduce this to 1
        self.assertEqual(report["derivative"]["expression"], "1")
        self.assertIsInstance(report["derivative"]["value"], float)
        code, report = calc("--derivative", "sin(x)*0 + x", "--at", "2")
        self.assertIsInstance(report["derivative"]["value"], int)

    def test_printed_derivative_parses_back_to_the_same_value(self):
        for expression in ("sin(x)*exp(2*x)", "(x**2 + 1)/(x - 3)", "sqrt(1 + x**2)", "x**x", "log(x)**3 - 2**x", "-(x - 1)**-2"):
            code, report = calc("--derivative", expression, "--at", "0.7")
            self.assertEqual(code, 0, report)
            again = value(report["derivative"]["expression"], "--set", "x=0.7")
            self.assertTrue(close(again, number(report["derivative"]["value"]), 1e-12), (expression, report))

    def test_what_has_no_rule_is_refused(self):
        for expression in ("abs(x)", "x // 2", "x % 2", "floor(x)", "max(x, 1)"):
            self.assertEqual(calc("--derivative", expression)[0], 2, expression)
        self.assertEqual(calc("--derivative", "x*y")[0], 2)  # two names: which one varies?
        code, report = calc("--derivative", "x*y", "--var", "y")
        self.assertEqual((code, report["status"]), (2, "invalid"))  # x still has no value
        code, report = calc("--derivative", "a*y**2", "--var", "y", "--set", "a=3")
        self.assertEqual(report["derivative"]["expression"], "6*y")

    def test_numeric_integral_matches_known_values(self):
        for expression, low, high, expected in (("exp(-x**2)", "0", "1", 0.7468241328124271), ("sin(x)", "0", "pi", 2.0),
                                                ("1/x", "1", "e", 1.0), ("sqrt(1 - x**2)", "0", "1", math.pi / 4), ("exp(x)", "1", "0", 1 - math.e)):  # the last runs high to low
            code, report = calc("--integral", expression, "--from", low, "--to", high)
            self.assertEqual(code, 0, report)
            self.assertTrue(close(report["integral"]["value"], expected), (expression, report))
            self.assertTrue(report["integral"]["converged"])

    def test_a_narrow_peak_between_sample_points_is_found(self):
        # A single pass of the quadrature rule reported 3.4e-9 for this and called it converged.
        # Exactly: (atan(9e5) + atan(1e5)) / 1e6.
        code, report = calc("--integral", "1/(1 + 1000000000000*(x - 0.1)**2)", "--from", "0", "--to", "1")
        expected = (math.atan(9e5) + math.atan(1e5)) / 1e6
        self.assertTrue(math.isclose(report["integral"]["value"], expected, rel_tol=1e-9), (report, expected))
        self.assertTrue(report["integral"]["converged"])
        code, report = calc("--integral", "1/x", "--from", "0", "--to", "1")  # diverges: reported as not converged, exit 1
        self.assertEqual((code, report["integral"]["converged"]), (1, False))

    def test_a_flat_narrow_peak_between_quadrature_points_is_found_by_the_scan(self):
        # A plateau of height 1 and width 2e-5 on top of 1: every quadrature sample missed it and the answer was
        # 0.9999999999999967, "converged". The area of 1/(1 + t**16) over the line is (pi/8)/sin(pi/16).
        code, report = calc("--integral", "1 + 1/(1 + (100000*(x - 0.341378011))**16)", "--from", "0", "--to", "1")
        expected = 1 + (math.pi / 8) / math.sin(math.pi / 16) / 100000
        self.assertTrue(math.isclose(report["integral"]["value"], expected, rel_tol=1e-10), (report, expected))
        self.assertTrue(report["integral"]["converged"])
        self.assertGreaterEqual(report["integral"]["scan_points"], 4096)

    def test_a_costly_constant_is_worked_out_once(self):
        # irr(-1, 2) is 1. Recomputed at each sample point this integral took over ten seconds.
        started = time.monotonic()
        code, report = calc("--integral", "exp(-x**2) + irr(-1, 2)", "--from", "0", "--to", "1")
        self.assertTrue(close(report["integral"]["value"], 1.7468241328124271))
        self.assertLess(time.monotonic() - started, 2.0)
        solved = calc("--solve", "sin(x) + irr(-1, 2)/10 == 0", "--between", "3", "4")[1]["solve"]["solutions"][0]["values"]["x"]
        self.assertTrue(close(solved, math.pi + math.asin(0.1)))

    def test_bounds_that_are_one_float_are_refused(self):
        code, report = calc("--integral", "2**60*sin(x)", "--from", "1", "--to", "1 + 1/2**60")  # the answer is sin(1), not 0
        self.assertEqual((code, report["status"]), (2, "invalid"))
        self.assertEqual(calc("--solve", "sin(x) == 0", "--between", "3", "3 + 1/2**60")[0], 2)
        code, report = calc("--integral", "x", "--from", "1", "--to", "1 + 1/2**60")  # a polynomial is integrated exactly
        self.assertEqual(number(report["integral"]["value"]), ((1 + Fraction(1, 2**60)) ** 2 - 1) / 2)

    def test_an_integrand_undefined_inside_the_range_is_refused(self):
        self.assertEqual(calc("--integral", "log(x)", "--from", "-1", "--to", "1")[0], 2)
        self.assertEqual(calc("--integral", "sin(x)")[0], 2)  # no antiderivative is written for a non-polynomial
        self.assertEqual(calc("--integral", "sin(x)", "--from", "0")[0], 2)

    def test_expand(self):
        code, report = calc("--expand", "(x + 1)**3 - x/2")
        self.assertEqual(report["expand"]["polynomial"], "x**3 + 3*x**2 + 5/2*x + 1")
        self.assertEqual([number(c) for c in report["expand"]["coefficients_low_to_high"]], [1, Fraction(5, 2), 3, 1])
        self.assertEqual(calc("--expand", "(x + 1)**65")[0], 2)  # above the degree budget
        self.assertEqual(calc("--expand", "sin(x)")[0], 2)
        self.assertEqual(calc("--expand", "(x - x)**1000000")[0], 2)  # refused, not looped over


@unittest.skipUnless(BINARY, "analyzer binary not built")
class FinanceTests(unittest.TestCase):
    def test_numpy_financial_documented_examples(self):
        # Values printed in numpy-financial's documentation (commit 031ed55), with its argument order except where noted.
        for expression, expected, tolerance in (
                ("fv(0.05/12, 10*12, -100, -100)", 15692.92889433575, 1e-13),
                ("pmt(0.075/12, 12*15, 200000)", -1854.0247200054619, 1e-13),
                ("pmt(0, 10, 100, -20)", -8.0, 1e-13),
                ("nper(0.07/12, -150, 8000)", 64.07334877066185, 1e-9),
                ("npv(0.08, -40000, 5000, 8000, 12000, 30000)", 3065.2226681795255, 1e-10),
                ("irr(-100, 39, 59, 55, 20)", 0.28095, 1e-4),
                ("irr(-100, 0, 0, 74)", -0.0955, 1e-3),
                ("irr(-100, 100, 0, -7)", -0.0833, 1e-3),
                ("irr(-100, 100, 0, 7)", 0.06206, 1e-4),
                ("irr(-5, 10.5, 1, -8, 1)", 0.0886, 1e-3),
                ("irr(-250000, 100000, 150000, 200000, 250000, 300000)", 0.5672303344358536, 1e-12),
                ("mirr(0.10, 0.12, -100, 50, -60, 70)", -0.03909366594356467, 1e-13)):  # numpy: mirr(values, finance, reinvest)
            self.assertTrue(close(value(expression), expected, tolerance), (expression, value(expression)))

    def test_exact_inputs_give_exact_results(self):
        self.assertEqual(value("fv(5/100, 2, 0, -100)"), Fraction(441, 4))  # 100 * 1.05**2
        self.assertEqual(value("npv(1/10, -100, 110)"), 0)
        self.assertEqual(value("irr(-100, 110)"), Fraction(1, 10))
        self.assertEqual(value("irr(-100, 0, 121)"), Fraction(1, 10))
        self.assertEqual(value("pv(1/10, 1, 0, 110)"), -100)
        self.assertEqual(value("pmt(0, 10, 100, -20)"), -8)
        self.assertEqual(value("rate(10, -10, 100, 0)"), 0)  # ten payments of 10 repay 100 at no interest

    def test_a_float_argument_always_gives_a_float_result(self):
        for exact, approximate in (("nper(0, -10, 100)", "nper(0.0, -10, 100)"), ("rate(10, -10, 100, 0)", "rate(10.0, -10, 100, 0)"),
                                   ("fv(0, 3, -10, 0)", "fv(0, 3, -10.0, 0)"), ("npv(0, 1, 2)", "npv(0, 1.0, 2)"), ("irr(-100, 110)", "irr(-100.0, 110)")):
            self.assertNotIsInstance(value(exact), float, exact)
            self.assertIsInstance(value(approximate), float, approximate)
            self.assertTrue(close(value(exact), value(approximate)))

    def test_future_value_matches_a_period_by_period_simulation(self):
        rng = random.Random(41)
        for _ in range(60):
            rate, periods = Fraction(rng.randint(-20, 30), 400), rng.randint(0, 24)
            payment, present, when = Fraction(rng.randint(-500, 500)), Fraction(rng.randint(-5000, 5000)), rng.randint(0, 1)
            balance = present
            for _ in range(periods):  # the definition, not the closed form
                balance = (balance + payment) * (1 + rate) if when else balance * (1 + rate) + payment
            expression = f"fv({rate}, {periods}, {payment}, {present}, {when})"
            self.assertEqual(value(expression), -balance, expression)

    def test_float_rates_match_exact_fractions_even_when_tiny(self):
        # The textbook formula subtracts nearly equal numbers at a small rate: fv(1e-12, 10, -100, 0) came out as
        # 1000.0889 where the true value is 1000.0000000045. The oracle is the same formula in exact fractions.
        rng = random.Random(89)
        for _ in range(120):
            rate = rng.choice([1e-15, 1e-12, 3e-9, 1e-6, 0.004, 0.05, 0.35, -0.02, -1e-10])
            periods, payment, present, when = rng.randint(1, 60), rng.randint(-900, 900), rng.randint(-90000, 90000), rng.randint(0, 1)
            r = Fraction(rate)
            grown = (1 + r) ** periods
            factor = (1 + r * when) * (grown - 1) / r
            cases = {f"fv({rate!r}, {periods}, {payment}, {present}, {when})": -(present * grown + payment * factor),
                     f"pv({rate!r}, {periods}, {payment}, {present}, {when})": -(present + payment * factor) / grown,
                     f"pmt({rate!r}, {periods}, {present}, {payment}, {when})": -(payment + present * grown) / factor}
            for expression, expected in cases.items():
                if expected != 0:
                    self.assertTrue(math.isclose(value(expression), float(expected), rel_tol=1e-11), (expression, value(expression), float(expected)))
        # Ten payments repay 1000 plus a sliver of interest; the expected value is the formula evaluated to 50 digits.
        self.assertTrue(math.isclose(value("nper(1e-12, -100, 1000)"), 10.000000000055, rel_tol=1e-14))

    def test_each_function_inverts_the_others(self):
        rng = random.Random(43)
        for _ in range(40):
            rate, periods = rng.choice([0.004, 0.01, 0.035, 0.08, 0.15]), rng.randint(3, 40)
            payment, present, when = -rng.randint(50, 900), rng.randint(1000, 90000), rng.randint(0, 1)
            future = value(f"fv({rate}, {periods}, {payment}, {present}, {when})")
            self.assertTrue(close(value(f"pv({rate}, {periods}, {payment}, {future!r}, {when})"), present, 1e-9))
            self.assertTrue(close(value(f"pmt({rate}, {periods}, {present}, {future!r}, {when})"), payment, 1e-9))
            self.assertTrue(close(value(f"nper({rate}, {payment}, {present}, {future!r}, {when})"), periods, 1e-7))
            self.assertTrue(close(value(f"rate({periods}, {payment}, {present}, {future!r}, {when})"), rate, 1e-7), (rate, periods, payment, present, when))

    def test_irr_makes_the_net_present_value_zero_at_any_length(self):
        rng = random.Random(47)
        for periods in (3, 12, 33, 60, 120, 239):  # above 32 periods the bracketed search takes over
            flows = [-rng.randint(50000, 90000)] + [rng.randint(200, 4000) for _ in range(periods)]
            listed = ", ".join(map(str, flows))
            found = value(f"irr({listed})")
            self.assertTrue(abs(float(value(f"npv({found!r}, {listed})"))) < 1e-6 * abs(flows[0]), (periods, found))

    def test_a_rate_near_zero_keeps_its_digits(self):
        # sqrt(1 + 2**-60) - 1: found as a root in the rate itself, not as a growth factor near one minus one.
        self.assertTrue(math.isclose(value("irr(-1, 0, 1 + 1/2**60)"), 4.336808689942018e-19, rel_tol=1e-12))
        self.assertEqual(value("irr(-1, 2, 0)"), 1)  # a closing flow of zero changes nothing

    def test_long_flows_are_solved_exactly_too(self):
        # Thirty-four flows whose sum exceeds zero by 2**-60: floats cannot hold the difference. Expected value from
        # the closed form (1 + 2**-60)**(1/33) - 1, which is 2**-60/33 to first order.
        flows = ", ".join(["-1"] + ["0"] * 32 + ["1 + 1/2**60"])
        self.assertTrue(math.isclose(value(f"irr({flows})"), 2.6283689029951623e-20, rel_tol=1e-12))
        self.assertEqual(value("irr(" + ", ".join(["-100"] + ["0"] * 39 + ["100"]) + ")"), 0)  # break-even after 40 periods, exactly
        code, report = calc("irr(" + ", ".join(["-1", "3", "-3"] * 12) + ")")  # many sign changes over 35 periods: refused, not guessed
        self.assertEqual(code, 2, report)

    def test_rate_is_confirmed_against_the_exact_inputs(self):
        # One period from -1 to 1 + 2**-60: the rate is 2**-60. In floats the future value is 1.0 and the iteration
        # settled on 2.8e-17; the rate is now polished with the equation evaluated exactly.
        self.assertTrue(math.isclose(value("rate(1, 0, -1, 1 + 1/2**60)"), 2.0 ** -60, rel_tol=1e-12))
        self.assertTrue(math.isclose(value("rate(10, 0, -3500, 10000)"), (10000 / 3500) ** 0.1 - 1, rel_tol=1e-13))
        self.assertTrue(math.isclose(value("rate(2, 0, -100, 121)"), 0.1, rel_tol=1e-13))  # 100 * 1.1**2

    def test_bad_arguments_are_refused(self):
        for expression in ("irr(100, 110)", "irr(-100)", "fv(0.05, 10)", "pv(0.05, 10, -100, 0, 2)", "mirr(0.1, 0.1, 100, 50)", "npv(-1, 100, 100)",
                           "nper(0.05, 10, -1000)", "npv(0.05)", "rate(10, 100, 1000, 5000)"):
            self.assertEqual(calc(expression)[0], 2, expression)


def corners(objective, constraints, count):
    """Every corner of a linear program, by solving each choice of `count` constraints as equalities in fractions."""
    best = None
    for chosen in itertools.combinations(constraints, count):
        rows = [[Fraction(a) for a in row] + [Fraction(bound)] for row, _, bound in chosen]
        rank = 0
        for column in range(count):  # Gauss-Jordan
            pivot = next((r for r in range(rank, count) if rows[r][column] != 0), None)
            if pivot is None:
                break
            rows[rank], rows[pivot] = rows[pivot], rows[rank]
            rows[rank] = [v / rows[rank][column] for v in rows[rank]]
            for r in range(count):
                if r != rank and rows[r][column] != 0:
                    rows[r] = [a - rows[r][column] * b for a, b in zip(rows[r], rows[rank])]
            rank += 1
        if rank < count:
            continue
        point = [rows[i][count] for i in range(count)]
        if all((sum(a * x for a, x in zip(row, point)) <= bound) if op == "<=" else (sum(a * x for a, x in zip(row, point)) >= bound) for row, op, bound in constraints):
            score = sum(a * x for a, x in zip(objective, point))
            best = score if best is None else max(best, score)
    return best


def program(names, objective, constraints):
    sides = [" + ".join(f"{a}*{n}" for a, n in zip(row, names)) + f" {op} {bound}" for row, op, bound in constraints]
    return [" + ".join(f"{a}*{n}" for a, n in zip(objective, names))] + [argument for side in sides for argument in ("--subject", side)]


@unittest.skipUnless(BINARY, "analyzer binary not built")
class OptimizeTests(unittest.TestCase):
    def test_textbook_program_is_exact_and_proved(self):
        code, report = calc("--maximize", "3*x + 2*y", "--subject", "x + y <= 4", "--subject", "x + 3*y <= 6", "--subject", "x <= 3", "--subject", "x >= 0", "--subject", "y >= 0")
        answer = report["optimize"]
        self.assertEqual((code, answer["outcome"], answer["objective"], answer["values"], answer["exact"], answer["proved_optimal"]), (0, "optimal", 11, {"x": 3, "y": 1}, True, True))
        code, report = calc("--minimize", "2*x + 3*y", "--subject", "x + y >= 10", "--subject", "x <= 6", "--subject", "y >= 1", "--subject", "x >= 0")
        self.assertEqual((report["optimize"]["objective"], report["optimize"]["values"]), (24, {"x": 6, "y": 4}))

    def test_fractional_corner_is_reported_as_a_fraction(self):
        code, report = calc("--maximize", "x + y", "--subject", "2*x + y <= 4", "--subject", "x + 3*y <= 5", "--subject", "x >= 0", "--subject", "y >= 0")
        answer = report["optimize"]
        self.assertEqual(({k: number(v) for k, v in answer["values"].items()}, number(answer["objective"]), answer["proved_optimal"]), ({"x": Fraction(7, 5), "y": Fraction(6, 5)}, Fraction(13, 5), True))

    def test_infeasible_and_unbounded_are_named(self):
        self.assertEqual(calc("--minimize", "x", "--subject", "x >= 2", "--subject", "x <= 1")[1]["optimize"]["outcome"], "infeasible")
        self.assertEqual(calc("--maximize", "x + y", "--subject", "x >= 0", "--subject", "y >= 0")[1]["optimize"]["outcome"], "unbounded")

    def test_whole_number_program(self):
        arguments = ["--maximize", "5*x + 4*y", "--subject", "6*x + 4*y <= 24", "--subject", "x + 2*y <= 6", "--subject", "x >= 0", "--subject", "y >= 0"]
        relaxed = calc(*arguments)[1]["optimize"]
        self.assertEqual(({k: number(v) for k, v in relaxed["values"].items()}, relaxed["objective"]), ({"x": 3, "y": Fraction(3, 2)}, 21))
        whole = calc(*arguments, "--integer", "x,y")[1]["optimize"]
        self.assertEqual((whole["values"], whole["objective"], whole["exact"], whole["proved_optimal"]), ({"x": 4, "y": 0}, 20, True, False))

    def test_a_whole_number_name_must_be_limited_by_the_constraints(self):
        # The solver searches whole numbers inside 32 bits; a limit the caller did not write is never applied silently.
        for arguments in (["--maximize", "x", "--subject", "x <= 3000000000", "--integer", "x"],  # no lower limit
                          ["--maximize", "x", "--subject", "x >= 0", "--integer", "x"],  # no upper limit: the true answer is unbounded
                          ["--maximize", "x", "--subject", "x >= 0", "--subject", "x <= 3000000000", "--integer", "x"],  # beyond the solver's range
                          ["--minimize", "0 - x", "--subject", "x >= 0", "--integer", "x"]):
            code, report = calc(*arguments)
            self.assertEqual((code, report["status"]), (2, "invalid"), arguments)
            self.assertIn("whole-number name x", report["error"])
        code, report = calc("--maximize", "x", "--subject", "x >= 0", "--subject", "2*x <= 7", "--integer", "x")
        self.assertEqual((report["optimize"]["objective"], report["optimize"]["values"]), (3, {"x": 3}))
        code, report = calc("--maximize", "x", "--subject", "x >= 0", "--subject", "x <= 1999999999", "--integer", "x")
        self.assertEqual(report["optimize"]["objective"], 1999999999)

    def test_fractions_reach_the_solver_exactly_and_numbers_too_large_for_it_are_refused(self):
        # A third is not a float; each constraint is scaled to whole numbers first, so the answer is still exact and proved.
        code, report = calc("--maximize", "x/3 + y/7", "--subject", "x/3 + y/5 <= 4/7", "--subject", "x >= 0", "--subject", "y >= 0")
        answer = report["optimize"]
        self.assertEqual((number(answer["objective"]), number(answer["values"]["x"]), answer["proved_optimal"]), (Fraction(4, 7), Fraction(12, 7), True))
        code, report = calc("--maximize", "x/3 + y", "--subject", "x + y <= 4", "--subject", "x >= 0", "--subject", "y >= 0", "--subject", "x <= 3", "--integer", "x,y")
        self.assertEqual((report["optimize"]["objective"], report["optimize"]["values"]), (4, {"x": 0, "y": 4}))
        # 2**60 + 1 and 2**60 are the same float, so the solver cannot see that x is worth more than y. The true optimum is
        # x = 3, y = 1; an answer that cannot be proved is refused, with or without whole numbers.
        big = ["--maximize", "(2**60 + 1)*x + 2**60*y", "--subject", "x + y <= 4", "--subject", "x >= 0", "--subject", "y >= 0", "--subject", "x <= 3"]
        for arguments in (big, big + ["--integer", "x,y"]):
            code, report = calc(*arguments)
            if code == 0:  # accepted only when proved, and then it must be the true optimum
                self.assertEqual((report["optimize"]["proved_optimal"], report["optimize"]["values"]), (True, {"x": 3, "y": 1}))
            else:
                self.assertIn("does not fit a float exactly", report["error"])
        self.assertEqual(calc("--maximize", "x/2**1100", "--subject", "x <= 4", "--subject", "x >= 0")[0], 2)

    def test_a_name_the_objective_ignores_does_not_cost_exactness_or_proof(self):
        # x is free between its limits; the answer is still exact and proved from the one constraint that binds.
        code, report = calc("--minimize", "3*y", "--subject", "x >= -6", "--subject", "x <= 2", "--subject", "y >= -5", "--subject", "y <= 2", "--subject", "-6*y <= 2")
        answer = report["optimize"]
        self.assertEqual((answer["objective"], number(answer["values"]["y"]), answer["exact"], answer["proved_optimal"]), (-1, Fraction(-1, 3), True, True))

    def test_a_whole_number_the_solver_returns_inexactly_is_rebuilt(self):
        # The solver returned w = 0.99999969999992 for this program; the answer is w = 1 and an objective of -26.
        code, report = calc("--maximize", "-2*x - 7*y + 6*z - w", "--subject", "x >= -3", "--subject", "y >= 1", "--subject", "z >= -5", "--subject", "w >= -4",
                            "--subject", "x <= 0", "--subject", "y <= 4", "--subject", "z <= -3", "--subject", "w <= 1", "--subject", "-4/3*x + 8*y - 2*z + 5/3*w >= -2",
                            "--subject", "2*x - y + 2*z >= -17/2", "--subject", "-4*x - 2*y - 6*z - 4*w <= 14", "--integer", "w,x,y,z")
        answer = report["optimize"]
        self.assertEqual((answer["objective"], answer["values"], answer["exact"]), (-26, {"w": 1, "x": 0, "y": 1, "z": -3}, True))

    def test_a_solver_answer_that_cannot_be_confirmed_is_refused(self):
        # The solver returned x = -10, y = 8.99999999 here, which breaks x + y == -1 and the whole-number rule.
        # The true optimum is x = 0, y = -1 with an objective of -1.
        code, report = calc("--maximize", "y - x", "--subject", "x >= -10", "--subject", "y >= -10", "--subject", "999999999*x + 1000000000*y <= -1000000000",
                            "--subject", "x + y == -1", "--integer", "x,y")
        if code == 0:
            self.assertEqual((report["optimize"]["values"], report["optimize"]["objective"], report["optimize"]["exact"]), ({"x": 0, "y": -1}, -1, True))
        else:
            self.assertIn("could not be confirmed", report["error"])

    def test_mixed_whole_and_continuous_names_are_rebuilt_exactly(self):
        code, report = calc("--maximize", "8*x - 4*y - 5*z", "--subject", "x >= -2", "--subject", "y >= -2", "--subject", "z >= 1", "--subject", "x <= 2", "--subject", "y <= 3",
                            "--subject", "z <= 6", "--subject", "x/2 - 3/2*y + 3*z <= 6", "--subject", "2*x - 5/2*y - 6*z <= -7", "--integer", "x,y")
        answer = report["optimize"]
        # Expected value from a separate exact search over every whole x and y with z at the ends of the range left to it.
        self.assertEqual((number(answer["objective"]), {k: number(v) for k, v in answer["values"].items()}, answer["exact"]), (Fraction(59, 12), {"x": 2, "y": 1, "z": Fraction(17, 12)}, True))

    def test_random_programs_match_corner_enumeration(self):
        rng = random.Random(53)
        for _ in range(120):
            count = rng.randint(2, 3)
            names = ["x", "y", "z"][:count]
            constraints = [([int(i == j) for j in range(count)], ">=", 0) for i in range(count)]
            constraints += [([int(i == j) for j in range(count)], "<=", rng.randint(3, 12)) for i in range(count)]  # a box keeps it bounded
            constraints += [([rng.randint(-4, 9) for _ in range(count)], "<=", rng.randint(5, 40)) for _ in range(rng.randint(1, 4))]
            objective = [rng.randint(-5, 9) for _ in range(count)]
            if not any(objective):
                continue
            expected = corners(objective, constraints, count)
            code, report = calc("--maximize", *program(names, objective, constraints))
            answer = report["optimize"]
            self.assertEqual((code, answer["outcome"], answer["exact"]), (0, "optimal", True), (objective, constraints, report))
            self.assertEqual(number(answer["objective"]), expected, (objective, constraints, report))
            point = [number(answer["values"][n]) for n in names]
            self.assertEqual(sum(a * x for a, x in zip(objective, point)), expected)

    def test_random_whole_number_programs_match_a_grid_search(self):
        rng = random.Random(59)
        for _ in range(60):
            limits = [rng.randint(2, 7), rng.randint(2, 7)]
            extra = [([rng.randint(1, 9), rng.randint(1, 9)], "<=", rng.randint(8, 45)) for _ in range(rng.randint(1, 3))]
            objective = [rng.randint(1, 9), rng.randint(1, 9)]
            constraints = [([1, 0], ">=", 0), ([0, 1], ">=", 0), ([1, 0], "<=", limits[0]), ([0, 1], "<=", limits[1])] + extra
            expected = max(objective[0] * x + objective[1] * y for x in range(limits[0] + 1) for y in range(limits[1] + 1)
                           if all(row[0] * x + row[1] * y <= bound for row, _, bound in extra))
            code, report = calc("--maximize", *program(["x", "y"], objective, constraints), "--integer", "x,y")
            self.assertEqual((code, report["optimize"]["objective"]), (0, expected), (objective, constraints, report))

    def test_what_is_not_a_linear_program_is_refused(self):
        for arguments in (["--maximize", "x*y", "--subject", "x <= 1"], ["--maximize", "x", "--subject", "x < 1"], ["--maximize", "x", "--subject", "x**2 <= 1"],
                          ["--maximize", "3", "--subject", "x <= 1"], ["--maximize", "x", "--subject", "x <= 1", "--integer", "q"]):
            self.assertEqual(calc(*arguments)[0], 2, arguments)

    def test_a_constraint_with_nothing_to_choose_is_true_or_makes_the_program_infeasible(self):
        code, report = calc("--maximize", "x", "--subject", "x <= 4", "--subject", "1 <= 2", "--subject", "0*x <= 17")
        self.assertEqual((report["optimize"]["outcome"], report["optimize"]["objective"]), ("optimal", 4))
        code, report = calc("--maximize", "x", "--subject", "x <= 4", "--subject", "x - x >= 1")
        self.assertEqual(report["optimize"]["outcome"], "infeasible")


@unittest.skipUnless(shutil.which("cargo") and MANIFEST.is_file(), "needs cargo and the analyzer source")
class RustUnitTests(unittest.TestCase):
    def test_unit_tests_inside_the_analyzer_pass(self):
        # Checks the command line cannot reach, such as refusing to call a corner optimal when it is not.
        done = subprocess.run(["cargo", "test", "--release", "--offline", "--quiet", "--manifest-path", str(MANIFEST)], capture_output=True, text=True, timeout=600)
        self.assertEqual(done.returncode, 0, done.stdout[-2000:] + done.stderr[-2000:])
        self.assertRegex(done.stdout, r"test result: ok\. [1-9]\d* passed")


@unittest.skipUnless(BINARY, "analyzer binary not built")
class BudgetTests(unittest.TestCase):
    def test_hostile_inputs_end_quickly_with_a_stated_outcome(self):
        nested = "x" + "**x" * 150
        cases = [["--solve", "(x - 1)**64 == 0"], ["--solve", "(x**2 - 2)**16 * (x - 1/3)**4 == 0"], ["--solve", "x**40 == 2"], ["--expand", "((x + 1)**8)**8"],
                 ["--derivative", nested, "--at", "1.01"], ["--derivative", "*".join(["sin(x)"] * 120), "--at", "1"], ["--integral", "sin(1/x)", "--from", "0.001", "--to", "1"],
                 ["--integral", "1/x", "--from", "-1", "--to", "1"], ["--solve", "x**x == 2", "--between", "1", "2"], ["--solve", "(2**4000*x - 1)*(x - 5)*(x - 7) == 0"],
                 ["irr(" + ", ".join(["-1", "2"] * 100) + ")"], ["--maximize", "x", "--subject", "x <= 1e308", "--subject", "x >= -1e308"],
                 ["--set", "a=2**4000", "--solve", "a*x**2 + a*x - a == 0"], ["--solve", "1e-300*x**2 - 1e300 == 0"], ["--derivative", "x", "--at", "1/0"]]
        for arguments in cases:
            done = subprocess.run([str(BINARY), "calc", *arguments], capture_output=True, text=True, timeout=20)
            self.assertIn(done.returncode, (0, 1, 2), (arguments[:2], done.stderr[-300:]))
            self.assertEqual(json.loads(done.stdout)["schema"], "code-audit.calc.v1")

    def test_a_repeated_root_polynomial_is_solved_completely(self):
        code, report = calc("--solve", "(x**2 - 2)**8 * (x - 1/3)**4 * (x**3 - x - 1)**2 == 0")
        found = [float(number(s["values"]["x"])) for s in report["solve"]["solutions"]]
        self.assertEqual(len(found), 4)
        for got, want in zip(found, (-math.sqrt(2), 1 / 3, 1.324717957244746, math.sqrt(2))):
            self.assertTrue(close(got, want, 1e-15))


@unittest.skipUnless(BINARY and ORACLES, "needs the analyzer binary and SymPy, NumPy and mpmath")
class OracleTests(unittest.TestCase):
    """Seeded random inputs compared with SymPy, NumPy and mpmath."""

    def test_polynomial_roots_match_sympy(self):
        x = sympy.Symbol("x")
        rng = random.Random(61)
        for _ in range(150):
            if rng.random() < 0.5:  # built from factors, so rational and repeated roots are common
                factors = [f"({rng.randint(1, 6)}*x - {rng.randint(-9, 9)})" for _ in range(rng.randint(1, 5))]
                factors += rng.sample(["(x**2 - 2)", "(x**2 + 1)", "(x**3 - x - 1)", "(x**2 - 3*x + 1)"], rng.randint(0, 2))
                source = "*".join(f"{f}**{rng.randint(1, 3)}" if rng.random() < 0.3 else f for f in factors)
            else:
                source = " + ".join(f"{rng.randint(-20, 20)}*x**{k}" for k in range(rng.randint(2, 9))) + f" + {rng.randint(1, 9)}*x**{rng.randint(9, 11)}"
            expected = sorted(set(sympy.Poly(sympy.sympify(source), x).real_roots()), key=lambda r: r.evalf(40))
            code, report = calc("--solve", f"{source} == 0")
            self.assertEqual(code, 0, (source, report))
            found = report["solve"]["solutions"]
            self.assertEqual(len(found), len(expected), (source, found, expected))
            for got, want in zip(found, expected):
                shown = number(got["values"]["x"])
                if want.is_Rational:
                    self.assertEqual((shown, got["exact"]), (Fraction(int(want.p), int(want.q)), True), source)
                else:
                    self.assertFalse(got["exact"])
                    self.assertTrue(math.isclose(shown, float(want.evalf(30)), rel_tol=4e-16, abs_tol=0), (source, shown, want.evalf(30)))

    def test_linear_systems_match_sympy(self):
        rng = random.Random(67)
        for _ in range(80):
            count = rng.randint(2, 5)
            names = list("abcde")[:count]
            symbols = sympy.symbols(names)
            rows = [[Fraction(rng.randint(-9, 9), rng.randint(1, 4)) for _ in range(count)] for _ in range(count)]
            if rng.random() < 0.2:
                rows[-1] = [2 * v for v in rows[0]]  # dependent rows
            bounds = [Fraction(rng.randint(-30, 30), rng.randint(1, 3)) for _ in range(count)]
            equations = [" + ".join(f"({a})*{n}" for a, n in zip(row, names)) + f" == {bound}" for row, bound in zip(rows, bounds)]
            matrix = sympy.Matrix([[sympy.Rational(a.numerator, a.denominator) for a in row] for row in rows])
            right = sympy.Matrix([sympy.Rational(b.numerator, b.denominator) for b in bounds])
            expected = sympy.linsolve((matrix, right), *symbols)
            code, report = calc(*[argument for equation in equations for argument in ("--solve", equation)])
            if code == 2 and "nothing to solve" in report.get("error", "") or code == 2 and "one equation" in report.get("error", ""):
                continue
            self.assertEqual(code, 0, (equations, report))
            unknowns = report["solve"]["unknowns"]
            if matrix[:, [names.index(n) for n in unknowns]].rank() < len(unknowns) or len(unknowns) < count:
                continue  # a column of zeros dropped a name, or the system is singular: covered by the fixed cases
            solution, = expected
            got = report["solve"]["solutions"][0]["values"]
            self.assertEqual([number(got[n]) for n in names], [Fraction(int(v.p), int(v.q)) for v in solution], equations)

    def expression(self, rng, depth):
        if depth == 0 or rng.random() < 0.25:
            return rng.choice(["x", "x", str(rng.randint(1, 5)), f"{rng.randint(1, 9)}/{rng.randint(2, 7)}"])
        kind = rng.random()
        if kind < 0.45:
            return f"({self.expression(rng, depth - 1)} {rng.choice('+-*/')} {self.expression(rng, depth - 1)})"
        if kind < 0.6:
            return f"({self.expression(rng, depth - 1)})**{rng.choice(['2', '3', '(1/2)', '(-1)', 'x'])}"
        return f"{rng.choice(['sin', 'cos', 'exp', 'log', 'sqrt', 'tan'])}({self.expression(rng, depth - 1)})"

    def test_derivatives_match_sympy(self):
        x = sympy.Symbol("x")
        rng = random.Random(71)
        compared = 0
        for _ in range(400):
            source, at = self.expression(rng, 3), rng.choice(["0.7", "1.3", "2.1"])
            try:
                expected = complex(sympy.diff(sympy.sympify(source), x).evalf(25, subs={x: sympy.Float(at, 25)}))
            except (TypeError, ValueError, ZeroDivisionError):
                continue
            if expected.imag or not math.isfinite(expected.real) or abs(expected.real) > 1e12:
                continue  # outside the real domain, or too steep for a float comparison to mean anything
            code, report = calc("--derivative", source, "--at", at)
            if code != 0:
                continue  # the expression leaves the real numbers at this point (log or sqrt of a negative)
            compared += 1
            self.assertTrue(math.isclose(float(number(report["derivative"]["value"])), expected.real, rel_tol=1e-9, abs_tol=1e-9), (source, at, report, expected))
        self.assertGreater(compared, 200)

    def test_integrals_match_sympy_and_mpmath(self):
        x = sympy.Symbol("x")
        rng = random.Random(73)
        for _ in range(60):  # polynomials: exact
            source = " + ".join(f"({rng.randint(-9, 9)}/{rng.randint(1, 5)})*x**{k}" for k in range(rng.randint(1, 6)))
            low, high = Fraction(rng.randint(-6, 6), rng.randint(1, 3)), Fraction(rng.randint(-6, 6), rng.randint(1, 3))
            expected = sympy.integrate(sympy.sympify(source, rational=True), (x, sympy.Rational(low.numerator, low.denominator), sympy.Rational(high.numerator, high.denominator)))
            code, report = calc("--integral", source, "--from", str(low), "--to", str(high))
            self.assertEqual(number(report["integral"]["value"]), Fraction(int(expected.p), int(expected.q)), source)
        for source, low, high in (("exp(-x**2)", 0, 3), ("sin(x)**2", 0, 5), ("1/(1 + x**2)", -4, 4), ("log(x)*x", 1, 9), ("sqrt(x)*cos(x)", 0, 6),
                                  ("exp(x)/(1 + exp(x))", -3, 7), ("tan(x)", 0, 1.5), ("x**x", 1, 3), ("2**x - x**2", 0, 4), ("1/sqrt(x)", 1, 100)):
            expected = float(mpmath.quad(lambda t: sympy.sympify(source).evalf(30, subs={x: t}), [low, high]))
            code, report = calc("--integral", source, "--from", str(low), "--to", str(high))
            self.assertEqual(code, 0, (source, report))
            self.assertTrue(math.isclose(report["integral"]["value"], expected, rel_tol=1e-9, abs_tol=1e-9), (source, report, expected))

    def test_expansion_matches_sympy(self):
        x = sympy.Symbol("x")
        rng = random.Random(79)
        for _ in range(80):
            factors = [f"({rng.randint(-5, 5)}*x**{rng.randint(0, 3)} + {rng.randint(-7, 7)}/{rng.randint(1, 4)})**{rng.randint(1, 3)}" for _ in range(rng.randint(1, 4))]
            source = rng.choice([" * ", " - ", " + "]).join(factors)
            expected = sympy.Poly(sympy.expand(sympy.sympify(source, rational=True)), x).all_coeffs()[::-1] if sympy.expand(sympy.sympify(source, rational=True)) != 0 else []
            code, report = calc("--expand", source)
            self.assertEqual(code, 0, (source, report))
            self.assertEqual([number(c) for c in report["expand"]["coefficients_low_to_high"]], [Fraction(int(c.p), int(c.q)) for c in expected], source)
            again = sympy.expand(sympy.sympify(report["expand"]["polynomial"], rational=True))
            self.assertEqual(again, sympy.expand(sympy.sympify(source, rational=True)), source)

    def test_irr_matches_the_numpy_financial_algorithm(self):
        rng = random.Random(83)
        for _ in range(150):
            flows = [-rng.randint(100, 9000)] + [rng.randint(-2000, 5000) for _ in range(rng.randint(1, 9))]
            if not any(f > 0 for f in flows):
                continue
            # numpy-financial's irr: the real roots g of the flows read as a polynomial, rates g - 1 above -1, then its selection rule.
            growth = numpy.roots(flows)
            rates = sorted(float(g.real) - 1 for g in growth if abs(g.imag) < 1e-9 and g.real > 1e-9)
            code, report = calc("irr(" + ", ".join(map(str, flows)) + ")")
            if not rates:
                self.assertEqual(code, 2, flows)
                continue
            if any(r >= 0 for r in rates) and any(r < 0 for r in rates):
                rates = [r for r in rates if r >= 0]
            expected = min(rates, key=abs)
            self.assertEqual(code, 0, (flows, report))
            self.assertTrue(math.isclose(float(number(report["results"][0]["value"])), expected, rel_tol=1e-6, abs_tol=1e-7), (flows, report, rates))


if __name__ == "__main__":
    unittest.main()
