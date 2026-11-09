"""Exercise the audit fixture CLI on synthetic clean and defective observations."""

import json
from pathlib import Path
import subprocess
import sys
import unittest


SCRIPT = Path(__file__).with_name("algorithm_fixture.py")


class AlgorithmFixture(unittest.TestCase):
    def run_fixture(self, fixture, exit_code):
        if isinstance(fixture, dict):
            fixture = json.dumps(fixture)
        result = subprocess.run([sys.executable, "-B", SCRIPT, "-"], input=fixture,
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, exit_code, result.stderr or result.stdout)
        report = json.loads(result.stdout)
        self.assertEqual(report["schema"], "code-audit.algorithm-fixture.v1")
        self.assertEqual(report["status"], ("pass", "fail", "invalid")[exit_code])
        return report

    def test_kmeans_accepts_one_exact_step_and_detects_wrong_tie_centroid_and_inertia(self):
        fixture = {"kind": "kmeans_step", "points": [[0], [1], [2], [4]],
                   "centroids": [[0], [4]],
                   "observed": {"labels": [0, 0, 0, 1], "centroids": [[1], [4]],
                                "assignment_inertia": 5}}
        self.assertEqual(self.run_fixture(fixture, 0)["findings"], [])

        fixture["observed"] = {"labels": [0, 0, 1, 1], "centroids": [[0.5], [3]],
                               "assignment_inertia": 2.5}
        findings = self.run_fixture(fixture, 1)["findings"]
        self.assertEqual({row["path"] for row in findings},
                         {"/labels/2", "/centroids/0/0", "/centroids/1/0", "/assignment_inertia"})

    def test_fractional_centroid_has_exact_output_and_requires_explicit_tolerance(self):
        fixture = {"kind": "kmeans_step", "points": [[0], [0], [1], [4]],
                   "centroids": [[0], [4]],
                   "observed": {"labels": [0, 0, 0, 1], "centroids": [["1/3"], [4]],
                                "assignment_inertia": 1}}
        self.assertEqual(self.run_fixture(fixture, 0)["expected"]["centroids"], [["1/3"], [4]])
        fixture["observed"]["centroids"][0][0] = 0.333333
        self.run_fixture(fixture, 1)
        fixture["tolerance"] = {"abs": 1e-6}
        self.run_fixture(fixture, 0)

    def test_kmeans_refuses_empty_cluster_policy(self):
        fixture = {"kind": "kmeans_step", "points": [[0]],
                   "centroids": [[0], [4]], "observed": {}}
        self.assertIn("empty-cluster", self.run_fixture(fixture, 2)["error"])

    def test_dbscan_counts_self_includes_equal_distance_and_cannot_merge_via_border(self):
        groups = [set(range(4)), set(range(4, 8))]
        edges = {frozenset((0, 8)), frozenset((4, 8))}
        distances = [[int(i != j) if any({i, j} <= g for g in groups) else
                      (0 if i == j else 1 if frozenset((i, j)) in edges else 2)
                      for j in range(9)] for i in range(9)]
        fixture = {"kind": "dbscan", "distances": distances, "eps": 1, "min_samples": 4,
                   "observed": {
                       "neighbors": [[0, 1, 2, 3, 8], [0, 1, 2, 3], [0, 1, 2, 3],
                                     [0, 1, 2, 3], [4, 5, 6, 7, 8], [4, 5, 6, 7],
                                     [4, 5, 6, 7], [4, 5, 6, 7], [0, 4, 8]],
                       "core": list(range(8)), "core_components": [[0, 1, 2, 3], [4, 5, 6, 7]]}}
        self.run_fixture(fixture, 0)
        fixture["observed"]["core_components"] = [list(range(8))]
        fixture["observed"]["neighbors"][8] = [8]
        self.assertEqual({row["path"] for row in self.run_fixture(fixture, 1)["findings"]},
                         {"/core_components", "/neighbors/8"})

    def test_dbscan_refuses_asymmetric_distances(self):
        fixture = {"kind": "dbscan", "distances": [[0, 1], [2, 0]], "eps": 1,
                   "min_samples": 1, "observed": {}}
        self.assertIn("symmetric", self.run_fixture(fixture, 2)["error"])

    def test_observations_check_tokens_score_and_discrete_label_separately(self):
        fixture = {"kind": "observations", "tolerance": {"abs": 0.01},
                   "expected": {"tokens": ["not", "good"], "score": -0.5, "label": 0},
                   "observed": {"tokens": ["not", "good"], "score": -0.491, "label": 0}}
        self.run_fixture(fixture, 0)
        fixture["observed"] = {"tokens": ["good"], "score": 0.5, "label": 0.0}
        findings = self.run_fixture(fixture, 1)["findings"]
        self.assertEqual({row["path"] for row in findings}, {"/tokens", "/score", "/label"})

    def test_type_only_mismatch_is_visible_after_serialization(self):
        fixture = {"kind": "observations", "expected": {"label": 1}, "observed": {"label": 1.0}}
        self.assertEqual(self.run_fixture(fixture, 1)["findings"],
                         [{"path": "/label", "expected": 1, "observed": 1,
                           "expected_type": "integer", "observed_type": "number"}])

    def test_missing_unexpected_and_pointer_escaping(self):
        fixture = {"kind": "observations", "expected": {"a/b": None}, "observed": {"a~b": None}}
        self.assertEqual(self.run_fixture(fixture, 1)["findings"],
                         [{"path": "/a~1b", "expected": None}, {"path": "/a~0b", "observed": None}])

    def test_nonfinite_duplicate_and_excess_precision_inputs_fail(self):
        for fixture in ('{"kind":"observations","kind":"dbscan"}',
                        '{"kind":"observations","expected":{"s":NaN},"observed":{}}',
                        '{"kind":"observations","expected":{"s":1e1000000},"observed":{}}',
                        " " * 65537):
            with self.subTest(fixture=fixture[:100]):
                self.run_fixture(fixture, 2)

    def test_findings_are_bounded(self):
        fixture = {"kind": "observations", "expected": {"values": [0] * 65},
                   "observed": {"values": [1] * 65}}
        report = self.run_fixture(fixture, 1)
        self.assertEqual(len(report["findings"]), 64)
        self.assertTrue(report["findings_truncated"])

    def test_long_path_segments_and_unmatched_deep_values_are_rejected(self):
        long_key = "a" * 129
        fixture = {"kind": "observations", "expected": {long_key: 0}, "observed": {}}
        self.assertIn("field name", self.run_fixture(fixture, 2)["error"])
        deep = 0
        for _ in range(25):
            deep = [deep]
        fixture = {"kind": "observations", "expected": {"label": 0}, "observed": {"label": deep}}
        self.assertIn("nesting limit", self.run_fixture(fixture, 2)["error"])

    def test_exact_number_expansion_cannot_emit_an_oversize_receipt(self):
        expected = '{"scores":[' + ",".join(["1e-64"] * 4500) + "]}"
        fixture = '{"kind":"observations","expected":' + expected + ',"observed":' + expected + "}"
        self.assertLess(len(fixture), 65536)
        self.assertIn("receipt exceeds", self.run_fixture(fixture, 2)["error"])


if __name__ == "__main__":
    unittest.main()
