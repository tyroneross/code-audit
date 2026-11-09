"""publish_check finds private names and machine paths before a push, and stays quiet on fictional ones."""
import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import publish_check

PRIVATE = "secret-desk-app"  # a made-up private repository name for the tests


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

    def test_clean_repository_exits_zero(self):
        self.commit({"README.md": "nothing private here\n"})
        self.assertEqual(self.run_check()[0], 0)

    def test_binary_files_are_skipped(self):
        (self.repo / "blob.bin").write_bytes(b"\0\0" + PRIVATE.encode())
        self.commit({})
        self.assertEqual(self.run_check()[1]["findings"], [])


if __name__ == "__main__":
    unittest.main()
