"""Tests for recon.py and the recipe-id / candidates behavior of outcome.py (audit-methods.md)."""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import outcome  # noqa: E402
import recon  # noqa: E402

GIT_ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def write(root, files):
    for rel, text in files.items():
        p = Path(root, rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)


def git(root, *args):
    subprocess.run(["git", "-C", root, *args], check=True, capture_output=True, timeout=20, env=GIT_ENV)


class ReconTest(unittest.TestCase):
    def test_git_listing_keeps_names_git_would_quote(self):
        # Without -z, git quotes these names and recon dropped them, losing their signals.
        with tempfile.TemporaryDirectory() as root:
            write(root, {"tab\tname.py": "x = retry()\n", "\u00e9.py": "y = 1\n"})
            git(root, "init", "-q")
            git(root, "add", "-A")
            r = recon.recon(root)
            self.assertEqual(r["signals"]["files"], 2)
            self.assertIn("R5b", r["route"]["recipes"])

    def test_inaccessible_files_count_as_incomplete_not_absent(self):
        with tempfile.TemporaryDirectory() as root:
            write(root, {"locked/a.py": "x = retry()\n", "b.py": "y = 1\n"})
            git(root, "init", "-q")
            git(root, "add", "-A")
            os.chmod(os.path.join(root, "locked"), 0)
            try:
                r = recon.recon(root)
            finally:
                os.chmod(os.path.join(root, "locked"), 0o755)
            self.assertEqual(r["signals"]["incomplete"]["unreadable"], ["locked/a.py"])
            self.assertIn("R5b", r["route"]["recipes"])

    def test_unlistable_directories_without_git_count_as_incomplete(self):
        with tempfile.TemporaryDirectory() as root:
            write(root, {"locked/a.py": "x = retry()\n", "b.py": "y = 1\n"})
            os.chmod(os.path.join(root, "locked"), 0)
            try:
                r = recon.recon(root)
            finally:
                os.chmod(os.path.join(root, "locked"), 0o755)
            self.assertEqual(r["signals"]["incomplete"]["unreadable"], ["locked/"])
            self.assertIn("R5b", r["route"]["recipes"])

    def test_unread_files_keep_signal_gated_recipes(self):
        with tempfile.TemporaryDirectory() as root:
            write(root, {"a.py": "x = 1\n", "big.py": "y = 2\n"})
            limit = recon.READ_LIMIT
            recon.READ_LIMIT = 3
            try:
                r = recon.recon(root)
            finally:
                recon.READ_LIMIT = limit
            self.assertEqual(sorted(r["signals"]["incomplete"]["truncated"]), ["a.py", "big.py"])
            for rid in ("R4", "R5a", "R5b"):
                self.assertIn(rid, r["route"]["recipes"])

    def test_repo_scope_signals_and_route_without_git(self):
        with tempfile.TemporaryDirectory() as root:
            write(root, {
                "svc/a.py": "import json\nopen(p, 'a').write(json.dumps(x))\n",
                "svc/b.py": "def f():\n    return 1\n",
                "web/c.ts": "const r = await retry(() => fetch(u), { timeout: 5 })\n",
                "web/package.json": "{}", "svc/pyproject.toml": "",
                "node_modules/x/retry.js": "retry()\n", "dist/out.js": "JSON.stringify(1)\n",
            })
            r = recon.recon(root)
            s = r["signals"]
            self.assertEqual(s["scope"], "repo")
            self.assertEqual(s["languages"], {"python": 2, "typescript": 1})
            self.assertTrue(s["multi_lang"])
            self.assertEqual((s["io_conc"], s["retry"], s["serial"], s["services"]), (1, 1, 1, 2))  # skipped dirs not counted
            self.assertEqual(r["route"]["row"], "repo-large")
            self.assertEqual(r["route"]["recipes"], ["R1", "R2", "R3", "R4", "R5a", "R5b"])
            self.assertTrue(r["route"]["contract_lane"])

    def test_diff_scope_from_base_uses_paths_relative_to_root(self):
        with tempfile.TemporaryDirectory() as top:
            root = os.path.join(top, "pkg")
            write(root, {"m/a.py": "x = 1\n", "m/b.py": "y = 2\n"})
            git(top, "init", "-q")
            git(top, "-c", "user.email=t@e", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "base")
            git(top, "add", ".")
            git(top, "-c", "user.email=t@e", "-c", "user.name=t", "commit", "-q", "-m", "add")
            Path(root, "m/a.py").write_text("x = retry(timeout=3)\n")
            r = recon.recon(root, base="HEAD")
            self.assertEqual((r["signals"]["scope"], r["signals"]["files"], r["signals"]["diff_modules"]), ("diff", 1, 1))
            self.assertEqual(r["signals"]["repo_files"], 2)
            self.assertEqual(r["route"], {"row": "diff-small", "recipes": ["R1", "R5b"], "lanes": "none"})

    def test_cli_rejects_missing_root(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(recon.main(["/nonexistent/recon-root"]), 2)


class OutcomeRecipeTest(unittest.TestCase):
    def add(self, repo, item, decision, log):
        with redirect_stdout(io.StringIO()):
            return outcome.main(["add", "--repo", repo, "--item", item, "--where", "a.py:1", "--decision", decision, "--log-file", log])

    def test_recipe_and_section_fg_ids_are_accepted_and_record_the_repo(self):
        with tempfile.TemporaryDirectory() as repo, tempfile.TemporaryDirectory() as out:
            log = os.path.join(out, "o.jsonl")
            for item in ("R1", "R5a", "R5b", "R6:two-write-append", "F3", "G2"):
                self.assertEqual(self.add(repo, item, "accepted", log), 0, item)
            for item in ("R7", "R5c", "R1:slug", "R6:Bad Slug", "H1"):
                self.assertEqual(self.add(repo, item, "accepted", log), 2, item)
            rows = [json.loads(l) for l in Path(log).read_text().splitlines()]
            self.assertEqual({r["repo"] for r in rows}, {os.path.realpath(repo)})

    def test_candidates_need_confirmed_outcomes_on_distinct_repos(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b, tempfile.TemporaryDirectory() as out:
            log = os.path.join(out, "o.jsonl")
            self.add(a, "R5b", "fixed", log)
            self.add(b, "R5b", "kept", log)
            self.add(a, "R2", "accepted", log)
            self.add(a, "R2", "fixed", log)          # same repo twice: still one repo
            self.add(a, "R4", "accepted", log)
            self.add(b, "R4", "rejected", log)       # rejected outcomes do not count
            self.add(a, "B2", "fixed", log)
            self.add(b, "B2", "fixed", log)          # checklist ids are already rules, not candidates
            buf = io.StringIO()
            with redirect_stdout(buf):
                self.assertEqual(outcome.main(["candidates", "--min-repos", "2", "--log-file", log, "--json"]), 0)
            self.assertEqual(json.loads(buf.getvalue()), {"R5b": sorted([os.path.realpath(a), os.path.realpath(b)])})

    def test_candidates_read_legacy_rows_from_per_repo_logs(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            for repo in (a, b):
                Path(repo, ".code-principles").mkdir()
                Path(repo, ".code-principles", "outcomes.jsonl").write_text(json.dumps({"item": "R1", "decision": "fixed", "where": "x:1"}) + "\n")
            buf = io.StringIO()
            with redirect_stdout(buf):
                outcome.main(["candidates", "--repo", a, "--repo", b, "--json"])
            self.assertEqual(list(json.loads(buf.getvalue())), ["R1"])


if __name__ == "__main__":
    unittest.main()
