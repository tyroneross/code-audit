#!/usr/bin/env python3
"""Normalize a mutation-testing report into separately counted outcomes.

Inputs (produced by the project's own tooling; this script runs none of it):
  cargo-mutants  Rust: mutants.out/outcomes.json (checked against cargo-mutants 27.1.0)
  stryker        mutation-testing-elements JSON (schema v1/v2): StrykerJS for
                 TypeScript/JavaScript, Stryker.NET, and PIT for Java through
                 pitest-mutation-testing-elements-plugin

Counts follow measurement.md: selected, executed, behaviorally killed,
surviving, uncovered and inconclusive stay separate. Timeouts, build or compile
failures and runtime errors are inconclusive, never kills. The score
killed / (killed + surviving) is null when nothing was executed. cargo-mutants
records its baseline; a failed or missing baseline makes the whole report
untrustworthy. Stryker reports carry no baseline, which is recorded as unknown.
"""
import argparse
import json
from pathlib import Path
import sys

CARGO = {"CaughtMutant": "killed", "MissedMutant": "surviving", "Unviable": "inconclusive",
         "Timeout": "inconclusive", "Failure": "inconclusive"}
STRYKER = {"Killed": "killed", "Survived": "surviving", "NoCoverage": "uncovered", "Timeout": "inconclusive",
           "CompileError": "inconclusive", "RuntimeError": "inconclusive", "Ignored": "not_run", "Pending": "not_run"}
FORMATS = ("cargo-mutants", "stryker")


def empty():
    return {"selected": 0, "killed": 0, "surviving": 0, "uncovered": 0, "inconclusive": 0, "not_run": 0}


def tally(rows):
    counts, by_file, surviving = empty(), {}, []
    for path, bucket, detail in rows:
        counts["selected"] += 1
        counts[bucket] += 1
        by_file.setdefault(path, empty())
        by_file[path]["selected"] += 1
        by_file[path][bucket] += 1
        if bucket in ("surviving", "uncovered"):
            surviving.append({"path": path, "outcome": bucket, **detail})
    executed = counts["killed"] + counts["surviving"]
    counts["executed"] = executed
    counts["score"] = round(counts["killed"] / executed, 4) if executed else None
    return counts, by_file, surviving


def cargo_mutants(document):
    baseline, rows, unknown = None, [], []
    for outcome in document.get("outcomes", []):
        scenario, summary = outcome.get("scenario"), outcome.get("summary")
        if scenario == "Baseline":
            baseline = summary
            continue
        mutant = (scenario or {}).get("Mutant") if isinstance(scenario, dict) else None
        if mutant is None or summary not in CARGO:
            unknown.append(summary)
            continue
        line = (mutant.get("span") or {}).get("start", {}).get("line")
        function = (mutant.get("function") or {}).get("function_name")
        rows.append((mutant.get("file"), CARGO[summary], {"line": line, "function": function, "description": mutant.get("name")}))
    if baseline is None:
        baseline_status = "missing"
    else:
        baseline_status = "passed" if baseline == "Success" else f"failed: {baseline}"
    return rows, baseline_status, unknown, {"tool": "cargo-mutants", "version": document.get("cargo_mutants_version")}


def stryker(document):
    if not str(document.get("schemaVersion", "")).split(".")[0] in ("1", "2"):
        raise ValueError("stryker report requires schemaVersion 1 or 2")
    rows, unknown = [], []
    for path, entry in document.get("files", {}).items():
        for mutant in entry.get("mutants", []):
            status = mutant.get("status")
            if status not in STRYKER:
                unknown.append(status)
                continue
            line = (mutant.get("location") or {}).get("start", {}).get("line")
            rows.append((path, STRYKER[status], {"line": line, "description": mutant.get("description") or mutant.get("mutatorName")}))
    framework = document.get("framework") or {}
    return rows, "unknown (not recorded in this report format)", unknown, {"tool": framework.get("name", "mutation-testing-elements"), "version": framework.get("version"), "schemaVersion": document.get("schemaVersion")}


def normalize(path, fmt):
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    rows, baseline, unknown, source = (cargo_mutants if fmt == "cargo-mutants" else stryker)(document)
    counts, by_file, surviving = tally(rows)
    warnings = []
    if baseline != "passed":
        warnings.append(f"baseline {baseline}; kills are not evidence of assertion strength until a passing baseline is confirmed")
    if unknown:
        warnings.append(f"{len(unknown)} outcomes had unrecognized statuses and were left out: {sorted(set(map(str, unknown)))}")
    if not counts["executed"]:
        warnings.append("no mutant executed to a behavioral result; mutation evidence is unavailable, not perfect")
    trusted = baseline == "passed" and bool(counts["executed"]) and not unknown
    return {"schema": "code-audit.mutation.v1", "input": str(Path(path).resolve()), "source": source,
            "baseline": baseline, "trusted": trusted, "counts": counts, "by_file": by_file,
            "surviving_or_uncovered": surviving[:500], "warnings": warnings}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                     epilog="Exit: 0 normalized and trusted; 1 normalized but untrusted (baseline/execution); 2 invalid input.")
    parser.add_argument("report", help="mutation report JSON")
    parser.add_argument("--format", required=True, choices=FORMATS)
    args = parser.parse_args(argv)
    try:
        result = normalize(args.report, args.format)
    except (OSError, ValueError, json.JSONDecodeError, AttributeError) as error:
        print(json.dumps({"schema": "code-audit.mutation.v1", "status": "invalid", "error": str(error)}))
        return 2
    print(json.dumps(result, indent=2))
    return 0 if result["trusted"] else 1


if __name__ == "__main__":
    sys.exit(main())
