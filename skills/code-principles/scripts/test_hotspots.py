"""Hotspot ranking: commits x flagged functions, with untouched and clean files scoring zero."""
import contextlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import hotspots

DEEP = "def deep(a, b, c):\n    if a:\n        for x in b:\n            if x:\n                return c\n    return None\n"
CLEAN = "def clean(a):\n    return a\n"


@unittest.skipUnless(shutil.which("git"), "Git is required")
class HotspotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.git("init", "-q", "-b", "main")
        for name, body in (("busy.py", DEEP), ("stable.py", DEEP), ("churny_clean.py", CLEAN), ("tests/test_deep.py", DEEP)):
            self.write(name, body)
        self.commit("base")
        for index in range(3):
            self.write("busy.py", DEEP + f"# edit {index}\n")
            self.write("churny_clean.py", CLEAN + f"# edit {index}\n")
            self.write("tests/test_deep.py", DEEP + f"# edit {index}\n")
            self.commit(f"edit {index}")

    def git(self, *args):
        subprocess.run(["git", "-C", str(self.root), "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args], check=True, capture_output=True)

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def commit(self, message):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)

    def test_score_is_commits_times_flagged_production_functions(self):
        report = hotspots.rank(self.root)
        self.assertEqual(report["status"], "measured", report["gaps"])
        self.assertEqual([(f["path"], f["commits"], f["flagged_functions"], f["score"]) for f in report["top"]], [("busy.py", 4, 1, 4), ("stable.py", 1, 1, 1)])
        self.assertEqual(report["top"][0]["read_first"], [{"function_id": "deep:1", "cc": 4, "signals": ["max_nesting"]}])
        self.assertEqual((report["files_measured"], report["files_with_flagged_functions"], report["hotspot_files"]), (3, 2, 2))

    def test_window_and_top_limit_the_listing(self):
        self.assertEqual([f["path"] for f in hotspots.rank(self.root, top=1)["top"]], ["busy.py"])
        self.write("uncommitted.py", DEEP)
        listed = hotspots.rank(self.root, paths=["uncommitted.py", "busy.py"])
        self.assertEqual(([f["path"] for f in listed["top"]], listed["unchanged_flagged_files"]), (["busy.py"], 1))

    def test_resolved_window_is_reported_and_a_future_start_is_rejected(self):
        self.assertRegex(hotspots.rank(self.root)["since_resolved_utc"], r"^20\d\d-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        with self.assertRaises(ValueError):
            hotspots.rank(self.root, since="2037-01-01")

    def test_path_with_a_space_is_counted(self):
        self.write("my dir/odd name.py", DEEP)
        self.commit("spaced")
        self.assertIn(("my dir/odd name.py", 1), [(f["path"], f["commits"]) for f in hotspots.rank(self.root)["top"]])

    def test_commits_before_a_rename_count_for_the_present_name(self):
        self.git("mv", "busy.py", "renamed.py")
        self.commit("rename")
        self.write("renamed.py", DEEP + "# after rename\n")
        self.commit("edit renamed")
        top = {f["path"]: f["commits"] for f in hotspots.rank(self.root)["top"]}
        self.assertEqual(top["renamed.py"], 6)  # 4 as busy.py, the rename, one edit after it
        self.assertNotIn("busy.py", top)

    def test_invalid_input_and_missing_history_exit_two(self):
        def run(*argv):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                return hotspots.main([*argv]), json.loads(out.getvalue())
        with tempfile.TemporaryDirectory() as plain:
            (Path(plain) / "a.py").write_text(CLEAN)
            self.assertEqual(run(plain)[0], 2)
        self.assertEqual(run(str(self.root), "--top", "0")[0], 2)
        code, report = run(str(self.root))
        self.assertEqual((code, report["schema"]), (0, "code-audit.hotspots.v1"))


if __name__ == "__main__":
    unittest.main()
