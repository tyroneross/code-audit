#!/usr/bin/env python3
"""Compare the working tree with a base revision: what changed in size, structure, tests and protected regions.

  structure_delta.py ROOT [--base REV] [--max-changed-lines 500] [--fail-on-flags]

Without --base the base is the merge base of HEAD with the first of: the origin/HEAD target, origin/main,
origin/master, main, master; HEAD when none resolves. Uncommitted and untracked files count as changes.

Changed source files are measured at the base (from `git show`, written to a temporary directory) and in the
working tree with complexity.py, then functions are paired by path and name. Flags are places to look, never
defects, and a report with no flag does not show that behaviour is preserved: run the project's tests.

  tests_changed             a test file is in the change; a behaviour-preserving change normally leaves tests alone
  protected_region_changed  code between comment lines that begin with `simplify-ignore-start` and
                            `simplify-ignore-end` differs from the base
  protected_region_unbalanced  a start marker without an end, or the reverse
  large_change              more added plus deleted lines than --max-changed-lines; prefer an automated transform
                            and smaller reviewable steps
  function_got_worse        a paired function gained complexity, nesting, bumps, condition operators or parameters,
                            or newly crossed a threshold
  new_hotspot               an added production function is a CC hotspot or carries a structural signal
  pattern_introduced        a pattern lead exists now that the base did not have

Exit: 0 report written; 1 --fail-on-flags and a flag fired; 2 invalid input, Git unavailable or measurement
incomplete. Read-only: no project code or tests are executed and nothing is written inside ROOT.
"""
import argparse
import collections
import difflib
import json
from pathlib import Path
import re
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import complexity  # noqa: E402
import gitsafe  # noqa: E402
from scan import TEST_PATH  # noqa: E402  shared test-path convention

BASE_CANDIDATES = ("refs/remotes/origin/main", "refs/remotes/origin/master", "refs/heads/main", "refs/heads/master")
# A marker counts only as the first thing in a comment, so prose or a string that mentions it does not open a region.
MARKER = re.compile(r"^\s*(?:#|//|/\*|\*|<!--|--|;|%)\s*simplify-ignore-(start|end)\b")
WORSE_WHEN_HIGHER = ("cc", *complexity.STRUCTURE_FIELDS)
COMPARED = (*WORSE_WHEN_HIGHER, "lines")
MAX_CHANGED_LINES = 500


def text(output):
    return output.decode("utf-8", "replace").strip() if output else ""


def resolve_base(root, requested):
    """(commit, how it was chosen). The default follows the first existing mainline ref, like a review baseline."""
    if requested:
        commit = text(gitsafe.run(root, "rev-parse", "--verify", f"{requested}^{{commit}}"))
        if not commit:
            raise ValueError(f"base revision {requested!r} does not resolve to a commit")
        return commit, f"--base {requested}"
    head = text(gitsafe.run(root, "rev-parse", "--verify", "HEAD^{commit}"))
    if not head:
        raise ValueError("not a Git repository with a commit; pass a source root inside one")
    origin_head = text(gitsafe.run(root, "symbolic-ref", "-q", "refs/remotes/origin/HEAD"))
    for ref in dict.fromkeys([origin_head, *BASE_CANDIDATES]):
        if ref and gitsafe.run(root, "rev-parse", "--verify", f"{ref}^{{commit}}"):
            merge_base = text(gitsafe.run(root, "merge-base", "HEAD", ref))
            if merge_base:
                return merge_base, f"merge base of HEAD and {ref}"
    return head, "HEAD (no mainline ref resolved)"


def line_counts(before, after):
    """(added, deleted) lines between two byte strings, or None when either looks binary."""
    if any(b"\0" in data[:8000] for data in (before, after)):
        return None
    old, new = before.decode("utf-8", "replace").splitlines(), after.decode("utf-8", "replace").splitlines()
    added = deleted = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag != "equal":
            deleted += i2 - i1
            added += j2 - j1
    return added, deleted


def base_bytes(root, base, path):
    """The file's bytes at base, or None when it did not exist there."""
    return gitsafe.run(root, "show", *gitsafe.NO_DRIVERS, f"{base}:./{path}")


def working_bytes(root, path):
    """The working file's bytes; None unless it is a regular file, so links, FIFOs and devices are never opened."""
    full = Path(root) / path
    if gitsafe.kind(full) != "file":
        return None
    try:
        return full.read_bytes()
    except OSError:
        return None


def changed_files(root, base):
    """({path: (added, deleted) or None for binary or unreadable}, {path: (bytes at base, working bytes)}) for every
    path that differs from base, untracked included. A side that does not exist is b""; an unreadable side is None."""
    states = gitsafe.changed_paths(root, base)
    if states is None:
        raise ValueError("git could not list the base tree or hash the working files; cannot list the change")
    changed, contents = {}, {}
    for path, state in states.items():
        before = b"" if state in ("added", "untracked") else base_bytes(root, base, path)
        after = b"" if state == "deleted" else working_bytes(root, path)
        contents[path] = (before, after)
        changed[path] = None if before is None or after is None else line_counts(before, after)
    return changed, contents


def protected_regions(source):
    """(Counter of protected block texts, balanced). A block is the lines strictly between a start and an end marker."""
    blocks, current, balanced = collections.Counter(), None, True
    for line in source.splitlines(keepends=True):  # exact bytes: trailing spaces and line endings count
        marker = MARKER.match(line)
        if marker is None:
            if current is not None:
                current.append(line)
        elif marker.group(1) == "start":
            balanced, current = balanced and current is None, []
        else:
            balanced = balanced and current is not None
            if current is not None:
                blocks["".join(current)] += 1
            current = None
    return blocks, balanced and current is None


def protected_changes(contents):
    """(paths whose protected code differs from base, paths with unbalanced markers)."""
    altered, unbalanced = [], []
    for path, (before, after) in sorted(contents.items()):
        before, after = ((data or b"").decode("utf-8", "replace") for data in (before, after))
        if "simplify-ignore-" not in before + after:
            continue
        old, _ = protected_regions(before)
        new, balanced = protected_regions(after)
        if old - new:
            altered.append(path)
        if not balanced:
            unbalanced.append(path)
    return altered, unbalanced


def measure_side(root, paths, thresholds, threshold):
    """complexity report for paths under root, or an empty measured report when there is nothing to measure."""
    if not paths:
        return {"status": "measured", "gaps": [], "functions": [], "patterns": []}
    report = complexity.measure(root, sorted(paths), threshold=threshold, structure=thresholds)
    # A change with no named function is normal here, not a coverage gap.
    report["gaps"] = [g for g in report["gaps"] if not g["reason"].startswith("no named functions")]
    return report


def pair_functions(before, after):
    """(pairs, added, removed): rows matched by path and name, in line order when a name repeats."""
    def grouped(rows):
        groups = collections.defaultdict(list)
        for row in sorted(rows, key=lambda r: r["line"]):
            groups[(row["path"], row["name"])].append(row)
        return groups
    def shape(row):
        return tuple(row[name] for name in COMPARED)
    old, new = grouped(before), grouped(after)
    pairs, added, removed = [], [], []
    for key in sorted(set(old) | set(new)):
        a, b = old.get(key, []), list(new.get(key, []))
        unmatched = []
        # When a name repeats (overloads, a stub added beside an implementation), an unchanged function pairs with itself first.
        for row in a:
            twin = next((candidate for candidate in b if shape(candidate) == shape(row)), None) if len(a) != len(b) else None
            if twin is None:
                unmatched.append(row)
            else:
                b.remove(twin)
                pairs.append((row, twin))
        pairs += list(zip(unmatched, b))
        added += b[len(unmatched):]
        removed += unmatched[len(b):]
    return pairs, added, removed


def brief(row):
    return {"path": row["path"], "function_id": row["function_id"], "kind": row["kind"], "hotspot": row["hotspot"],
            "signals": row["signals"], **{name: row[name] for name in COMPARED}}


def function_changes(pairs):
    """One entry per paired function whose measurements moved, with what got higher and what newly crossed a threshold."""
    changed = []
    for old, new in pairs:
        moves = {name: [old[name], new[name]] for name in COMPARED if old[name] != new[name]}
        if not moves:
            continue
        higher = [name for name in WORSE_WHEN_HIGHER if None not in (old[name], new[name]) and new[name] > old[name]]
        crossed = sorted(set(new["signals"]) - set(old["signals"])) + (["hotspot"] if new["hotspot"] and not old["hotspot"] else [])
        changed.append({"path": new["path"], "function": new["name"], "kind": new["kind"], "changes": moves,
                        "worse": higher, "newly_flagged": crossed})
    return changed


def lead_keys(report):
    """Pattern leads keyed without line numbers, which shift when code moves."""
    owners = {r["function_id"]: r["name"] for r in report["functions"]}
    return collections.Counter((p["path"], p["rule"], owners.get(p["function_id"]), p["detail"]) for p in report["patterns"])


def totals(rows):
    return {"functions": len(rows), "sum_cc": sum(r["cc"] for r in rows), "max_cc": max((r["cc"] for r in rows), default=0),
            "max_nesting": max((r["max_nesting"] or 0 for r in rows), default=0),
            "hotspots": sum(r["hotspot"] for r in rows), "with_signals": sum(bool(r["signals"]) for r in rows)}


def compare(before, after):
    """Structure section of the report and the three structure flags."""
    pairs, added, removed = pair_functions(before["functions"], after["functions"])
    changed = function_changes(pairs)
    introduced = [{"path": path, "rule": rule, "function": function, "detail": detail}
                  for path, rule, function, detail in sorted((lead_keys(after) - lead_keys(before)).elements(), key=str)]
    section = {"before": totals(before["functions"]), "after": totals(after["functions"]),
               "changed_functions": changed, "added_functions": [brief(r) for r in added],
               "removed_functions": [brief(r) for r in removed], "patterns_introduced": introduced}
    candidates = [
        ("function_got_worse", [f"{c['path']}:{c['function']}" for c in changed if c["worse"] or c["newly_flagged"]]),
        ("new_hotspot", [f"{r['path']}:{r['function_id']}" for r in added if r["kind"] == "production" and (r["hotspot"] or r["signals"])]),
        ("pattern_introduced", [f"{lead['path']}: {lead['rule']}" for lead in introduced]),
    ]
    return section, [{"flag": flag, "items": items} for flag, items in candidates if items]


def hygiene_flags(changed, contents, lines, max_changed_lines):
    """Flags that need no measurement: edited tests, protected regions and the size of the change."""
    altered, unbalanced = protected_changes(contents)
    candidates = [
        ("tests_changed", sorted(p for p in changed if TEST_PATH.search(p))),
        ("protected_region_changed", altered),
        ("protected_region_unbalanced", unbalanced),
        ("large_change", [f"{lines} changed lines exceed {max_changed_lines}"] if lines > max_changed_lines else []),
    ]
    return [{"flag": flag, "items": items} for flag, items in candidates if items]


def measure_both(root, contents, structure, threshold):
    """(source file count, report at the base, report of the working tree) for the changed source files."""
    sources = [p for p in contents if Path(p).suffix in complexity.SOURCE_SUFFIXES]
    with tempfile.TemporaryDirectory(prefix="structure-delta-") as scratch:
        at_base = []
        for path in sources:
            before = contents[path][0]
            if before:
                target = Path(scratch) / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(before)
                at_base.append(path)
        report = measure_side(scratch, at_base, structure, threshold)
    return len(sources), report, measure_side(root, [p for p in sources if gitsafe.kind(root / p) == "file"], structure, threshold)


def delta(root, base=None, max_changed_lines=MAX_CHANGED_LINES, threshold=complexity.CC_THRESHOLD, structure=None):
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError(f"source root is not a directory: {root}")
    if isinstance(max_changed_lines, bool) or not isinstance(max_changed_lines, int) or max_changed_lines < 1:
        raise ValueError("max changed lines must be a positive integer")
    commit, chosen = resolve_base(root, base)
    changed, contents = changed_files(root, commit)
    lines = sum(sum(counts) for counts in changed.values() if counts)
    measured, before, after = measure_both(root, contents, structure, threshold)
    section, structure_flags = compare(before, after)
    flags = hygiene_flags(changed, contents, lines, max_changed_lines) + structure_flags
    gaps = [{"side": side, **gap} for side, report in (("base", before), ("working tree", after)) for gap in report["gaps"]]
    return {"schema": "code-audit.structure-delta.v1", "root": str(root), "base": commit, "base_chosen_by": chosen,
            "changed_files": len(changed), "changed_lines": lines, "max_changed_lines": max_changed_lines,
            "binary_or_unreadable_files": sorted(p for p, counts in changed.items() if counts is None),
            "measured_source_files": measured, "status": "incomplete" if gaps else ("flags" if flags else "clear"),
            "flags": flags, "gaps": gaps, "structure": section,
            "note": "Flags are places to look. No flag does not show that behaviour is preserved; run the project's tests."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("root", help="source root inside a Git repository")
    parser.add_argument("--base", help="revision to compare with (default: merge base with the mainline)")
    parser.add_argument("--max-changed-lines", type=int, default=MAX_CHANGED_LINES, help=f"size budget for one change (default: {MAX_CHANGED_LINES})")
    parser.add_argument("--threshold", type=int, default=complexity.CC_THRESHOLD, help=f"CC hotspot boundary passed to complexity.py (default: {complexity.CC_THRESHOLD})")
    parser.add_argument("--structure", nargs="+", metavar="NAME=N", help="structural-signal thresholds passed to complexity.py")
    parser.add_argument("--fail-on-flags", action="store_true", help="exit 1 when any flag fired; a flag never establishes a defect")
    args = parser.parse_args(argv)
    try:
        report = delta(args.root, args.base, args.max_changed_lines, args.threshold, args.structure)
    except (ValueError, OSError) as error:
        print(json.dumps({"schema": "code-audit.structure-delta.v1", "status": "invalid", "error": str(error)}))
        return 2
    print(json.dumps(report, indent=2))
    if report["status"] == "incomplete":
        return 2
    return int(args.fail_on_flags and bool(report["flags"]))


if __name__ == "__main__":
    sys.exit(main())
