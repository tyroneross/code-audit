#!/usr/bin/env python3
"""Record whether code-principles findings held up, and score checklist items.

  outcome.py add --repo PATH --item A3 --where file:line --decision fixed [--gain TEXT] [--note TEXT] [--log-file PATH]
  outcome.py score [--repo PATH ...] [--json]

Log lives at <repo>/.code-principles/outcomes.jsonl (one JSON object per line).
Decisions: fixed (changed and verified), accepted (real issue, not fixed yet),
rejected (not a real issue), kept (real tradeoff, current code is right).
"""
import argparse
import datetime
import json
import os
import re
import sys
from collections import Counter, defaultdict

DECISIONS = ("fixed", "accepted", "rejected", "kept")
ITEM = re.compile(r"^[A-E][0-9]{1,2}$")


def log_path(repo, log_file=None):
    if log_file:
        return os.path.abspath(log_file)
    return os.path.join(os.path.abspath(repo), ".code-principles", "outcomes.jsonl")


def add(args):
    if not ITEM.match(args.item):
        print(f"outcome.py: item must look like A3 or D1, got {args.item!r}", file=sys.stderr)
        return 2
    if not os.path.isdir(args.repo):
        print(f"outcome.py: no such repo directory: {args.repo}", file=sys.stderr)
        return 2
    record = {
        "at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "item": args.item,
        "where": args.where,
        "decision": args.decision,
    }
    for key in ("gain", "note", "agent"):
        value = getattr(args, key)
        if value:
            record[key] = value
    path = log_path(args.repo, args.log_file)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")
    print(json.dumps(record))
    return 0


def read(repo, log_file=None):
    path = log_path(repo, log_file)
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                print(f"outcome.py: skipped unreadable line {n} in {path}", file=sys.stderr)
    return rows


def score(args):
    counts = defaultdict(Counter)
    sources = [(None, f) for f in (args.log_file or [])] + [(r, None) for r in (args.repo or ([] if args.log_file else ["."]))]
    for repo, log_file in sources:
        for row in read(repo, log_file):
            counts[row.get("item", "?")][row.get("decision", "?")] += 1
    table = {}
    for item in sorted(counts):
        c = counts[item]
        total = sum(c.values())
        real = c["fixed"] + c["accepted"] + c["kept"]
        table[item] = {**{d: c[d] for d in DECISIONS}, "total": total, "hit_rate": round(real / total, 2) if total else None}
    if args.json:
        print(json.dumps(table, indent=1))
        return 0
    if not table:
        print("No outcomes logged yet.")
        return 0
    print(f"{'item':<5} {'total':>5} {'fixed':>5} {'accepted':>8} {'kept':>4} {'rejected':>8} {'hit rate':>8}")
    for item, r in table.items():
        print(f"{item:<5} {r['total']:>5} {r['fixed']:>5} {r['accepted']:>8} {r['kept']:>4} {r['rejected']:>8} {r['hit_rate']:>8.0%}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Record and score code-principles findings.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("--repo", required=True)
    a.add_argument("--item", required=True)
    a.add_argument("--where", required=True)
    a.add_argument("--decision", required=True, choices=DECISIONS)
    a.add_argument("--gain")
    a.add_argument("--note")
    a.add_argument("--agent")
    a.add_argument("--log-file", help="write here instead of <repo>/.code-principles/outcomes.jsonl (for read-only reviews)")
    s = sub.add_parser("score")
    s.add_argument("--repo", action="append")
    s.add_argument("--log-file", action="append")
    s.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    return add(args) if args.cmd == "add" else score(args)


if __name__ == "__main__":
    sys.exit(main())
