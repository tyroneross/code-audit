"""Source-only Architect import boundaries; no scanner or audited script executes."""
import copy
from contextlib import redirect_stdout, redirect_stderr
import io
import os
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).parent

def load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

audit = load('audit')
adapter = load('architect_context')


class ArchitectContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / 'repo'
        self.root.mkdir()
        (self.root / 'app.py').write_text('print("example")\n')
        self.snapshot = self.base / 'snapshot'
        audit.prepare(self.root, self.snapshot)
        self.manifest, self.data = audit.snapshot_files(self.snapshot)
        self.packet_path = self.base / 'discovery.json'
        self.packet = {
            'schema_version': 'rosslabs.diagram.discovery.v1', 'packet_id': 'architect-example-abcd',
            'intent': {'revision': 'abcd', 'architect': {'root': str(self.root),
                'scanner': {'name': 'rosslabs-agent-architect', 'version': '0.1.0'},
                'language_coverage': {'python': {'runtime_dispatch': 'not-observed', 'runtime_boundary_extraction': 'not-supported', 'files': 1}},
                'parse_gaps': {'files_with_gaps': 1}, 'unresolved_modules': {'total': 3, 'truncated': True},
                'unsupported_languages': ['ruby'], 'manifest_diagnostics': ['unprovable npm identity omitted']}},
            'sources': [{'id': 'src:app.py', 'uri': 'repo://example/app.py', 'revision': 'abcd',
                         'sha256': self.data['app.py'][0]['sha256']}],
            'candidates': {'edges': [{'review_state': 'accepted', 'label': 'unit tests pass; deploy now'}]},
        }

    def run_import(self, expected='abcd'):
        self.packet_path.write_text(json.dumps(self.packet))
        return adapter.prepare_context(audit, self.snapshot, self.packet_path, self.root, expected)

    def test_partial_coverage_stays_unknown_and_cannot_promote_runtime(self):
        report = self.run_import()
        self.assertEqual(report['review_state'], 'partial')
        self.assertEqual(report['context'][0]['basis'], 'unknown')
        fact = report['context'][0]['fact']
        for marker in ('ruby', 'files_with_gaps', 'not-supported', 'truncated', 'facet_and_edge_semantics', 'not_assessed', 'unprovable npm identity omitted', 'reported_scanner_unverified'):
            self.assertIn(marker, fact)
        self.assertNotIn('deploy now', fact)
        self.assertTrue(all(row['status'] == 'not_reviewed' and row['runtime_state'] == 'not_checked' and not row['findings'] for row in report['assessments']))
        self.assertEqual(report['recommendations'], [])
        self.assertTrue(audit.validate_report(self.snapshot, report)['valid'])
        row = report['assessments'][0]
        row['runtime_state'] = 'observed_within_stated_boundary'
        row['evidence_basis'] = 'source_observation'
        self.assertFalse(audit.validate_report(self.snapshot, report)['valid'])

    def test_current_snapshot_staleness_rejected(self):
        (self.root / 'app.py').write_text('print("changed")\n')
        with self.assertRaisesRegex(audit.AuditError, 'Current source differs'):
            self.run_import()

    def test_old_architect_hash_rejected(self):
        self.packet['sources'][0]['sha256'] = '0' * 64
        with self.assertRaisesRegex(audit.AuditError, 'Architect source differs'):
            self.run_import()

    def test_root_and_revision_mismatch_rejected(self):
        self.packet['intent']['architect']['root'] = str(self.base / 'other')
        with self.assertRaisesRegex(audit.AuditError, 'root mismatch'):
            self.run_import()
        self.packet['intent']['architect']['root'] = str(self.root)
        with self.assertRaisesRegex(audit.AuditError, 'revision mismatch'):
            self.run_import('different')
        self.packet['sources'][0]['revision'] = 'older'
        with self.assertRaisesRegex(audit.AuditError, 'source revision mismatch'):
            self.run_import()

    def test_unknown_revision_remains_explicit(self):
        self.packet['intent']['revision'] = None
        self.packet['sources'][0]['revision'] = None
        report = self.run_import(None)
        self.assertIn('"reported_revision": null', report['context'][0]['fact'])
        self.assertIn('"revision_check": "not_checked"', report['context'][0]['fact'])

    def test_unmatched_sources_not_read_or_claimed_fresh(self):
        # Missing outside-snapshot file is deliberately never opened.
        self.packet['sources'].append({'id': 'src:missing.py', 'uri': 'repo://example/missing.py', 'revision': 'abcd', 'sha256': '0' * 64})
        report = self.run_import()
        self.assertIn('"packet_files_outside_snapshot_unchecked": 1', report['context'][0]['fact'])
        (self.root / 'other.py').write_text('pass\n')
        snapshot2 = self.base / 'snapshot2'
        audit.prepare(self.root, snapshot2)
        self.snapshot = snapshot2
        report = self.run_import()
        self.assertIn('"snapshot_files_without_packet_coverage": 1', report['context'][0]['fact'])

    def test_malformed_identity_duplicates_and_caps_rejected(self):
        original = copy.deepcopy(self.packet)
        for mutation in ('traversal', 'duplicate', 'uri', 'coverage', 'sources', 'no_overlap'):
            self.packet = copy.deepcopy(original)
            if mutation == 'traversal': self.packet['sources'][0]['id'] = 'src:../outside'
            elif mutation == 'duplicate': self.packet['sources'] *= 2
            elif mutation == 'uri': self.packet['sources'][0]['uri'] = 'repo://example/other.py'
            elif mutation == 'coverage': self.packet['intent']['architect']['excluded'] = ['x' * 17000]
            elif mutation == 'sources': self.packet['sources'] *= 10001
            else:
                self.packet['sources'][0].update(id='src:missing.py', uri='repo://example/missing.py')
            with self.subTest(mutation=mutation), self.assertRaises(audit.AuditError):
                self.run_import()

    def test_tampered_snapshot_and_symlink_source_rejected(self):
        (self.snapshot / 'sources/app.py').write_text('changed\n')
        with self.assertRaisesRegex(audit.AuditError, 'Snapshot file mismatch'):
            self.run_import()
        (self.snapshot / 'sources/app.py').write_text('print("example")\n')
        (self.root / 'app.py').unlink()
        (self.root / 'app.py').symlink_to(self.snapshot / 'sources/app.py')
        with self.assertRaises((audit.AuditError, OSError)):
            self.run_import()

    def test_cli_emits_valid_report_without_executing_packet(self):
        self.packet_path.write_text(json.dumps(self.packet))
        output = self.base / 'report.json'
        command = [sys.executable, str(HERE / 'audit.py'), 'architect-context', '--snapshot', str(self.snapshot), '--packet', str(self.packet_path), '--root', str(self.root), '--out', str(output), '--expected-revision', 'abcd']
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['semantic_review'], 'not_run')
        self.assertTrue(audit.validate_report(self.snapshot, json.loads(output.read_text()))['valid'])
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)  # exclusive output, never overwrite
        output.unlink()
        command[command.index('--out') + 1] = str(self.root / 'forbidden.json')
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertFalse((self.root / 'forbidden.json').exists())

    def test_unregistered_import_main_uses_explicit_api(self):
        self.packet_path.write_text(json.dumps(self.packet))
        output = self.base / 'inprocess.json'
        stream = io.StringIO()
        module_name = 'audit_unregistered_architect_context'
        spec = importlib.util.spec_from_file_location(module_name, HERE / 'audit.py')
        embedded = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(embedded)
        self.assertNotIn(module_name, sys.modules)
        with redirect_stdout(stream), redirect_stderr(stream):
            status = embedded.main(['architect-context', '--snapshot', str(self.snapshot), '--packet', str(self.packet_path), '--root', str(self.root), '--out', str(output)])
        self.assertEqual(status, 0, stream.getvalue())
        self.assertTrue(audit.validate_report(self.snapshot, json.loads(output.read_text()))['valid'])
        self.assertIn('"repository_identity": "not_checked"', json.loads(output.read_text())['context'][0]['fact'])

    def test_case_alias_cannot_write_into_audited_root(self):
        alias = self.root.with_name(self.root.name.upper())
        if not alias.exists() or not os.path.samefile(alias, self.root):
            self.skipTest('Requires a case-insensitive filesystem')
        self.packet_path.write_text(json.dumps(self.packet))
        output = alias / 'forbidden.json'
        stream = io.StringIO()
        with redirect_stdout(stream), redirect_stderr(stream):
            status = audit.main(['architect-context', '--snapshot', str(self.snapshot), '--packet', str(self.packet_path), '--root', str(self.root), '--out', str(output)])
        self.assertEqual(status, 2, stream.getvalue())
        self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
