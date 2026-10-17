"""Behavioral regressions for large-review coverage and contextual planning."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import audit
import campaign
import planning


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'repository'
        self.root.mkdir()
        (self.root / 'app.py').write_text('amount_in_cents = 100\n')
        self.session = self.base / 'session'

    def start(self, **kwargs):
        value = campaign.create(self.root, self.session, **kwargs)
        return value, self.session / 'inventory.json'

    def review(self, value, inventory):
        snapshot = self.session / 'batch'
        campaign.batch(inventory, value['batches'][0]['id'], self.root, snapshot)
        manifest, data = audit.snapshot_files(snapshot)
        report = audit.template(manifest)
        report.update(review_state='complete', reviewer='Fixture reviewer', summary='Scoped source review; remaining contracts are unknown.')
        for row in report['assessments']:
            row.update(status='insufficient_evidence', applicability='Need the relevant caller contract.', explanation='Source alone does not establish the required behavior.', counterevidence='The collected source was inspected.', uncertainty='Caller context remains unknown.', assumption_change='A caller contract would resolve applicability.')
        report['assessments'][0]['evidence'] = [audit.locator(data, path, 1, 1) for path in data if data[path][0]['lines']]
        audit.write_json(self.session / 'report.json', report)
        ledger = {'inventory_id': value['inventory_id'], 'reviews': [{'snapshot': 'batch', 'report': 'report.json', 'reviewed_files': list(data)}]}
        audit.write_json(self.session / 'reviews.json', ledger)
        return snapshot, report, ledger

    def test_inventory_exceeds_old_snapshot_file_cap_and_obeys_batch_budgets(self):
        for i in range(330):
            (self.root / f'file_{i:03}.py').write_text(f'number = {i}\n')
        value, path = self.start(batch_files=17, batch_bytes=400)
        self.assertEqual(len(value['files']), 331)
        self.assertTrue(value['discovery_complete'])
        assigned = [p for b in value['batches'] for p in b['paths']]
        self.assertEqual(len(assigned), len(set(assigned)))
        self.assertEqual(set(assigned), {r['path'] for r in value['files']})
        self.assertTrue(all(len(b['paths']) <= 17 and b['bytes'] <= 400 for b in value['batches']))
        self.assertEqual(campaign.read_inventory(path), value)

    def test_signals_are_observations_and_source_is_not_executed(self):
        marker = self.base / 'executed'
        (self.root / 'unsafe.py').write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\ntry:\n    work()\nexcept Exception:\n    pass\nasyncio.create_task(job())\n")
        value, _ = self.start(python_signals=True)
        signals = next(f['signals'] for f in value['files'] if f['path'] == 'unsafe.py')
        self.assertEqual({s['kind'] for s in signals['observations']}, {'broad_exception_handler', 'pass_only_handler', 'possible_background_task'})
        self.assertFalse(marker.exists())
        self.assertNotIn('violation', json.dumps(signals))

    def test_signal_truncation_and_parse_failure_are_explicit(self):
        signals = campaign.python_observations('try:\n    x()\nexcept:\n    pass\n', 1)
        self.assertEqual(len(signals['observations']), 1)
        self.assertEqual(signals['omitted_observations'], 1)
        self.assertEqual(campaign.python_observations('broken = (', 5)['observations'][0]['kind'], 'parse_unavailable')

    def test_exclusions_do_not_follow_symlinks_or_expose_secret_contents(self):
        outside = self.base / 'outside.py'
        outside.write_text('private_outside_marker = 1\n')
        (self.root / 'link.py').symlink_to(outside)
        (self.root / '.env').write_text('DO_NOT_EXPORT = 1')
        (self.root / 'opaque.dat').write_bytes(b'\x00binary')
        hidden = self.root / 'node_modules'
        hidden.mkdir()
        (hidden / 'dependency.js').write_text('const x = 1;')
        value, _ = self.start()
        self.assertEqual([r['path'] for r in value['files']], ['app.py'])
        self.assertTrue(value['discovery_complete'])
        reasons = {r['path']: r['reason'] for r in value['omissions']}
        self.assertEqual(reasons['link.py'], 'symlink')
        self.assertEqual(reasons['opaque.dat'], 'binary_or_non_utf8')
        self.assertNotIn('private_outside_marker', json.dumps(value))

    def test_enumeration_limit_stays_partial(self):
        for i in range(10):
            (self.root / str(i)).write_text('value\n')
        value, path = self.start(max_entries=3)
        self.assertFalse(value['discovery_complete'])
        result = campaign.progress(path, self.session / 'reviews-template.json', self.root)
        self.assertFalse(result['selected_inventory_review_complete'])

    def test_batch_rejects_source_changed_since_inventory(self):
        value, path = self.start()
        (self.root / 'app.py').write_text('changed = True\n')
        with self.assertRaises(audit.AuditError):
            campaign.batch(path, value['batches'][0]['id'], self.root, self.session / 'stale')

    def test_explicit_context_can_expand_primary_batch(self):
        (self.root / 'README.md').write_text('Caller contract\n')
        value, path = self.start(batch_files=1)
        manifest = campaign.batch(path, value['batches'][0]['id'], self.root, self.session / 'batch', ['app.py'])
        self.assertEqual(len(manifest['files']), 2)

    def test_review_progress_is_resumable_and_requires_current_inventory(self):
        value, path = self.start()
        self.review(value, path)
        result = campaign.progress(path, self.session / 'reviews.json')
        self.assertEqual(result['agent_attested_reviewed_files'], 1)
        self.assertFalse(result['selected_inventory_review_complete'])
        result = campaign.progress(path, self.session / 'reviews.json', self.root)
        self.assertTrue(result['selected_inventory_review_complete'])
        (self.root / 'new.py').write_text('new = 1\n')
        result = campaign.progress(path, self.session / 'reviews.json', self.root)
        self.assertEqual(result['added_files'], ['new.py'])
        self.assertFalse(result['selected_inventory_review_complete'])

    def test_review_progress_detects_changed_and_deleted_sources(self):
        value, path = self.start()
        self.review(value, path)
        (self.root / 'app.py').write_text('changed = 2\n')
        self.assertEqual(campaign.progress(path, self.session / 'reviews.json', self.root)['changed_files'], ['app.py'])
        (self.root / 'app.py').unlink()
        self.assertEqual(campaign.progress(path, self.session / 'reviews.json', self.root)['deleted_files'], ['app.py'])

    def test_review_attestation_without_actual_citation_is_rejected(self):
        value, path = self.start()
        _, report, _ = self.review(value, path)
        report['assessments'][0]['evidence'] = []
        (self.session / 'report.json').write_text(json.dumps(report))
        with self.assertRaises(audit.AuditError):
            campaign.progress(path, self.session / 'reviews.json')

    def test_partial_reports_do_not_count_as_complete_coverage(self):
        value, path = self.start()
        snapshot, _, _ = self.review(value, path)
        manifest, _ = audit.snapshot_files(snapshot)
        (self.session / 'report.json').write_text(json.dumps(audit.template(manifest)))
        with self.assertRaises(audit.AuditError):
            campaign.progress(path, self.session / 'reviews.json')

    def test_review_artifact_escape_and_tampered_inventory_rejected(self):
        value, path = self.start()
        _, _, ledger = self.review(value, path)
        ledger['reviews'][0]['report'] = '../outside.json'
        (self.session / 'reviews.json').write_text(json.dumps(ledger))
        with self.assertRaises(audit.AuditError):
            campaign.progress(path, self.session / 'reviews.json')
        value['files'][0]['path'] = '../outside.py'
        value['inventory_id'] = audit.digest(audit.canonical({k: v for k, v in value.items() if k != 'inventory_id'}))
        path.write_text(json.dumps(value))
        with self.assertRaises(audit.AuditError):
            campaign.read_inventory(path)

    def test_directory_or_file_changed_to_symlink_is_not_read(self):
        outside = self.base / 'outside.py'
        outside.write_text('outside_private = 1\n')
        original = audit.safe_read

        def swap(root, rel, limit):
            if rel == 'app.py':
                (self.root / rel).unlink()
                (self.root / rel).symlink_to(outside)
            return original(root, rel, limit)

        with patch.object(audit, 'safe_read', side_effect=swap):
            value = campaign.inventory(self.root)
        self.assertFalse(value['discovery_complete'])
        self.assertEqual(value['files'], [])

    def plan_fixture(self):
        snapshot = self.base / 'snapshot'
        audit.prepare(self.root, snapshot)
        value = planning.template(snapshot, 'Preserve amount units across a parser change')
        _, data = audit.snapshot_files(snapshot)
        value.update(scope=['app.py'], acceptance=['The returned amount remains in cents.'], context=[{'fact': 'The source amount is explicitly in cents.', 'basis': 'source', 'evidence': [audit.locator(data, 'app.py', 1, 1)]}])
        for decision in value['decisions']:
            decision.update(disposition='exclude', reason='This fixture makes no change to the operation described by this principle.', context_refs=[0])
        value['decisions'][5].update(disposition='apply', reason='The input and output must preserve the cents unit.', premises=['The input unit is cents.'], approach='Keep the explicit unit name and validate the actual parser boundary.', tradeoff='An enforced wrapper type is not justified by this single local value.', revisit_when='Another currency or unit crosses the public boundary.', verification={'plan': 'Supply a known cents amount to the parser.', 'expected_outcome': '100 cents returns 100 cents without conversion.', 'boundary': 'Parser input and returned value, not provider execution.'})
        value['steps'] = [{'id': 'S1', 'action': 'Preserve the parser value and inspect the unit boundary.', 'paths': ['app.py'], 'principles': ['P06']}]
        return snapshot, value

    def test_plan_template_cannot_pass_before_contextual_decisions(self):
        snapshot, _ = self.plan_fixture()
        empty = planning.template(snapshot, 'Change a parser')
        self.assertTrue(planning.validate(snapshot, empty)['valid'])
        result = planning.validate(snapshot, empty, require_ready=True)
        self.assertFalse(result['valid'])
        self.assertEqual(len(result['unresolved']), 30)

    def test_plan_requires_real_step_integration_not_rule_mentions(self):
        snapshot, value = self.plan_fixture()
        self.assertTrue(planning.validate(snapshot, value, True, self.root)['ready'])
        value['steps'][0]['principles'] = []
        self.assertFalse(planning.validate(snapshot, value, True)['valid'])

    def test_plan_rejects_missing_rationale_tradeoff_or_verification(self):
        snapshot, value = self.plan_fixture()
        for field in ('reason', 'approach', 'tradeoff', 'revisit_when'):
            modified = copy.deepcopy(value)
            modified['decisions'][5][field] = ''
            self.assertFalse(planning.validate(snapshot, modified, True)['valid'], field)
        value['decisions'][5]['verification']['expected_outcome'] = ''
        self.assertFalse(planning.validate(snapshot, value, True)['valid'])

    def test_unknown_context_cannot_justify_apply_or_exclude(self):
        snapshot, value = self.plan_fixture()
        value['context'][0]['basis'] = 'unknown'
        self.assertFalse(planning.validate(snapshot, value, True)['valid'])

    def test_source_citation_and_catalog_cannot_be_fabricated(self):
        snapshot, value = self.plan_fixture()
        modified = copy.deepcopy(value)
        modified['context'][0]['evidence'][0]['excerpt'] = 'invented'
        self.assertFalse(planning.validate(snapshot, modified, True)['valid'])
        value['catalog_sha256'] = '0' * 64
        self.assertFalse(planning.validate(snapshot, value, True)['valid'])

    def test_plan_scope_and_current_source_are_checked(self):
        snapshot, value = self.plan_fixture()
        modified = copy.deepcopy(value)
        modified['steps'][0]['paths'] = ['other.py']
        self.assertFalse(planning.validate(snapshot, modified, True)['valid'])
        (self.root / 'app.py').write_text('different = 1\n')
        self.assertFalse(planning.validate(snapshot, value, True, self.root)['valid'])

    def test_rendered_plan_contains_why_options_assumption_changes_and_boundary(self):
        snapshot, value = self.plan_fixture()
        text = planning.render(snapshot, value, True, self.root)
        for phrase in ('Why the principle exists', 'Other options and costs', 'If underlying assumptions change', 'Our relevant context', 'Chosen approach', 'Expected observation', 'Boundary'):
            self.assertIn(phrase, text)
        self.assertIn('Structural readiness: ready', text)
        self.assertIn('P05 (exclude)', text)

    def test_preparation_does_not_write_to_source_or_snapshot(self):
        snapshot, _ = self.plan_fixture()
        for out in (self.root / 'plan', snapshot / 'plan'):
            with self.assertRaises(audit.AuditError):
                planning.prepare(snapshot, 'Change a parser', out, self.root)
        out = self.base / 'plan'
        value = planning.prepare(snapshot, 'Change a parser', out, self.root)
        self.assertEqual(len(value['decisions']), 30)
        self.assertTrue((out / 'context.md').exists())

    def test_compact_handoff_keeps_decisions_evidence_and_verification(self):
        snapshot, value = self.plan_fixture()
        full = planning.render(snapshot, value, True, self.root)
        compact = planning.render(snapshot, value, True, self.root, compact=True)
        self.assertLess(len(compact.encode('utf-8')), len(full.encode('utf-8')))
        decision = value['decisions'][5]
        for text in (decision['reason'], decision['approach'], decision['tradeoff'], decision['revisit_when'], decision['verification']['plan'], decision['verification']['expected_outcome'], decision['verification']['boundary'], value['context'][0]['evidence'][0]['file_sha256'], 'P05 (exclude)', 'unsafe uses and unsupported claims', 'P06.md'):
            self.assertIn(text, compact)
        self.assertTrue((audit.REFERENCES / 'cards/P06.md').is_file())
        path = self.base / 'compact-plan.json'
        audit.write_json(path, value)
        run = subprocess.run([sys.executable, '-B', str(Path(planning.__file__)), 'render', '--snapshot', str(snapshot), '--plan', str(path), '--require-ready', '--check-current-root', str(self.root), '--compact'], cwd=self.base, capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(run.stdout, compact)

    def test_cli_works_from_an_unrelated_directory_and_rejects_unready_plan(self):
        snapshot, _ = self.plan_fixture()
        plan = self.base / 'plan.json'
        plan.write_text(json.dumps(planning.template(snapshot, 'Change a parser')))
        result = subprocess.run([sys.executable, str(Path(planning.__file__)), 'check', '--snapshot', str(snapshot), '--plan', str(plan), '--require-ready'], cwd=self.base, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse(json.loads(result.stdout)['ready'])

    def test_empty_files_can_be_attested_without_fabricated_line_citations(self):
        (self.root / 'empty.py').write_text('')
        value, path = self.start()
        self.review(value, path)
        self.assertTrue(campaign.progress(path, self.session / 'reviews.json', self.root)['selected_inventory_review_complete'])

    def test_source_byte_budget_keeps_discovery_partial(self):
        (self.root / 'large.py').write_text('value = 123456789\n' * 20)
        value, _ = self.start(max_file_bytes=100)
        self.assertFalse(value['discovery_complete'])
        self.assertTrue(any(o['reason'] == 'file_byte_budget' for o in value['omissions']))

    def test_single_entry_skill_and_demoted_workflows(self):
        package = Path(audit.__file__).resolve().parents[3]
        entry = package / 'skills' / 'code-audit' / 'SKILL.md'
        self.assertIn('name: code-audit', entry.read_text())
        self.assertTrue((audit.REFERENCES / 'cards' / 'P19.md').is_file())
        for name in ('audit', 'plan', 'improve'):
            text = (package / 'skills' / name / 'SKILL.md').read_text()
            self.assertIn('user-invocable: false', text.split('---')[1])
        self.assertFalse((package / 'agent-skills').exists())
        self.assertTrue((audit.REFERENCES / 'reviewer-role.md').is_file())
        self.assertIn('No execution authority', json.dumps(planning.validate(self.plan_fixture()[0], {})))


if __name__ == '__main__':
    unittest.main()
