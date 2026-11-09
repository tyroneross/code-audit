#!/usr/bin/env python3
"""Run matched synthetic audit checks against a baseline and candidate CLI.

The frozen observations below represent target outputs. This measures the
mechanical checks on those outputs, without running target code or scoring a
model's ability to choose the checks.
"""
import argparse
import json
import subprocess
import sys
from collections import Counter
from decimal import Decimal, localcontext
from fractions import Fraction
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "skills/code-principles/scripts/algorithm_fixture.py"


def run(command, payload=None):
    result = subprocess.run(command, input=payload, capture_output=True, text=True, timeout=15)
    report = json.loads(result.stdout)
    if result.returncode not in (0, 1, 2):
        raise RuntimeError(f"{command[0]} exited {result.returncode}: {result.stderr}")
    return result.returncode, report


def value(number):
    return Fraction(number["exact"] if isinstance(number, dict) else number)


def contains(interval, point):
    low, high = value(interval["low"]), value(interval["high"])
    return (
        (point > low or (point == low and interval["low_closed"]))
        and (point < high or (point == high and interval["high_closed"]))
    )


def piecewise(binary, baseline, observed):
    code, report = run([
        binary, "calc", "--piece", "x < 4: 3", "--piece", "else: 4",
        "--target", "== 3", "--between", "3", "5",
    ])
    if baseline and code == 2 and "unknown option --piece" in report["error"]:
        return "unavailable"
    if code != 0:
        raise ValueError(report)
    intervals = report["piecewise"]["solutions"]
    return "pass" if any(contains(interval, 4) for interval in intervals) == observed else "finding"


def nonlinear(binary, baseline, observed):
    code, report = run([
        binary, "calc", "--solve", "x*x+y == 6", "--solve", "x-y == 0",
        "--start", "x=1", "--start", "y=1",
    ])
    if baseline and code == 2 and "unknown option --start" in report["error"]:
        return "unavailable"
    if code != 0 or not report["solve"]["converged"]:
        raise ValueError(report)
    point = report["solve"]["solutions"][0]["values"]
    if set(point) != {"x", "y"} or any(abs(float(point[name]) - 2.0) > 1e-8 for name in point):
        raise ValueError(f"Solver disagreed with the analytic root (2, 2): {point}")
    return "pass" if all(abs(float(point[name]) - observed[name]) <= 1e-8 for name in point) else "finding"


def algorithm(fixture_path, payload):
    if fixture_path is None:
        return "unavailable"
    code, report = run([sys.executable, "-B", fixture_path, "-"], json.dumps(payload))
    if code not in (0, 1):
        raise ValueError(report)
    return "pass" if code == 0 else "finding"


def stable_sum(binary, observed):
    with localcontext() as ctx:
        ctx.prec = 60
        reference = (Decimal(1000).exp() + Decimal(1001).exp()).ln()
    code, report = run([
        binary, "calc", "--check", f"{observed} == {reference:.16f}", "--tolerance", "1e-12",
    ])
    if code == 2 and report["status"] == "invalid" and "finite" in report["error"]:
        return "finding"
    if code not in (0, 1):
        raise ValueError(report)
    return "pass" if code == 0 else "finding"


def compare(baseline, candidate, baseline_fixture=None):
    cases = {
        "branch-boundary": (False, True),
        "local-system": ({"x": 2.0, "y": 2.0}, {"x": 2.0, "y": 1.0}),
        "stable-logsumexp": ("1001+log(1+exp(-1))", "log(exp(1000)+exp(1001))"),
        "lloyd-update": (
            {"labels": [0, 0, 1], "centroids": [[1], [4]], "assignment_inertia": 4},
            {"labels": [0, 0, 1], "centroids": [[2], [4]], "assignment_inertia": 4},
        ),
        "dbscan-cutoff": (
            {"neighbors": [[0, 1], [0, 1]], "core": [0, 1], "core_components": [[0, 1]]},
            {"neighbors": [[0], [1]], "core": [], "core_components": []},
        ),
        "sentiment-negation": (
            {"tokens": ["not", "good"], "score": -0.5},
            {"tokens": ["good"], "score": 0.5},
        ),
    }
    templates = {
        "lloyd-update": {"kind": "kmeans_step", "points": [[0], [2], [4]], "centroids": [[0], [4]]},
        "dbscan-cutoff": {"kind": "dbscan", "distances": [[0, 1], [1, 0]], "eps": 1, "min_samples": 2},
        "sentiment-negation": {"kind": "observations", "expected": {"tokens": ["not", "good"], "score": -0.5}},
    }
    rows = []
    for case, observations in cases.items():
        for expected, observed in zip(("pass", "finding"), observations):
            row = {"case": case, "expected": expected}
            for arm, binary, fixture in (("baseline", baseline, baseline_fixture), ("candidate", candidate, FIXTURE)):
                if case == "branch-boundary":
                    outcome = piecewise(binary, arm == "baseline", observed)
                elif case == "local-system":
                    outcome = nonlinear(binary, arm == "baseline", observed)
                elif case == "stable-logsumexp":
                    outcome = stable_sum(binary, observed)
                else:
                    outcome = algorithm(fixture, {**templates[case], "observed": observed})
                row[arm] = outcome
            rows.append(row)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--baseline-fixture", type=Path)
    args = parser.parse_args()
    baseline, candidate = args.baseline.resolve(), args.candidate.resolve()
    invalid_invocations = (
        ("--target", "== 1"),
        ("--piece", "else: x", "--target", "== 1"),
        ("--start", "x=1"),
        ("--start", "x=1", "--solve", "x=1", "--between", "0", "2"),
        ("--piece", "else: x", "--target", "== 1", "--between", "0", "2", "--solve", "x=1"),
    )
    for arguments in invalid_invocations:
        code, report = run([candidate, "calc", *arguments])
        if code != 2 or report["status"] != "invalid":
            raise ValueError(f"Expected invalid invocation {arguments}: {report}")
    rows = compare(baseline, candidate, args.baseline_fixture)
    summary = {}
    for arm in ("baseline", "candidate"):
        summary[arm] = dict(Counter(
            "unavailable" if row[arm] == "unavailable" else
            row["expected"] if row[arm] == row["expected"] else "wrong"
            for row in rows
        ))
    binaries = {name: sha256(path.read_bytes()).hexdigest()
                for name, path in (("baseline", baseline), ("candidate", candidate))}
    print(json.dumps({"binary_sha256": binaries, "rows": rows, "summary": summary}, indent=2))
    return int(any(row["candidate"] != row["expected"] for row in rows))


if __name__ == "__main__":
    raise SystemExit(main())
