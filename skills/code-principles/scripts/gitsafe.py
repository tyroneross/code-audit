"""One guarded way to read Git state in a repository under review.

A reviewed repository's own configuration can name programs that Git runs during read commands:
`core.fsmonitor` on status, diff and ls-files; `gpg.program` on log and show when `log.showSignature` is set;
external diff and textconv drivers on diff, log and show; clean or process filters whenever Git compares
with the working tree; and the remote command when a partial clone fetches a missing object. Every script reads
Git through `run`, which overrides the first two and turns lazy fetching off. Pass NO_DRIVERS to
log and show to disable the third. Nothing here asks Git to compare with the working tree: `changed_paths`
hashes working files itself with filters off, and `numstat` compares two scratch copies outside the repository.
"""
import hashlib
import os
import stat
import subprocess
import tempfile

NO_DRIVERS = ("--no-ext-diff", "--no-textconv")
# Command-line configuration outranks the repository's own.
OVERRIDES = ("-c", "core.fsmonitor=false", "-c", "log.showSignature=false")
# In a partial clone a read of a missing object fetches it, which runs the repository's remote command
# (core.sshCommand, a remote helper) and writes objects. A missing object is reported as missing instead.
ENVIRONMENT = {"GIT_NO_LAZY_FETCH": "1"}


def run(root, *args, timeout=20, stdin=None, ok=(0,)):
    """stdout bytes of `git -C root args`, or None when Git is missing, times out or exits with a status outside ok."""
    try:
        result = subprocess.run(["git", *OVERRIDES, "-C", str(root), *args], capture_output=True, timeout=timeout, input=stdin,
                                env={**os.environ, **ENVIRONMENT})
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode in ok else None


def links_at(root, base):
    """Root-relative paths that are symbolic links at base. Their blob is the link target, not file contents."""
    tree = run(root, "ls-tree", "-r", "-z", base, "--", ".")
    return {entry.split("\t", 1)[1] for entry in names(tree or b"") if entry.startswith("120000 ")}


def blobs(root, base, paths):
    """{path: bytes at base, or None when absent there} read in one Git process, without filters or textconv."""
    wanted = [path for path in paths if "\n" not in path]
    request = "".join(f"{base}:./{path}\n" for path in wanted).encode("utf-8", "surrogateescape")
    output = run(root, "cat-file", "--batch", stdin=request, timeout=300) if wanted else b""
    found, offset = dict.fromkeys(paths), 0
    for path in wanted:
        if output is None:
            break
        end = output.index(b"\n", offset)
        header = output[offset:end].split()
        offset = end + 1
        if header[-1:] == [b"missing"] or len(header) != 3:
            continue
        size = int(header[2])
        if header[1] == b"blob":  # a directory or submodule at base has no file bytes
            found[path] = output[offset:offset + size]
        offset += size + 1
    return found


def numstat(before, after):
    """(added, deleted) lines between two byte strings as Git counts them, or None when Git treats either as binary.

    The two sides are written to a scratch directory and compared with `diff --no-index` from there, so no
    repository configuration or attribute applies and no working-tree file is read.
    """
    with tempfile.TemporaryDirectory(prefix="gitsafe-numstat-") as scratch:
        for name, data in (("before", before), ("after", after)):
            with open(os.path.join(scratch, name), "wb") as handle:
                handle.write(data)
        # Exit 1 means the files differ, which is the expected case.
        output = run(scratch, "diff", "--no-index", "--numstat", *NO_DRIVERS, "--", "before", "after", timeout=120, ok=(0, 1))
    fields = (output or b"").decode("utf-8", "replace").split("\t")
    if output == b"":
        return 0, 0
    if len(fields) < 3 or not (fields[0].isdigit() and fields[1].isdigit()):
        return None
    return int(fields[0]), int(fields[1])


def names(output):
    return [name for name in output.decode("utf-8", "surrogateescape").split("\0") if name]


def kind(root, path):
    """'file', 'link', 'missing' or 'other' for root-relative path, without opening it, so a FIFO or device is never read.

    A path whose directory resolves outside root (a tracked directory replaced by a link to somewhere else) is
    'other': nothing outside the source root is ever hashed or read.
    """
    real_root = os.path.realpath(str(root))
    full = os.path.join(real_root, path)
    parent = os.path.realpath(os.path.dirname(full))
    if parent != real_root and not parent.startswith(real_root + os.sep):
        return "other"
    try:
        mode = os.lstat(full).st_mode
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
    tree, staged, untracked = run(root, "ls-tree", "-r", "-z", base, "--", "."), run(root, "ls-files", "-s", "-z"), run(root, "ls-files", "--others", "--exclude-standard", "-z")
    if tree is None or staged is None or untracked is None:
        return None
    at_base, base_links = {}, set()
    for entry in names(tree):
        meta, path = entry.split("\t", 1)
        mode, object_type, oid = meta.split()
        if object_type == "blob":
            at_base[path] = oid
            if mode == "120000":
                base_links.add(path)
    # `ls-files -s` rows are "<mode> <oid> <stage>\t<path>"; mode 160000 is a submodule, which has no bytes to compare.
    tracked = {path for meta, path in (entry.split("\t", 1) for entry in names(staged)) if not meta.startswith("160000 ")}
    untracked = names(untracked)
    states, to_hash = {}, []
    for path in sorted(set(at_base) | tracked | set(untracked)):
        found = kind(root, path)
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
        # Same bytes but a link on one side and a file on the other is a change: a link target is not file contents.
        if oids[path] != at_base.get(path) or (path in at_base and (found == "link") != (path in base_links)):
            states[path] = "modified" if path in at_base else "added" if path in tracked else "untracked"
    return states
