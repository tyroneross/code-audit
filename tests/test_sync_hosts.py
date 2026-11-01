"""sync_hosts.py against a fake home folder; never touches the real one."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import sync_hosts  # noqa: E402


def done(stdout='', returncode=0):
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr='')


class SyncHosts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        for d in ('.claude', '.cursor', '.gemini', '.agents'):
            (self.home / d).mkdir()
        self.claude = self.home / '.claude' / 'settings.json'
        self.claude.write_text(json.dumps({'enabledPlugins': {'other@x': True}, 'theme': 'dark'}))
        (self.home / '.gemini' / 'settings.json').write_text(json.dumps({'ui': {'theme': 'x'}}))
        self.patch = mock.patch.object(Path, 'home', return_value=self.home)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def run_main(self, *args, run=None):
        out = StringIO()
        argv = ['--repo', str(ROOT), *args] + ([] if run else ['--skip-codex'])
        with redirect_stdout(out):
            code = sync_hosts.main(argv, run=run or subprocess.run)
        return code, out.getvalue()

    def test_check_reports_drift_and_changes_nothing(self):
        before = self.claude.read_text()
        code, out = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn('register marketplace code-audit-local', out)
        self.assertEqual(self.claude.read_text(), before)
        self.assertFalse((self.home / '.agents' / 'skills').exists())

    def test_apply_installs_everywhere_keeps_other_settings_and_is_idempotent(self):
        self.assertEqual(self.run_main('--apply')[0], 0)
        s = json.loads(self.claude.read_text())
        self.assertTrue(s['enabledPlugins']['code-audit@code-audit-local'])
        self.assertTrue(s['enabledPlugins']['other@x'])
        self.assertEqual(s['theme'], 'dark')
        self.assertEqual(json.loads((self.home / '.gemini' / 'settings.json').read_text())['ui'], {'theme': 'x'})
        for folder in ('.cursor/skills', '.agents/skills'):
            for name in sync_hosts.skills(ROOT):
                self.assertEqual(sync_hosts.target_of(self.home / folder / name), ROOT / 'skills' / name)
        self.assertTrue(list((self.home / '.claude').glob('settings.json.bak-*')))
        code, out = self.run_main()
        self.assertEqual(code, 0, out)
        self.assertIn('everything is in sync', out)

    def test_existing_unrelated_skill_blocks_and_is_left_alone(self):
        (self.home / '.agents' / 'skills' / 'plan').mkdir(parents=True)
        code, out = self.run_main('--apply')
        self.assertEqual(code, 1)
        self.assertIn('BLOCKED', out)
        self.assertFalse((self.home / '.agents' / 'skills' / 'plan').is_symlink())

    def test_memory_server_update_keeps_user_fields(self):
        (self.home / '.cursor' / 'mcp.json').write_text(json.dumps({'mcpServers': {'code-audit-debugger': {
            'command': 'node', 'args': ['/old/path.cjs'], 'env': {'X': '1'}, 'disabled': False}}}))
        self.run_main('--apply')
        entry = json.loads((self.home / '.cursor' / 'mcp.json').read_text())['mcpServers']['code-audit-debugger']
        self.assertEqual(entry['args'], [str(ROOT / 'scripts' / 'debugger-server.cjs')])
        self.assertEqual(entry['env'], {'X': '1'})
        self.assertIn('disabled', entry)

    def test_non_json_or_symlinked_config_is_left_untouched(self):
        jsonc = '{\n  // comment\n  "a": 1,\n}\n'
        (self.home / '.cursor' / 'mcp.json').write_text(jsonc)
        real = self.home / 'real-gemini.json'
        real.write_text('{}')
        (self.home / '.gemini' / 'settings.json').unlink()
        (self.home / '.gemini' / 'settings.json').symlink_to(real)
        code, out = self.run_main('--apply')
        self.assertEqual(code, 1)
        self.assertEqual((self.home / '.cursor' / 'mcp.json').read_text(), jsonc)
        self.assertTrue((self.home / '.gemini' / 'settings.json').is_symlink())
        self.assertEqual(real.read_text(), '{}')

    def test_config_changed_during_run_is_not_overwritten(self):
        original_write = sync_hosts.Config.write
        def racing_write(cfg):
            cfg.path.write_text(json.dumps({'edited': 'by someone else'}))
            return original_write(cfg)
        with mock.patch.object(sync_hosts.Config, 'write', racing_write):
            code, out = self.run_main('--apply')
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(self.claude.read_text()), {'edited': 'by someone else'})

    def test_cleanup_never_touches_links_outside_owned_roots(self):
        shared = self.home / '.agents' / 'skills'
        shared.mkdir(parents=True)
        (shared / 'escape').symlink_to(str(ROOT / 'skills' / '..' / '..' / 'unrelated' / 'missing'))
        (shared / 'sibling').symlink_to(str(ROOT) + '/skills-other/missing')
        claude_skills = self.home / '.claude' / 'skills'
        claude_skills.mkdir()
        (claude_skills / 'retired').symlink_to(str(ROOT.parent / 'code-principles-audit' / 'skills' / 'code-principles'))
        (claude_skills / 'same-name-elsewhere').symlink_to('/elsewhere/code-principles-audit/skills/x')
        (claude_skills / 'dotdot').symlink_to(str(ROOT.parent / 'code-principles-audit' / '..' / 'keep'))
        self.run_main('--apply', '--retire')
        for kept in (shared / 'escape', shared / 'sibling', claude_skills / 'same-name-elsewhere', claude_skills / 'dotdot'):
            self.assertTrue(kept.is_symlink(), kept)
        self.assertFalse((claude_skills / 'retired').is_symlink())

    def test_codex_wrong_source_blocks_and_failure_is_reported(self):
        (self.home / '.codex').mkdir()
        with mock.patch.object(sync_hosts.shutil, 'which', return_value='/bin/codex'):
            listing = 'Marketplace `code-audit-local`\n/old/checkout/.agents/plugins/marketplace.json\n'
            code, out = self.run_main('--apply', run=lambda *a, **k: done(listing))
            self.assertEqual(code, 1)
            self.assertIn('not ' + str(ROOT), out)
            listing = f'Marketplace `code-audit-local-backup`\n/other\n'
            calls = []
            def fake(cmd, **k):
                calls.append(cmd[2:])
                return done(listing) if cmd[2:4] == ['marketplace', 'list'] else done('', 1)
            code, out = self.run_main('--apply', run=fake)
            self.assertIn(['marketplace', 'add', str(ROOT)], calls)
            self.assertEqual(code, 1)
            self.assertIn('failed', out)


    def codex_fake(self, listing, installed, fail=()):
        calls = []
        def fake(cmd, **k):
            sub = cmd[2:]
            calls.append(sub)
            if sub[:1] and sub[0] in fail or ' '.join(sub[:2]) in fail:
                return done('', 1)
            if sub[:2] == ['marketplace', 'list']:
                return done(listing)
            if sub[:1] == ['list']:
                return done('code-audit@code-audit-local  installed, enabled  0.3.1\n' if installed else 'other@x  installed\n')
            return done('ok')
        return fake, calls

    def test_codex_prefix_collision_and_missing_plugin(self):
        (self.home / '.codex').mkdir()
        good = f'Marketplace `code-audit-local`\n{ROOT}/.agents/plugins/marketplace.json\n'
        with mock.patch.object(sync_hosts.shutil, 'which', return_value='/bin/codex'):
            fake, _ = self.codex_fake(f'Marketplace `code-audit-local`\n{ROOT}-old/.agents/plugins/marketplace.json\n', True)
            code, out = self.run_main('--apply', run=fake)
            self.assertEqual(code, 1)
            self.assertIn('BLOCKED  codex', out)
            self.run_main('--apply')  # settle the other hosts
            fake, _ = self.codex_fake(good, installed=False)
            self.assertEqual(self.run_main(run=fake)[0], 1)  # missing plugin is drift
            fake, _ = self.codex_fake(good, installed=True)
            self.assertEqual(self.run_main(run=fake)[0], 0)  # refresh alone is not drift

    def test_codex_stops_after_a_failed_step(self):
        (self.home / '.codex').mkdir()
        with mock.patch.object(sync_hosts.shutil, 'which', return_value='/bin/codex'):
            fake, calls = self.codex_fake('', False, fail=('marketplace list',))
            self.assertEqual(self.run_main('--apply', run=fake)[0], 1)
            self.assertNotIn(['add', 'code-audit@code-audit-local'], calls)
            fake, calls = self.codex_fake('', False, fail=('marketplace add',))
            self.run_main('--apply', run=fake)
            self.assertIn(['marketplace', 'add', str(ROOT)], calls)
            self.assertNotIn(['add', 'code-audit@code-audit-local'], calls)

    def test_link_to_removed_skill_is_repaired_not_deleted(self):
        shared = self.home / '.agents' / 'skills'
        shared.mkdir(parents=True)
        (shared / 'plan').symlink_to(str(ROOT / 'skills' / 'removed'))
        self.run_main('--apply')
        self.assertEqual(sync_hosts.target_of(shared / 'plan'), ROOT / 'skills' / 'plan')

    def test_link_changed_after_planning_is_not_deleted(self):
        claude_skills = self.home / '.claude' / 'skills'
        claude_skills.mkdir()
        link = claude_skills / 'retired'
        link.symlink_to(str(ROOT.parent / 'code-principles-audit' / 'skills' / 'x'))
        original = sync_hosts.Sync.apply_all
        def retarget_then_apply(sync, run):
            link.unlink()
            link.symlink_to('/somewhere/else')
            return original(sync, run)
        with mock.patch.object(sync_hosts.Sync, 'apply_all', retarget_then_apply):
            code, out = self.run_main('--apply', '--retire')
        self.assertEqual(code, 1)
        self.assertEqual(os.readlink(link), '/somewhere/else')

    def test_numbers_that_cannot_round_trip_block_the_write(self):
        text = '{"precise": 1.234567890123456789, "tiny": 1e-400}'
        (self.home / '.cursor' / 'mcp.json').write_text(text)
        code, out = self.run_main('--apply')
        self.assertEqual(code, 1)
        self.assertIn('cannot be preserved', out)
        self.assertEqual((self.home / '.cursor' / 'mcp.json').read_text(), text)

    def test_codex_not_installed_row_and_list_failure(self):
        (self.home / '.codex').mkdir()
        self.run_main('--apply')
        good = f'Marketplace `code-audit-local`\n{ROOT}/.agents/plugins/marketplace.json\n'
        def fake_with(list_out, list_code=0):
            calls = []
            def fake(cmd, **k):
                calls.append(cmd[2:])
                if cmd[2:4] == ['marketplace', 'list']:
                    return done(good)
                if cmd[2:3] == ['list']:
                    return done(list_out, list_code)
                return done('ok')
            return fake, calls
        with mock.patch.object(sync_hosts.shutil, 'which', return_value='/bin/codex'):
            fake, _ = fake_with('code-audit@code-audit-local  not installed  0.3.1  /x\n')
            self.assertEqual(self.run_main(run=fake)[0], 1)
            fake, calls = fake_with('', 1)
            code, out = self.run_main('--apply', run=fake)
            self.assertEqual(code, 1)
            self.assertNotIn(['add', 'code-audit@code-audit-local'], calls)

    def test_symlinked_folder_with_dotdot_is_not_treated_as_owned(self):
        # repos/alias -> other/deep, so repos/alias/../owned resolves to other/owned, not repos/owned.
        repos, other = self.home / 'repos', self.home / 'other' / 'deep'
        (repos / 'owned' / 'skills').mkdir(parents=True)
        other.mkdir(parents=True)
        (repos / 'alias').symlink_to(other)
        link = self.home / 'tricky-link'
        link.symlink_to(str(repos / 'alias' / '..' / 'owned' / 'skills' / 'x'))
        self.assertFalse(sync_hosts.inside(sync_hosts.raw_target(link), repos / 'owned'))
        self.assertTrue(sync_hosts.inside(repos / 'owned' / 'skills' / 'x', repos / 'owned'))

if __name__ == '__main__':
    unittest.main()
