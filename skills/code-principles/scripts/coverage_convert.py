#!/usr/bin/env python3
"""Convert a coverage report into source-bound function coverage for complexity.py.

Inputs (produced by the project's own tooling; this script runs none of it):
  lcov    Rust (cargo llvm-cov --lcov), Swift (xcrun llvm-cov export -format=lcov),
          TypeScript/JavaScript (c8, Jest, Vitest lcov reporters), Python (coverage lcov)
  go      Go coverprofile (go test -coverprofile=cover.out ./...)
  jacoco  Java JaCoCo XML report

Function coverage is LINE coverage inside each measured function's span, with
named nested functions' lines removed. Branch-level partial coverage is not
measured: a one-line function reads 0% or 100%. Functions with no executable
lines in the report get no value, so complexity.py keeps their CRAP unknown.

The output binds every file to the SHA256 of its source at conversion time, so
complexity.py drops coverage for a file edited afterwards. A source file modified
after the coverage report was written is reported as a gap and left out. That
check uses file modification times only: a report re-exported later from old
profile data (for example llvm-cov export run again on stale .profdata) looks
fresh, so regenerate coverage from a current test run.

Report paths are matched to measured files exactly, by the Go module path in
go.mod for Go profiles, or by a shared path suffix. A suffix that is only the
file name, when other measured files share that name, is ambiguous and stays
unmatched.
"""
import argparse
from collections import defaultdict
import json
import os
from pathlib import Path
import sys
import xml.etree.ElementTree as ElementTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
import complexity  # noqa: E402

FORMATS = ("lcov", "go", "jacoco")


def parse_lcov(text):
    """Return {source path: {line: hit count}} from lcov DA records."""
    files, current = defaultdict(dict), None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("SF:"):
            current = line[3:]
        elif line.startswith("DA:") and current is not None:
            fields = line[3:].split(",")
            number, hits = int(fields[0]), int(float(fields[1]))
            files[current][number] = max(files[current].get(number, 0), hits)
        elif line == "end_of_record":
            current = None
    return files


def parse_go(text):
    """Return {import path: {line: hit count}} from a Go coverprofile."""
    files = defaultdict(dict)
    for raw in text.splitlines():
        if not raw.strip() or raw.startswith("mode:"):
            continue
        location, _statements, count = raw.rsplit(" ", 2)
        name, span = location.rsplit(":", 1)
        start, end = span.split(",")
        first, last = int(start.split(".")[0]), int(end.split(".")[0])
        for number in range(first, last + 1):
            files[name][number] = max(files[name].get(number, 0), int(count))
    return files


def parse_jacoco(text):
    """Return {package/SourceFile.java: {line: covered instruction count}}."""
    files = defaultdict(dict)
    root = ElementTree.fromstring(text)
    for package in root.iter("package"):
        for source in package.iter("sourcefile"):
            name = f"{package.get('name')}/{source.get('name')}".lstrip("/")
            for line in source.iter("line"):
                missed, covered = int(line.get("mi", 0)), int(line.get("ci", 0))
                if missed + covered:
                    files[name][int(line.get("nr"))] = covered
    return files


def go_modules(root, measured_paths):
    """Map each Go module path to its root-relative directory, from go.mod files at or above measured .go files."""
    modules = {}
    directories = {Path(p).parent for p in measured_paths if p.endswith(".go")}
    for directory in directories:
        for folder in [directory, *directory.parents]:
            gomod = root / folder / "go.mod"
            if gomod.is_file():
                for line in gomod.read_text(encoding="utf-8", errors="replace").splitlines():
                    words = line.split("//")[0].split()
                    if len(words) == 2 and words[0] == "module":
                        modules[words[1].strip('"')] = folder.as_posix()
                        break
                break
    return modules


def resolve(report_name, root, measured_paths, modules=None):
    """Map a report's file name to one measured root-relative path, or None."""
    candidate = Path(report_name)
    if candidate.is_absolute():
        try:
            rel = candidate.resolve().relative_to(root).as_posix()
        except ValueError:
            return None
        return rel if rel in measured_paths else None
    if report_name in measured_paths:
        return report_name
    owners = [m for m in (modules or {}) if report_name.startswith(m + "/")]
    if owners:
        # Go import path: strip the longest module path; go.mod is authoritative.
        module = max(owners, key=len)
        rel = (Path(modules[module]) / report_name[len(module) + 1:]).as_posix()
        rel = rel[2:] if rel.startswith("./") else rel
        return rel if rel in measured_paths else None
    matches = [p for p in measured_paths if p.endswith("/" + report_name) or report_name.endswith("/" + p)]
    if len(matches) != 1:
        return None
    match = matches[0]
    shared_name_only = "/" not in report_name or "/" not in match
    same_name = [p for p in measured_paths if Path(p).name == Path(match).name]
    return None if shared_name_only and len(same_name) > 1 else match


def function_percentages(rows, hits):
    """Line coverage per function, excluding lines of named functions nested inside it."""
    result = {}
    for row in rows:
        # Strictly contained rows only: a row with the same span is a sibling, not a child.
        nested = [r for r in rows if r is not row and row["line"] <= r["line"] and r["end_line"] <= row["end_line"]
                  and (r["line"], r["end_line"]) != (row["line"], row["end_line"])]
        lines = [n for n in range(row["line"], row["end_line"] + 1)
                 if n in hits and not any(r["line"] <= n <= r["end_line"] for r in nested)]
        if lines:
            covered = sum(hits[n] > 0 for n in lines)
            result[row["function_id"]] = round(100 * covered / len(lines), 4)
    return result


def convert(root, report_path, fmt, paths=None):
    root = Path(root).resolve()
    report_path = Path(report_path)
    text = report_path.read_text(encoding="utf-8")
    parsed = {"lcov": parse_lcov, "go": parse_go, "jacoco": parse_jacoco}[fmt](text)
    measured = complexity.measure(root, paths)
    by_path = defaultdict(list)
    for row in measured["functions"]:
        by_path[row["path"]].append(row)
    report_mtime = report_path.stat().st_mtime
    files, gaps, unmatched = {}, list(measured["gaps"]), []
    modules = go_modules(root, set(by_path)) if fmt == "go" else {}
    for name, hits in parsed.items():
        rel = resolve(name, root, set(by_path), modules)
        if rel is None:
            unmatched.append(name)
            continue
        if (root / rel).stat().st_mtime > report_mtime:
            gaps.append({"path": rel, "reason": "source modified after the coverage report; rerun coverage"})
            continue
        functions = function_percentages(by_path[rel], hits)
        if functions:
            files[rel] = {"sha256": measured["source_sha256"][rel], "functions": functions}
    for rel in sorted(set(by_path) - set(files)):
        if not any(g["path"] == rel for g in gaps):
            gaps.append({"path": rel, "reason": "no coverage data for this file"})
    return {"schema": complexity.COVERAGE_SCHEMA, "files": files,
            "provenance": {"input": str(report_path.resolve()), "format": fmt, "revision": measured["revision"],
                           "method": "line coverage within function span; nested named functions excluded",
                           "analyzers": measured["analyzers"]},
            "unmatched_report_files": sorted(unmatched)[:200], "unmatched_report_file_count": len(unmatched),
            "gaps": gaps}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                     epilog="Exit: 0 written; 2 invalid input. Pass the output to complexity.py --coverage.")
    parser.add_argument("root", help="source root used for measurement")
    parser.add_argument("report", help="coverage report file")
    parser.add_argument("--format", required=True, choices=FORMATS)
    parser.add_argument("--paths", nargs="+", help="root-relative files/directories to measure (default: tracked source)")
    args = parser.parse_args(argv)
    try:
        document = convert(args.root, args.report, args.format, args.paths)
    except (OSError, ValueError, ElementTree.ParseError, IndexError) as error:
        print(json.dumps({"schema": complexity.COVERAGE_SCHEMA, "status": "invalid", "error": str(error)}))
        return 2
    print(json.dumps(document, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
