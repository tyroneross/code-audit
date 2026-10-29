"""Withheld test: the self-review detector must not file a missing-test finding
for a script the re-validator would immediately close as covered."""
import sys, tempfile, unittest
from pathlib import Path

ROOT = Path.cwd() / "scripts"
for p in (ROOT / "self_review", ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import selfscan  # noqa: E402
import revalidate_self_review_findings as reval  # noqa: E402


def _targets(findings):
    out = set()
    for f in findings:
        if f.get("kind") == "self_missing_test":
            out.add(f["signal"].rsplit(" ", 1)[-1])
    return out


class DetectorAgreesWithRevalidator(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        s = self.root / "scripts"; s.mkdir()
        t = self.root / "tests" / "architecture"; t.mkdir(parents=True)
        (s / "widget.py").write_text("x = 1\n")
        (s / "test_widget.py").write_text("import widget\n")
        (s / "slice_acp.py").write_text("def build():\n    return 1\n")
        (t / "test_acp.py").write_text("from slice_acp import build\n")
        (s / "agent_rally.py").write_text("y = 2\n")
        (s / "test_agent_rally_retract.py").write_text("import agent_rally\n")
        (s / "orphan.py").write_text("z = 3\n")

    def test_detector_matches_revalidator(self):
        findings = selfscan.scan_self_simplification(self.root, 1, [])
        flagged = _targets(findings)
        for name in ("widget.py", "slice_acp.py", "agent_rally.py", "orphan.py"):
            test, _how = reval.find_test(self.root, Path(name).stem)
            covered = test is not None
            self.assertEqual(name in flagged, not covered,
                             f"{name}: detector flagged={name in flagged}, revalidator covered={covered}")
        self.assertIn("orphan.py", flagged)
        self.assertNotIn("slice_acp.py", flagged)
        self.assertNotIn("agent_rally.py", flagged)


if __name__ == "__main__":
    unittest.main()
