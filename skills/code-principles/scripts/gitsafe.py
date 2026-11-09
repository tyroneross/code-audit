"""One guarded way to read Git state in a repository under review.

A reviewed repository's own configuration can name programs that Git runs during read commands: `core.fsmonitor` on
status, diff and ls-files, and external diff or textconv drivers on diff and log. Every script reads Git through
`run`, which disables the first; pass NO_DRIVERS to diff, log and show commands to disable the others.
"""
import subprocess

NO_DRIVERS = ("--no-ext-diff", "--no-textconv")


def run(root, *args, timeout=20):
    """stdout bytes of `git -C root args`, or None when Git is missing, times out or exits non-zero."""
    try:
        result = subprocess.run(["git", "-c", "core.fsmonitor=false", "-C", str(root), *args], capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None
