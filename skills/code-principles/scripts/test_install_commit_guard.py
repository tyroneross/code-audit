"""The commit guard blocks a handoff in any repository, runs the repository's own hook, and comes out cleanly."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


class CommitGuard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name).resolve() / "home"
        self.home.mkdir()
        # A home of its own: the real global Git configuration is never touched.
        self.env = {"HOME": str(self.home), "PATH": os.environ["PATH"], "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_NOSYSTEM": "1"}
        self.repo = self.home / "work" / "app"
        self.repo.mkdir(parents=True)
        self.git("init", "-q", "-b", "main")

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args, check=True):
        return subprocess.run(["git", "-C", str(self.repo), *args], capture_output=True, text=True, env=self.env, check=check)

    def guard(self, *args):
        return subprocess.run(["python3", str(HERE / "install_commit_guard.py"), *args], capture_output=True, text=True, env=self.env)

    def commit(self, name, text):
        (self.repo / name).write_text(text)
        self.git("add", "-f", name)
        return self.git("commit", "-q", "-m", "add " + name, check=False)

    def test_blocks_a_handoff_allows_ordinary_work_and_runs_the_local_hook(self):
        self.assertEqual(self.guard("--status").returncode, 1)
        self.assertEqual(self.guard().returncode, 0)
        self.assertEqual(self.guard("--status").returncode, 0)
        local = self.repo / ".git" / "hooks" / "pre-commit"
        local.write_text("#!/bin/sh\necho ran >> \"$(git rev-parse --git-dir)/local-hook-ran\"\n")
        local.chmod(0o755)

        blocked = self.commit("HANDOFF.md", "next steps\n")
        self.assertEqual(blocked.returncode, 1)
        self.assertIn("session-file", blocked.stdout + blocked.stderr)
        self.assertFalse((self.repo / ".git" / "local-hook-ran").exists())
        self.git("rm", "--cached", "-q", "HANDOFF.md")  # no commit yet, so nothing to restore from

        self.assertEqual(self.commit("main.py", "print(1)\n").returncode, 0)
        self.assertEqual((self.repo / ".git" / "local-hook-ran").read_text(), "ran\n")

    def test_an_exempt_repository_may_commit_a_handoff(self):
        self.guard()
        (self.home / ".code-audit" / "sweep-exempt.txt").write_text("# keeps handoffs\napp\n")
        self.assertEqual(self.commit("HANDOFF.md", "next steps\n").returncode, 0)

    def test_a_missing_check_does_not_block_and_removal_restores_git(self):
        self.guard()
        hook = self.home / ".code-audit" / "git-hooks" / "pre-commit"
        hook.write_text(hook.read_text().replace("publish_check.py", "gone.py"))
        result = self.commit("HANDOFF.md", "next steps\n")
        self.assertEqual(result.returncode, 0)
        self.assertIn("could not run", result.stderr)
        self.assertEqual(self.guard("--remove").returncode, 0)
        self.assertFalse((self.home / ".code-audit" / "git-hooks").exists())
        self.assertEqual(subprocess.run(["git", "config", "--global", "--get", "core.hooksPath"], capture_output=True, env=self.env).returncode, 1)

    def test_refuses_to_replace_another_hooks_path(self):
        subprocess.run(["git", "config", "--global", "core.hooksPath", str(self.home / "other")], env=self.env, check=True)
        self.assertEqual(self.guard().returncode, 2)
        self.assertFalse((self.home / ".code-audit" / "git-hooks").exists())


if __name__ == "__main__":
    unittest.main()
