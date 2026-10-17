"""Behavioral checks for evaluation accounting and incomplete/invalid receipts."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from score import score

ROOT = Path(__file__).resolve().parent


class ReviewScoring(unittest.TestCase):
    def setUp(self):
        self.cases = json.loads((ROOT / "cases.json").read_text())
        self.oracles = json.loads((ROOT / "private/oracles.json").read_text())
        self.review = {"cases": [{"case_id": row["id"], "coverage": "complete", "findings": []}
                                  for row in self.cases["cases"]]}
        self.judged = {"judgments": []}

    def add(self, cid, fid="F1", oid=None, valid=True, harmful=False, duplicate=False,
            origin="introduced"):
        row = next(row for row in self.review["cases"] if row["case_id"] == cid)
        row["findings"].append({"id": fid, "cause": "Supported mechanism", "locations": ["file.py:1"],
                                "severity": "high", "origin": origin, "disposition": "open",
                                "suggested_change": "Repair cause", "verification": "Before/after check"})
        self.judged["judgments"].append({"case_id": cid, "finding_id": fid, "oracle_id": oid,
            "valid": valid, "harmful": harmful, "duplicate": duplicate,
            "rationale": "External adjudicator inspected the source and contract."})

    def run_score(self):
        return score(self.review, self.judged, self.cases, self.oracles)

    def test_empty_complete_review_misses_defects_but_preserves_clean_controls(self):
        result = self.run_score()
        self.assertEqual(result["detected_classes"], 0)
        self.assertEqual(result["seeded_defect_classes"], 8)
        self.assertEqual(result["clean_cases_without_findings"], ["R02", "R03", "R05"])
        self.assertIsNone(result["finding_precision"])
        self.assertEqual(result["cases_version"], 2)
        self.assertEqual(len(result["cases_sha256"]), 64)

    def test_multiple_findings_for_same_cause_do_not_inflate_recall(self):
        self.add("R01", "F1", "stale-poll")
        self.add("R01", "F2", "stale-poll", duplicate=True)
        result = self.run_score()
        self.assertEqual(result["detected_classes"], 1)
        self.assertEqual(result["duplicate_findings"], 1)

    def test_harmful_advice_is_counted_even_when_defect_is_real(self):
        self.add("R01", oid="stale-poll", harmful=True)
        self.add("R02", valid=False, harmful=True)
        result = self.run_score()
        self.assertEqual(result["harmful_advice"], 2)
        self.assertEqual(result["harmful_false_positives"], 1)
        self.assertEqual(result["false_positives"], 1)
        self.assertNotIn("R02", result["clean_cases_without_findings"])

    def test_unavailable_clean_case_is_not_clean_success(self):
        row = self.review["cases"][1]
        row.update(coverage="unavailable", reason="Missing source")
        result = self.run_score()
        self.assertEqual(result["fully_reviewed_cases"], 8)
        self.assertNotIn("R02", result["clean_cases_without_findings"])
        self.assertNotIn("R02", result["clean_cases_without_false_or_harmful_findings"])

    def test_valid_unseeded_finding_is_not_a_clean_control_failure(self):
        # Supplied external judgment is deliberate test data, not a semantic finding.
        self.add("R03", oid=None, valid=True, harmful=False)
        result = self.run_score()
        self.assertNotIn("R03", result["clean_cases_without_findings"])
        self.assertIn("R03", result["clean_cases_without_false_or_harmful_findings"])
        self.assertEqual(result["false_positives"], 0)
        self.assertEqual(result["detected_classes"], 0)
        before = result["cases_sha256"]
        self.cases["cases"][0]["request"] += " Changed contract."
        self.assertNotEqual(before, self.run_score()["cases_sha256"])

    def test_missing_case_or_judgment_is_rejected(self):
        original = deepcopy(self.review)
        self.review["cases"].pop()
        with self.assertRaisesRegex(ValueError, "every case"):
            self.run_score()
        self.review = original
        self.add("R01", oid="stale-poll")
        self.judged["judgments"] = []
        with self.assertRaisesRegex(ValueError, "unadjudicated"):
            self.run_score()

    def test_duplicate_ids_and_unknown_oracle_are_rejected(self):
        self.add("R01", oid="stale-poll")
        self.add("R01", oid="stale-poll")
        with self.assertRaisesRegex(ValueError, "duplicate judgment"):
            self.run_score()
        self.judged["judgments"].pop()
        self.review["cases"][0]["findings"].pop()
        self.judged["judgments"][0]["oracle_id"] = "invented"
        with self.assertRaisesRegex(ValueError, "unknown oracle"):
            self.run_score()

    def test_origin_is_separate_from_validity(self):
        self.add("R09", oid="missing-owner-check", origin="introduced")
        result = self.run_score()
        self.assertEqual(result["detected_classes"], 1)
        self.assertEqual(result["origin_errors"], 1)
        self.assertEqual(result["false_positives"], 0)

    def test_reopened_disposition_is_accepted_and_matched(self):
        self.add("R06", fid="F-ready", oid="reopen-ready")
        row = next(row for row in self.review["cases"] if row["case_id"] == "R06")
        row["findings"][0]["disposition"] = "reopened"
        # Duplicate status is supplied by the external adjudicator, not inferred.
        result = self.run_score()
        self.assertEqual(result["detected_classes"], 1)
        self.assertEqual(result["duplicate_findings"], 0)

    def test_extra_or_string_boolean_adjudication_rejected(self):
        self.add("R01", oid="stale-poll")
        self.judged["judgments"][0]["valid"] = "true"
        with self.assertRaisesRegex(ValueError, "booleans"):
            self.run_score()
        self.judged["judgments"][0]["valid"] = True
        self.review["cases"][0]["findings"] = []
        with self.assertRaisesRegex(ValueError, "absent from review"):
            self.run_score()


if __name__ == "__main__":
    unittest.main()
