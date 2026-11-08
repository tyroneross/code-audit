#!/usr/bin/env python3
"""Measure named Python functions without executing project code.

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
Only Python is supported; selected other source languages remain explicit gaps.
Directory walks exclude generated/vendor directories (SKIP below) and do not
follow symlinked subdirectories. Explicit file selections override SKIP.
"""
import argparse
import ast
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys

SKIP = {".git", "node_modules", "dist", "build", "vendor", "target", "__pycache__", ".venv"}
SOURCE_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".rs", ".go", ".swift", ".java", ".kt", ".rb", ".cs", ".c", ".cpp", ".h", ".hpp"}
COVERAGE_SCHEMA = "code-audit.function-coverage.v1"


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

    def visit_ClassDef(self, node):
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node):
        name = ".".join([*self.scope, node.name])
        counter = Decisions()
        for statement in node.body:
            counter.visit(statement)
        self.rows.append({"name": name, "line": node.lineno,
                          "end_line": node.end_lineno, "function_id": f"{name}:{node.lineno}",
                          "cc": counter.score})
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

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
        result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, timeout=10)
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
            chosen.extend(walk(path, gaps) if path.is_dir() else [path])
        return chosen, "explicit", gaps
    tracked = git(root, "ls-files", "-z")
    if tracked is not None:
        return [root / os.fsdecode(p) for p in tracked.split(b"\0") if p and Path(os.fsdecode(p)).suffix in SOURCE_SUFFIXES and not set(Path(os.fsdecode(p)).parts) & SKIP], "tracked-source", gaps
    return [p for p in walk(root, gaps) if p.suffix in SOURCE_SUFFIXES], "walk-source", gaps


def measure(root, paths=None, coverage=None, threshold=10):
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError(f"source root is not a directory: {root}")
    if not isinstance(threshold, int) or isinstance(threshold, bool) or threshold < 1:
        raise ValueError("threshold must be a positive integer")
    coverage = coverage_document(coverage)
    selected, selection, gaps = select(root, paths)
    rows, digests = [], {}
    selected_names = set()
    for path in selected:
        try:
            name = path.resolve().relative_to(root).as_posix()
        except (ValueError, OSError):
            gaps.append({"path": str(path), "reason": "outside source root"})
            continue
        if name in selected_names:
            continue
        selected_names.add(name)
        if path.suffix != ".py":
            gaps.append({"path": name, "reason": "unsupported language; Python named functions only"})
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
        visitor.visit(tree)
        for row in visitor.rows:
            percent = supplied["functions"].get(row["function_id"]) if compatible else None
            row.update(path=name, coverage_percent=percent,
                       crap=None if percent is None else round(row["cc"] ** 2 * (1 - percent / 100) ** 3 + row["cc"], 6),
                       hotspot=row["cc"] >= threshold)
            rows.append(row)
    if not rows:
        gaps.append({"path": ".", "reason": "no named Python functions measured; no clean-review conclusion"})
    revision = git(root, "rev-parse", "HEAD")
    return {"schema": "code-audit.complexity.v1", "root": str(root),
            "revision": revision.decode().strip() if revision else None,
            "selection": selection, "selected_files": sorted(selected_names),
            "directory_walk_exclusions": sorted(SKIP), "follow_directory_symlinks": False,
            "source_sha256": digests, "threshold": threshold, "hotspot_rule": "cc >= threshold",
            "method": "python-ast-decisions-v1; named functions; see --help for counted decisions",
            "status": "incomplete" if gaps else "measured", "gaps": gaps,
            "function_count": len(rows), "hotspot_count": sum(r["hotspot"] for r in rows),
            "coverage_unavailable_functions": sum(r["coverage_percent"] is None for r in rows),
            "functions": sorted(rows, key=lambda r: (-r["cc"], r["path"], r["line"]))}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                     epilog="Exit: 0 report measured; 1 --fail-on-hotspots found CC >= threshold; 2 incomplete scope or invalid input. No project code/tests are executed or dependencies installed.")
    parser.add_argument("root", help="source root")
    parser.add_argument("--paths", nargs="+", help="explicit root-relative files/directories (default: tracked source files, walk fallback)")
    parser.add_argument("--coverage", help="source-digest-bound function-coverage JSON; absent coverage remains unknown")
    parser.add_argument("--threshold", type=int, default=10, help="CC hotspot boundary, inclusive (default: 10)")
    parser.add_argument("--fail-on-hotspots", action="store_true", help="exit 1 for measured hotspots; never establishes a defect")
    args = parser.parse_args(argv)
    try:
        report = measure(args.root, args.paths, args.coverage, args.threshold)
    except (ValueError, OSError, json.JSONDecodeError) as error:
        print(json.dumps({"schema": "code-audit.complexity.v1", "status": "invalid", "error": str(error)}))
        return 2
    print(json.dumps(report, indent=2))
    if report["status"] == "incomplete":
        return 2
    return int(args.fail_on_hotspots and report["hotspot_count"] > 0)


if __name__ == "__main__":
    sys.exit(main())
