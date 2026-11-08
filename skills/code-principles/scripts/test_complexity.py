"""Behavior and evidence-boundary checks for optional complexity scoring."""
import contextlib
import hashlib
import io
import json
import shutil
import subprocess
from pathlib import Path
import tempfile
import unittest

import complexity


class ComplexityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def source(self, text, name="module.py"):
        path = self.root / name
        path.write_text(text)
        return path

    def report(self, paths=None, coverage=None, threshold=10):
        return complexity.measure(self.root, paths if paths is not None else ["module.py"], coverage, threshold)

    def coverage(self, path, functions, digest=None):
        document = {"schema": complexity.COVERAGE_SCHEMA, "files": {
            path.name: {"sha256": digest or hashlib.sha256(path.read_bytes()).hexdigest(), "functions": functions}}}
        coverage = self.root / "coverage.json"
        coverage.write_text(json.dumps(document))
        return coverage

    def test_decisions_and_nested_function_isolation(self):
        self.source("def outer(a, b, c):\n    if a and b or c:\n        return [x for x in a if x]\n    def inner(x):\n        return 1 if x else 2\n    return inner(a)\n")
        rows = {r["name"]: r for r in self.report()["functions"]}
        self.assertEqual(rows["outer"]["cc"], 6)  # base, if, two boolean ops, generator, filter
        self.assertEqual(rows["outer.inner"]["cc"], 2)
        self.assertEqual(rows["outer.inner"]["function_id"], "outer.inner:4")

    def test_async_class_and_exception_decisions(self):
        self.source("class Service:\n    async def run(self, xs):\n        async for x in xs:\n            try:\n                assert x\n            except ValueError:\n                while x:\n                    x -= 1\n        return lambda z: z if z else 0\n")
        row = self.report()["functions"][0]
        self.assertEqual(row["name"], "Service.run")
        self.assertEqual(row["cc"], 5)

    def test_match_default_case_not_a_decision(self):
        self.source("def choose(x):\n    match x:\n        case 1: return 1\n        case _: return 0\n")
        self.assertEqual(self.report()["functions"][0]["cc"], 2)
        self.source("def choose(x):\n    match x:\n        case _ if x: return 1\n        case _: return 0\n")
        self.assertEqual(self.report()["functions"][0]["cc"], 2)

    def test_absent_coverage_is_unknown_not_zero(self):
        self.source("def f(x):\n    return 1 if x else 0\n")
        report = self.report()
        row = report["functions"][0]
        self.assertEqual(report["status"], "measured")
        self.assertIsNone(row["coverage_percent"])
        self.assertIsNone(row["crap"])
        self.assertEqual(report["coverage_unavailable_functions"], 1)

    def test_zero_and_full_coverage_crap(self):
        path = self.source("def f(x):\n    return 1 if x else 0\n")
        for percent, expected in [(0, 6), (50, 2.5), (100, 2)]:
            with self.subTest(percent=percent):
                row = self.report(coverage=self.coverage(path, {"f:1": percent}))["functions"][0]
                self.assertEqual(row["coverage_percent"], percent)
                self.assertEqual(row["crap"], expected)

    def test_missing_function_coverage_stays_unknown(self):
        path = self.source("def f():\n    return 1\n")
        row = self.report(coverage=self.coverage(path, {"other:1": 100}))["functions"][0]
        self.assertIsNone(row["crap"])

    def test_stale_source_coverage_marks_gap(self):
        path = self.source("def f():\n    return 1\n")
        report = self.report(coverage=self.coverage(path, {"f:1": 100}, "a" * 64))
        self.assertEqual(report["status"], "incomplete")
        self.assertIsNone(report["functions"][0]["crap"])
        self.assertIn("digest mismatch", report["gaps"][0]["reason"])

    def test_invalid_coverage_percentages(self):
        path = self.source("def f():\n    return 1\n")
        for percent in [True, "50", -1, 101, float("nan"), float("inf"), 10 ** 500]:
            with self.subTest(percent=str(percent)):
                with self.assertRaises(ValueError):
                    self.report(coverage=self.coverage(path, {"f:1": percent}))

    def test_invalid_coverage_shape_and_paths(self):
        path = self.root / "coverage.json"
        for document in [[], {}, {"schema": complexity.COVERAGE_SCHEMA, "files": {"../x.py": {}}}]:
            with self.subTest(document=document):
                path.write_text(json.dumps(document))
                with self.assertRaises(ValueError):
                    complexity.coverage_document(path)

    def test_threshold_is_inclusive_and_failing_gate_is_opt_in(self):
        self.source("def f(x):\n" + "    if x: pass\n" * 9)
        self.assertTrue(self.report()["functions"][0]["hotspot"])
        self.assertEqual(self.report()["hotspot_count"], 1)
        for flags, expected in [([], 0), (["--fail-on-hotspots"], 1), (["--threshold", "11", "--fail-on-hotspots"], 0)]:
            with self.subTest(flags=flags), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(complexity.main([str(self.root), "--paths", "module.py", *flags]), expected)

    def test_unsupported_empty_missing_and_parse_errors_are_not_clean(self):
        self.source("fun f() {}", "module.kt")
        self.source("# no functions\n", "empty.py")
        self.source("def broken(\n", "broken.py")
        for name in ["module.kt", "empty.py", "missing.py", "broken.py"]:
            with self.subTest(name=name), contextlib.redirect_stdout(io.StringIO()):
                report = self.report([name])
                self.assertEqual(report["status"], "incomplete")
                self.assertTrue(report["gaps"])
                self.assertEqual(complexity.main([str(self.root), "--paths", name]), 2)

    def test_source_digest_revision_scope_and_dedup(self):
        path = self.source("def f():\n    return 1\n")
        report = self.report(["module.py", "module.py"])
        self.assertEqual(report["function_count"], 1)
        self.assertEqual(report["source_sha256"]["module.py"], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertIsNone(report["revision"])
        self.assertEqual(report["selection"], "explicit")

    def test_outside_root_symlink_is_a_gap(self):
        with tempfile.TemporaryDirectory() as outside:
            path = Path(outside) / "other.py"
            path.write_text("def other(): return 1\n")
            (self.root / "alias.py").symlink_to(path)
            report = self.report(["alias.py"])
            self.assertEqual(report["status"], "incomplete")
            self.assertEqual(report["function_count"], 0)
            self.assertEqual(report["gaps"][0]["reason"], "outside source root")

    def test_directory_selection_ignores_package_metadata_but_reports_other_languages(self):
        package = self.root / "pkg"
        package.mkdir()
        (package / "a.py").write_text("def f(): return 1\n")
        (package / "py.typed").write_text("")
        (package / "README.md").write_text("Package documentation.\n")
        report = self.report(["pkg"])
        self.assertEqual(report["status"], "measured")
        self.assertEqual(report["selected_files"], ["pkg/a.py"])
        self.assertEqual(report["function_count"], 1)
        (package / "b.kt").write_text("fun f() {}\n")
        report = self.report(["pkg"])
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["gaps"][0]["path"], "pkg/b.kt")
        self.assertEqual(self.report(["pkg/README.md"])["status"], "incomplete")

    @unittest.skipUnless(shutil.which("git"), "Git is required for fsmonitor regression")
    def test_git_inventory_does_not_execute_configured_fsmonitor(self):
        self.source("def f(): return 1\n")
        def git(*args):
            subprocess.run(["git", "-C", str(self.root), *args],
                           check=True, capture_output=True)
        git("init")
        git("add", "module.py")
        marker = self.root / "fsmonitor-executed"
        hook = self.root / "fsmonitor-hook"
        hook.write_text('#!/bin/sh\n: > "' + str(marker) + '"\nprintf "token\\0"\n')
        hook.chmod(0o700)
        git("config", "core.fsmonitor", str(hook))
        git("config", "core.fsmonitorHookVersion", "2")
        report = complexity.measure(self.root)
        self.assertEqual(report["status"], "measured")
        self.assertEqual(report["selection"], "tracked-source")
        self.assertEqual(report["selected_files"], ["module.py"])
        self.assertFalse(marker.exists(), "source inventory executed repository fsmonitor")

    def test_invalid_threshold_is_rejected(self):
        self.source("def f(): return 1\n")
        for threshold in [0, -1, True, 2.5]:
            with self.subTest(threshold=threshold), self.assertRaises(ValueError):
                self.report(threshold=threshold)


if __name__ == "__main__":
    unittest.main()
