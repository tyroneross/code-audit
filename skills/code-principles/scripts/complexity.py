#!/usr/bin/env python3
"""Measure named functions without executing project code.

Python is parsed with the stdlib AST. Rust, TypeScript/TSX, Java, Go and Swift
are parsed by the bundled tree-sitter analyzer in runtime/complexity (see its
src/main.rs for per-language counting rules). Build it once, offline:
  cargo build --release --offline --manifest-path <plugin>/runtime/complexity/Cargo.toml
or point CODE_AUDIT_COMPLEXITY_BIN at a built binary. A missing analyzer is a
reported gap for those files, never a clean result.

Python counting:

CC starts at 1 and adds 1 for if/conditional expressions, loops, except handlers,
asserts, each comprehension generator/filter and each non-default match case;
boolean chains add len(values)-1. Nested functions/classes/lambdas do not add to
an enclosing function. Each named nested function is measured separately.

Coverage JSON: {"schema":"code-audit.function-coverage.v1", "files":{
  "module.py":{"sha256":"<source bytes SHA256>","functions":{"name:1":75}}}}
Function keys are qualified names plus definition line (e.g. "Class.method:8").
Coverage percentages must be finite numbers in [0,100]. A matching source digest
is required. Missing compatible function coverage means coverage and CRAP null.
CRAP = CC**2 * (1 - coverage/100)**3 + CC. Scores are review leads, not defects.
Each function row carries language, kind (production|test) and test_reason.
Test code is identified by path convention (shared with scan.py) or by the
analyzer (#[test], #[cfg(test)], @Test, XCTestCase). Other languages remain
explicit gaps. --duplicates adds structural duplicate candidates for the
tree-sitter languages (similarity >= 0.8 by default); they are leads only, and
Python functions are not compared (stated as a gap in the duplicates section).
In the tree-sitter languages, decision points outside every function (top-level
statements, initializers) are a reported gap, never silently dropped; Python
module-level code is not measured.

Structural signals: each row also carries max_nesting, bumps, condition_operators,
params and lines (name line to closing line, inclusive). `signals` names the ones
at or above --structure thresholds; `hotspot` stays the CC rule. `patterns` lists
parser-backed leads (identical_operands, self_assignment, duplicate_branches,
repeated_condition). Signals and patterns are places to read, never defects, and
none changes the exit status. An analyzer built before these fields existed
yields null values and one gap.
Directory walks select source suffixes, exclude generated/vendor directories
(SKIP below), and do not follow symlinked subdirectories. Explicit files override
these filters. Git inventory disables repository-configured fsmonitor hooks.
"""
import argparse
import ast
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import python_structure  # noqa: E402
from scan import TEST_PATH  # noqa: E402  shared test-path convention

SKIP = {".git", "node_modules", "dist", "build", "vendor", "target", "__pycache__", ".venv"}
SOURCE_SUFFIXES = {".py", ".ts", ".mts", ".cts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".rs", ".go", ".swift", ".java", ".kt", ".rb", ".cs", ".c", ".cpp", ".h", ".hpp"}
COVERAGE_SCHEMA = "code-audit.function-coverage.v1"
NATIVE_SUFFIXES = {".rs", ".ts", ".mts", ".cts", ".tsx", ".java", ".go", ".swift"}
NATIVE_MANIFEST = Path(__file__).resolve().parents[3] / "runtime" / "complexity" / "Cargo.toml"
PYTHON_ANALYZER = {"name": "python-ast", "version": sys.version.split()[0], "method": "python-ast-decisions-v1",
                   "structure_method": "python-ast-structure-v1", "languages": ["python"]}
STRUCTURE_FIELDS = ("max_nesting", "bumps", "condition_operators", "params")
# Inclusive reading-order thresholds. Sources and the two unsourced defaults: references/measurement.md.
STRUCTURE_THRESHOLDS = {"max_nesting": 3, "lines": 50, "params": 6, "bumps": 2, "condition_operators": 3}


def native_binary():
    """Return the built tree-sitter analyzer, or None when it is unavailable."""
    override = os.environ.get("CODE_AUDIT_COMPLEXITY_BIN")
    if override:
        candidates = [Path(override)]
    else:
        installed = shutil.which("code-audit-complexity")
        candidates = [NATIVE_MANIFEST.parent / "target" / "release" / "code-audit-complexity", *([Path(installed)] if installed else [])]
    return next((c for c in candidates if c.is_file() and os.access(c, os.X_OK)), None)


def native_build_hint():
    return f"cargo build --release --offline --manifest-path {NATIVE_MANIFEST} (or cargo install --offline --path {NATIVE_MANIFEST.parent})"


def classify(path, test_reason=None):
    """Return (kind, reason): analyzer evidence first, then path convention."""
    if test_reason:
        return "test", test_reason
    if TEST_PATH.search(path):
        return "test", "test path convention"
    return "production", None


def run_native(root, names, duplicates, similarity, gaps):
    """Run the analyzer on root-relative names; return its report or None."""
    if not names:
        return None
    binary = native_binary()
    if binary is None:
        for name in names:
            gaps.append({"path": name, "reason": f"tree-sitter analyzer not built; run: {native_build_hint()}"})
        return None
    command = [str(binary), "--root", str(root)]
    if duplicates:
        command += ["--duplicates", "--similarity", str(similarity)]
    try:
        result = subprocess.run([*command, "--", *names], capture_output=True, timeout=600)
        report = json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
        for name in names:
            gaps.append({"path": name, "reason": f"tree-sitter analyzer failed: {error}"})
        return None
    if result.returncode != 0 or report.get("status") != "measured":
        for name in names:
            gaps.append({"path": name, "reason": f"tree-sitter analyzer failed: {report.get('error', result.returncode)}"})
        return None
    return report


class Decisions(ast.NodeVisitor):
    """Count decisions in one function body, excluding nested scopes."""
    def __init__(self):
        self.score = 1

    def visit_FunctionDef(self, node):
        pass

    visit_AsyncFunctionDef = visit_FunctionDef
    visit_ClassDef = visit_FunctionDef
    visit_Lambda = visit_FunctionDef

    def generic_visit(self, node):
        if isinstance(node, (ast.If, ast.IfExp, ast.For, ast.AsyncFor, ast.While,
                             ast.ExceptHandler, ast.Assert)):
            self.score += 1
        elif isinstance(node, ast.BoolOp):
            self.score += len(node.values) - 1
        elif isinstance(node, ast.comprehension):
            self.score += 1 + len(node.ifs)
        elif isinstance(node, ast.match_case):
            # A bare capture (including _) is the default arm, not a decision.
            self.score += (not isinstance(node.pattern, ast.MatchAs)
                           or node.pattern.pattern is not None or node.guard is not None)
        super().generic_visit(node)


class Functions(ast.NodeVisitor):
    def __init__(self):
        self.scope = []
        self.rows = []
        self.in_class = False  # the innermost enclosing scope is a class body

    def enter(self, node, in_class):
        self.scope.append(node.name)
        outer, self.in_class = self.in_class, in_class
        self.generic_visit(node)
        self.in_class = outer
        self.scope.pop()

    def visit_ClassDef(self, node):
        self.enter(node, True)

    def visit_FunctionDef(self, node):
        name = ".".join([*self.scope, node.name])
        counter = Decisions()
        for statement in node.body:
            counter.visit(statement)
        shape = python_structure.Shape(node.body)
        self.rows.append({"name": name, "line": node.lineno,
                          "end_line": node.end_lineno, "function_id": f"{name}:{node.lineno}",
                          "cc": counter.score, "max_nesting": shape.max_nesting, "bumps": shape.bumps,
                          "condition_operators": shape.condition_operators,
                          "params": python_structure.param_count(node.args, self.in_class)})
        self.enter(node, False)

    visit_AsyncFunctionDef = visit_FunctionDef


def coverage_document(path):
    if path is None:
        return {}
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("schema") != COVERAGE_SCHEMA or not isinstance(document.get("files"), dict):
        raise ValueError(f"coverage requires schema {COVERAGE_SCHEMA!r} and files object")
    files = document["files"]
    for name, entry in files.items():
        if not isinstance(name, str) or Path(name).is_absolute() or ".." in Path(name).parts:
            raise ValueError("coverage paths must be source-root-relative")
        if not isinstance(entry, dict) or not isinstance(entry.get("sha256"), str) or len(entry["sha256"]) != 64 or any(c not in "0123456789abcdef" for c in entry["sha256"]):
            raise ValueError(f"coverage {name!r} requires a lowercase SHA256 source digest")
        if not isinstance(entry.get("functions"), dict):
            raise ValueError(f"coverage {name!r} requires functions object")
        for function_id, percent in entry["functions"].items():
            if not isinstance(function_id, str) or not function_id:
                raise ValueError("coverage function identifiers must be nonempty strings")
            if isinstance(percent, bool) or not isinstance(percent, (int, float)) or not 0 <= percent <= 100 or not math.isfinite(percent):
                raise ValueError(f"coverage {name}:{function_id} must be a finite percentage in [0,100]")
    return files


def git(root, *args):
    try:
        result = subprocess.run(["git", "-c", "core.fsmonitor=false", "-C", str(root), *args], capture_output=True, timeout=10)
        return result.stdout if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def walk(path, gaps):
    def unreadable(error):
        gaps.append({"path": str(error.filename), "reason": f"cannot enumerate source directory: {error}"})
    for directory, dirs, names in os.walk(path, onerror=unreadable):
        dirs[:] = sorted(d for d in dirs if d not in SKIP)
        for name in sorted(names):
            yield Path(directory) / name


def select(root, paths):
    gaps = []
    if paths is not None:
        chosen = []
        for name in paths:
            path = root / name
            try:
                path.resolve().relative_to(root)
            except (ValueError, OSError):
                gaps.append({"path": str(path), "reason": "outside source root"})
                continue
            chosen.extend((p for p in walk(path, gaps) if p.suffix in SOURCE_SUFFIXES)
                          if path.is_dir() else [path])
        return chosen, "explicit", gaps
    tracked = git(root, "ls-files", "-z")
    if tracked is not None:
        return [root / os.fsdecode(p) for p in tracked.split(b"\0") if p and Path(os.fsdecode(p)).suffix in SOURCE_SUFFIXES and not set(Path(os.fsdecode(p)).parts) & SKIP], "tracked-source", gaps
    return [p for p in walk(root, gaps) if p.suffix in SOURCE_SUFFIXES], "walk-source", gaps


def structure_thresholds(overrides):
    """Defaults with `name=value` overrides applied; rejects unknown names and non-positive values."""
    thresholds = dict(STRUCTURE_THRESHOLDS)
    for item in overrides or []:
        name, _, value = item.partition("=")
        if name not in thresholds or not value.isdigit() or int(value) < 1:
            raise ValueError(f"--structure expects name=positive-integer with name in {sorted(thresholds)}; got {item!r}")
        thresholds[name] = int(value)
    return thresholds


def measure(root, paths=None, coverage=None, threshold=10, duplicates=False, similarity=0.8, structure=None):
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError(f"source root is not a directory: {root}")
    if not isinstance(threshold, int) or isinstance(threshold, bool) or threshold < 1:
        raise ValueError("threshold must be a positive integer")
    if isinstance(similarity, bool) or not isinstance(similarity, (int, float)) or not 0 <= similarity <= 1:
        raise ValueError("similarity must be a number in [0,1]")
    coverage = coverage_document(coverage)
    limits = structure_thresholds(structure)
    selected, selection, gaps = select(root, paths)
    rows, digests, patterns = [], {}, []
    selected_names = set()
    seen_files = set()
    native_names = []
    for path in selected:
        try:
            name = path.resolve().relative_to(root).as_posix()
        except (ValueError, OSError):
            gaps.append({"path": str(path), "reason": "outside source root"})
            continue
        try:
            identity = (path.stat().st_dev, path.stat().st_ino)
        except OSError:
            identity = name
        # Case-insensitive volumes can spell one file two ways; dedupe by file identity.
        if name in selected_names or identity in seen_files:
            continue
        seen_files.add(identity)
        selected_names.add(name)
        if path.suffix in NATIVE_SUFFIXES:
            native_names.append(name)
            continue
        if path.suffix != ".py":
            gaps.append({"path": name, "reason": "unsupported language; analyzers cover Python, Rust, TypeScript, Java, Go and Swift"})
            continue
        try:
            raw = path.read_bytes()
            tree = ast.parse(raw, filename=name)
        except (OSError, SyntaxError, ValueError) as error:
            gaps.append({"path": name, "reason": f"cannot parse source: {error}"})
            continue
        digest = hashlib.sha256(raw).hexdigest()
        digests[name] = digest
        supplied = coverage.get(name)
        compatible = supplied is not None and supplied["sha256"] == digest
        if supplied is not None and not compatible:
            gaps.append({"path": name, "reason": "coverage source digest mismatch; CRAP unavailable"})
        visitor = Functions()
        try:
            visitor.visit(tree)
            leads = python_structure.patterns(tree)
        except RecursionError:
            gaps.append({"path": name, "reason": "expression nesting exceeds the interpreter recursion limit; file not measured"})
            continue
        for row in visitor.rows:
            add_row(rows, row, name, "python", None, supplied if compatible else None, threshold, limits)
        for rule, line, detail in leads:
            owner = max((r for r in visitor.rows if r["line"] <= line <= r["end_line"]), key=lambda r: r["line"], default=None)
            patterns.append({"rule": rule, "path": name, "line": line, "language": "python",
                             "function_id": owner and owner["function_id"], "detail": detail})
    native = run_native(root, native_names, duplicates, similarity, gaps)
    if native and "structure_method" not in native["analyzer"]:
        gaps.append({"path": ".", "reason": "tree-sitter analyzer predates structural signals and pattern leads; "
                                            f"those fields are null for its files. Rebuild: {native_build_hint()}"})
    test_modules = rust_test_module_files((native or {}).get("files", []))
    for entry in (native or {}).get("files", []):
        name = entry["path"]
        if "error" in entry:
            gaps.append({"path": name, "reason": entry["error"]})
            continue
        digests[name] = entry["sha256"]
        if entry["parse_errors"]:
            gaps.append({"path": name, "reason": "source has parse errors; affected functions may be missing or miscounted"})
        if entry.get("unowned_decisions", 0) > 0:
            gaps.append({"path": name, "reason": f"{entry['unowned_decisions']} decision points outside any measured function "
                                                 "(top-level statements or initializers) are not attributed to a row"})
        supplied = coverage.get(name)
        compatible = supplied is not None and supplied["sha256"] == entry["sha256"]
        if supplied is not None and not compatible:
            gaps.append({"path": name, "reason": "coverage source digest mismatch; CRAP unavailable"})
        for function in entry["functions"]:
            row = {key: function[key] for key in ("name", "line", "end_line", "function_id", "cc")}
            row.update({key: function.get(key) for key in STRUCTURE_FIELDS})
            reason = function["test_reason"] or test_modules.get(name)
            add_row(rows, row, name, entry["language"], reason, supplied if compatible else None, threshold, limits)
        patterns.extend({**lead, "path": name, "language": entry["language"]} for lead in entry.get("patterns", []))
    if not rows:
        gaps.append({"path": ".", "reason": "no named functions measured; no clean-review conclusion"})
    analyzers = [PYTHON_ANALYZER] if any(r["language"] == "python" for r in rows) or not native else []
    if native:
        analyzers.append({**native["analyzer"], "languages": sorted({e["language"] for e in native["files"] if "language" in e})})
    languages = {}
    for row in rows:
        languages[row["language"]] = languages.get(row["language"], 0) + 1
    duplicate_report = label_duplicates(native.get("duplicates"), rows) if duplicates and native else None
    kinds = {(r["path"], r["function_id"]): r["kind"] for r in rows}
    for lead in patterns:
        lead["kind"] = kinds.get((lead["path"], lead["function_id"])) or classify(lead["path"])[0]
    patterns.sort(key=lambda lead: (lead["kind"] != "production", lead["path"], lead["line"], lead["rule"]))
    revision = git(root, "rev-parse", "HEAD")
    return {"schema": "code-audit.complexity.v1", "root": str(root),
            "revision": revision.decode().strip() if revision else None,
            "selection": selection, "selected_files": sorted(selected_names),
            "directory_walk_exclusions": sorted(SKIP), "follow_directory_symlinks": False,
            "source_sha256": digests, "threshold": threshold, "hotspot_rule": "cc >= threshold",
            "method": "named functions; python-ast-decisions-v1 and tree-sitter-decisions-v1; see --help for counted decisions",
            "analyzers": analyzers, "languages": languages,
            "status": "incomplete" if gaps else "measured", "gaps": gaps,
            "function_count": len(rows), "hotspot_count": sum(r["hotspot"] for r in rows),
            "production_function_count": sum(r["kind"] == "production" for r in rows),
            "test_function_count": sum(r["kind"] == "test" for r in rows),
            "production_hotspot_count": sum(r["hotspot"] and r["kind"] == "production" for r in rows),
            "coverage_unavailable_functions": sum(r["coverage_percent"] is None for r in rows),
            "structure_thresholds": limits, "structure_rule": "value >= threshold",
            "structure_signal_count": sum(bool(r["signals"]) for r in rows),
            "production_structure_signal_count": sum(bool(r["signals"]) and r["kind"] == "production" for r in rows),
            "pattern_count": len(patterns),
            "production_pattern_count": sum(lead["kind"] == "production" for lead in patterns),
            "patterns": patterns,
            **({"duplicates": duplicate_report} if duplicate_report else {}),
            "functions": sorted(rows, key=lambda r: (-r["cc"], r["path"], r["line"]))}


def rust_test_module_files(entries):
    """Map Rust files loaded only as test modules to the declaration that made them test code.

    `#[cfg(test)] mod name;` loads name.rs or name/mod.rs, and every module declared
    inside a test-only file is test-only too. Resolution covers selected files only.
    """
    declared = {e["path"]: e.get("modules", []) for e in entries if "error" not in e}
    found, queue = {}, []
    for path, modules in declared.items():
        for module in modules:
            if module["under_test"]:
                queue.append((module["candidates"], f"module declared under #[cfg(test)] in {path}"))
    while queue:
        candidates, reason = queue.pop()
        for candidate in candidates:
            if candidate in declared and candidate not in found:
                found[candidate] = reason
                queue.extend((m["candidates"], f"module declared inside test-only {candidate}") for m in declared[candidate])
    return found


def label_duplicates(report, rows):
    """Tag each duplicate side with production|test so test-only pairs can be read separately."""
    if not report:
        return report
    kinds = {(r["path"], r["function_id"]): r["kind"] for r in rows}
    for pair in report["pairs"]:
        for side in ("a", "b"):
            pair[side]["kind"] = kinds.get((pair[side]["path"], pair[side]["function_id"]))
    report["production_pairs_reported"] = sum(p["a"]["kind"] == "production" and p["b"]["kind"] == "production" for p in report["pairs"])
    python_rows = sum(r["language"] == "python" for r in rows)
    report["gaps"] = [{"language": "python", "functions_not_compared": python_rows,
                       "reason": "duplicate detection covers the tree-sitter languages only; Python functions are not compared"}]
    return report


def add_row(rows, row, path, language, test_reason, supplied, threshold, limits):
    """Attach path, language, test split, coverage, CRAP and structural signals to one function row."""
    percent = supplied["functions"].get(row["function_id"]) if supplied else None
    kind, reason = classify(path, test_reason)
    row["lines"] = row["end_line"] - row["line"] + 1
    row.update(path=path, language=language, kind=kind, test_reason=reason, coverage_percent=percent,
               crap=None if percent is None else round(row["cc"] ** 2 * (1 - percent / 100) ** 3 + row["cc"], 6),
               hotspot=row["cc"] >= threshold,
               signals=[name for name, limit in limits.items() if row.get(name) is not None and row[name] >= limit])
    rows.append(row)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                     epilog="Exit: 0 report measured; 1 --fail-on-hotspots found CC >= threshold; 2 incomplete scope or invalid input. No project code/tests are executed or dependencies installed.")
    parser.add_argument("root", help="source root")
    parser.add_argument("--paths", nargs="+", help="explicit root-relative files/directories (default: tracked source files, walk fallback)")
    parser.add_argument("--coverage", help="source-digest-bound function-coverage JSON; absent coverage remains unknown")
    parser.add_argument("--threshold", type=int, default=10, help="CC hotspot boundary, inclusive (default: 10)")
    parser.add_argument("--fail-on-hotspots", action="store_true", help="exit 1 for measured hotspots; never establishes a defect")
    parser.add_argument("--duplicates", action="store_true", help="add structural duplicate candidates (tree-sitter languages only)")
    parser.add_argument("--similarity", type=float, default=0.8, help="duplicate candidate similarity, inclusive (default: 0.8)")
    parser.add_argument("--structure", nargs="+", metavar="NAME=N",
                        help="inclusive structural-signal thresholds (default: " + " ".join(f"{k}={v}" for k, v in STRUCTURE_THRESHOLDS.items()) + ")")
    args = parser.parse_args(argv)
    try:
        report = measure(args.root, args.paths, args.coverage, args.threshold, args.duplicates, args.similarity, args.structure)
    except (ValueError, OSError, json.JSONDecodeError) as error:
        print(json.dumps({"schema": "code-audit.complexity.v1", "status": "invalid", "error": str(error)}))
        return 2
    print(json.dumps(report, indent=2))
    if report["status"] == "incomplete":
        return 2
    return int(args.fail_on_hotspots and report["hotspot_count"] > 0)


if __name__ == "__main__":
    sys.exit(main())
