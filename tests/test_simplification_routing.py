"""The simplification capability is reachable, host-neutral and consistent with its measured record."""
import json
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/code-principles/scripts"
REFERENCE = ROOT / "skills/code-principles/references/simplification.md"
ADDED = [REFERENCE, ROOT / "research/code-health-sources.md", SCRIPTS / "structure_delta.py", SCRIPTS / "hotspots.py",
         SCRIPTS / "python_structure.py", SCRIPTS / "gitsafe.py", SCRIPTS / "calc.py"]
sys.path.insert(0, str(SCRIPTS))
import complexity  # noqa: E402


class SimplificationRouting(unittest.TestCase):
    def test_entry_and_principles_skills_route_to_the_reference(self):
        entry = (ROOT / "skills/code-audit/SKILL.md").read_text()
        route = [line for line in entry.splitlines() if "simplification.md" in line]
        self.assertEqual(len(route), 1)
        self.assertTrue(route[0].startswith("else if authorized simplification"))
        target = (ROOT / "skills/code-audit" / route[0].rsplit(" ", 1)[1]).resolve()
        self.assertEqual(target, REFERENCE)
        self.assertIn("(references/simplification.md)", (ROOT / "skills/code-principles/SKILL.md").read_text())
        # The eval harness rewrites this exact line; changing it breaks evals/fresh/make_guidance.py.
        self.assertIn("follow the starting route in references/audit-methods.md, adapt per its rules and end with its coverage matrix", entry)

    def test_reference_names_only_tools_that_exist(self):
        text = REFERENCE.read_text()
        for script in re.findall(r"<cp>/scripts/(\w+\.py)", text):
            self.assertTrue((SCRIPTS / script).is_file(), script)
        for flag in re.findall(r"`([a-z_]+)`", text):
            if flag.endswith(("_changed", "_worse", "_hotspot", "_introduced", "_unbalanced")) or flag == "large_change":
                self.assertIn(flag, (SCRIPTS / "structure_delta.py").read_text(), flag)

    def test_added_guidance_and_tools_assume_no_host_or_model(self):
        banned = re.compile(r"\b(CLAUDE_PLUGIN_ROOT|PreToolUse|PostToolUse|subagent_type|opus|sonnet|haiku|gpt-\d|gemini)\b", re.I)
        for path in ADDED:
            with self.subTest(path=path.name):
                text = path.read_text()
                self.assertIsNone(banned.search(text), banned.search(text))
                self.assertNotIn("—", text)
        self.assertNotIn("CLAUDE.md", REFERENCE.read_text())

    def test_measured_tier_matches_the_precision_record(self):
        record = json.loads((ROOT / "skills/code-principles/references/pattern-precision.json").read_text())
        measured = {rule for rule, row in record["rules"].items() if row["hits"] >= 8 and row["precision"] >= 0.7}
        self.assertEqual(measured, complexity.MEASURED_PATTERNS)
        for rule, row in record["rules"].items():
            self.assertEqual((row["hits"], row["true_positive"]), (len(row["sample"]), sum(s["label"] == "tp" for s in row["sample"])), rule)
        self.assertEqual(set(record["status"]), {"identical_operands", "self_assignment", "duplicate_branches", "repeated_condition"})

    def test_numbers_are_computed_by_script_in_every_entry_point(self):
        self.assertTrue((SCRIPTS / "calc.py").is_file())
        entry = (ROOT / "skills/code-audit/SKILL.md").read_text()
        self.assertIn("compute, do not estimate", entry)
        self.assertIn("../code-principles/scripts/calc.py", entry)
        self.assertTrue((ROOT / "skills/code-audit/../code-principles/scripts/calc.py").resolve().is_file())
        for path in ("skills/code-principles/SKILL.md", "skills/code-principles/references/measurement.md",
                     "skills/code-principles/references/focused-checklist.md", "skills/code-principles/references/simplification.md"):
            self.assertIn("calc.py", (ROOT / path).read_text(), path)

    def test_every_considered_source_is_pinned(self):
        text = (ROOT / "research/code-health-sources.md").read_text()
        pinned = {entry["source"]: entry["head"] for entry in json.loads((ROOT / "docs/source-provenance.json").read_text())["sources"]}
        for source in ("addyosmani/agent-skills", "anthropics/claude-plugins-official", "dvy1987/agent-loom", "google/error-prone",
                       "codescene-oss/codescene-vscode", "rust-lang/rust-clippy"):
            self.assertIn(pinned[source], text, source)

    def test_documented_thresholds_match_the_scorer(self):
        text = (ROOT / "skills/code-principles/references/measurement.md").read_text()
        for name, value in complexity.STRUCTURE_THRESHOLDS.items():
            self.assertRegex(text, rf"\| `{name}` \|[^\n]*\| {value} \|", name)


if __name__ == "__main__":
    unittest.main()
