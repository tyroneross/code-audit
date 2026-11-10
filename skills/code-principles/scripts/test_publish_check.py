"""publish_check blocks on secrets, machine paths, identities, personal addresses and session files; warns on private names."""
import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import publish_check

PRIVATE = "secret-desk-app"  # a made-up private repository name for the tests
# Made-up credentials, assembled at run time so no scanner (this one included) sees a key in this file.
FAKE_KEYS = {"aws": "AKIA" + "Q" * 16, "github": "ghp_" + "a1" * 18, "model": "sk-ant-" + "b2" * 20,
             "pem": "-----BEGIN RSA " + "PRIVATE KEY-----"}
# A made-up signing identity and personal address, assembled the same way.
SIGNING = "Developer ID " + "Application: Pat Example (AB12" + "CD34EF)"
MAILBOX = "pat.realperson" + "@" + "icloud.com"


def git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t", "HOME": str(root), "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"})


class PublishCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.repo = base / "public-tool"
        self.repo.mkdir()
        self.names = base / "names.txt"  # outside the repository, as in real use
        self.names.write_text(f"# private repositories\n{PRIVATE}\npublic-tool\n")
        git(self.repo, "init", "-q", "-b", "main")

    def tearDown(self):
        self.tmp.cleanup()

    def commit(self, files, message="add"):
        for name, text in files.items():
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", message)

    def run_check(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = publish_check.main(["--repo", str(self.repo), "--names", str(self.names), "--json", *args])
        return code, json.loads(out.getvalue())

    def test_finds_private_name_in_data_file_and_home_path_in_code(self):
        self.commit({"refs/precision.json": f'{{"key": "{PRIVATE}/daemon/main.rs:12"}}\n',
                     "evals/run.py": 'ROOT = "/Users/realowner/dev/x"\n'})
        code, out = self.run_check()
        kinds = sorted((f["kind"], f["where"]) for f in out["findings"])
        self.assertEqual(code, 1)
        self.assertEqual(kinds, [("home-path", "evals/run.py"), ("private-name", "refs/precision.json")])

    def test_matches_name_case_insensitively_at_token_edges_only(self):
        self.commit({"a.md": "Secret-Desk-App leaked\n", "b.md": "mysecret-desk-apps is another word\n"})
        _, out = self.run_check()
        self.assertEqual([f["where"] for f in out["findings"]], ["a.md"])

    def test_ignores_fictional_users_and_own_repository_name(self):
        self.commit({"doc.md": "see /Users/example/x and /home/runner/work and C:\\Users\\you\\x\npublic-tool is us\n"})
        code, out = self.run_check()
        self.assertEqual((code, out["findings"]), (0, []))

    def test_home_folder_inside_a_longer_path_is_not_a_machine_path(self):
        self.commit({"a.py": 'P = ".store/decisions/home/decisions.json"\nQ = "file:///Users/realowner/x"\n'})
        _, out = self.run_check()
        self.assertEqual([(f["kind"], f["line"]) for f in out["findings"]], [("home-path", 2)])

    def test_machine_path_after_an_escaped_newline_is_found(self):
        self.commit({"log.jsonl": '{"out": "done\\n/Users/realowner/x\\t/home/realowner/y"}\n',
                     "run.sh": 'export TOOL="${TOOL:-/Users/realowner/bin/tool}"\n'})
        _, out = self.run_check()
        self.assertEqual([f["kind"] for f in out["findings"]], ["home-path", "home-path", "home-path"])

    def test_allow_file_exempts_home_paths_but_never_private_names(self):
        self.commit({".publish-allow": "tests/*\n",
                     "tests/test_x.py": f'P = "/Users/realowner/x"  # fixture\nNAME = "{PRIVATE}"\n'})
        _, out = self.run_check()
        self.assertEqual([f["kind"] for f in out["findings"]], ["private-name"])

    def test_range_scans_added_lines_and_commit_messages_only(self):
        self.commit({"old.md": f"{PRIVATE} was here before\n"})
        base = subprocess.run(["git", "-C", str(self.repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        self.commit({"new.md": "clean line\n/home/realowner/x\n"}, message=f"port the {PRIVATE} parser")
        _, out = self.run_check("--range", f"{base}..HEAD")
        got = sorted((f["kind"], f["where"].split()[0], f["line"]) for f in out["findings"])
        self.assertEqual(got, [("home-path", "new.md", 2), ("private-name", "commit", 1)])

    def test_bang_line_excludes_a_name_that_is_also_a_folder_name(self):
        self.names.write_text(f"{PRIVATE}\ngit-folder\n!Git-Folder\n")
        self.commit({"a.md": "cd git-folder\n"})
        self.assertEqual(self.run_check()[1]["findings"], [])

    def test_private_name_alone_warns_and_exits_zero(self):
        self.commit({"notes.md": f"ported from {PRIVATE}\n"})
        code, out = self.run_check()
        self.assertEqual((code, out["blocking"], out["warnings"]), (0, 0, 1))
        self.assertEqual([(f["kind"], f["severity"]) for f in out["findings"]], [("private-name", "warn")])

    def test_each_secret_format_blocks_and_is_never_printed(self):
        for label, key in FAKE_KEYS.items():
            with self.subTest(label):
                self.commit({"config.env": f"TOKEN={key}\n"}, message=label)
                code, out = self.run_check()
                self.assertEqual((code, [(f["kind"], f["severity"]) for f in out["findings"]]), (1, [("secret", "block")]))
                self.assertNotIn(key, json.dumps(out))

    def test_allow_file_never_exempts_a_secret(self):
        self.commit({".publish-allow": "tests/*\n", "tests/test_x.py": f'KEY = "{FAKE_KEYS["github"]}"\n'})
        self.assertEqual(self.run_check()[0], 1)

    def test_secret_in_commit_message_blocks_in_range_mode(self):
        self.commit({"a.md": "one\n"})
        base = subprocess.run(["git", "-C", str(self.repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        self.commit({"b.md": "two\n"}, message=f"use {FAKE_KEYS['aws']} for the bucket")
        code, out = self.run_check("--range", f"{base}..HEAD")
        self.assertEqual((code, [f["kind"] for f in out["findings"]]), (1, ["secret"]))

    def test_clean_repository_exits_zero(self):
        self.commit({"README.md": "nothing private here\n"})
        self.assertEqual(self.run_check()[0], 0)

    def test_binary_files_are_skipped(self):
        (self.repo / "blob.bin").write_bytes(b"\0\0" + PRIVATE.encode())
        self.commit({})
        self.assertEqual(self.run_check()[1]["findings"], [])

    def test_signing_identity_blocks_and_is_never_printed(self):
        self.commit({"docs/release.md": f'export IDENTITY="{SIGNING}"\n'})
        code, out = self.run_check()
        self.assertEqual((code, [(f["kind"], f["token"]) for f in out["findings"]]),
                         (1, [("identity", "Developer ID Application: [redacted]")]))
        self.assertNotIn("Pat Example", json.dumps(out))
        self.assertNotIn("AB12CD34EF", json.dumps(out))

    def test_personal_address_blocks_but_a_fictional_or_work_one_does_not(self):
        self.commit({"notes.md": f"sign in as {MAILBOX}\nwrite to user@gmail.com or team@company.example\n"})
        code, out = self.run_check()
        self.assertEqual((code, [(f["kind"], f["line"], f["token"]) for f in out["findings"]]),
                         (1, [("personal-email", 1, "[redacted]@icloud.com")]))
        self.assertNotIn(MAILBOX.split("@")[0], json.dumps(out))

    def test_commit_trailer_address_is_not_a_finding_but_one_in_the_message_body_is(self):
        self.commit({"a.md": "one\n"})
        base = subprocess.run(["git", "-C", str(self.repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        self.commit({"b.md": "two\n"}, message=f"fix it\n\nCo-Authored-By: Pat <{MAILBOX}>")
        self.assertEqual(self.run_check("--range", f"{base}..HEAD")[1]["findings"], [])
        self.commit({"c.md": "three\n"}, message=f"ask {MAILBOX} about this")
        _, out = self.run_check("--range", f"{base}..HEAD")
        self.assertEqual([f["kind"] for f in out["findings"]], ["personal-email"])

    def test_handoffs_and_rally_state_block_by_path_and_source_named_handoff_does_not(self):
        self.commit({"HANDOFF.md": "next steps\n", "docs/HANDOFF-2026-01-01.md": "x\n", "docs/handoffs/a.md": "x\n",
                     ".rally/log/1.jsonl": "{}\n", ".build-loop/handoff-latest.md": "x\n",
                     "src/handoff.ts": "export {}\n", "tests/fixtures/handoff-case.json": "{}\n",
                     "skills/x/references/handoffs.md": "how handoffs work\n"})
        code, out = self.run_check()
        self.assertEqual(code, 1)
        self.assertEqual(sorted((f["where"], f["token"]) for f in out["findings"]),
                         [(".build-loop/handoff-latest.md", "handoff document"), (".rally/log/1.jsonl", "Rally state"),
                          ("HANDOFF.md", "handoff document"), ("docs/HANDOFF-2026-01-01.md", "handoff document"),
                          ("docs/handoffs/a.md", "handoff document")])

    def test_allow_file_exempts_a_repository_that_keeps_handoffs(self):
        self.commit({".publish-allow": "handoffs/*\n", "handoffs/2026/plan.md": f"run as {MAILBOX}\n", "HANDOFF.md": "x\n"})
        _, out = self.run_check()
        self.assertEqual([(f["kind"], f["where"]) for f in out["findings"]], [("session-file", "HANDOFF.md")])

    def test_range_reports_a_handoff_added_in_the_range_only(self):
        self.commit({"HANDOFF.md": "old\n"})
        base = subprocess.run(["git", "-C", str(self.repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        self.commit({"docs/HANDOFF-new.md": "new\n"})
        _, out = self.run_check("--range", f"{base}..HEAD")
        self.assertEqual([(f["kind"], f["where"]) for f in out["findings"]], [("session-file", "docs/HANDOFF-new.md")])

    def test_a_guide_about_handoffs_is_not_a_handoff(self):
        self.commit({"docs/HANDOFFS-AND-LAUNCHING.md": "how to hand off\n"})
        self.assertEqual(self.run_check()[1]["findings"], [])

    def test_staged_reads_the_next_commit_and_nothing_already_recorded(self):
        self.commit({"docs/HANDOFF-old.md": f"as {MAILBOX}\n"})
        (self.repo / "HANDOFF.md").write_text("next\n")
        (self.repo / "notes.md").write_text(f'IDENTITY="{SIGNING}"\n')
        (self.repo / "unstaged.md").write_text(f"mail {MAILBOX}\n")
        git(self.repo, "add", "HANDOFF.md", "notes.md")
        code, out = self.run_check("--staged")
        self.assertEqual((code, out["scope"]), (1, "staged"))
        self.assertEqual(sorted((f["kind"], f["where"]) for f in out["findings"]),
                         [("identity", "notes.md"), ("session-file", "HANDOFF.md")])

    def test_staged_in_an_exempt_repository_reports_nothing(self):
        (self.repo / "HANDOFF.md").write_text("next\n")
        git(self.repo, "add", "HANDOFF.md")
        self.assertEqual(publish_check.main(["--repo", str(self.repo), "--staged", "--exempt", "public-tool"]), 0)

    def test_kinds_limits_the_check(self):
        self.commit({"HANDOFF.md": 'ROOT = "/Users/realowner/x"\n'})
        _, out = self.run_check("--kinds", "session-file")
        self.assertEqual([f["kind"] for f in out["findings"]], ["session-file"])
        self.assertEqual(publish_check.main(["--repo", str(self.repo), "--kinds", "nonsense"]), 2)


class Sweep(unittest.TestCase):
    """--sweep reads every repository under a directory once and says which hold a finding."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve()

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, name, files, remote=None):
        repo = self.base / name
        repo.mkdir(parents=True)
        git(repo, "init", "-q", "-b", "main")
        for path, text in files.items():
            (repo / path).parent.mkdir(parents=True, exist_ok=True)
            (repo / path).write_text(text)
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "add")
        if remote:
            git(repo, "remote", "add", "origin", remote)
        return repo

    def run_sweep(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = publish_check.main(["--sweep", str(self.base), "--json", *args])
        return code, json.loads(out.getvalue())

    def test_finds_the_repositories_with_a_handoff_or_an_identity_and_not_home_paths(self):
        self.make("clean", {"README.md": 'see "/Users/realowner/x"\n'})
        self.make("apps/leaky", {"HANDOFF.md": f'IDENTITY="{SIGNING}"\n'})
        self.make("keeper", {".publish-allow": "handoffs/*\n", "handoffs/a.md": "x\n"})
        code, out = self.run_sweep()
        self.assertEqual((code, out["repositories"], out["with_findings"]), (1, 3, 1))
        report = out["reports"][0]
        self.assertTrue(report["path"].endswith("apps/leaky"))
        self.assertEqual(sorted(f["kind"] for f in report["findings"]), ["identity", "session-file"])
        self.assertEqual(report["visibility"], "no-remote")

    def test_a_second_clone_of_one_remote_and_a_linked_worktree_are_read_once(self):
        first = self.make("tool", {"HANDOFF.md": "x\n"}, remote="https://example.com/someone/tool.git")
        self.make("cache/copies/tool", {"HANDOFF.md": "x\n"}, remote="git@example.com:someone/tool.git")
        git(first, "worktree", "add", "-q", str(self.base / "tool-wt"), "-b", "side")
        code, out = self.run_sweep()
        self.assertEqual((code, out["repositories"], out["skipped"]["duplicate-clone"]), (1, 1, 1))
        self.assertEqual(out["reports"][0]["path"], str(first))

    def test_clean_directory_exits_zero(self):
        self.make("clean", {"README.md": "nothing\n"})
        self.assertEqual(self.run_sweep()[0], 0)

    def test_an_exempt_repository_is_listed_and_not_read(self):
        self.make("memory-store", {"handoffs/a.md": "x\n", "HANDOFF.md": "x\n"})
        self.make("app", {"README.md": "nothing\n"})
        code, out = self.run_sweep("--exempt", "Memory-Store")
        self.assertEqual((code, out["repositories"], out["with_findings"]), (0, 1, 0))
        self.assertEqual([Path(p).name for p in out["skipped"]["exempt"]], ["memory-store"])


if __name__ == "__main__":
    unittest.main()
