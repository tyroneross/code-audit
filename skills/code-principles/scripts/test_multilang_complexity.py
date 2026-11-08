"""Tree-sitter analyzer checks: counted decisions, test split, gaps, CRAP and duplicates."""
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

import complexity

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "multilang"
# Hand-counted from the comments in each fixture file.
EXPECTED_CC = {
    ("src/sample.rs", "Gate.check:5"): 5, ("src/sample.rs", "Gate.loops:17"): 5,
    ("src/sample.rs", "outer:29"): 2, ("src/sample.rs", "outer.inner:30"): 2,
    ("src/sample.ts", "Router.route:3"): 5, ("src/sample.ts", "scan:12"): 6, ("src/sample.ts", "spin:26"): 3,
    ("src/Sample.java", "Sample.count:5"): 5, ("src/Sample.java", "Sample.pick:17"): 5,
    ("src/sample.go", "Box.Size:6"): 6, ("src/sample.go", "Apply:24"): 2,
    ("src/Sample.swift", "Gate.check:3"): 6, ("src/Sample.swift", "Gate.spin:13"): 6,
}
EXPECTED_TESTS = {
    ("src/sample.rs", "tests.helper:38"): "inside #[cfg(test)] item",
    ("src/sample.rs", "tests.checks:40"): "#[test] attribute",
    ("src/sample.rs", "async_case:44"): "#[tokio::test] attribute",
    ("src/Sample.java", "Sample.testPick:31"): "@Test annotation",
    ("SwiftTests/GateTests.swift", "GateTests.testCheck:4"): "test method in XCTestCase subclass",
    ("tests/sample_test.go", "TestSize:5"): "test path convention",
}
NATIVE = complexity.native_binary() is not None
SKIP_REASON = "tree-sitter analyzer not built: " + complexity.native_build_hint()


@unittest.skipUnless(NATIVE, SKIP_REASON)
class NativeAnalyzerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def fixture_report(self, **kwargs):
        return complexity.measure(FIXTURES, ["src", "tests", "SwiftTests"], **kwargs)

    def by_key(self, report):
        return {(r["path"], r["function_id"]): r for r in report["functions"]}

    def test_counted_decisions_match_hand_counts_in_every_language(self):
        report = self.fixture_report()
        self.assertEqual(report["status"], "measured", report["gaps"])
        rows = self.by_key(report)
        for key, cc in EXPECTED_CC.items():
            with self.subTest(key=key):
                self.assertEqual(rows[key]["cc"], cc)
                self.assertEqual(rows[key]["kind"], "production")
        self.assertEqual(set(report["languages"]), {"rust", "typescript", "java", "go", "swift"})
        native = [a for a in report["analyzers"] if a["name"] == "code-audit-complexity"][0]
        self.assertTrue(native["parser"].startswith("tree-sitter 0.27"))
        self.assertTrue(all(native["grammars"].values()))

    def test_test_code_is_split_from_production_with_a_reason(self):
        rows = self.by_key(self.fixture_report())
        for key, reason in EXPECTED_TESTS.items():
            with self.subTest(key=key):
                self.assertEqual(rows[key]["kind"], "test")
                self.assertEqual(rows[key]["test_reason"], reason)
        report = self.fixture_report()
        self.assertEqual(report["production_function_count"] + report["test_function_count"], report["function_count"])

    def test_cfg_not_test_is_production_and_inner_cfg_test_marks_the_file(self):
        (self.root / "a.rs").write_text("#[cfg(not(test))]\nfn live() {}\n")
        (self.root / "b.rs").write_text("#![cfg(test)]\nfn helper() {}\n")
        rows = self.by_key(complexity.measure(self.root, ["a.rs", "b.rs"]))
        self.assertEqual(rows[("a.rs", "live:2")]["kind"], "production")
        self.assertEqual(rows[("b.rs", "helper:2")]["kind"], "test")

    def test_coverage_produces_crap_only_with_matching_digest(self):
        source = self.root / "lib.rs"
        source.write_text("fn f(a: bool) -> u8 { if a { 1 } else { 0 } }\n")
        digest = complexity.measure(self.root, ["lib.rs"])["source_sha256"]["lib.rs"]
        for sha, expected in [(digest, 2 ** 2 * 0.5 ** 3 + 2), ("0" * 64, None)]:
            cov = self.root / "cov.json"
            cov.write_text(json.dumps({"schema": complexity.COVERAGE_SCHEMA, "files": {"lib.rs": {"sha256": sha, "functions": {"f:1": 50}}}}))
            row = complexity.measure(self.root, ["lib.rs"], str(cov))["functions"][0]
            self.assertEqual(row["crap"], expected)

    def test_parse_errors_and_missing_files_are_gaps(self):
        (self.root / "bad.go").write_text("package x\nfunc f( {\n")
        for name in ["bad.go", "missing.swift"]:
            with self.subTest(name=name):
                report = complexity.measure(self.root, [name])
                self.assertEqual(report["status"], "incomplete")
                self.assertEqual(report["gaps"][0]["path"], name)

    def test_duplicates_report_identical_structure_and_skip_distinct_code(self):
        body = "    let mut n = 0;\n" + "    if a > n { n += a; } else { n -= 1; }\n    for i in 0..a { if i % 2 == 0 { n += i; } }\n" * 4 + "    n\n"
        (self.root / "d.rs").write_text(f"fn one(a: u32) -> u32 {{\n{body}}}\nfn two(b: u32) -> u32 {{\n{body.replace('a', 'b')}}}\nfn other() -> u32 {{ 1 }}\n")
        report = complexity.measure(self.root, ["d.rs"], duplicates=True)
        pairs = report["duplicates"]["pairs"]
        self.assertEqual(len(pairs), 1)
        self.assertEqual({pairs[0]["a"]["function_id"], pairs[0]["b"]["function_id"]}, {"one:1", "two:13"})
        self.assertEqual(pairs[0]["similarity"], 1.0)
        self.assertNotIn("duplicates", complexity.measure(self.root, ["d.rs"]))

    def test_one_file_spelled_two_ways_is_measured_once(self):
        (self.root / "Dir").mkdir()
        (self.root / "Dir" / "m.go").write_text("package m\nfunc F() {}\n")
        if not (self.root / "dir").exists():
            self.skipTest("case-sensitive filesystem")
        report = complexity.measure(self.root, ["Dir", "dir"])
        self.assertEqual(report["function_count"], 1)


class MissingAnalyzerTests(unittest.TestCase):
    def test_missing_analyzer_is_a_gap_with_build_instructions(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.dict(os.environ, {"CODE_AUDIT_COMPLEXITY_BIN": str(Path(folder) / "absent")}):
            (Path(folder) / "m.ts").write_text("export function f() {}\n")
            report = complexity.measure(folder, ["m.ts"])
        self.assertEqual(report["status"], "incomplete")
        self.assertIn("cargo build --release --offline", report["gaps"][0]["reason"])
        self.assertEqual(report["function_count"], 0)


if __name__ == "__main__":
    unittest.main()
