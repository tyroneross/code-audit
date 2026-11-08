"""Coverage conversion, mutation normalization, companion doctor and Rust test-module checks."""
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

import companions
import complexity
import coverage_convert
import mutation_report

REPORTS = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "multilang" / "reports"
NATIVE = complexity.native_binary() is not None


class Workspace(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, name, text, age=0):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        if age:
            stamp = time.time() - age
            os.utime(path, (stamp, stamp))
        return path


class CoverageConversionTests(Workspace):
    PY = "def outer(a):\n    def inner():\n        return 1\n    if a:\n        return inner()\n    return 0\n"

    def test_lcov_line_coverage_excludes_nested_functions_and_binds_digest(self):
        self.write("m.py", self.PY, age=60)
        lcov = self.write("lcov.info", "SF:m.py\nDA:1,1\nDA:3,0\nDA:4,1\nDA:5,0\nDA:6,1\nend_of_record\n")
        document = coverage_convert.convert(self.root, lcov, "lcov", ["m.py"])
        functions = document["files"]["m.py"]["functions"]
        self.assertEqual(functions["outer:1"], 75.0)  # lines 1,4,5,6: three of four hit
        self.assertEqual(functions["outer.inner:2"], 0.0)
        cov = self.write("cov.json", json.dumps(document))
        rows = {r["function_id"]: r for r in complexity.measure(self.root, ["m.py"], str(cov))["functions"]}
        self.assertEqual(rows["outer:1"]["coverage_percent"], 75.0)
        self.assertIsNotNone(rows["outer:1"]["crap"])

    def test_source_newer_than_report_is_a_gap_and_unmatched_files_are_listed(self):
        lcov = self.write("lcov.info", "SF:m.py\nDA:1,1\nend_of_record\nSF:/elsewhere/x.py\nDA:1,1\nend_of_record\n", age=60)
        self.write("m.py", self.PY)
        document = coverage_convert.convert(self.root, lcov, "lcov", ["m.py"])
        self.assertEqual(document["files"], {})
        self.assertIn("source modified after", document["gaps"][0]["reason"])
        self.assertEqual(document["unmatched_report_files"], ["/elsewhere/x.py"])

    def test_go_profile_and_jacoco_parse_line_hits(self):
        go = coverage_convert.parse_go("mode: set\nexample.com/m/pkg/a.go:3.10,5.2 2 1\nexample.com/m/pkg/a.go:6.1,6.9 1 0\n")
        self.assertEqual(go["example.com/m/pkg/a.go"], {3: 1, 4: 1, 5: 1, 6: 0})
        self.assertEqual(coverage_convert.resolve("example.com/m/pkg/a.go", self.root, {"pkg/a.go"}), "pkg/a.go")
        jacoco = coverage_convert.parse_jacoco('<report name="r"><package name="demo"><sourcefile name="A.java">'
                                               '<line nr="3" mi="0" ci="2"/><line nr="4" mi="1" ci="0"/><line nr="5" mi="0" ci="0"/>'
                                               '</sourcefile></package></report>')
        self.assertEqual(jacoco["demo/A.java"], {3: 2, 4: 0})
        self.assertEqual(coverage_convert.resolve("demo/A.java", self.root, {"src/main/java/demo/A.java"}), "src/main/java/demo/A.java")
        self.assertIsNone(coverage_convert.resolve("A.java", self.root, {"x/A.java", "y/A.java"}))

    @unittest.skipUnless(NATIVE, "tree-sitter analyzer not built")
    def test_rust_lcov_from_cargo_llvm_cov_shape(self):
        self.write("src/lib.rs", "pub fn clamp(x: i32) -> i32 { if x > 10 { 10 } else { x } }\npub fn untested(a: i32) -> i32 { a }\n", age=60)
        lcov = self.write("lcov.info", f"SF:{self.root.resolve()}/src/lib.rs\nFN:1,_RN5clamp\nDA:1,1\nDA:2,0\nend_of_record\n")
        files = coverage_convert.convert(self.root, lcov, "lcov", ["src"])["files"]
        self.assertEqual(files["src/lib.rs"]["functions"], {"clamp:1": 100.0, "untested:2": 0.0})


class MutationTests(Workspace):
    def test_real_cargo_mutants_output(self):
        result = mutation_report.normalize(REPORTS / "cargo-mutants-27.1.0-outcomes.json", "cargo-mutants")
        self.assertEqual(result["baseline"], "passed")
        self.assertTrue(result["trusted"])
        self.assertEqual({k: result["counts"][k] for k in ("selected", "killed", "surviving", "executed")},
                         {"selected": 11, "killed": 5, "surviving": 6, "executed": 11})
        self.assertEqual(result["counts"]["score"], round(5 / 11, 4))
        survivors = [(row["function"], row["line"]) for row in result["surviving_or_uncovered"]]
        # The demo's only test, clamp(20) == 10, cannot tell `>` from `>=`.
        self.assertEqual(survivors, [("clamp", 1)] + [("untested", 2)] * 5)

    def test_timeouts_and_failed_baseline_are_never_kills(self):
        mutant = {"Mutant": {"file": "src/a.rs", "name": "m", "span": {"start": {"line": 1}}}}
        report = self.write("o.json", json.dumps({"outcomes": [{"scenario": "Baseline", "summary": "Failure"},
                                                              {"scenario": mutant, "summary": "Timeout"},
                                                              {"scenario": mutant, "summary": "Unviable"}]}))
        result = mutation_report.normalize(report, "cargo-mutants")
        self.assertFalse(result["trusted"])
        self.assertEqual(result["counts"]["killed"], 0)
        self.assertEqual(result["counts"]["inconclusive"], 2)
        self.assertIsNone(result["counts"]["score"])
        self.assertEqual(mutation_report.main([str(report), "--format", "cargo-mutants"]), 1)

    def test_stryker_statuses_are_separated(self):
        statuses = ["Killed", "Killed", "Survived", "NoCoverage", "Timeout", "CompileError", "Ignored"]
        mutants = [{"id": str(i), "mutatorName": "x", "status": s, "location": {"start": {"line": i + 1, "column": 1}, "end": {"line": i + 1, "column": 2}}}
                   for i, s in enumerate(statuses)]
        report = self.write("m.json", json.dumps({"schemaVersion": "2", "thresholds": {}, "files": {"a.ts": {"language": "typescript", "source": "", "mutants": mutants}}}))
        counts = mutation_report.normalize(report, "stryker")["counts"]
        self.assertEqual({k: counts[k] for k in ("killed", "surviving", "uncovered", "inconclusive", "not_run", "executed")},
                         {"killed": 2, "surviving": 1, "uncovered": 1, "inconclusive": 2, "not_run": 1, "executed": 3})
        bad = self.write("bad.json", json.dumps({"schemaVersion": "9", "files": {}}))
        self.assertEqual(mutation_report.main([str(bad), "--format", "stryker"]), 2)


class CompanionTests(unittest.TestCase):
    def test_doctor_covers_every_language_without_running_tools(self):
        with mock.patch("subprocess.run") as run:
            report = companions.doctor()
        run.assert_not_called() if os.environ.get("JAVA_HOME") or os.sys.platform != "darwin" else None
        self.assertEqual(set(report["languages"]), {"rust", "typescript", "java", "go", "swift", "python"})
        for language, kinds in report["languages"].items():
            for kind, spec in kinds.items():
                self.assertIn("available", spec, (language, kind))
                if spec["convert"] is None:
                    self.assertIn("gap", spec)

    def test_macos_java_placeholder_is_not_a_runtime(self):
        with mock.patch.dict(os.environ, {"JAVA_HOME": ""}), mock.patch.object(companions.sys, "platform", "darwin"), \
                mock.patch("subprocess.run", return_value=mock.Mock(returncode=1)):
            self.assertFalse(companions.java_runtime())


@unittest.skipUnless(NATIVE, "tree-sitter analyzer not built")
class RustTestModuleTests(Workspace):
    def test_out_of_line_cfg_test_modules_and_their_children_are_test_code(self):
        self.write("src/lib.rs", "#[cfg(test)]\nmod helpers;\nmod live;\nfn root() {}\n")
        self.write("src/helpers.rs", "mod deep;\nfn help() {}\n")
        self.write("src/helpers/deep.rs", "fn deeper() {}\n")
        self.write("src/live.rs", "fn shipped() {}\n")
        rows = {r["name"]: r for r in complexity.measure(self.root, ["src"])["functions"]}
        self.assertEqual(rows["help"]["kind"], "test")
        self.assertIn("src/lib.rs", rows["help"]["test_reason"])
        self.assertEqual(rows["deeper"]["kind"], "test")
        self.assertEqual(rows["shipped"]["kind"], "production")
        self.assertEqual(rows["root"]["kind"], "production")


if __name__ == "__main__":
    unittest.main()
