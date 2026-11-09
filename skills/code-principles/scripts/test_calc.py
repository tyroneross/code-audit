"""calc.py evaluates arithmetic exactly, checks comparisons and refuses anything that is not arithmetic."""
import contextlib
from fractions import Fraction
import io
import json
import unittest

import calc


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
        for expression in ("mean()", "stdev(1)", "min()"):
            with self.subTest(expression=expression), self.assertRaises(ValueError):
                calc.evaluate(expression)

    def test_crap_formula_matches_the_scorer(self):
        import complexity
        row = complexity.finish_row({"name": "f", "line": 1, "end_line": 3, "function_id": "f:1", "cc": 10, "path": "m.py", "language": "python"},
                                    None, {"functions": {"f:1": 50}}, complexity.CC_THRESHOLD, {})
        self.assertTrue(calc.check(f"10**2 * (1 - 50/100)**3 + 10 == {row['crap']}")[0])


if __name__ == "__main__":
    unittest.main()
