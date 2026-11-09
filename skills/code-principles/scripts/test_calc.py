"""calc.py evaluates arithmetic exactly, checks comparisons and refuses anything that is not arithmetic."""
import contextlib
from fractions import Fraction
import io
import json
import math
from pathlib import Path
import random
import subprocess
import unittest

import calc
import complexity

VECTORS = json.loads((Path(__file__).resolve().parent / "calc_vectors.json").read_text())
BINARY = complexity.native_binary()


def python_engine(arguments):
    """(exit status, report) from calc.py in this process."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = calc.main(list(arguments))
    return code, json.loads(out.getvalue())


def rust_engine(arguments):
    """(exit status, report) from the analyzer binary's calc subcommand."""
    done = subprocess.run([str(BINARY), "calc", *arguments], capture_output=True, text=True, timeout=30)
    return done.returncode, json.loads(done.stdout)


ENGINES = {"python": python_engine, **({"rust": rust_engine} if BINARY else {})}


def same(actual, expected):
    """An integer and a fraction must match exactly and keep their kind; a float matches within 1e-12."""
    if isinstance(expected, bool) or isinstance(actual, bool):
        return False
    if isinstance(expected, int):
        return isinstance(actual, int) and actual == expected
    if isinstance(expected, str):
        return isinstance(actual, dict) and actual["exact"] == expected
    return isinstance(actual, float) and math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-300)


class SharedVectorTests(unittest.TestCase):
    """Both calculators must give the hand-worked answer for every shared vector."""

    def test_values(self):
        for engine, run in ENGINES.items():
            code, report = run([expression for expression, _ in VECTORS["values"]])
            self.assertEqual((code, report["status"]), (0, "ok"), (engine, report.get("error")))
            for (expression, expected), result in zip(VECTORS["values"], report["results"]):
                with self.subTest(engine=engine, expression=expression):
                    self.assertTrue(same(result["value"], expected), (result["value"], expected))

    def test_invalid_expressions_are_refused(self):
        for engine, run in ENGINES.items():
            for expression in VECTORS["invalid"]:
                with self.subTest(engine=engine, expression=expression):
                    code, report = run([expression])
                    self.assertEqual((code, report["status"]), (2, "invalid"))

    def test_checks(self):
        for engine, run in ENGINES.items():
            for comparison, expected in VECTORS["checks"]:
                with self.subTest(engine=engine, comparison=comparison):
                    code, report = run(["--check", comparison])
                    self.assertEqual((code, report["checks"][0]["passed"]), (0 if expected else 1, expected))
            for comparison in VECTORS["invalid_checks"]:
                with self.subTest(engine=engine, comparison=comparison):
                    self.assertEqual(run(["--check", comparison])[0], 2)

    def agree(self, seed, numbers, functions, single):
        """Run seeded random expressions through both calculators: the same refusals and the same values."""
        rng = random.Random(seed)
        binary_ops = ["+", "-", "*", "/", "//", "%", "**"]

        def expression(depth):
            roll = rng.random()
            if depth == 0 or roll < 0.3:
                return rng.choice(numbers)
            if roll < 0.75:
                return f"({expression(depth - 1)} {rng.choice(binary_ops)} {expression(depth - 1)})"
            if roll < 0.85:
                return f"-{expression(depth - 1)}"
            name = rng.choice(functions)
            count = 1 if name in single else rng.randint(1, 4)
            return f"{name}({', '.join(expression(depth - 1) for _ in range(count))})"

        valid = 0
        for _ in range(600):
            source = expression(3)
            (python_code, python_report), (rust_code, rust_report) = python_engine([source]), rust_engine([source])
            with self.subTest(expression=source):
                self.assertEqual(python_code, rust_code, (python_report.get("error"), rust_report.get("error")))
                if python_code == 0:
                    valid += 1
                    a, b = python_report["results"][0]["value"], rust_report["results"][0]["value"]
                    self.assertEqual(type(a), type(b), (a, b))
                    if isinstance(a, float):
                        self.assertTrue(math.isclose(a, b, rel_tol=1e-12, abs_tol=0), (a, b))
                    elif isinstance(a, dict):
                        self.assertEqual(a["exact"], b["exact"])
                    else:
                        self.assertEqual(a, b)
        return valid

    @unittest.skipUnless(BINARY, "analyzer binary not built; the Python calculator is the only engine")
    def test_random_expressions_agree_between_the_two_calculators(self):
        numbers = ["0", "1", "2", "3", "7", "10", "12", "100", "1/3", "2/7", "0.5", "1.25", "2.0", "1e3", "-4", "-1/2"]
        functions = ["abs", "round", "floor", "ceil", "sqrt", "min", "max", "sum", "mean", "median"]
        valid = self.agree(20261109, numbers, functions, ("abs", "round", "floor", "ceil", "sqrt"))
        self.assertGreater(valid, 200, "the generator should produce mostly valid expressions")

    @unittest.skipUnless(BINARY, "analyzer binary not built; the Python calculator is the only engine")
    def test_random_expressions_at_the_edges_of_floats_agree_too(self):
        # Values too small or too large for a float, values next to 1, and the functions that turn exact values
        # into floats: where an exact value must become a float, both calculators convert or refuse alike.
        numbers = ["1", "2", "3", "1/3", "0.5", "2.0", "1/2**1100", "2**1100", "1 + 1/2**60", "1 - 1/2**70", "1e-300", "1e300", "3/2**600", "1/2**2000", "7/5"]
        functions = ["sqrt", "log", "log2", "log10", "sum", "mean", "median", "stdev", "pstdev", "abs", "min", "max"]
        valid = self.agree(20261110, numbers, functions, ("sqrt", "log", "log2", "log10", "abs"))
        self.assertGreater(valid, 100, "the generator should produce a good share of valid expressions")


class CalcTests(unittest.TestCase):
    def run_main(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = calc.main([*argv])
        return code, json.loads(out.getvalue())

    def test_integers_and_fractions_stay_exact(self):
        self.assertEqual(calc.evaluate("99 + 124 + 89 + 10"), 322)
        self.assertEqual(calc.evaluate("1/3 + 1/6"), Fraction(1, 2))
        self.assertEqual(calc.evaluate("7 // 2"), 3)
        self.assertEqual(calc.evaluate("-7 % 3"), 2)
        self.assertEqual(calc.evaluate("2 ** 10"), 1024)
        self.assertEqual(calc.evaluate("round(100 * 21 / 47, 1)"), Fraction(447, 10))
        self.assertEqual(calc.evaluate("max(3, 7, 5) - min(3, 7, 5) + sum(1, 2, 3) + abs(-4)"), 14)

    def test_floats_and_irrational_functions_return_floats(self):
        self.assertAlmostEqual(calc.evaluate("sqrt(2)"), 1.4142135623730951)
        self.assertAlmostEqual(calc.evaluate("2 ** 0.5"), 1.4142135623730951)
        self.assertEqual(calc.evaluate("0.5 + 0.25"), 0.75)
        self.assertEqual(calc.evaluate("ceil(7 / 2) + floor(7 / 2)"), 7)

    def test_check_compares_exactly_and_floats_within_tolerance(self):
        self.assertEqual(calc.check("10**2 * (1 - 1/2)**3 + 10 == 45/2"), (True, Fraction(45, 2), Fraction(45, 2)))
        self.assertTrue(calc.check("0.1 + 0.2 == 0.3")[0])
        self.assertFalse(calc.check("1/3 == 0.33")[0])
        self.assertFalse(calc.check("21 / 47 == 1/2")[0])
        self.assertTrue(calc.check("21 / 47 < 1/2")[0])
        self.assertTrue(calc.check("0.1 + 0.2 != 0.4")[0])

    def test_cli_reports_values_and_exit_codes(self):
        code, report = self.run_main("1/3 + 1/6", "2 + 2", "--check", "2 + 2 == 4")
        self.assertEqual((code, report["status"]), (0, "ok"))
        self.assertEqual([r["value"] for r in report["results"]], [{"exact": "1/2", "decimal": 0.5}, 4])
        self.assertEqual(report["checks"][0]["passed"], True)
        code, report = self.run_main("--check", "2 + 2 == 5")
        self.assertEqual((code, report["status"], report["checks"][0]["left"]), (1, "failed", 4))

    def test_anything_that_is_not_arithmetic_is_refused(self):
        hostile = ["__import__('os').system('true')", "open('x')", "x + 1", "(1).real", "'a' * 3", "True + 1", "[1, 2][0]",
                   "lambda: 1", "sum(x for x in (1, 2))", "round(1.5, ndigits=0)", "2 +", "1 / 0", "9 ** 9 ** 9", "1e308 * 10", "(-8) ** (1/3)"]
        for expression in hostile:
            with self.subTest(expression=expression):
                with self.assertRaises(ValueError):
                    calc.evaluate(expression)
                self.assertEqual(self.run_main(expression)[0], 2)
        with self.assertRaises(ValueError):
            calc.check("2 + 2")
        with self.assertRaises(ValueError):
            calc.check("1 < 2 < 3")

    def test_size_budget_refuses_before_computing(self):
        for expression in ("((2**4096)**4096)**4096", "9 ** 9 ** 9", "2 ** 4097", "(2**2000) * (2**2000) * (2**2000)", "round(1/3, 10**100)", "round(1/3, 1/2)"):
            with self.subTest(expression=expression), self.assertRaises(ValueError):
                calc.evaluate(expression)
        self.assertEqual(calc.evaluate("2 ** 2000").bit_length(), 2001)

    def test_rounding_and_large_exact_values_do_not_crash(self):
        self.assertEqual(calc.evaluate("round(1.25, 1)"), 1.2)
        self.assertEqual(calc.evaluate("round(2/3, 3)"), Fraction(667, 1000))
        self.assertEqual(calc.evaluate("round(5/2)"), 2)
        code, report = self.run_main("10**400 / 3", "--check", "10**400 / 3 > 1")
        self.assertEqual((code, report["results"][0]["value"]["decimal"], report["checks"][0]["passed"]), (0, None, True))
        self.assertTrue(report["results"][0]["value"]["exact"].endswith("/3"))
        self.assertEqual(self.run_main("--check", "10.0**300 * 10.0**300 == 1")[0], 2)

    def test_floor_division_stays_exact_and_inside_the_budget(self):
        self.assertEqual(calc.evaluate("((10**20 + 1) // 1) / (1 // 1) - 10**20"), 1)
        self.assertEqual(calc.evaluate("7 // 2 / 2"), Fraction(3, 2))
        self.assertEqual(calc.evaluate("floor(7 / 2) / 2 + ceil(7 / 2) / 3"), Fraction(17, 6))
        for expression in ("(2 // 1) ** (10 ** 100)", "floor(2) ** (10 ** 100)", "1" + "0" * 6000, "1" + "0" * 1300, "max(2, 1) ** (10 ** 100)"):
            with self.subTest(expression=expression[:30]), self.assertRaises(ValueError):
                calc.evaluate(expression)

    def test_largest_permitted_exact_results_can_be_printed_and_read_back(self):
        import subprocess, sys
        argv = [sys.executable, calc.__file__, "(2**2000) * (2**2000)", "(2**2000) * (2**2000) / 3", "1" + "0" * 1200, "2**4095"]
        done = subprocess.run(argv, capture_output=True, text=True, timeout=30)
        report = json.loads(done.stdout)  # a fresh interpreter with the default digit limit reads every permitted result
        self.assertEqual((done.returncode, report["results"][0]["value"]), (0, 2 ** 4000))
        self.assertTrue(report["results"][1]["value"]["exact"].endswith("/3"))
        self.assertEqual((report["results"][2]["value"], report["results"][3]["value"]), (10 ** 1200, 2 ** 4095))
        self.assertLess(len(str(2 ** calc.MAX_BITS)), 4300)

    def test_no_input_escapes_as_an_uncaught_error_or_unbounded_work(self):
        big = "sum(" + ", ".join(f"1/(10**1000 + {2 * i + 1})" for i in range(40)) + ")"
        cases = ["((-1) ** (1/2)) // 1", "(-8) ** (1/3) + 1", "-" * 350 + "1", "1 + " * 300 + "1",
                 "9" * 2500, big, "mean(" + big[4:], "median()", "log(0)", "log(-1)", "sqrt(-1)", "0.0 ** -1"]
        for expression in cases:
            with self.subTest(expression=expression[:40]):
                with self.assertRaises(ValueError):
                    calc.evaluate(expression)
                self.assertEqual(self.run_main(expression)[0], 2)
        for comparison in ("-" * 350 + "1 == 1", "((-1) ** (1/2)) == 1", "1 == " + "9" * 2500):
            with self.subTest(comparison=comparison[:40]):
                with self.assertRaises(ValueError):
                    calc.check(comparison)
                self.assertEqual(self.run_main("--check", comparison)[0], 2)
        self.assertEqual(calc.evaluate("sum(1/3, 1/6, 1/2)"), 1)
        self.assertEqual(calc.evaluate("-" * 100 + "1"), 1)
        self.assertEqual(calc.evaluate("(" * 120 + "1" + ")" * 120), 1)

    def test_expression_may_begin_with_a_minus_sign(self):
        code, report = self.run_main("-5 + 3", "--check", "-1 == -1", "--check", "-2 < -1")
        self.assertEqual((code, report["results"][0]["value"]), (0, -2))
        self.assertEqual([c["passed"] for c in report["checks"]], [True, True])

    def test_statistics_come_from_the_standard_library(self):
        self.assertEqual(calc.evaluate("mean(1, 2, 4)"), Fraction(7, 3))
        self.assertEqual(calc.evaluate("median(5, 1, 3, 2)"), Fraction(5, 2))
        self.assertAlmostEqual(calc.evaluate("stdev(2, 4, 4, 4, 5, 5, 7, 9)"), 2.138089935299395)
        self.assertEqual(calc.evaluate("pstdev(2, 4, 4, 4, 5, 5, 7, 9)"), 2.0)
        self.assertEqual((calc.evaluate("min(7/2)"), calc.evaluate("max(2.5)")), (Fraction(7, 2), 2.5))
        self.assertEqual((calc.evaluate("round(2.5)"), calc.evaluate("round(-1e3)"), calc.evaluate("round(0.5)")), (2, -1000, 0))
        for expression in ("mean()", "stdev(1)", "min()"):
            with self.subTest(expression=expression), self.assertRaises(ValueError):
                calc.evaluate(expression)

    def test_a_fraction_no_float_is_near_has_no_decimal(self):
        for engine, run in ENGINES.items():
            with self.subTest(engine=engine):
                for expression, decimal in (("1/3", 0.3333333333333333), ("1/2**2000 + 1/2**2001", None), ("10**400 / 3", None), ("3/2**1074", 1.5e-323)):
                    code, report = run([expression])
                    self.assertEqual(report["results"][0]["value"]["decimal"], decimal, expression)

    def test_the_script_names_the_binary_for_what_only_the_binary_does(self):
        for argv in (["--solve", "x + 1 == 2"], ["2 * x", "--set", "x=3"], ["--maximize", "x", "--subject", "x <= 1"], ["pmt(0.05, 10, 1000)"], ["x + 1"]):
            code, report = self.run_main(*argv)
            self.assertEqual((code, report["status"]), (2, "invalid"), argv)
            self.assertIn("analyzer binary", report["error"], argv)

    def test_crap_formula_matches_the_scorer(self):
        import complexity
        row = complexity.finish_row({"name": "f", "line": 1, "end_line": 3, "function_id": "f:1", "cc": 10, "path": "m.py", "language": "python"},
                                    None, {"functions": {"f:1": 50}}, complexity.CC_THRESHOLD, {})
        self.assertTrue(calc.check(f"10**2 * (1 - 50/100)**3 + 10 == {row['crap']}")[0])


if __name__ == "__main__":
    unittest.main()
