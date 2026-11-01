import json
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import stats  # noqa: E402
import tempfile  # noqa: E402


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
        arm = StatsInputs.arm
        arms = {'a': arm({'F01': 1, 'F02': 1, 'F03': 0}), 'b': arm({'F01': 0, 'F02': 1, 'F04': 1})}
        row = stats.compare(arms, 'a', 'b', universe={'F01', 'F02', 'F03', 'F04'})
        self.assertEqual((row['paired_cases'], row['a_only'], row['b_only'], row['dropped']), (2, 1, 0, 2))

    def test_holm_is_monotone(self):
        rows = stats.holm([{'p': 0.01}, {'p': 0.04}, {'p': 0.03}])
        self.assertEqual([r['p_holm'] for r in rows], [0.03, 0.06, 0.06])


class StatsInputs(unittest.TestCase):
    arm = staticmethod(lambda per, ctl=None, tokens=10, seconds=1: {
        'per_case': {k: [v] for k, v in per.items()}, 'per_control': {k: [v] for k, v in (ctl or {}).items()},
        'review_trials': len(per), 'control_trials': len(ctl or {}), 'review_invalid': 0, 'detected': sum(per.values()),
        'control_false_positives': sum((ctl or {}).values()), 'findings': 0, 'tokens': tokens, 'seconds': seconds})

    def test_controls_are_paired(self):
        arms = {'a': self.arm({'F01': 1}, {'C1': 1, 'C2': 1}), 'b': self.arm({'F01': 1}, {'C1': 0})}
        row = stats.compare(arms, 'a', 'b')
        self.assertEqual((row['paired_controls'], row['delta_control_fp']), (1, 1))

    def test_union_is_or_with_summed_cost(self):
        u = stats.union(self.arm({'F01': 1, 'F02': 0}, tokens=20), self.arm({'F01': 0, 'F02': 1}, tokens=10))
        self.assertEqual((u['detected'], u['review_trials'], u['tokens']), (2, 2, 30.0))

    def test_cost_is_per_trial(self):
        arms = {'a': self.arm({'F01': 1, 'F02': 1}, tokens=40), 'b': self.arm({'F01': 1}, tokens=20)}
        self.assertEqual(stats.compare(arms, 'a', 'b')['cost_ratio']['tokens'], 1.0)

    def test_missing_arm_is_no_data_and_duplicates_refused(self):
        self.assertEqual(stats.verdict(stats.compare({}, 'a', 'b')), 'no data')
        with tempfile.TemporaryDirectory() as d:
            p1, p2 = Path(d) / '1.json', Path(d) / '2.json'
            for p in (p1, p2): p.write_text(json.dumps({'arms': {'none': self.arm({'F01': 1})}}))
            with self.assertRaises(SystemExit): stats.load([p1, p2])


class Runner(unittest.TestCase):
    def setUp(self):
        import importlib.util  # evals/matched/run.py shadows the name `run` once harness is imported
        spec = importlib.util.spec_from_file_location('fresh_run', HERE / 'run.py'); self.run = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.run)

    def test_hint_skips_controls_only(self):
        jobs = self.run.jobs_for(['none', 'hint'], None)
        controls = {c['id'] for c in self.run.CASES['review'] if c['role'] == 'control'}
        self.assertFalse(any(arm == 'hint' and case['id'] in controls for case, arm in jobs))
        self.assertTrue(any(arm == 'none' and case['id'] in controls for case, arm in jobs))

    def test_tool_log_classifies_the_full_command(self):
        cmd = 'echo ' + 'x' * 500 + ' && python3 tools/scan.py repo'
        line = json.dumps({'type': 'item.completed', 'item': {'type': 'command_execution', 'command': cmd}})
        commands, used = self.run.tool_log(line)
        self.assertTrue(used['scan']); self.assertEqual(len(commands[0]), 400)

    def test_view_keeps_only_new_two_pass_findings(self):
        with tempfile.TemporaryDirectory() as d:
            raw = Path(d) / 'raw' / 'F01-none-2pass-1'; raw.mkdir(parents=True)
            (raw / 'meta.json').write_text(json.dumps({'arm': 'none-2pass', 'case_id': 'F01', 'new_findings': 1}))
            (raw / 'answer.json').write_text(json.dumps({'coverage': 'complete', 'findings': [{'id': 'old'}, {'id': 'new'}]}))
            self.run.scoring_view(Path(d) / 'raw', Path(d) / 'view')
            v = Path(d) / 'view' / 'F01-none-2pass-1'
            self.assertEqual(json.loads((v / 'meta.json').read_text())['arm'], 'none-2pass-new')
            self.assertEqual([f['id'] for f in json.loads((v / 'answer.json').read_text())['findings']], ['new'])

    def test_tools_come_from_the_pinned_revision(self):
        if not self.run.ARCHITECT.is_file(): self.skipTest('architect binary unavailable')
        with tempfile.TemporaryDirectory() as d:
            hashes = self.run.install_tools(Path(d) / 'tools')
        import subprocess
        pinned = subprocess.run(['git', '-C', str(HERE.parents[1]), 'show', f'{self.run.TOOLS_REV}:skills/code-principles/scripts/scan.py'], capture_output=True, check=True, timeout=30).stdout
        self.assertEqual(hashes['scan.py'], self.run.sha(pinned))


class Cases(unittest.TestCase):
    def test_case_set_shape(self):
        cases = json.loads((HERE / 'cases.json').read_text()); oracles = json.loads((HERE / 'private/oracles.json').read_text())
        defects = [c for c in cases['review'] if c['role'] == 'defect']; controls = [c for c in cases['review'] if c['role'] == 'control']
        self.assertGreaterEqual(len(defects), 40); self.assertEqual(len(controls), 8)
        self.assertEqual({c['key'] for c in defects}, set(oracles))
        for c in controls: self.assertEqual(c['revision'], oracles[c['key']]['fix'])


if __name__ == '__main__':
    unittest.main()
