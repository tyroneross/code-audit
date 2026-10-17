#!/usr/bin/env python3
"""Score externally adjudicated review findings; never infer semantic validity."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def require(condition, message):
    if not condition:
        raise ValueError(message)


def keyed(rows, field, label):
    require(isinstance(rows, list), f"{label} must be a list")
    result = {}
    for row in rows:
        require(isinstance(row, dict), f"{label} row must be an object")
        key = row.get(field)
        require(isinstance(key, str) and bool(key.strip()), f"{label} missing {field}")
        require(key not in result, f"duplicate {label} {key}")
        result[key] = row
    return result


def score(review, adjudication, manifest, oracle_packet):
    """Receipts authenticate neither reviewer execution nor adjudicator judgment."""
    cases = keyed(manifest["cases"], "id", "case")
    outputs = keyed(review["cases"], "case_id", "review case")
    require(set(outputs) == set(cases), "review must contain every case exactly once")
    oracles = oracle_packet["oracles"]
    require(set(oracles) == set(cases), "oracle/case coverage mismatch")
    expected = {cid: keyed(rows, "id", "oracle") for cid, rows in oracles.items()}
    judgments = {}
    require(isinstance(adjudication.get("judgments"), list), "judgments must be a list")
    for row in adjudication["judgments"]:
        require(isinstance(row, dict), "judgment must be an object")
        key = (row.get("case_id"), row.get("finding_id"))
        require(all(isinstance(k, str) and k for k in key), "judgment missing identity")
        require(key not in judgments, "duplicate judgment")
        require(all(type(row.get(k)) is bool for k in ("valid", "harmful", "duplicate")),
                "valid/harmful/duplicate must be booleans")
        require(isinstance(row.get("rationale"), str) and bool(row["rationale"].strip()),
                "judgment needs an evidence-based rationale")
        judgments[key] = row
    seen, matched, missed, unavailable = set(), set(), [], []
    findings_total = valid_total = harmful = harmful_fp = false_positive = duplicates = origin_errors = 0
    details = []
    for cid, result in outputs.items():
        coverage = result.get("coverage")
        require(coverage in ("complete", "unavailable"), "unknown coverage")
        if coverage == "unavailable":
            require(isinstance(result.get("reason"), str) and bool(result["reason"].strip()),
                    "unavailable coverage needs a reason")
            unavailable.append(cid)
        findings = keyed(result.get("findings"), "id", "finding")
        for fid, finding in findings.items():
            require(isinstance(finding.get("cause"), str) and bool(finding["cause"].strip()),
                    "finding needs a cause")
            locations = finding.get("locations")
            require(isinstance(locations, list) and bool(locations) and
                    all(isinstance(p, str) and bool(p.strip()) for p in locations),
                    "finding needs source locations")
            require(finding.get("severity") in ("high", "medium", "low"), "unknown severity")
            require(finding.get("origin") in ("introduced", "pre_existing", "unknown"), "unknown origin")
            require(finding.get("disposition") in ("open", "reopened"), "unknown disposition")
            for field in ("suggested_change", "verification"):
                require(isinstance(finding.get(field), str) and bool(finding[field].strip()),
                        f"finding needs {field}")
            key = (cid, fid)
            require(key in judgments, f"unadjudicated finding {cid}/{fid}")
            judgment = judgments[key]
            seen.add(key)
            oid = judgment.get("oracle_id")
            require(oid is None or (isinstance(oid, str) and oid in expected[cid]), "unknown oracle")
            require(oid is None or judgment["valid"], "invalid finding cannot match an oracle")
            findings_total += 1
            valid_total += judgment["valid"]
            false_positive += not judgment["valid"]
            harmful += judgment["harmful"]
            harmful_fp += judgment["harmful"] and not judgment["valid"]
            duplicates += judgment["duplicate"]
            if oid is not None:
                matched.add((cid, oid))
                origin_errors += finding["origin"] != expected[cid][oid]["origin"]
            details.append({"case_id": cid, "finding_id": fid, **judgment})
        for oid in expected[cid]:
            if (cid, oid) not in matched:
                missed.append({"case_id": cid, "oracle_id": oid, "coverage": coverage})
    require(seen == set(judgments), "adjudication contains findings absent from review")
    total = sum(len(rows) for rows in expected.values())
    clean = [cid for cid in cases if not expected[cid]]
    return {
        "version": 1,
        "cases_version": manifest.get("version"), "oracles_version": oracle_packet.get("version"),
        "cases_sha256": hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "oracles_sha256": hashlib.sha256(json.dumps(oracle_packet, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "cases": len(cases), "fully_reviewed_cases": len(cases) - len(unavailable),
        "unavailable_cases": unavailable,
        "seeded_defect_classes": total, "detected_classes": len(matched),
        "seeded_class_recall": len(matched) / total if total else None,
        "missed_classes": missed,
        "findings": findings_total, "valid_findings": valid_total,
        "finding_precision": valid_total / findings_total if findings_total else None,
        "false_positives": false_positive, "harmful_advice": harmful,
        "harmful_false_positives": harmful_fp, "duplicate_findings": duplicates,
        "origin_errors": origin_errors,
        "clean_cases": clean,
        "clean_cases_without_findings": [cid for cid in clean if
            outputs[cid]["coverage"] == "complete" and not outputs[cid]["findings"]],
        "clean_cases_without_false_or_harmful_findings": [cid for cid in clean if
            outputs[cid]["coverage"] == "complete" and not any(
                row["case_id"] == cid and (not row["valid"] or row["harmful"]) for row in details)],
        "adjudications": details,
        "limits": ["Synthetic seeded cases; not production or population recall.",
                   "Adjudication is supplied evidence-based judgment, not authenticated by this scorer.",
                   "Unavailable cases remain visible and in the all-case recall denominator.",
                   "Duplicate IDs/classes do not demonstrate convergence; judge dispositions and new evidence."]
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review", type=Path)
    parser.add_argument("adjudication", type=Path)
    parser.add_argument("--cases", type=Path, default=ROOT / "cases.json")
    parser.add_argument("--oracles", type=Path, default=ROOT / "private/oracles.json")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        packets = [json.loads(p.read_text()) for p in
                   (args.review, args.adjudication, args.cases, args.oracles)]
        result = score(*packets)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(2, f"Invalid evaluation: {exc}\n")
    rendered = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered)
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
