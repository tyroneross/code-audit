"""sync_hosts.py against a fake home folder; never touches the real one."""
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import sync_hosts  # noqa: E402


class SyncHosts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        for d in ('.claude', '.cursor', '.gemini', '.agents'):
            (self.home / d).mkdir()
        (self.home / '.claude' / 'settings.json').write_text(json.dumps({'enabledPlugins': {'other@x': True}, 'theme': 'dark'}))
        (self.home / '.gemini' / 'settings.json').write_text(json.dumps({'ui': {'theme': 'x'}}))
        self.patch = mock.patch.object(Path, 'home', return_value=self.home)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def run_main(self, *args):
        out = StringIO()
        with redirect_stdout(out):
            code = sync_hosts.main(['--skip-codex', *args])
        return code, out.getvalue()

    def test_check_reports_drift_and_changes_nothing(self):
        before = (self.home / '.claude' / 'settings.json').read_text()
        code, out = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn('register marketplace code-audit-local', out)
        self.assertEqual((self.home / '.claude' / 'settings.json').read_text(), before)
        self.assertFalse((self.home / '.agents' / 'skills').exists())

    def test_apply_installs_everywhere_keeps_other_settings_and_is_idempotent(self):
        self.assertEqual(self.run_main('--apply')[0], 0)
        s = json.loads((self.home / '.claude' / 'settings.json').read_text())
        self.assertTrue(s['enabledPlugins']['code-audit@code-audit-local'])
        self.assertTrue(s['enabledPlugins']['other@x'])
        self.assertEqual(s['theme'], 'dark')
        self.assertEqual(s['extraKnownMarketplaces']['code-audit-local']['source']['path'], str(sync_hosts.REPO))
        self.assertEqual(json.loads((self.home / '.gemini' / 'settings.json').read_text())['ui'], {'theme': 'x'})
        for folder in ('.cursor/skills', '.agents/skills'):
            for name in sync_hosts.skills():
                self.assertEqual(Path(os.readlink(self.home / folder / name)), sync_hosts.REPO / 'skills' / name)
        self.assertTrue(list((self.home / '.claude').glob('settings.json.bak-*')))
        code, out = self.run_main()
        self.assertEqual(code, 0, out)

    def test_existing_unrelated_skill_is_left_alone(self):
        (self.home / '.agents' / 'skills').mkdir()
        (self.home / '.agents' / 'skills' / 'plan').mkdir()
        _, out = self.run_main('--apply')
        self.assertIn('CONFLICT', out)
        self.assertFalse((self.home / '.agents' / 'skills' / 'plan').is_symlink())

    def test_retire_removes_only_links_into_retired_repo(self):
        skills = self.home / '.claude' / 'skills'
        skills.mkdir()
        (skills / 'code-principles').symlink_to('/nowhere/code-principles-audit/skills/code-principles')
        (skills / 'keep').symlink_to('/nowhere/other/skills/keep')
        self.run_main('--apply', '--retire')
        self.assertFalse((skills / 'code-principles').is_symlink())
        self.assertTrue((skills / 'keep').is_symlink())


if __name__ == '__main__':
    unittest.main()
