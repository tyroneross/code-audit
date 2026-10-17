"""Behavioral contracts for outcome decisions, artifact budgets and handoffs."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import audit
import planning


class RecommendationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'repo'
        self.root.mkdir()
        (self.root / 'app.py').write_text('amount_in_cents = 100\n')
        (self.root / 'before.txt').write_text('Fixture before: 12 ms; invalid input was accepted.\n')
        (self.root / 'after.txt').write_text('Fixture after: 8 ms; invalid input was rejected.\n')
        self.snapshot = self.base / 'snapshot'
        audit.prepare(self.root, self.snapshot)
        self.manifest, self.data = audit.snapshot_files(self.snapshot)
        self.ev = audit.locator(self.data, 'app.py', 1, 1)
        self.before = audit.locator(self.data, 'before.txt', 1, 1)
        self.after = audit.locator(self.data, 'after.txt', 1, 1)

    def report(self):
        report = audit.template(self.manifest, schema_version=2)
        report.update(review_state='complete', reviewer='Synthetic contract fixture', summary='Exercise output structure; no real performance gain claimed.')
        for row in report['assessments']:
            row.update(status='insufficient_evidence', explanation='This fixture does not establish the caller contract.', uncertainty='Actual requirements remain unknown.')
        report['objectives'] = [{'id': 'O1', 'dimension': 'correctness', 'operation': 'Validate an amount', 'desired_outcome': 'Reject invalid input before use', 'direction': 'contract', 'workload': 'One controlled invalid input', 'constraints': ['Preserve supported cents inputs'], 'baseline': {'state': 'observed', 'description': 'The fixture records an accepted invalid input.', 'evidence': [self.before]}, 'verification': {'method': 'Exercise the parser boundary', 'expected_outcome': 'Invalid input is rejected', 'boundary': 'Controlled fixture only'}}]
        report['recommendations'] = [{'id': 'R1', 'decision': 'change', 'priority': 'now', 'principles': ['P06'], 'objective_refs': ['O1'], 'finding_refs': [], 'best_practice': 'Establish the actual input invariant before using unchecked data', 'preferred_approach': 'Validate the actual input rule before using the amount', 'why_preferred': 'A local check addresses the required contract without another service', 'code_impact': {'claim': 'The checked input cannot enter the amount path unchecked', 'basis': 'expected', 'evidence': []}, 'user_impact': {'claim': 'The caller should receive an actionable input rejection', 'basis': 'expected', 'evidence': []}, 'tradeoff': 'Adds a rejection case the caller must handle', 'alternatives': [{'approach': 'Use an enforced checked amount type', 'prefer_when': 'Several operations share the same validated invariant', 'benefit': 'Centralizes the shared invariant', 'cost': 'Adds construction and conversion work'}], 'revisit_when': 'The input contract gains another unit or currency', 'evidence': [self.ev], 'verification': {'plan': 'Supply invalid and supported cents inputs', 'expected_outcome': 'Reject invalid input and preserve supported values', 'boundary': 'Controlled parser fixture', 'checks_run': []}, 'result': {'state': 'proposed', 'explanation': 'No product change is implemented by this synthetic test', 'before_evidence': [], 'after_evidence': []}, 'measurements': []}]
        return report

    def check(self, report, **kwargs):
        return audit.validate_report(self.snapshot, report, **kwargs)

    def verified(self):
        report = self.report()
        recommendation = report['recommendations'][0]
        recommendation['result'].update(state='verified', explanation='The controlled fixture records the required before and after outcomes.', before_evidence=[self.before], after_evidence=[self.after])
        recommendation['verification']['checks_run'] = [self.after]
        return report

    def quantitative(self):
        report = self.verified()
        goal = report['objectives'][0]
        goal.update(dimension='speed', direction='lower', workload='Identical controlled fixture inputs')
        report['recommendations'][0]['measurements'] = [{'objective_id': 'O1', 'unit': 'ms', 'workload': goal['workload'], 'method': 'Controlled fixture values, not a production benchmark', 'boundary': 'Synthetic contract test', 'before': 12, 'after': 8, 'uncertainty': 'These numbers only exercise the validator contract', 'evidence_before': [self.before], 'evidence_after': [self.after]}]
        return report

    def test_new_packet_is_v2_and_unfinished(self):
        packet = audit.load_json(self.snapshot / 'report-template.json')
        self.assertEqual(packet['schema_version'], 2)
        self.assertTrue(self.check(packet)['valid'])
        self.assertFalse(self.check(packet, require_complete=True)['valid'])

    def test_v2_contract_works_for_existing_file_loader_consumers(self):
        spec = importlib.util.spec_from_file_location('unregistered_audit_consumer', audit.__file__)
        loaded = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(loaded)
        checked = loaded.validate_report(self.snapshot, self.report(), require_complete=True, require_outcomes=True)
        self.assertTrue(checked['valid'], checked)
        self.assertIn('User impact', loaded.render_report(self.snapshot, self.report()))

    def test_public_cli_requires_outcomes_and_renders_v2_from_other_directory(self):
        path = self.base / 'v2-report.json'
        audit.write_json(path, self.report())
        command = [sys.executable, '-B', str(Path(audit.__file__)), 'validate', '--snapshot', str(self.snapshot), '--report', str(path), '--require-complete', '--require-outcomes']
        run = subprocess.run(command, cwd=self.base, capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        legacy = self.report()
        legacy['schema_version'] = 1
        del legacy['objectives'], legacy['recommendations']
        old = self.base / 'legacy.json'
        audit.write_json(old, legacy)
        command[command.index(str(path))] = str(old)
        run = subprocess.run(command, cwd=self.base, capture_output=True, text=True)
        self.assertEqual(run.returncode, 1, run.stderr)
        rendered = subprocess.run([sys.executable, '-B', str(Path(audit.__file__)), 'render', '--snapshot', str(self.snapshot), '--report', str(path), '--require-complete', '--require-outcomes'], cwd=self.base, capture_output=True, text=True)
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        self.assertIn('Applicable best practice', rendered.stdout)

    def test_legacy_v1_remains_supported_without_new_fields(self):
        report = self.report()
        report['schema_version'] = 1
        del report['objectives'], report['recommendations']
        checked = self.check(report, require_complete=True)
        self.assertTrue(checked['valid'], checked)
        self.assertFalse(self.check(report, require_outcomes=True)['valid'])
        self.assertIn('Legacy v1', audit.render_report(self.snapshot, report))
        self.assertEqual(audit.template(self.manifest)['schema_version'], 1)

    def test_complete_v2_requires_outcome_and_decision(self):
        for field in ('objectives', 'recommendations'):
            report = self.report()
            report[field] = []
            self.assertFalse(self.check(report)['valid'], field)
        self.assertTrue(self.check(self.report(), require_complete=True)['valid'])

    def test_impacts_and_preferred_reason_are_required(self):
        for field in ('code_impact', 'user_impact', 'why_preferred', 'tradeoff', 'revisit_when'):
            report = self.report()
            del report['recommendations'][0][field]
            self.assertFalse(self.check(report)['valid'], field)

    def test_observed_impact_needs_evidence_and_unknown_is_explicit(self):
        report = self.report()
        report['recommendations'][0]['user_impact']['basis'] = 'observed'
        self.assertFalse(self.check(report)['valid'])
        report['recommendations'][0]['user_impact'].update(basis='unknown', claim='Direct end-user impact is not established by this source.')
        self.assertTrue(self.check(report)['valid'])

    def test_proposal_can_have_unknown_baseline_but_verification_cannot(self):
        report = self.report()
        report['objectives'][0]['baseline'].update(state='unknown', description='A representative workload has not yet been observed.', evidence=[])
        self.assertTrue(self.check(report)['valid'])
        report['recommendations'][0].update(result=self.verified()['recommendations'][0]['result'], verification=self.verified()['recommendations'][0]['verification'])
        self.assertFalse(self.check(report)['valid'])

    def test_verified_change_needs_before_after_and_executed_check(self):
        self.assertTrue(self.check(self.verified())['valid'])
        for field in ('before_evidence', 'after_evidence'):
            report = self.verified()
            report['recommendations'][0]['result'][field] = []
            self.assertFalse(self.check(report)['valid'], field)
        report = self.verified()
        report['recommendations'][0]['verification']['checks_run'] = []
        self.assertFalse(self.check(report)['valid'])

    def test_verified_quantitative_claim_requires_improving_comparable_measurements(self):
        self.assertTrue(self.check(self.quantitative())['valid'])
        for mutate in ('missing', 'equal', 'worse', 'workload', 'boolean', 'infinite', 'uncited', 'objective'):
            report = self.quantitative()
            metric = report['recommendations'][0]['measurements'][0]
            if mutate == 'missing': report['recommendations'][0]['measurements'] = []
            elif mutate == 'equal': metric['after'] = metric['before']
            elif mutate == 'worse': metric['after'] = metric['before'] + 1
            elif mutate == 'workload': metric['workload'] = 'A different workload'
            elif mutate == 'boolean': metric['after'] = False
            elif mutate == 'infinite': metric['after'] = float('inf')
            elif mutate == 'uncited': metric['evidence_after'] = []
            else: metric['objective_id'] = 'missing'
            self.assertFalse(self.check(report)['valid'], mutate)

    def test_numeric_correctness_claim_also_requires_measurement(self):
        report = self.verified()
        report['objectives'][0]['direction'] = 'lower'
        self.assertFalse(self.check(report)['valid'])

    def test_large_integer_metrics_do_not_crash_the_validator(self):
        report = self.quantitative()
        metric = report['recommendations'][0]['measurements'][0]
        metric.update(before=2**10000, after=2**9999)
        self.assertTrue(self.check(report)['valid'])

    def test_keep_and_investigate_do_not_claim_verified_repairs(self):
        for decision in ('keep', 'investigate'):
            report = self.report()
            report['recommendations'][0].update(decision=decision)
            self.assertTrue(self.check(report)['valid'])
            report['recommendations'][0]['result']['state'] = 'verified'
            self.assertFalse(self.check(report)['valid'])

    def test_findings_need_linked_recommendations_and_cannot_be_hidden_as_keep(self):
        report = self.report()
        row = report['assessments'][5]
        row.update(status='violation', evidence_basis='source_observation', evidence=[self.ev], premises=['The actual caller accepts unchecked input.'])
        row['findings'] = [{'title': 'Fixture input contract', 'severity': 'medium', 'confidence': 'high', 'applicability': 'The fixture tests an unchecked input rule.', 'premises': ['The input has not been checked.'], 'evidence': [self.ev], 'consequence': 'Invalid input can enter the operation.', 'action': 'Check the actual boundary.', 'tradeoff': 'Adds an explicit rejection.', 'counterevidence': 'A caller check could make this unnecessary.', 'assumption_change': 'An enforced caller invariant changes the recommendation.', 'verification': copy.deepcopy(report['recommendations'][0]['verification'])}]
        self.assertFalse(self.check(report)['valid'])
        report['recommendations'][0]['finding_refs'] = [{'rule_id': 'P06', 'finding_index': 0}]
        self.assertTrue(self.check(report)['valid'])
        report['recommendations'][0]['decision'] = 'keep'
        self.assertFalse(self.check(report)['valid'])

    def test_unknown_fields_duplicate_ids_and_tampered_evidence_are_rejected(self):
        for mutate in ('field', 'id', 'evidence'):
            report = self.report()
            if mutate == 'field': report['recommendations'][0]['hidden_score'] = 100
            elif mutate == 'id': report['objectives'].append(copy.deepcopy(report['objectives'][0]))
            else: report['recommendations'][0]['evidence'][0]['excerpt'] = 'invented'
            self.assertFalse(self.check(report)['valid'], mutate)

    def test_render_preserves_impacts_alternatives_results_and_safe_text(self):
        report = self.quantitative()
        report['recommendations'][0]['user_impact']['claim'] = '<script>context</script>'
        text = audit.render_report(self.snapshot, report)
        for phrase in ('Code impact (expected)', 'User impact (expected)', 'Why preferred here', 'Alternatives', 'Recorded measurement', 'uncertainty', self.before['file_sha256']):
            self.assertIn(phrase, text)
        self.assertNotIn('<script>', text)

    def test_plan_handoff_preserves_context_locators_and_decision_references(self):
        plan = planning.template(self.snapshot, 'Preserve fixture amount units')
        plan['context'] = [{'fact': 'The fixture amount is in cents.', 'basis': 'source', 'evidence': [self.ev]}]
        text = planning.render(self.snapshot, plan)
        self.assertIn('app.py:1-1', text)
        self.assertIn(self.ev['file_sha256'], text)
        self.assertIn(self.ev['content_sha256'], text)

    def test_generated_json_checks_utf8_byte_budget_before_creating_output(self):
        value = {'description': 'é' * 20}
        size = len((json.dumps(value, indent=2, ensure_ascii=False) + '\n').encode())
        path = self.base / 'oversize.json'
        with patch.object(audit, 'MAX_JSON_BYTES', size - 1):
            with self.assertRaises(audit.AuditError): audit.write_json(path, value)
        self.assertFalse(path.exists())
        with patch.object(audit, 'MAX_JSON_BYTES', size): audit.write_json(path, value)
        self.assertEqual(path.stat().st_size, size)

    def test_default_long_path_collection_rejects_unreadable_metadata_instead_of_success(self):
        root = self.base / 'long-repo'
        root.mkdir()
        deep = root
        for i in range(3):
            deep = deep / (str(i) + 'd' * 199)
            deep.mkdir()
        for i in range(9900): (deep / (f'{i:05}_' + 'f' * 230 + '.py')).touch()
        out = self.base / 'long-snapshot'
        run = subprocess.run([sys.executable, '-B', str(Path(audit.__file__)), 'prepare', '--root', str(root), '--out', str(out)], capture_output=True, text=True)
        self.assertEqual(run.returncode, 2, run.stdout + run.stderr)
        self.assertIn('reader byte limit', json.loads(run.stderr)['error'])
        self.assertFalse((out / 'manifest.json').exists())
        self.assertFalse((out / 'report-template.json').exists())


if __name__ == '__main__':
    unittest.main()
