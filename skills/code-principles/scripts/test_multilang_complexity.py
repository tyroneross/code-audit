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


@unittest.skipUnless(NATIVE, SKIP_REASON)
class ReviewRegressionTests(unittest.TestCase):
    """Inputs from the 2026-11-08 independent review, one test per finding."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def measure(self, name, source, **kwargs):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
        return complexity.measure(self.root, [name], **kwargs)

    def rows(self, name, source):
        report = self.measure(name, source)
        return {r["name"]: r for r in report["functions"]}, report

    def test_top_level_anonymous_functions_get_their_own_rows(self):
        cases = [
            ("app.ts", 'app.get("/", (req, res) => { if (req.q) { res.send(1) } else if (req.r) { res.send(2) } });\n', "<anonymous@1>", 3),
            ("d.ts", "export default (a: boolean) => { if (a) return 1; return 2; };\n", "<anonymous@1>", 2),
            ("f.ts", "export default function() { if (a) {} }\n", "<anonymous@1>", 2),
            ("m.tsx", "export const Foo = React.memo((p: any) => { if (p.a) return <div/>; return null; });\n", "<anonymous@1>", 2),
            ("h.go", "package p\n\nvar Handler = func(x int) int { if x > 0 { return 1 }; return 0 }\n", "<anonymous@3>", 2),
            ("A.java", "class A {\n  static { if (x) {} }\n  Runnable r = () -> { if (z) {} };\n}\n", "A.<anonymous@2>", 2),
            ("s.rs", "static S: fn() = || { if true {} };\n", "<anonymous@1>", 2),
        ]
        for name, source, row, cc in cases:
            with self.subTest(name=name):
                rows, report = self.rows(name, source)
                self.assertEqual(rows[row]["cc"], cc)
                self.assertEqual(report["status"], "measured", report["gaps"])

    def test_closure_rows_inherit_cfg_test_from_their_item(self):
        rows, _ = self.rows("p.rs", "#[cfg(test)]\nstatic P: LazyLock<u8> = LazyLock::new(|| if true { 1 } else { 2 });\n"
                                    "static Q: LazyLock<u8> = LazyLock::new(|| 3);\n")
        self.assertEqual((rows["<anonymous@2>"]["kind"], rows["<anonymous@3>"]["kind"]), ("test", "production"))
        self.assertEqual(rows["<anonymous@2>"]["test_reason"], "#[cfg(test)] item")

    def test_two_anonymous_functions_on_one_line_get_distinct_ids(self):
        rows, _ = self.rows("two.ts", "a(() => { if (x) {} }); b(() => { if (y) {} });\n")
        self.assertEqual(set(rows), {"<anonymous@1>", "<anonymous@1:27>"})

    def test_anonymous_function_inside_a_named_function_adds_to_it(self):
        rows, _ = self.rows("in.ts", "function outer(o: any) { return o.map((v: any) => { if (v) { return 1 } return 2 }); }\n")
        self.assertEqual(set(rows), {"outer"})
        self.assertEqual(rows["outer"]["cc"], 2)

    def test_describe_and_it_callbacks_are_separate_test_rows(self):
        rows, _ = self.rows("suite.ts", 'describe("x", () => { it("y", () => { if (1) {} }); });\n')
        self.assertEqual(rows["<anonymous@1>"]["cc"], 1)
        self.assertEqual(rows["<anonymous@1>.<anonymous@1>"]["cc"], 2)
        self.assertTrue(all(r["kind"] == "test" and r["test_reason"] == "describe/it/test callback" for r in rows.values()))

    def test_decisions_outside_any_function_are_a_gap(self):
        for name, source in [("q.java", "class A { int q = a ? 1 : 2; }\n"), ("top.ts", "if (process.env.X) { start(); }\n"),
                             ("c.rs", "const N: usize = if cfg!(unix) { 1 } else { 2 };\n")]:
            with self.subTest(name=name):
                report = self.measure(name, source)
                self.assertEqual(report["status"], "incomplete")
                self.assertIn("outside any measured function", report["gaps"][0]["reason"])

    def test_swift_computed_properties_are_measured(self):
        source = ("struct V {\n  var body: some View { if x > 0 { 1 } else if x < 0 { 2 } }\n"
                  "  var label: String {\n    get { x > 0 ? \"p\" : \"n\" }\n    set { if newValue.isEmpty { } }\n  }\n"
                  "  var o: Int = 0 {\n    willSet { if newValue > 1 {} }\n    didSet { if o > 2 {} }\n  }\n}\n")
        rows, _ = self.rows("V.swift", source)
        expected = {"V.body": 3, "V.label.get": 2, "V.label.set": 2, "V.o.willSet": 2, "V.o.didSet": 2}
        self.assertEqual({k: rows[k]["cc"] for k in expected}, expected)

    def test_cfg_predicates_mark_test_code_only_when_they_require_test(self):
        cases = {"not(any(test, miri))": "production", "any(test, feature = \"x\")": "production",
                 "feature = \"test-util\"": "production", "test": "test", "all(test, unix)": "test",
                 "not(not(test))": "test", "any(test, all(test, unix))": "test", "all(not(test), unix)": "production"}
        for predicate, kind in cases.items():
            with self.subTest(predicate=predicate):
                rows, _ = self.rows("cfg.rs", f"#[cfg({predicate})]\npub fn make() {{}}\n")
                self.assertEqual(rows["make"]["kind"], kind)

    def test_rust_let_chain_and_catch_all_binding_arm(self):
        rows, _ = self.rows("l.rs", "fn iflet(o: Option<i32>) -> i32 { if let Some(v) = o && v > 3 { v } else { 0 } }\n"
                                    "fn f(x: i32) -> i32 { match x { 1 => 1, other => other } }\n"
                                    "fn g(x: i32) -> i32 { match x { 1 => 1, other if other > 2 => 2, NONE => 3, _ => 0 } }\n")
        self.assertEqual((rows["iflet"]["cc"], rows["f"]["cc"], rows["g"]["cc"]), (3, 2, 4))

    def test_swift_conditions_count_comma_separated_clauses_and_where_guards(self):
        source = ("func a(x: Int?, y: Int?) { if let x, let y, x > y { } }\n"
                  "func d(x: Int?) { if case .some(let v) = x { } }\n"
                  "func e(x: Int?) { if case let .some(v) = x, v > 1 { } }\n"
                  "func s(x: Int) { switch x { case 3 where x > 2: break; case 1, 2: break; default: break } }\n")
        rows, _ = self.rows("c.swift", source)
        self.assertEqual({k: rows[k]["cc"] for k in "ades"}, {"a": 4, "d": 2, "e": 3, "s": 4})

    def test_go_generic_receivers_use_the_base_type(self):
        rows, _ = self.rows("g.go", "package p\nfunc (s *Stack[T]) Push(v T) {}\nfunc (m Map[K, V]) Get() {}\nfunc (Stack[T]) Pop() {}\n")
        self.assertEqual(set(rows), {"Stack.Push", "Map.Get", "Stack.Pop"})

    def test_java_case_null_default_is_the_default_arm(self):
        rows, _ = self.rows("B.java", 'class A { String f(Object o){ return switch(o){ case null, default -> "c"; case 1, 2 -> "d"; }; } }\n')
        self.assertEqual(rows["A.f"]["cc"], 2)

    def test_rust_crate_roots_resolve_modules_beside_them(self):
        (self.root / "Cargo.toml").write_text("[package]\nname = \"x\"\n")
        files = {"src/bin/tool.rs": "#[cfg(test)]\nmod helpers;\nfn main() {}\n", "src/bin/helpers.rs": "fn help() {}\n",
                 "tests/it.rs": "#[cfg(test)]\nmod common;\n", "tests/common.rs": "fn shared() {}\n",
                 "src/lib.rs": "mod outer {\n    #[cfg(test)]\n    #[path = \"t.rs\"]\n    mod t;\n}\n", "src/outer/t.rs": "fn inner_test() {}\n"}
        for name, text in files.items():
            (self.root / name).parent.mkdir(parents=True, exist_ok=True)
            (self.root / name).write_text(text)
        rows = {r["name"]: r for r in complexity.measure(self.root, ["src", "tests"])["functions"]}
        self.assertEqual(rows["help"]["test_reason"], "module declared under #[cfg(test)] in src/bin/tool.rs")
        self.assertEqual(rows["inner_test"]["test_reason"], "module declared under #[cfg(test)] in src/lib.rs")
        self.assertEqual(rows["shared"]["kind"], "test")

    def test_duplicate_banding_follows_the_threshold(self):
        body = "    let mut n = 0;\n" + "    if a > n { n += a; } else { n -= 1; }\n    for i in 0..a { if i % 2 == 0 { n += i; } }\n" * 4 + "    n\n"
        (self.root / "d.rs").write_text(f"fn one(a: u32) -> u32 {{\n{body}}}\nfn two(b: u32) -> u32 {{\n{body.replace('a', 'b')}}}\n")
        for similarity in (0.3, 0.5, 0.8, 0.95, 1.0, 0.0):
            with self.subTest(similarity=similarity):
                duplicates = complexity.measure(self.root, ["d.rs"], duplicates=True, similarity=similarity)["duplicates"]
                self.assertGreaterEqual(duplicates["estimated_recall_at_threshold"], 0.98)
                self.assertEqual(duplicates["candidate_pairs_found"], 1)
                self.assertNotIn("pairs_at_or_above_threshold", duplicates)
                self.assertEqual(duplicates["gaps"][0]["language"], "python")


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
