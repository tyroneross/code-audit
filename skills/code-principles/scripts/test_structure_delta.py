"""Before/after check: each flag fires on a planted change and a clean simplification raises none."""
import contextlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import structure_delta

NESTED = """def process(data):
    if data is not None:
        if data.is_valid():
            if data.has_permission():
                return do_work(data)
            else:
                raise PermissionError("No permission")
        else:
            raise ValueError("Invalid data")
    else:
        raise TypeError("Data is None")
"""
FLAT = """def process(data):
    if data is None:
        raise TypeError("Data is None")
    if not data.is_valid():
        raise ValueError("Invalid data")
    if not data.has_permission():
        raise PermissionError("No permission")
    return do_work(data)
"""
PROTECTED = """def fast(buf, key):
    # simplify-ignore-start: unrolled on purpose
    a = buf[0] ^ key[0]
    b = buf[1] ^ key[1]
    # simplify-ignore-end
    return a, b
"""


@unittest.skipUnless(shutil.which("git"), "Git is required")
class StructureDeltaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.git("init", "-q", "-b", "main")
        self.write("app.py", NESTED)
        self.write("fast.py", PROTECTED)
        self.write("tests/test_app.py", "def test_process():\n    assert True\n")
        self.commit("base")

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
                              check=True, capture_output=True, text=True).stdout.strip()

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def commit(self, message):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)

    def flags(self, **kwargs):
        report = structure_delta.delta(self.root, **kwargs)
        return {f["flag"]: f["items"] for f in report["flags"]}, report

    def test_clean_simplification_raises_no_flag_and_shows_the_improvement(self):
        self.write("app.py", FLAT)
        flags, report = self.flags()
        self.assertEqual((flags, report["status"]), ({}, "clear"))
        change = report["structure"]["changed_functions"][0]
        self.assertEqual(change["changes"]["max_nesting"], [3, 1])
        self.assertEqual((change["worse"], change["newly_flagged"]), ([], []))
        self.assertEqual((report["structure"]["before"]["with_signals"], report["structure"]["after"]["with_signals"]), (1, 0))
        self.assertIn("does not show that behaviour is preserved", report["note"])

    def test_no_change_is_clear_with_nothing_measured(self):
        flags, report = self.flags()
        self.assertEqual((flags, report["changed_files"], report["status"]), ({}, 0, "clear"))

    def test_edited_test_file_is_flagged(self):
        self.write("app.py", FLAT)
        self.write("tests/test_app.py", "def test_process():\n    assert False\n")
        flags, _ = self.flags()
        self.assertEqual(flags, {"tests_changed": ["tests/test_app.py"]})

    def test_changed_removed_and_unbalanced_protected_regions_are_flagged(self):
        self.write("fast.py", PROTECTED.replace("a = buf[0] ^ key[0]", "a = buf[0] ^ key[1]"))
        self.assertEqual(self.flags()[0], {"protected_region_changed": ["fast.py"]})
        self.write("fast.py", PROTECTED.replace("    # simplify-ignore-end\n", ""))
        self.assertEqual(self.flags()[0], {"protected_region_changed": ["fast.py"], "protected_region_unbalanced": ["fast.py"]})
        self.write("fast.py", "def fast(buf, key):\n    return buf[0] ^ key[0], buf[1] ^ key[1]\n")
        self.assertEqual(self.flags()[0], {"protected_region_changed": ["fast.py"]})

    def test_marker_mentioned_in_prose_or_a_string_opens_no_region(self):
        self.write("notes.md", "Wrap hot code in `simplify-ignore-start` and close it later.\n<!-- simplify-ignore-start: table -->\n| a |\n<!-- simplify-ignore-end -->\n")
        self.write("tool.py", 'START = "simplify-ignore-start"\nprint("see simplify-ignore-end")\n')
        self.assertEqual(self.flags()[0], {})
        self.commit("docs")
        self.write("notes.md", "Wrap hot code in `simplify-ignore-start` and close it later.\n<!-- simplify-ignore-start: table -->\n| b |\n<!-- simplify-ignore-end -->\n")
        self.assertEqual(self.flags()[0], {"protected_region_changed": ["notes.md"]})

    def test_edit_outside_a_protected_region_is_not_flagged(self):
        self.write("fast.py", PROTECTED.replace("return a, b", "return (a, b)").replace("def fast(buf, key):", "def fast(buf, key):\n    # note"))
        self.assertEqual(self.flags()[0], {})

    def test_change_larger_than_the_budget_is_flagged(self):
        self.write("app.py", FLAT)
        flags, report = self.flags(max_changed_lines=5)
        self.assertEqual(flags, {"large_change": [f"{report['changed_lines']} changed lines exceed 5"]})
        self.assertGreater(report["changed_lines"], 5)

    def test_function_that_got_worse_is_flagged(self):
        self.commit_flat()
        self.write("app.py", NESTED)
        flags, report = self.flags()
        self.assertEqual(flags, {"function_got_worse": ["app.py:process"]})
        change = report["structure"]["changed_functions"][0]
        self.assertEqual((change["worse"], change["newly_flagged"]), (["max_nesting", "bumps"], ["max_nesting"]))

    def test_added_hotspot_and_introduced_pattern_are_flagged(self):
        self.commit_flat()
        self.write("app.py", FLAT + "\ndef helper(a, b, c, d, e, f):\n    return a if b else a\n")
        flags, report = self.flags()
        self.assertEqual(flags, {"new_hotspot": ["app.py:helper:10"], "pattern_introduced": ["app.py: duplicate_branches"]})
        self.assertEqual(report["structure"]["added_functions"][0]["signals"], ["params"])

    def test_untracked_source_file_counts_as_added(self):
        self.write("extra.py", "def extra():\n    return 1\n")
        _, report = self.flags()
        self.assertEqual((report["changed_files"], report["changed_lines"]), (1, 2))
        self.assertEqual([r["function_id"] for r in report["structure"]["added_functions"]], ["extra:1"])

    def test_deleted_file_reports_removed_functions(self):
        (self.root / "app.py").unlink()
        _, report = self.flags()
        self.assertEqual([r["function_id"] for r in report["structure"]["removed_functions"]], ["process:1"])

    def test_default_base_is_the_merge_base_with_the_mainline(self):
        base = self.git("rev-parse", "HEAD")
        self.git("checkout", "-q", "-b", "feature")
        self.write("app.py", FLAT)
        self.commit("simplify")
        _, report = self.flags()
        self.assertEqual((report["base"], report["base_chosen_by"]), (base, "merge base of HEAD and refs/heads/main"))
        self.assertEqual(report["changed_files"], 1)
        self.git("branch", "-q", "-m", "main", "trunk")
        _, report = self.flags()
        self.assertEqual(report["base_chosen_by"], "HEAD (no mainline ref resolved)")
        self.assertEqual(report["changed_files"], 0)
        _, report = self.flags(base="trunk")
        self.assertEqual((report["base"], report["base_chosen_by"]), (base, "--base trunk"))

    def test_invalid_inputs_exit_two_and_flags_exit_one_only_on_request(self):
        def run(*argv):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = structure_delta.main([*argv])
            return code, json.loads(out.getvalue())
        with tempfile.TemporaryDirectory() as plain:
            self.assertEqual(run(plain)[0], 2)
        self.assertEqual(run(str(self.root), "--base", "no-such-rev")[0], 2)
        self.assertEqual(run(str(self.root), "--max-changed-lines", "0")[0], 2)
        self.write("tests/test_app.py", "def test_process():\n    assert False\n")
        self.assertEqual(run(str(self.root))[0], 0)
        code, report = run(str(self.root), "--fail-on-flags")
        self.assertEqual((code, report["status"]), (1, "flags"))

    def test_git_reads_do_not_run_repository_configured_programs(self):
        marker = self.root.parent / (self.root.name + "-executed")
        self.addCleanup(lambda: marker.unlink(missing_ok=True))
        hook = self.root / "hook"
        hook.write_text('#!/bin/sh\n: > "' + str(marker) + '"\nprintf "token\\0"\n')
        hook.chmod(0o700)
        self.commit("hook")
        self.write(".gitattributes", "*.py filter=planted diff=planted\n")
        self.commit("attributes")
        for key in ("core.fsmonitor", "diff.external", "filter.planted.clean", "filter.planted.process", "diff.planted.textconv"):
            self.git("config", key, str(hook))
        self.git("config", "core.fsmonitorHookVersion", "2")
        self.write("app.py", FLAT)
        report = structure_delta.delta(self.root)
        self.assertEqual(report["changed_files"], 1)
        import recon
        recon.recon(str(self.root), base="HEAD")
        self.assertFalse(marker.exists(), "a Git read executed a program named in the repository configuration")

    def test_repetitive_file_is_counted_like_git_without_stalling(self):
        self.write("data.txt", "{\n}\n" * 10000)
        self.commit("data")
        self.write("data.txt", "{\n{\n}\n" * 6000)
        _, report = self.flags()
        expected = self.git("diff", "--numstat", "HEAD", "--", "data.txt").split("\t")[:2]
        self.assertEqual(report["changed_lines"], int(expected[0]) + int(expected[1]))

    def test_base_contents_are_read_in_one_batch_and_only_for_files(self):
        import gitsafe
        self.write("dir/odd name é.py", "x = 1\n")
        self.write("empty.txt", "")
        self.commit("more")
        read = gitsafe.blobs(self.root, "HEAD", ["dir/odd name é.py", "missing.py", "empty.txt", "dir", "app.py"])
        self.assertEqual((read["dir/odd name é.py"], read["missing.py"], read["empty.txt"], read["dir"]), (b"x = 1\n", None, b"", None))
        self.assertEqual(read["app.py"], NESTED.encode())

    def test_unchanged_submodule_is_not_listed(self):
        self.git("update-index", "--add", "--cacheinfo", f"160000,{self.git('rev-parse', 'HEAD')},vendor/mod")
        (self.root / "vendor/mod").mkdir(parents=True)
        self.git("commit", "-q", "-m", "submodule")
        _, report = self.flags()
        self.assertEqual((report["changed_files"], report["binary_or_unreadable_files"]), (0, []))

    def test_reordered_same_name_functions_pair_with_themselves(self):
        getter = "    @property\n    def x(self):\n        return self._x\n"
        setter = "    @x.setter\n    def x(self, value):\n        if value:\n            for v in value:\n                if v:\n                    self._x = v\n"
        self.write("prop.py", "class A:\n" + getter + "\n" + setter)
        self.commit("props")
        self.write("prop.py", "class A:\n" + setter + "\n" + getter)
        self.assertEqual(self.flags()[0], {})

    def test_links_fifos_and_devices_are_never_opened(self):
        import os
        os.mkfifo(self.root / "pipe.py")
        os.symlink(self.root / "pipe.py", self.root / "link.txt")
        os.symlink("/dev/zero", self.root / "zero.py")
        _, report = self.flags()
        # Git does not list a FIFO as untracked; links are listed and reported unreadable without being opened.
        self.assertEqual(report["binary_or_unreadable_files"], ["link.txt", "zero.py"])
        self.assertEqual((report["changed_files"], report["measured_source_files"]), (2, 1))
        # A source file that could not be read was not measured: a gap, never a clean result.
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual([(g["side"], g["path"]) for g in report["gaps"]], [("working tree", "zero.py")])

    def test_partial_clone_does_not_fetch_a_missing_object(self):
        top = self.root.parent / (self.root.name + "-partial")
        self.addCleanup(lambda: shutil.rmtree(top, ignore_errors=True))
        source, clone, marker, hook = top / "source", top / "clone", top / "ran", top / "hook"
        source.mkdir(parents=True)
        def git(where, *args):
            subprocess.run(["git", "-C", str(where), "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false", *args], check=True, capture_output=True)
        git(source, "init", "-q", "-b", "main")
        (source / "app.py").write_text(NESTED)
        git(source, "add", "-A")
        git(source, "commit", "-q", "-m", "base")
        git(source, "config", "uploadpack.allowFilter", "true")
        subprocess.run(["git", "clone", "-q", "--filter=blob:none", "--no-checkout", f"file://{source}", str(clone)], check=True, capture_output=True)
        hook.write_text('#!/bin/sh\n: > "' + str(marker) + '"\nexit 1\n')
        hook.chmod(0o700)
        git(clone, "config", "remote.origin.url", "ssh://example.invalid/repository")
        git(clone, "config", "core.sshCommand", str(hook))
        (clone / "app.py").write_text(FLAT)
        report = structure_delta.delta(clone, base="HEAD")
        self.assertFalse(marker.exists(), "a Git read fetched a missing object through the repository's remote command")
        self.assertEqual((report["status"], [(g["side"], g["path"]) for g in report["gaps"]]), ("incomplete", [("base", "app.py")]))

    def test_whitespace_only_edit_inside_a_protected_region_is_flagged(self):
        self.write("fast.py", PROTECTED.replace("a = buf[0] ^ key[0]\n", "a = buf[0] ^ key[0]  \n"))
        self.assertEqual(self.flags()[0], {"protected_region_changed": ["fast.py"]})

    def test_unchanged_function_pairs_with_itself_when_a_same_name_function_is_added(self):
        self.write("over.py", "class A:\n    def run(self, a):\n        if a:\n            for x in a:\n                if x:\n                    return x\n        return None\n")
        self.commit("impl")
        self.write("over.py", "class A:\n    def run(self):\n        return 0\n\n    def run(self, a):\n        if a:\n            for x in a:\n                if x:\n                    return x\n        return None\n")
        flags, report = self.flags()
        self.assertEqual(flags, {})
        self.assertEqual([r["function_id"] for r in report["structure"]["added_functions"]], ["A.run:2"])

    def commit_flat(self):
        self.write("app.py", FLAT)
        self.commit("flat")


if __name__ == "__main__":
    unittest.main()
