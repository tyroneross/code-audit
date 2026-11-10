#!/usr/bin/env python3
"""Find text that must not leave this machine before a repository is published or pushed.

Three kinds of finding, in every tracked text file (code, data, docs, tests) and in commit messages:
  secret        blocks  a credential in a recognisable format (cloud, Git host and model-provider keys, private key blocks)
  home-path     blocks  a machine-specific path such as /Users/<name>/, /home/<name>/ or C:\\Users\\<name>\\
  private-name  warns   a name from the local private-names list (private repositories, clients, internal hosts)

A private name is a secrecy concern, not a security one: it is listed and counted, and the push proceeds. The secret
patterns are a fixed-format floor, not a full scanner; run a dedicated one (trufflehog, gitleaks) on whole history
before a first publish. Secret values are never printed: only their first characters.

The private-names list never lives in the repository it guards. Sources, merged:
  --names FILE, or $CODE_AUDIT_PRIVATE_NAMES (a file path), or ~/.code-audit/private-names.txt (one name per line, # comments)
  --from-gh OWNER   adds the names of OWNER's private GitHub repositories (`gh repo list --visibility private`)
A line `!name` in the names file removes that name, for a private repository whose name is also an ordinary word or
folder name (a repository called git-folder matches every path through a folder of that name).
The reviewed repository's own name is never reported.

Scope: tracked files at --rev (default HEAD), or with --range A..B only lines added in that range plus its commit
messages. Home paths under fictional users (example, alice, user, ...) are ignored. A `.publish-allow` file at the
repository root lists path globs whose home paths are intentional (test fixtures); secrets and private names cannot be
allowed.

Exit 0 nothing blocks (warnings may be listed), 1 a blocking finding, 2 usage or Git error. Output: text, or --json with schema code-audit.publish.v1.
"""
import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gitsafe  # noqa: E402

HOME_PATH = re.compile(r"(?:/Users/|/home/)([A-Za-z0-9._-]+)(?=/|\b)|[A-Za-z]:\\{1,2}Users\\{1,2}([A-Za-z0-9._-]+)")
FICTIONAL_USERS = {"example", "you", "user", "username", "me", "name", "alice", "bob", "jdoe", "john", "jane", "dev",
                   "devuser", "runner", "shared", "public", "default", "guest", "someone", "your-name", "yourname", "x"}
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
# The one place that decides what stops a push. A kind missing here cannot be reported (KeyError in finding()).
SEVERITY = {"secret": "block", "home-path": "block", "private-name": "warn"}
DEFAULT_NAMES = Path.home() / ".code-audit" / "private-names.txt"
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


def scan_text(text, where, names_re, allow_home):
    found = []
    for number, line in enumerate(text.splitlines(), 1):
        shown = SECRETS.sub(lambda m: m.group(0)[:6] + "[redacted]", line).strip()[:200]
        for m in SECRETS.finditer(line):
            found.append(finding("secret", where, number, m.group(0)[:6] + "[redacted]", shown))
        if names_re:
            for m in names_re.finditer(line):
                found.append(finding("private-name", where, number, m.group(1), shown))
        if not allow_home:
            for m in HOME_PATH.finditer(line):
                user = (m.group(1) or m.group(2) or "").lower()
                if user and user not in FICTIONAL_USERS and not user.startswith(("example", "<", "$")):
                    found.append(finding("home-path", where, number, m.group(0), shown))
    return found


def allowed_globs(root, rev):
    blob = gitsafe.blobs(root, rev, [".publish-allow"]).get(".publish-allow")
    return [g.strip() for g in (blob or b"").decode("utf-8", "replace").splitlines() if g.strip() and not g.startswith("#")]


def decode(blob):
    if blob is None or b"\0" in blob[:8192] or len(blob) > MAX_BLOB:
        return None
    return blob.decode("utf-8", "replace")


def scan_tree(root, rev, names_re, globs):
    listing = gitsafe.run(root, "ls-tree", "-r", "-z", "--name-only", rev, "--", ".", timeout=120)
    if listing is None:
        raise RuntimeError(f"cannot list files at {rev}")
    links = gitsafe.links_at(root, rev)
    paths = [p for p in gitsafe.names(listing) if p not in links]
    found = []
    for path, blob in gitsafe.blobs(root, rev, paths).items():
        text = decode(blob)
        if text is not None:
            found += scan_text(text, path, names_re, any(fnmatch.fnmatch(path, g) for g in globs))
    return found


def scan_range(root, spec, names_re, globs):
    diff = gitsafe.run(root, "diff", *gitsafe.NO_DRIVERS, "--no-color", "--unified=0", spec, "--", ".", timeout=300)
    log = gitsafe.run(root, "log", *gitsafe.NO_DRIVERS, "--format=%H%x00%B%x01", spec, timeout=120)
    if diff is None or log is None:
        raise RuntimeError(f"cannot read range {spec}")
    found, path, number = [], None, 0
    for raw in diff.decode("utf-8", "replace").splitlines():
        if raw.startswith("+++ "):
            path = raw[6:] if raw.startswith("+++ b/") else None
        elif raw.startswith("@@"):
            hunk = re.search(r"\+(\d+)", raw)
            number = int(hunk.group(1)) - 1 if hunk else 0
        elif raw.startswith("+") and path:
            number += 1
            for f in scan_text(raw[1:], path, names_re, any(fnmatch.fnmatch(path, g) for g in globs)):
                f["line"] = number
                found.append(f)
    for entry in log.decode("utf-8", "replace").split("\x01"):
        if "\x00" in entry:
            sha, body = entry.strip().split("\x00", 1)
            found += scan_text(body, f"commit {sha[:12]} message", names_re, False)
    return found


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--repo", type=Path, default=Path.cwd())
    g = p.add_mutually_exclusive_group()
    g.add_argument("--rev", default="HEAD")
    g.add_argument("--range", metavar="A..B")
    p.add_argument("--names", type=Path)
    p.add_argument("--from-gh", metavar="OWNER")
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    root = a.repo.resolve()
    if gitsafe.run(root, "rev-parse", "--git-dir") is None:
        print(f"publish_check: {root} is not a Git repository", file=sys.stderr)
        return 2
    try:
        names = load_names(a.names, a.from_gh, root.name)
        names_re, globs = name_pattern(names), allowed_globs(root, a.range.split("..")[-1] if a.range else a.rev)
        findings = scan_range(root, a.range, names_re, globs) if a.range else scan_tree(root, a.rev, names_re, globs)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"publish_check: {error}", file=sys.stderr)
        return 2
    blocking = sum(f["severity"] == "block" for f in findings)
    summary = {"schema": "code-audit.publish.v1", "repo": root.name, "scope": a.range or a.rev,
               "private_names_checked": len(names), "blocking": blocking, "warnings": len(findings) - blocking,
               "findings": findings}
    if a.json:
        print(json.dumps(summary, indent=1))
    else:
        if not names:
            print("note: no private names configured; only secrets and home paths were checked (see --help)")
        for f in sorted(findings, key=lambda f: f["severity"] != "block"):
            print(f"{f['severity']:5} {f['kind']:12} {f['where']}:{f['line']}  {f['token']}")
        print(f"{blocking} blocking, {len(findings) - blocking} warning(s); {len(names)} private name(s) checked")
    return 1 if blocking else 0


if __name__ == "__main__":
    sys.exit(main())
