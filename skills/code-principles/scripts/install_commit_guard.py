#!/usr/bin/env python3
"""Install or remove the commit guard: a Git pre-commit check that runs in every repository on this machine.

`git commit` then refuses a commit that would record a handoff document, agent coordination state, a code-signing
identity, a personal mail address or a credential (publish_check.py --staged). Nothing is read but the staged change.

How: Git has one global place for hooks, core.hooksPath, and it replaces a repository's own .git/hooks. So the folder
installed here (~/.code-audit/git-hooks) holds one small script under every client hook name: it runs the check for
pre-commit, then runs the repository's own hook of the same name if there is one. A repository that sets its own
core.hooksPath (husky, lefthook) is not covered: add the check to its hooks. Merge, rebase and cherry-pick commits do
not run pre-commit in Git: publish_check.py --sweep finds what those bring in.

The guard never stops work it cannot judge: when the check cannot run (moved, no python3) the commit proceeds with a
note. Repositories named in ~/.code-audit/sweep-exempt.txt are not checked.

  install_commit_guard.py            install; refuses when core.hooksPath already points somewhere else
  install_commit_guard.py --remove   remove the folder and unset core.hooksPath if it is this one
  install_commit_guard.py --status   say what is installed; exit 0 installed, 1 not

This changes global Git configuration. Run it only when the machine's owner asked for it.
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

HOOKS = ("applypatch-msg", "pre-applypatch", "post-applypatch", "pre-commit", "pre-merge-commit", "prepare-commit-msg",
         "commit-msg", "post-commit", "pre-rebase", "post-checkout", "post-merge", "pre-push", "post-rewrite",
         "pre-auto-gc", "reference-transaction", "sendemail-validate", "post-index-change")
MARK = "# managed by code-audit install_commit_guard.py"
KINDS = "secret,identity,personal-email,session-file"
DISPATCH = """#!/bin/sh
{mark}
# Runs the commit guard for pre-commit, then the repository's own hook of the same name.
name=$(basename "$0")
if [ "$name" = pre-commit ]; then
  python3 "{check}" --staged --kinds {kinds}
  status=$?
  if [ "$status" -eq 1 ]; then
    echo "commit guard: this commit would record the findings above." >&2
    echo "  A handoff or Rally file: keep it out of Git (git restore --staged <path>; it is ignored machine-wide)." >&2
    echo "  An identity or address: replace it with the command that looks it up." >&2
    echo "  Intentional in this repository: add a path glob to .publish-allow, or the folder name to ~/.code-audit/sweep-exempt.txt." >&2
    exit 1
  elif [ "$status" -ne 0 ]; then
    echo "commit guard: the check could not run (status $status); the commit is not blocked." >&2
  fi
fi
common=$(git rev-parse --git-common-dir 2>/dev/null) || exit 0
if [ -x "$common/hooks/$name" ]; then
  exec "$common/hooks/$name" "$@"
fi
exit 0
"""


def git_global(*args):
    return subprocess.run(["git", "config", "--global", *args], capture_output=True, text=True)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = p.add_mutually_exclusive_group()
    g.add_argument("--remove", action="store_true")
    g.add_argument("--status", action="store_true")
    a = p.parse_args(argv)
    folder = Path.home() / ".code-audit" / "git-hooks"
    current = git_global("--get", "core.hooksPath").stdout.strip()
    ours = bool(current) and Path(current).expanduser().resolve() == folder.resolve()
    if a.status:
        installed = ours and (folder / "pre-commit").exists()
        print(f"commit guard: {'installed at ' + str(folder) if installed else 'not installed'}"
              + (f" (core.hooksPath is {current})" if current and not ours else ""))
        return 0 if installed else 1
    if a.remove:
        if ours:
            git_global("--unset", "core.hooksPath")
        if folder.exists() and MARK in (folder / "pre-commit").read_text(encoding="utf-8"):
            shutil.rmtree(folder)
        print("commit guard: removed")
        return 0
    if current and not ours:
        print(f"commit guard: core.hooksPath is already {current}; not replacing it. Add the check to those hooks:\n"
              f"  python3 {Path(__file__).resolve().parent / 'publish_check.py'} --staged --kinds {KINDS}", file=sys.stderr)
        return 2
    folder.mkdir(parents=True, exist_ok=True)
    script = DISPATCH.format(mark=MARK, check=Path(__file__).resolve().parent / "publish_check.py", kinds=KINDS)
    for name in HOOKS:
        target = folder / name
        target.write_text(script, encoding="utf-8")
        target.chmod(0o755)
    done = git_global("core.hooksPath", str(folder))
    if done.returncode != 0:
        print(f"commit guard: could not set core.hooksPath: {done.stderr.strip()}", file=sys.stderr)
        return 2
    print(f"commit guard: installed at {folder}; every repository without its own core.hooksPath is covered")
    return 0


if __name__ == "__main__":
    sys.exit(main())
