"""Hard benchmark integrity: manifest, answer-key isolation, schema strictness, deterministic matching, blinding."""
import json
from pathlib import Path
import random
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import harness  # noqa: E402
import grade as score  # noqa: E402

REPOS = harness.ROOT.is_dir()


class Manifest(unittest.TestCase):
    def test_every_review_case_has_an_oracle_inside_its_packet(self):
        for case in harness.CASES['review']:
            oracle = score.ORACLES[case['key']]
            entry = next((f for f in case['files'] if f['path'] == oracle['file']), None)
            self.assertIsNotNone(entry, case['id'])
            if case['role'] == 'defect' and entry.get('ranges'):
                for a, b in oracle['lines']:
                    self.assertTrue(any(s <= a and b <= e for s, e in entry['ranges']), (case['id'], a, b))

    def test_repair_editables_are_workspace_files_and_private_tests_stay_out_of_it(self):
        for case in harness.CASES['repair']:
            placed = {case.get('place', {}).get(p, p) for p in case['files']} | set(case.get('fixtures', {}))
            self.assertTrue(set(case['editable']) <= placed, case['id'])
            if 'private' in case['withheld']: self.assertTrue(case['withheld']['private'].startswith('private/'))

    def test_review_schema_is_strict(self):
        def walk(node):
            if node.get('type') == 'object':
                self.assertFalse(node['additionalProperties']); self.assertEqual(set(node['required']), set(node['properties']))
                for child in node['properties'].values(): walk(child)
            if node.get('type') == 'array': walk(node['items'])
        walk(harness.REVIEW_SCHEMA)

    def test_launch_is_pinned(self):
        cmd = harness.codex_command('/x/schema.json')
        self.assertEqual(harness.assert_launch(cmd)['asserted_model'], 'gpt-6.1-sol')
        self.assertIn('--output-schema', cmd)

    @unittest.skipUnless(REPOS, 'source repositories unavailable')
    def test_prompts_carry_no_answer_key(self):
        for case in harness.CASES['review']:
            prompt = harness.review_prompt(case, 'none'); oracle = score.ORACLES[case['key']]
            self.assertNotIn(oracle['mechanism'][:60], prompt); self.assertNotIn(oracle.get('fix', 'x' * 40), prompt)
        for case in harness.CASES['repair']:
            _, test = harness.withheld_test(case)
            self.assertNotIn(test.decode()[:200], json.dumps({k: v.decode(errors='replace') for k, v in harness.workspace_files(case).items()}))


class Matching(unittest.TestCase):
    oracle = {'file': 'src/scan-lock.ts', 'lines': [[457, 459], [363, 367]]}

    def test_location_hit_requires_same_file_and_window(self):
        hit = lambda *locs: score.location_hit({'locations': list(locs)}, self.oracle)
        self.assertTrue(hit('src/scan-lock.ts:458'))
        self.assertTrue(hit('scan-lock.ts:468'))          # suffix path, within tolerance
        self.assertTrue(hit('`src/scan-lock.ts:350-360`'))  # range overlapping the second window minus tolerance
        self.assertFalse(hit('src/scan-lock.ts:480'))
        self.assertFalse(hit('src/other-scan-lock.ts:458'))
        self.assertFalse(hit('src/cli/commands/scan.ts:458'))
        self.assertFalse(hit('no location'))


class Blinding(unittest.TestCase):
    @unittest.skipUnless(REPOS, 'source repositories unavailable')
    def test_judge_packets_hide_arms_and_aggregate_requires_location_and_judgment(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / 'raw'; judges = Path(folder) / 'judges'; labels = Path(folder) / 'labels.json'
            for arm, loc in [('code-audit', 'src/scan-lock.ts:458'), ('none', 'src/scan-lock.ts:120')]:
                d = out / f'H01-{arm}-1'; d.mkdir(parents=True)
                (d / 'meta.json').write_text(json.dumps({'family': 'review', 'case_id': 'H01', 'arm': arm, 'repeat': 1, 'status': 'completed', 'elapsed_seconds': 3, 'usage': {'input_tokens': 5, 'output_tokens': 1}}))
                (d / 'answer.json').write_text(json.dumps({'coverage': 'complete', 'findings': [{'id': 'F1', 'cause': 'gate failure not retryable', 'locations': [loc], 'severity': 'high', 'suggested_change': 's', 'verification': 'v'}]}))
            score.judge_packets(out, judges, labels, random.Random(1))
            text = ''.join(p.read_text() for p in judges.glob('*.json'))
            for word in ['code-audit', 'coding-debugger', 'code-principles', '"none"', 'H01-']: self.assertNotIn(word, text)
            mapping = json.loads(labels.read_text()); packet = next(k for k in mapping if k.startswith('J-'))
            rows = json.loads((judges / f'{packet}.json').read_text().split('PACKET\n', 1)[1])['findings']
            judgments = Path(folder) / 'j'; judgments.mkdir()
            (judgments / f'{packet}.json').write_text(json.dumps({'judgments': [{'label': r['label'], 'finding_id': r['finding_id'], 'matches': True, 'reason': 'r'} for r in rows]}))
            bad = out / 'H01-coding-debugger-1'; bad.mkdir()
            (bad / 'meta.json').write_text(json.dumps({'family': 'review', 'case_id': 'H01', 'arm': 'coding-debugger', 'repeat': 1, 'status': 'host_failed'}))
            arms = score.aggregate(out, score.load_judgments(judgments, mapping))
            # An invalid trial is excluded from the denominator, not scored as a miss.
            self.assertEqual((arms['coding-debugger']['review_trials'], arms['coding-debugger']['review_invalid']), (0, 1))
            # Both judged as matching, but only the finding inside the oracle window counts as detected.
            self.assertEqual((arms['code-audit']['detected'], arms['none']['detected']), (1, 0))
            self.assertEqual(arms['code-audit']['tokens'], 6)
            c = out / 'C01-none-1'; c.mkdir()
            (c / 'meta.json').write_text(json.dumps({'family': 'review', 'case_id': 'C01', 'arm': 'none', 'repeat': 1, 'status': 'completed'}))
            (c / 'answer.json').write_text(json.dumps({'coverage': 'complete', 'findings': []}))
            self.assertEqual(score.aggregate(out, {}, ['H01'])['none']['control_trials'], 1)  # controls kept under a case filter


class Repair(unittest.TestCase):
    def test_exit_zero_without_tests_does_not_pass_and_network_commands_are_flagged(self):
        self.assertEqual(harness.test_counts('Ran 0 tests in 0.0s\n\nOK\n'), {'ran': 0, 'failed': 0})
        self.assertEqual(harness.test_counts('Ran 11 tests in 0.1s\n\nFAILED (failures=2, errors=1)\n'), {'ran': 11, 'failed': 3})
        self.assertEqual(harness.test_counts('# tests 3\n# pass 3\n# fail 0\n'), {'ran': 3, 'failed': 0})
        row = lambda c: json.dumps({'type': 'item.completed', 'item': {'type': 'command_execution', 'command': c}})
        flagged = [row('git clone https://github.com/x/y'), row("python3 -c 'import urllib.request'"), row("/bin/zsh -lc 'cd x && curl -s https://example.com'"), row("node -e 'require(\"https\")'")]
        # Observed false positives from real trials: a yarn.lock glob, a test named after requests, a copyright e-mail domain.
        clean = [row("/bin/zsh -lc 'git status --short'"), row('sed -n 1,20p a.py'), row("rg --files -g '!yarn.lock' -g '!node_modules'"),
                 row('cat > t.mjs <<EOF\ntest("close rejects queued requests")\nEOF'), row('# <46267523+x@users.noreply.github.com>')]
        self.assertEqual(len(harness.network_commands('\n'.join(flagged))['network_commands']), 4)
        self.assertEqual(harness.network_commands('\n'.join(clean))['network_commands'], [])


class Verdicts(unittest.TestCase):
    def test_rule_thresholds(self):
        base = lambda rate, fp=0, passed=0: {'detection_rate': rate, 'control_false_positives': fp, 'repair_trials': 12, 'repair_passed': passed, 'per_case': {}}
        arms = {'code-audit': base(.6, 0, 8), 'coding-debugger': base(.4, 0, 8), 'code-principles-audit': base(.5, 0, 4), 'none': base(.8, 0, 10)}
        v = score.verdicts(arms)
        self.assertEqual(v['coding-debugger']['review']['verdict'], 'outperforms')
        self.assertEqual(v['code-principles-audit']['review']['verdict'], 'parity')
        self.assertEqual(v['code-principles-audit']['repair']['verdict'], 'outperforms')
        self.assertFalse(v['discrimination']['review_control_below_ceiling'])


if __name__ == '__main__':
    unittest.main()
