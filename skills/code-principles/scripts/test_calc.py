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

    def test_crap_formula_matches_the_scorer(self):
        import complexity
        row = complexity.finish_row({"name": "f", "line": 1, "end_line": 3, "function_id": "f:1", "cc": 10, "path": "m.py", "language": "python"},
                                    None, {"functions": {"f:1": 50}}, complexity.CC_THRESHOLD, {})
        self.assertTrue(calc.check(f"10**2 * (1 - 50/100)**3 + 10 == {row['crap']}")[0])


if __name__ == "__main__":
    unittest.main()
