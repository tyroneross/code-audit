#!/usr/bin/env python3
"""Find text that must not leave this machine before a repository is published or pushed.

Six kinds of finding, in every tracked text file (code, data, docs, tests), in file paths and in commit messages:
  secret          blocks  a credential in a recognisable format (cloud, Git host and model-provider keys, private key blocks)
  home-path       blocks  a machine-specific path such as /Users/<name>/, /home/<name>/ or C:\\Users\\<name>\\
  identity        blocks  a code-signing identity with its team id ("Developer ID Application: <name> (<10 characters>)")
  personal-email  blocks  an address at a personal mail provider (icloud.com, gmail.com, ...); commit trailers are exempt
  session-file    blocks  a tracked handoff document or agent coordination state, by path: HANDOFF.md, HANDOFF-*.md,
                          HANDOFF_*.md, handoff.md,
                          anything under handoffs/ or .rally/, a handoff under .build-loop/. These are written for the
                          next session on this machine and carry its paths, run state and identities.
  private-name    warns   a name from the local private-names list (private repositories, clients, internal hosts)

A private name is a secrecy concern, not a security one: it is listed and counted, and the push proceeds. The secret
patterns are a fixed-format floor, not a full scanner; run a dedicated one (trufflehog, gitleaks) on whole history
before a first publish. Secret values are never printed: only their first characters.

The private-names list never lives in the repository it guards. Sources, merged:
  --names FILE, or $CODE_AUDIT_PRIVATE_NAMES (a file path), or ~/.code-audit/private-names.txt (one name per line, # comments)
  --from-gh OWNER   adds the names of OWNER's private GitHub repositories (`gh repo list --visibility private`)
A line `!name` in the names file removes that name, for a private repository whose name is also an ordinary word or
folder name (a repository called git-folder matches every path through a folder of that name).
The reviewed repository's own name is never reported.

Scope: tracked files at --rev (default HEAD), or with --range A..B only lines and files added in that range plus its
commit messages. Home paths and addresses under fictional users (example, alice, user, ...) are ignored. A
`.publish-allow` file at the repository root lists path globs where home paths, identities, personal addresses and
session files are intentional (test fixtures, a repository whose job is to keep handoffs); secrets and private names
cannot be allowed. --kinds limits the check to the listed kinds. --staged reads what `git commit` is about to record
(added lines and added, changed or renamed paths in the index) and is what the commit guard runs; in a repository
named in the exempt list below it reports nothing.

--sweep DIR ... checks every repository under the directories in one run, for the question "did this get committed
anywhere": linked worktrees are skipped, clones of one remote are read once, and with --from-gh OWNER only OWNER's
repositories are read and each is labelled public or private. It defaults to the kinds that are wrong in a private
repository too (secret, identity, personal-email, session-file); home paths and private names are for publishing.
Repositories whose job is to hold such records (a memory store, a personal wiki) are named, one folder name per line,
in ~/.code-audit/sweep-exempt.txt or with --exempt NAME; they are listed as exempt and not read.

Exit 0 nothing blocks (warnings may be listed), 1 a blocking finding, 2 usage or Git error. Output: text, or --json with schema code-audit.publish.v1.
"""
import argparse
import bisect
import concurrent.futures
import fnmatch
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gitsafe  # noqa: E402

# The lookbehind keeps a folder named home or Users inside a longer path (records/home/x.json) from matching.
# A letter that is the end of an escape (\\n, \\t, \\r in JSON or a string literal) still counts as a path start.
HOME_PATH = re.compile(r"(?:(?<![A-Za-z0-9_.])|(?<=\\[nrt]))(?:/Users/|/home/)([A-Za-z0-9._-]+)(?=/|\b)|[A-Za-z]:\\{1,2}Users\\{1,2}([A-Za-z0-9._-]+)")
FICTIONAL_USERS = {"example", "you", "user", "username", "me", "name", "alice", "bob", "jdoe", "john", "jane", "dev",
                   "devuser", "runner", "shared", "public", "default", "guest", "someone", "private", "your-name", "yourname", "x"}
SECRETS = re.compile("|".join((
    r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b",                      # AWS access key id
    r"\bgh[pousr]_[A-Za-z0-9]{36,}",                        # GitHub token
    r"\bgithub_pat_[A-Za-z0-9_]{22,}",                      # GitHub fine-grained token
    r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{32,}",              # Anthropic / OpenAI key
    r"\bxox[abprs]-[A-Za-z0-9-]{10,}",                      # Slack token
    r"\bAIza[0-9A-Za-z_-]{35}\b",                           # Google API key
    r"\b[sr]k_live_[0-9A-Za-z]{24,}",                       # Stripe live key
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",                  # PEM private key block
)))
SIGNING_IDENTITY = re.compile(r"\b(?:Apple Development|Apple Distribution|Developer ID Application|Developer ID Installer|"
                              r"iPhone Developer|iPhone Distribution|Mac Developer|3rd Party Mac Developer (?:Application|Installer))"
                              r": [^\"'\n()]{1,80}\([A-Z0-9]{10}\)")
PERSONAL_MAIL = re.compile(r"(?<![A-Za-z0-9._%+-])([A-Za-z0-9._%+-]+)@((?:icloud|me|mac|gmail|googlemail|outlook|hotmail|live|"
                           r"yahoo|protonmail|fastmail)\.com|proton\.me|pm\.me)(?![A-Za-z0-9.-])", re.IGNORECASE)
FICTIONAL_MAILBOXES = FICTIONAL_USERS | {"noreply", "no-reply", "test", "foo", "email", "your.email", "youremail", "first.last",
                                         "firstname.lastname", "jane.doe", "john.doe", "janedoe", "johndoe"}
# "Co-Authored-By: Name <address>" and its kin repeat what the commit's author field already publishes.
TRAILER = re.compile(r"^\s*[A-Za-z][A-Za-z-]*-[Bb]y:")
# Case matters: HANDOFF.md is a session's note, handoff.ts is source. Each alternative names the reason reported.
SESSION_FILE = re.compile(r"(?:^|/)(?:(?P<rally>\.rally/)|(?P<handoff>HANDOFF(?=[._-])[^/]*\.(?:md|txt|json)$|handoffs/.*\.(?:md|txt|json)$|"
                          r"handoff(?:-latest|-generated)?\.md$|\.build-loop/(?:.*/)?handoff[^/]*$))")
# The one place that decides what stops a push. A kind missing here cannot be reported (KeyError in finding()).
SEVERITY = {"secret": "block", "home-path": "block", "identity": "block", "personal-email": "block", "session-file": "block",
            "private-name": "warn"}
# What a `.publish-allow` glob can exempt. A secret or a private name is never intentional.
ALLOWABLE = {"home-path", "identity", "personal-email", "session-file"}
SWEEP_KINDS = ("secret", "identity", "personal-email", "session-file")
# A fixed string that every match of a kind's pattern contains. `git grep` uses these to pick the few files worth
# reading, which is what makes a whole-tree or many-repository run quick. A pattern added above without its anchor
# here finds nothing: test_publish_check runs each format through this path.
# These are compared with case: the patterns they serve are case-sensitive, and a case-blind search for many fixed
# strings is some eighty times slower in Git.
ANCHORS = {
    "secret": ("AKIA", "ASIA", "ghp_", "gho_", "ghu_", "ghs_", "ghr_", "github_pat_", "sk-", "xoxa-", "xoxb-", "xoxp-", "xoxr-",
               "xoxs-", "AIza", "sk_live_", "rk_live_", "PRIVATE KEY-----"),
    "home-path": ("/Users/", "/home/", "Users\\"),
    "identity": ("Apple Development: ", "Apple Distribution: ", "Developer ID Application: ", "Developer ID Installer: ",
                 "iPhone Developer: ", "iPhone Distribution: ", "Mac Developer: "),
}
# Compared without case, as their patterns are: addresses, and private names.
ANCHORS_NOCASE = {
    "personal-email": ("@icloud.com", "@me.com", "@mac.com", "@gmail.com", "@googlemail.com", "@outlook.com", "@hotmail.com",
                       "@live.com", "@yahoo.com", "@protonmail.com", "@fastmail.com", "@proton.me", "@pm.me"),
}
SKIP_DIRS = {"node_modules", ".build", "build", "target", "dist", ".next", "DerivedData", "Pods", ".venv", "venv", "__pycache__",
             "SourcePackages", ".trash"}
DEFAULT_NAMES = Path.home() / ".code-audit" / "private-names.txt"
DEFAULT_EXEMPT = Path.home() / ".code-audit" / "sweep-exempt.txt"
MAX_BLOB = 5_000_000


def load_names(path, gh_owner, own_name):
    names, excluded = set(), set()
    source = path or os.environ.get("CODE_AUDIT_PRIVATE_NAMES") or (DEFAULT_NAMES if DEFAULT_NAMES.exists() else None)
    if source:
        for line in Path(source).read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if line.startswith("!"):
                excluded.add(line[1:].strip().lower())
            elif line:
                names.add(line)
    if gh_owner:
        out = subprocess.run(["gh", "repo", "list", gh_owner, "--visibility", "private", "--limit", "1000",
                              "--json", "name", "-q", ".[].name"], capture_output=True, text=True, timeout=60)
        if out.returncode != 0:
            raise RuntimeError(f"gh repo list failed: {out.stderr.strip()[:200]}")
        names.update(n for n in out.stdout.split() if n)
    names = {n for n in names if n.lower() not in excluded and n.lower() != own_name.lower()}
    return sorted(names, key=len, reverse=True)


def name_pattern(names):
    if not names:
        return None
    # Whole-token match: a name inside a longer identifier (my-repo-tools for my-repo) is still a match only at a token edge.
    return re.compile(r"(?<![A-Za-z0-9_])(" + "|".join(re.escape(n) for n in names) + r")(?![A-Za-z0-9_])", re.IGNORECASE)


def finding(kind, where, number, token, text):
    return {"kind": kind, "severity": SEVERITY[kind], "where": where, "line": number, "token": token, "text": text}


def redact(line):
    """A line with every value this script must not repeat replaced: keys, signing identities, mailbox names."""
    line = SECRETS.sub(lambda m: m.group(0)[:6] + "[redacted]", line)
    line = SIGNING_IDENTITY.sub(lambda m: m.group(0).split(":", 1)[0] + ": [redacted]", line)
    return PERSONAL_MAIL.sub(lambda m: "[redacted]@" + m.group(2), line)


def scan_text(text, where, names_re, allowed, kinds=frozenset(SEVERITY), message=False):
    """Findings in text, in line order. allowed: this path is exempt from the ALLOWABLE kinds. message: a commit message.

    Each pattern runs once over the whole text and a line is cut out only around a match: a large record file with no
    match costs one pass per pattern, not one per line. No pattern can match across a line break.
    """
    content = kinds if not allowed else kinds - ALLOWABLE
    hits = []  # (line number, kind rank, column, kind, token)
    starts = None

    def line_of(position):
        nonlocal starts
        if starts is None:
            starts = [0] + [m.end() for m in re.finditer("\n", text)]
        index = bisect.bisect_right(starts, position) - 1
        end = starts[index + 1] - 1 if index + 1 < len(starts) else len(text)
        return index + 1, starts[index], text[starts[index]:end]

    def add(rank, kind, match, token):
        number, begin, _ = line_of(match.start())
        hits.append((number, rank, match.start() - begin, kind, token))

    if "secret" in content:
        for m in SECRETS.finditer(text):
            add(0, "secret", m, m.group(0)[:6] + "[redacted]")
    if names_re and "private-name" in content:
        for m in names_re.finditer(text):
            add(1, "private-name", m, m.group(1))
    if "home-path" in content:
        for m in HOME_PATH.finditer(text):
            user = (m.group(1) or m.group(2) or "").lower()
            if user and user not in FICTIONAL_USERS and not user.startswith(("example", "<", "$")):
                add(2, "home-path", m, m.group(0))
    if "identity" in content:
        for m in SIGNING_IDENTITY.finditer(text):
            add(3, "identity", m, m.group(0).split(":", 1)[0] + ": [redacted]")
    if "personal-email" in content:
        for m in PERSONAL_MAIL.finditer(text):
            if m.group(1).lower() in FICTIONAL_MAILBOXES or m.group(1).lower().startswith("example"):
                continue
            if message and TRAILER.match(line_of(m.start())[2]):
                continue
            add(4, "personal-email", m, "[redacted]@" + m.group(2).lower())
    found = []
    for number, _, column, kind, token in sorted(hits):
        _, _, line = line_of(starts[number - 1])
        found.append(finding(kind, where, number, token, redact(line).strip()[:200]))
    return found


def scan_paths(paths, globs, kinds):
    """session-file findings for tracked paths: the file is the finding, whatever it contains."""
    if "session-file" not in kinds:
        return []
    found = []
    for path in paths:
        m = SESSION_FILE.search(path)
        if m and not is_allowed(path, globs):
            found.append(finding("session-file", path, 0, "Rally state" if m.group("rally") else "handoff document", path))
    return found


def is_allowed(path, globs):
    return any(fnmatch.fnmatch(path, g) for g in globs)


def allowed_globs(root, rev):
    blob = gitsafe.blobs(root, rev, [".publish-allow"]).get(".publish-allow")
    return [g.strip() for g in (blob or b"").decode("utf-8", "replace").splitlines() if g.strip() and not g.startswith("#")]


def decode(blob):
    if blob is None or b"\0" in blob[:8192] or len(blob) > MAX_BLOB:
        return None
    return blob.decode("utf-8", "replace")


def candidates(root, rev, tracked, kinds, names):
    """Tracked paths whose text holds an anchor of a wanted kind or a private name; every path when Git cannot say."""
    exact = [a for kind in sorted(kinds) for a in ANCHORS.get(kind, ())]
    nocase = [a for kind in sorted(kinds) for a in ANCHORS_NOCASE.get(kind, ())] + (list(names) if "private-name" in kinds else [])
    prefix, found = rev + ":", set()
    for anchors, flags in ((exact, ()), (nocase, ("-i",))):
        if not anchors:
            continue
        out = gitsafe.run(root, "grep", "-I", "-l", "-z", "-F", *flags, "-f", "-", rev, "--", ".",
                          stdin="\n".join(anchors).encode("utf-8"), ok=(0, 1), timeout=300)
        if out is None:
            return tracked
        found.update(name[len(prefix):] if name.startswith(prefix) else name for name in gitsafe.names(out))
    return [path for path in tracked if path in found]


def scan_tree(root, rev, names_re, globs, kinds=frozenset(SEVERITY), names=()):
    listing = gitsafe.run(root, "ls-tree", "-r", "-z", "--name-only", rev, "--", ".", timeout=120)
    if listing is None:
        raise RuntimeError(f"cannot list files at {rev}")
    links = gitsafe.links_at(root, rev)
    tracked = gitsafe.names(listing)
    found = scan_paths(tracked, globs, kinds)
    if kinds - {"session-file"}:
        wanted = [p for p in candidates(root, rev, tracked, kinds, names) if p not in links]
        for path, blob in gitsafe.blobs(root, rev, wanted).items():
            text = decode(blob)
            if text is not None:
                found += scan_text(text, path, names_re, is_allowed(path, globs), kinds)
    return found


def scan_range(root, spec, names_re, globs, kinds=frozenset(SEVERITY)):
    """Findings in what spec adds. spec is a range A..B, or None for the index against HEAD (no commit messages yet)."""
    select = ("--cached",) if spec is None else (spec,)
    diff = gitsafe.run(root, "diff", *gitsafe.NO_DRIVERS, "--no-color", "--unified=0", *select, "--", ".", timeout=300)
    log = b"" if spec is None else gitsafe.run(root, "log", *gitsafe.NO_DRIVERS, "--format=%H%x00%B%x01", spec, timeout=120)
    added = gitsafe.run(root, "diff", *gitsafe.NO_DRIVERS, "--name-only", "-z", "--diff-filter=AMR", *select, "--", ".", timeout=120)
    if diff is None or log is None or added is None:
        raise RuntimeError(f"cannot read {spec or 'the index'}")
    found, path, number = scan_paths(gitsafe.names(added), globs, kinds), None, 0
    for raw in diff.decode("utf-8", "replace").splitlines():
        if raw.startswith("+++ "):
            path = raw[6:] if raw.startswith("+++ b/") else None
        elif raw.startswith("@@"):
            hunk = re.search(r"\+(\d+)", raw)
            number = int(hunk.group(1)) - 1 if hunk else 0
        elif raw.startswith("+") and path:
            number += 1
            for f in scan_text(raw[1:], path, names_re, is_allowed(path, globs), kinds):
                f["line"] = number
                found.append(f)
    for entry in log.decode("utf-8", "replace").split("\x01"):
        if "\x00" in entry:
            sha, body = entry.strip().split("\x00", 1)
            found += scan_text(body, f"commit {sha[:12]} message", names_re, False, kinds, message=True)
    return found


def find_repos(roots, max_depth=7):
    """Main checkouts under roots. A linked worktree or submodule (.git is a file) shares another checkout's history.

    The walk stops at a repository: a checkout kept inside another repository's folder (a vendored dependency, a
    research copy) is not listed. Name its folder as a root to include it.
    """
    for root in roots:
        root = Path(root).expanduser().resolve()
        for folder, dirs, files in os.walk(root):
            if ".git" in dirs:
                yield Path(folder)
                dirs[:] = []
            elif ".git" in files or len(Path(folder).relative_to(root).parts) >= max_depth:
                dirs[:] = []
            else:
                dirs[:] = [d for d in dirs if d not in SKIP_DIRS]


def remote_slug(root):
    """owner/name of the origin remote in lower case, or None."""
    url = (gitsafe.run(root, "remote", "get-url", "origin") or b"").decode("utf-8", "replace").strip()
    m = re.search(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?/?$", url) if "://" in url or "@" in url else None
    return f"{m.group(1)}/{m.group(2)}".lower() if m and not url.startswith("file:") else None


def load_exempt(extra):
    names = {n.lower() for n in extra or ()}
    if DEFAULT_EXEMPT.exists():
        names.update(line.split("#", 1)[0].strip().lower() for line in DEFAULT_EXEMPT.read_text(encoding="utf-8").splitlines())
    return names - {""}


def check_repo(job):
    """One repository's report. Top-level so a worker process can run it."""
    root, seen, kinds = job
    report = {"path": str(root), "visibility": seen, "findings": [], "error": None}
    try:
        if gitsafe.run(root, "rev-parse", "--verify", "-q", "HEAD") is None:
            return report  # no commit yet: nothing is tracked
        report["findings"] = scan_tree(root, "HEAD", None, allowed_globs(root, "HEAD"), kinds)
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
        report["error"] = str(error)[:200]
    return report


def sweep(roots, owner, kinds, exempt=frozenset()):
    """(reports, skipped). One report per distinct repository: path, visibility, findings or an error."""
    visibility = {}
    if owner:
        out = subprocess.run(["gh", "repo", "list", owner, "--limit", "1000", "--json", "name,visibility"],
                             capture_output=True, text=True, timeout=60)
        if out.returncode != 0:
            raise RuntimeError(f"gh repo list failed: {out.stderr.strip()[:200]}")
        visibility = {f"{owner}/{r['name']}".lower(): r["visibility"].lower() for r in json.loads(out.stdout)}
    chosen, skipped = {}, {"other-owner": 0, "duplicate-clone": 0, "exempt": []}
    # Shortest path first: the working clone is kept, a cached or archived copy of the same remote is the duplicate.
    for root in sorted(set(find_repos(roots)), key=lambda p: (len(p.parts), str(p))):
        slug = remote_slug(root)
        if root.name.lower() in exempt:
            skipped["exempt"].append(str(root))
        elif owner and slug and not slug.startswith(owner.lower() + "/"):
            skipped["other-owner"] += 1
        elif slug in chosen:
            skipped["duplicate-clone"] += 1
        else:
            chosen[slug or str(root)] = (root, visibility.get(slug, "unlisted") if slug else "no-remote", kinds)
    # Processes, not threads: the reading is Git's, the matching is this interpreter's.
    with concurrent.futures.ProcessPoolExecutor(max_workers=min(8, os.cpu_count() or 2)) as pool:
        reports = list(pool.map(check_repo, chosen.values()))
    order = {"public": 0, "unlisted": 1, "private": 2, "no-remote": 3}
    reports.sort(key=lambda r: (order.get(r["visibility"], 1), r["path"]))
    return reports, skipped


def print_sweep(reports, skipped, kinds, as_json):
    hit = [r for r in reports if r["findings"]]
    blocking = sum(f["severity"] == "block" for r in hit for f in r["findings"])
    if as_json:
        print(json.dumps({"schema": "code-audit.publish-sweep.v1", "kinds": sorted(kinds), "repositories": len(reports),
                          "with_findings": len(hit), "blocking": blocking, "skipped": skipped,
                          "errors": [{"path": r["path"], "error": r["error"]} for r in reports if r["error"]],
                          "reports": hit}, indent=1))
        return blocking
    home = str(Path.home())
    for r in hit:
        counts = {}
        for f in r["findings"]:
            counts[f["kind"]] = counts.get(f["kind"], 0) + 1
        print(f"{r['visibility']:9} {r['path'].replace(home, '~', 1)}  " + ", ".join(f"{n} {k}" for k, n in sorted(counts.items())))
        for f in r["findings"][:8]:
            print(f"            {f['kind']:14} {f['where']}" + (f":{f['line']}  {f['token']}" if f["line"] else ""))
        if len(r["findings"]) > 8:
            print(f"            ... {len(r['findings']) - 8} more (--json lists all)")
    for r in reports:
        if r["error"]:
            print(f"error     {r['path'].replace(home, '~', 1)}  {r['error']}")
    print(f"{len(hit)} of {len(reports)} repositories have findings, {blocking} blocking; skipped "
          f"{skipped['other-owner']} of another owner, {skipped['duplicate-clone']} duplicate clone(s), "
          f"{len(skipped['exempt'])} exempt" + ("".join(f"\n  exempt: {p.replace(home, '~', 1)}" for p in skipped["exempt"])))
    return blocking


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--repo", type=Path, default=Path.cwd())
    g = p.add_mutually_exclusive_group()
    g.add_argument("--rev", default="HEAD")
    g.add_argument("--range", metavar="A..B")
    g.add_argument("--staged", action="store_true", help="check what the next commit would record")
    p.add_argument("--names", type=Path)
    p.add_argument("--from-gh", metavar="OWNER")
    p.add_argument("--json", action="store_true")
    p.add_argument("--kinds", metavar="K,K", help="check only these kinds: " + ", ".join(SEVERITY))
    p.add_argument("--sweep", nargs="+", metavar="DIR", type=Path, help="check every repository under these directories")
    p.add_argument("--exempt", action="append", metavar="NAME", help="with --sweep or --staged: a repository folder name not to read")
    a = p.parse_args(argv)
    kinds = frozenset(k.strip() for k in a.kinds.split(",") if k.strip()) if a.kinds else None
    if kinds is not None and not kinds <= set(SEVERITY):
        print(f"publish_check: unknown kind(s): {', '.join(sorted(kinds - set(SEVERITY)))}", file=sys.stderr)
        return 2
    if a.sweep:
        if a.range or a.names:
            print("publish_check: --sweep reads each repository's HEAD and no names file", file=sys.stderr)
            return 2
        try:
            reports, skipped = sweep(a.sweep, a.from_gh, kinds or frozenset(SWEEP_KINDS), load_exempt(a.exempt))
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
            print(f"publish_check: {error}", file=sys.stderr)
            return 2
        return 1 if print_sweep(reports, skipped, kinds or frozenset(SWEEP_KINDS), a.json) else 0
    kinds = kinds or frozenset(SEVERITY)
    root = a.repo.resolve()
    if a.staged:
        # A linked worktree's folder has its own name; the repository is the folder that holds the shared .git.
        common = (gitsafe.run(root, "rev-parse", "--path-format=absolute", "--git-common-dir") or b"").decode().strip()
        if common and Path(common).parent.name.lower() in load_exempt(a.exempt):
            return 0
    if gitsafe.run(root, "rev-parse", "--git-dir") is None:
        print(f"publish_check: {root} is not a Git repository", file=sys.stderr)
        return 2
    try:
        names = load_names(a.names, a.from_gh, root.name)
        names_re, globs = name_pattern(names), allowed_globs(root, a.range.split("..")[-1] if a.range else a.rev)
        if a.staged or a.range:
            findings = scan_range(root, a.range, names_re, globs, kinds)
        else:
            findings = scan_tree(root, a.rev, names_re, globs, kinds, names)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"publish_check: {error}", file=sys.stderr)
        return 2
    blocking = sum(f["severity"] == "block" for f in findings)
    summary = {"schema": "code-audit.publish.v1", "repo": root.name, "scope": "staged" if a.staged else a.range or a.rev,
               "private_names_checked": len(names), "blocking": blocking, "warnings": len(findings) - blocking,
               "findings": findings}
    if a.json:
        print(json.dumps(summary, indent=1))
    else:
        if not names:
            print("note: no private names configured; every other kind was checked (see --help)")
        for f in sorted(findings, key=lambda f: f["severity"] != "block"):
            print(f"{f['severity']:5} {f['kind']:14} {f['where']}:{f['line']}  {f['token']}")
        print(f"{blocking} blocking, {len(findings) - blocking} warning(s); {len(names)} private name(s) checked")
    return 1 if blocking else 0


if __name__ == "__main__":
    sys.exit(main())
