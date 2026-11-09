"""One guarded way to read Git state in a repository under review.

A reviewed repository's own configuration can name programs that Git runs during read commands:
`core.fsmonitor` on status, diff and ls-files; external diff and textconv drivers on diff, log and show; and
clean or process filters whenever Git compares with the working tree. Every script reads Git through `run`,
which disables the first. Pass NO_DRIVERS to log and show to disable the second. Nothing here asks Git to
compare with the working tree: `changed_paths` hashes working files itself with filters off.
"""
import hashlib
import os
import stat
import subprocess

NO_DRIVERS = ("--no-ext-diff", "--no-textconv")


def run(root, *args, timeout=20, stdin=None):
    """stdout bytes of `git -C root args`, or None when Git is missing, times out or exits non-zero."""
    try:
        result = subprocess.run(["git", "-c", "core.fsmonitor=false", "-C", str(root), *args], capture_output=True, timeout=timeout, input=stdin)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None


def names(output):
    return [name for name in output.decode("utf-8", "surrogateescape").split("\0") if name]


def kind(path):
    """'file', 'link', 'missing' or 'other' without opening the path, so a FIFO or device is never read."""
    try:
        mode = os.lstat(path).st_mode
    except OSError:
        return "missing"
    return "file" if stat.S_ISREG(mode) else "link" if stat.S_ISLNK(mode) else "other"


def changed_paths(root, base):
    """{root-relative path: state} for every path whose working-tree bytes differ from base; None when Git cannot answer.

    States: modified, added (tracked, absent from base), untracked, deleted, unreadable (not a regular file or
    link, or a name Git cannot take on one line). Blob ids come from `ls-tree`; working files are hashed with
    `hash-object --no-filters`. A repository that relies on filters (LFS, line-ending conversion) therefore
    lists the filtered files as modified. Submodules are skipped.
    """
    tree, tracked, untracked = run(root, "ls-tree", "-r", "-z", base, "--", "."), run(root, "ls-files", "-z"), run(root, "ls-files", "--others", "--exclude-standard", "-z")
    if tree is None or tracked is None or untracked is None:
        return None
    at_base = {}
    for entry in names(tree):
        meta, path = entry.split("\t", 1)
        _mode, object_type, oid = meta.split()
        if object_type == "blob":
            at_base[path] = oid
    tracked, untracked = set(names(tracked)), names(untracked)
    states, to_hash = {}, []
    for path in sorted(set(at_base) | tracked | set(untracked)):
        found = kind(os.path.join(str(root), path))
        if found == "missing":
            if path in at_base:
                states[path] = "deleted"
        elif found == "other" or "\n" in path:
            states[path] = "unreadable"
        else:
            to_hash.append((path, found))
    files = [path for path, found in to_hash if found == "file"]
    # hash-object resolves --stdin-paths from the repository top, so pass absolute paths.
    listing = "".join(os.path.join(os.path.abspath(str(root)), path) + "\n" for path in files)
    hashed = run(root, "hash-object", "--no-filters", "--stdin-paths", stdin=listing.encode("utf-8", "surrogateescape"), timeout=300) if files else b""
    if hashed is None or len(hashed.split()) != len(files):
        return None
    oids = dict(zip(files, hashed.decode().split()))
    # A link is stored as a blob holding its target; hash it here instead of one Git process per link.
    algorithm = (run(root, "rev-parse", "--show-object-format") or b"sha1").decode().strip() or "sha1"
    for path, found in to_hash:
        if found == "link":
            target = os.fsencode(os.readlink(os.path.join(str(root), path)))
            oids[path] = hashlib.new(algorithm, b"blob %d\0" % len(target) + target).hexdigest()
        if oids[path] != at_base.get(path):
            states[path] = "modified" if path in at_base else "added" if path in tracked else "untracked"
    return states
