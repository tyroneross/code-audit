"""Withheld test: regenerating skill surfaces must keep sub-skills hidden from
the host slash menu (frontmatter `user-invocable: false`) for every host, and
must not hide the router skills."""
import importlib.util, sys, unittest
from pathlib import Path

ROOT = Path.cwd()
spec = importlib.util.spec_from_file_location("gen", ROOT / "scripts" / "generate_host_surfaces.py")
GEN = importlib.util.module_from_spec(spec); sys.modules["gen"] = GEN; spec.loader.exec_module(GEN)

HIDDEN = ("mini-loop", "rally-workflows")
VISIBLE = ("agent-rally-point",)


def _fm(text):
    return text.split("---")[1]


class HiddenSkillsSurviveRegeneration(unittest.TestCase):
    def test_hidden_flag_rendered_for_every_host(self):
        config = GEN.load_config(ROOT)
        for skill in HIDDEN:
            for host in ("claude_code", "codex"):
                out = GEN.render_skill(ROOT, config, skill, host)
                self.assertIn("user-invocable: false", _fm(out), f"{skill}/{host} lost the hidden flag")

    def test_routers_stay_visible(self):
        config = GEN.load_config(ROOT)
        for skill in VISIBLE:
            if skill not in config["skills"]:
                continue
            for host in ("claude_code", "codex"):
                out = GEN.render_skill(ROOT, config, skill, host)
                self.assertNotIn("user-invocable: false", _fm(out), f"{skill}/{host} wrongly hidden")

    def test_regeneration_is_idempotent_on_disk(self):
        config = GEN.load_config(ROOT)
        for skill in HIDDEN:
            on_disk = (ROOT / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
            out = GEN.render_skill(ROOT, config, skill, "claude_code")
            self.assertEqual("user-invocable: false" in _fm(out),
                             "user-invocable: false" in _fm(on_disk),
                             f"{skill}: regeneration would change the checked-in hidden flag")


if __name__ == "__main__":
    unittest.main()
