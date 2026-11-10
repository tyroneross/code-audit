"""publish_check blocks on secrets and machine paths, warns on private names, and stays quiet on fictional ones."""
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
        self.commit({"log.jsonl": '{"out": "done\\n/Users/realowner/x\\t/home/realowner/y"}\n'})
        _, out = self.run_check()
        self.assertEqual([f["kind"] for f in out["findings"]], ["home-path", "home-path"])

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


if __name__ == "__main__":
    unittest.main()
