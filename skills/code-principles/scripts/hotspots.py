#!/usr/bin/env python3
"""Rank files by how often they change and how much flagged structure they carry.

  hotspots.py ROOT [--since "12 months ago"] [--paths P ...] [--top 20]

A file's score is commits x flagged functions, where commits counts non-merge commits that touched the file in
the window and a flagged production function is a CC hotspot or carries a structural signal (complexity.py).
Frequently changed code with flagged structure is where simplification pays back first; flagged code that never
changes and clean code that changes often both score 0. The ranking is a reading order, never a defect list.

Exit: 0 report written; 2 invalid input, Git unavailable or measurement incomplete. Read-only: reads Git history
and source files, executes no project code and writes nothing inside ROOT. A shallow clone is a reported gap.
Git never rejects --since text and can read an out-of-range date as a recent one, so check `since_resolved_utc`,
the start Git actually used. A start in the future is rejected.
"""
import argparse
import collections
import datetime
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import complexity  # noqa: E402
import gitsafe  # noqa: E402

SINCE = "12 months ago"
TOP = 20


def window_start(root, since):
    """UTC time Git resolves the window text to. Git never rejects the text, so the result is checked and reported."""
    resolved = (gitsafe.run(root, "rev-parse", f"--since={since}") or b"").decode().strip()
    if not resolved.startswith("--max-age=") or not resolved[10:].isdigit():
        raise ValueError(f"git could not resolve --since {since!r}; hotspots need a Git repository")
    start = int(resolved[10:])
    if not 0 < start <= time.time() + 86400:
        raise ValueError(f"--since {since!r} resolves outside the past (epoch {start}); use a date or interval Git can read")
    return datetime.datetime.fromtimestamp(start, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def churn(root, since):
    """Counter of non-merge commits per root-relative path in the window, or None when history cannot be read."""
    log = gitsafe.run(root, "log", *gitsafe.NO_DRIVERS, f"--since={since}", "--no-merges", "--format=%x00", "--name-only", "-z", "--relative", timeout=120)
    if log is None:
        return None
    commits = collections.Counter()
    # Each commit is a NUL-terminated empty subject followed by its NUL-separated paths.
    for commit in log.decode("utf-8", "surrogateescape").split("\0\0"):
        commits.update({path.strip("\n") for path in commit.split("\0") if path.strip("\n")})
    return commits


def flagged_by_file(functions):
    """Per file: production function count, worst CC and nesting, and the flagged functions worst first."""
    files = collections.defaultdict(lambda: {"flagged": [], "functions": 0, "max_cc": 0, "max_nesting": 0})
    for row in functions:
        if row["kind"] != "production":
            continue
        entry = files[row["path"]]
        entry["functions"] += 1
        entry["max_cc"] = max(entry["max_cc"], row["cc"])
        entry["max_nesting"] = max(entry["max_nesting"], row["max_nesting"] or 0)
        if row["hotspot"] or row["signals"]:
            entry["flagged"].append(row)
    for entry in files.values():
        entry["flagged"].sort(key=lambda r: (-r["cc"], r["line"]))
    return files


def scored(files, commits):
    """Files with their score, highest first."""
    ranked = [{"path": path, "score": commits[path] * len(entry["flagged"]), "commits": commits[path],
               "flagged_functions": len(entry["flagged"]), "functions": entry["functions"],
               "max_cc": entry["max_cc"], "max_nesting": entry["max_nesting"],
               "read_first": [{"function_id": r["function_id"], "cc": r["cc"], "signals": r["signals"]} for r in entry["flagged"][:3]]}
              for path, entry in files.items()]
    return sorted(ranked, key=lambda f: (-f["score"], -f["commits"], f["path"]))


def rank(root, since=SINCE, paths=None, top=TOP, **scoring):
    """Hotspot report; scoring passes `threshold` and `structure` through to complexity.measure."""
    root = Path(root).resolve()
    if isinstance(top, bool) or not isinstance(top, int) or top < 1:
        raise ValueError("top must be a positive integer")
    start = window_start(root, since)
    report = complexity.measure(root, paths, **scoring)
    commits = churn(root, since)
    if commits is None:
        raise ValueError("git log failed; hotspots need a Git repository with history")
    gaps = list(report["gaps"])
    if (gitsafe.run(root, "rev-parse", "--is-shallow-repository") or b"").strip() == b"true":
        gaps.append({"path": ".", "reason": "shallow clone: commit counts cover only the fetched history"})
    ranked = scored(flagged_by_file(report["functions"]), commits)
    hot = [f for f in ranked if f["score"] > 0]
    return {"schema": "code-audit.hotspots.v1", "root": str(root), "revision": report["revision"], "since": since, "since_resolved_utc": start,
            "score_rule": "commits x flagged production functions (CC hotspot or structural signal)",
            "threshold": report["threshold"], "structure_thresholds": report["structure_thresholds"],
            "status": "incomplete" if gaps else "measured", "gaps": gaps,
            "files_measured": len(ranked), "files_changed_in_window": sum(1 for f in ranked if f["commits"]),
            "files_with_flagged_functions": sum(1 for f in ranked if f["flagged_functions"]),
            "hotspot_files": len(hot), "unchanged_flagged_files": sum(1 for f in ranked if f["flagged_functions"] and not f["commits"]),
            "top": hot[:top]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("root", help="source root inside a Git repository")
    parser.add_argument("--since", default=SINCE, help=f"history window passed to git log --since (default: {SINCE!r})")
    parser.add_argument("--paths", nargs="+", help="explicit root-relative files/directories (default: tracked source files)")
    parser.add_argument("--top", type=int, default=TOP, help=f"files to list (default: {TOP})")
    parser.add_argument("--threshold", type=int, default=10, help="CC hotspot boundary passed to complexity.py (default: 10)")
    parser.add_argument("--structure", nargs="+", metavar="NAME=N", help="structural-signal thresholds passed to complexity.py")
    args = parser.parse_args(argv)
    try:
        report = rank(args.root, args.since, args.paths, args.top, threshold=args.threshold, structure=args.structure)
    except (ValueError, OSError) as error:
        print(json.dumps({"schema": "code-audit.hotspots.v1", "status": "invalid", "error": str(error)}))
        return 2
    print(json.dumps(report, indent=2))
    return 2 if report["status"] == "incomplete" else 0


if __name__ == "__main__":
    sys.exit(main())
