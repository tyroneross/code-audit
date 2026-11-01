import json
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import stats  # noqa: E402


class Stats(unittest.TestCase):
    def test_exact_mcnemar(self):
        self.assertAlmostEqual(stats.mcnemar(6, 0), 0.03125)
        self.assertAlmostEqual(stats.mcnemar(5, 0), 0.0625)
        self.assertEqual(stats.mcnemar(0, 0), 1.0)
        self.assertAlmostEqual(stats.mcnemar(3, 3), 1.0)

    def test_verdicts(self):
        row = lambda d, p, fp=0, cost=1.0: {'delta': d, 'p': p, 'delta_control_fp': fp, 'cost_ratio': {'tokens': cost, 'seconds': 1.0}}
        self.assertEqual(stats.verdict(row(0.2, 0.01)), 'helps')
        self.assertEqual(stats.verdict(row(0.2, 0.01, cost=2.5)), 'helps at cost')
        self.assertEqual(stats.verdict(row(0.2, 0.2)), 'parity')
        self.assertEqual(stats.verdict(row(-0.2, 0.01)), 'worse')
        self.assertEqual(stats.verdict(row(0.2, 0.01, fp=2)), 'worse')

    def test_compare_pairs_cases(self):
        arm = lambda per, fp=0: {'per_case': {k: [v] for k, v in per.items()}, 'control_false_positives': fp, 'tokens': 10, 'seconds': 1}
        arms = {'a': arm({'F01': 1, 'F02': 1, 'F03': 0}), 'b': arm({'F01': 0, 'F02': 1, 'F04': 1})}
        row = stats.compare(arms, 'a', 'b')
        self.assertEqual((row['paired_cases'], row['a_only'], row['b_only'], row['dropped']), (2, 1, 0, 2))

    def test_holm_is_monotone(self):
        rows = stats.holm([{'p': 0.01}, {'p': 0.04}, {'p': 0.03}])
        self.assertEqual([r['p_holm'] for r in rows], [0.03, 0.06, 0.06])


class Cases(unittest.TestCase):
    def test_case_set_shape(self):
        cases = json.loads((HERE / 'cases.json').read_text()); oracles = json.loads((HERE / 'private/oracles.json').read_text())
        defects = [c for c in cases['review'] if c['role'] == 'defect']; controls = [c for c in cases['review'] if c['role'] == 'control']
        self.assertGreaterEqual(len(defects), 40); self.assertEqual(len(controls), 8)
        self.assertEqual({c['key'] for c in defects}, set(oracles))
        for c in controls: self.assertEqual(c['revision'], oracles[c['key']]['fix'])


if __name__ == '__main__':
    unittest.main()
