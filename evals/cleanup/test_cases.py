"""Exercise seeded preservation boundaries and reuse existing scoring accounting."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('cleanup_review_score', ROOT.parent / 'review/score.py')
SCORER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SCORER)
CASES = json.loads((ROOT / 'cases.json').read_text())
ORACLES = json.loads((ROOT / 'private/oracles.json').read_text())


class CleanupCases(unittest.TestCase):
    def run_case(self, index, probe, edits=None):
        sources = dict(CASES['cases'][index]['sources'])
        for path, transform in (edits or {}).items():
            sources[path] = transform(sources[path])
        with tempfile.TemporaryDirectory() as directory:
            for path, content in sources.items():
                (Path(directory) / path).write_text(content)
            return subprocess.run([sys.executable, '-B', '-c', probe], cwd=directory,
                                  capture_output=True, text=True, timeout=10)

    def test_dynamic_handler_survives_safe_cleanup(self):
        probe = 'from loader import run; assert run("Hi") == ["HI"]'
        self.assertEqual(self.run_case(0, probe).returncode, 0)
        self.assertEqual(self.run_case(0, probe, {'handlers.py': lambda s: s.split('\ndef legacy')[0]}).returncode, 0)
        self.assertNotEqual(self.run_case(0, probe, {'handlers.py': lambda s: s.replace('def active(', 'def removed(')}).returncode, 0)

    def test_flag_dependency_survives_safe_cleanup(self):
        probe = 'from application import enabled; assert enabled() is True'
        self.assertEqual(self.run_case(1, probe).returncode, 0)
        self.assertEqual(self.run_case(1, probe, {'flags.py': lambda s: s.replace(', "retired": False', '')}).returncode, 0)
        self.assertNotEqual(self.run_case(1, probe, {'flags.py': lambda s: s.replace('"parent": True, ', '')}).returncode, 0)

    def test_emergency_control_survives_safe_cleanup(self):
        probe = '''from service import charge
assert charge(7) == {"charged": 7}
try:
    charge(7, emergency_stop=True)
except RuntimeError:
    pass
else:
    raise AssertionError("Emergency control lost")
'''
        self.assertEqual(self.run_case(2, probe).returncode, 0)
        self.assertEqual(self.run_case(2, probe, {'service.py': lambda s: s.split('\ndef retired_status')[0]}).returncode, 0)
        self.assertNotEqual(self.run_case(2, probe, {'service.py': lambda s: s.replace('if emergency_stop:', 'if False:')}).returncode, 0)

    def test_all_keep_misses_every_opportunity(self):
        review = {'cases': [{'case_id': c['id'], 'coverage': 'complete', 'findings': []} for c in CASES['cases']]}
        result = SCORER.score(review, {'judgments': []}, CASES, ORACLES)
        self.assertEqual(result['seeded_defect_classes'], 3)
        self.assertEqual(result['seeded_class_recall'], 0)

    def test_harm_is_visible_even_with_full_recall(self):
        review, judgments = {'cases': []}, {'judgments': []}
        for case in CASES['cases']:
            cid = case['id']
            oracle = ORACLES['oracles'][cid][0]
            review['cases'].append({'case_id': cid, 'coverage': 'complete', 'findings': [{
                'id': 'F1', 'cause': oracle['mechanism'], 'locations': oracle['locations'],
                'severity': 'low', 'origin': 'pre_existing', 'disposition': 'open',
                'suggested_change': 'Remove unused target and protected path',
                'verification': 'Proposed only; no checks run'}]})
            judgments['judgments'].append({'case_id': cid, 'finding_id': 'F1',
                'oracle_id': oracle['id'], 'valid': True, 'harmful': True, 'duplicate': False,
                'rationale': 'Synthetic accounting probe: supported target plus harmful protected-path removal.'})
        result = SCORER.score(review, judgments, CASES, ORACLES)
        self.assertEqual(result['seeded_class_recall'], 1)
        self.assertEqual(result['harmful_advice'], 3)


if __name__ == '__main__':
    unittest.main()
