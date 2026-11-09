#!/usr/bin/env python3
"""Print audit recon signals and the starting route as JSON (code-audit references/audit-methods.md).

  recon.py ROOT [--base REV | --paths FILE ...]

Read-only: lists files with `git ls-files` (os.walk fallback) and reads them with Python regex.
"""
import argparse, collections, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gitsafe  # noqa: E402

SKIP = {".git", "node_modules", "dist", "build", "vendor", "target", "__pycache__", ".venv", "fixtures"}
LANG = {".py": "python", ".ts": "typescript", ".tsx": "typescript", ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript",
        ".cjs": "javascript", ".rs": "rust", ".go": "go", ".swift": "swift", ".java": "java", ".kt": "kotlin", ".rb": "ruby", ".cs": "csharp"}
SERVICE = {"package.json", "pyproject.toml", "Cargo.toml", "go.mod", "Dockerfile", "Package.swift", "vercel.json", "fly.toml", "wrangler.toml"}
READ_LIMIT = 2_000_000  # characters read per file for signal detection
PATTERNS = {
    "io_conc": r"O_APPEND|appendFile|writeln!|flock|lockf|\.rename\(|os\.replace|open\([^)]*['\"]a|create_task|spawn|Promise\.all|asyncio\.gather",
    "retry": r"retry|backoff|timeout|deadline|retryable",
    "serial": r"json\.dumps|JSON\.stringify|serde|pydantic|zod|schema",
}


def git(root, *args):
    # -z gives raw NUL-separated paths; without it git quotes unusual names and they fail isfile().
    out = gitsafe.run(root, *args, "-z")
    return None if out is None else [p for p in out.decode("utf-8", "surrogateescape").split("\0") if p]


def all_files(root):
    """Return (paths, unreadable dirs). The walk fallback records directories it could not list."""
    listed = git(root, "ls-files")
    if listed is not None:
        return listed, []
    found, errors = [], []
    for d, dirs, files in os.walk(root, onerror=lambda e: errors.append(os.path.relpath(e.filename, root) + "/")):
        dirs[:] = [x for x in dirs if x not in SKIP]
        found += [os.path.relpath(os.path.join(d, f), root) for f in files]
    return found, errors


def recon(root, base=None, paths=None):
    files, walk_errors = all_files(root)
    scope = "diff" if base or paths else "repo"
    if base:
        # Tracked paths that differ from base, like `git diff --name-only`, without letting Git read the working tree.
        states = gitsafe.changed_paths(root, base)
        if states is None:
            raise SystemExit(f"recon.py: cannot diff against {base!r}")
        paths = sorted(p for p, state in states.items() if state != "untracked")
    targets, inaccessible = [], []
    for p in (paths if scope == "diff" else files):
        if set(p.split("/")) & SKIP:
            continue
        # Only a regular file inside the root is read. A link, or a path whose directory was replaced by a link
        # to somewhere else, is never followed, so nothing outside the source root is opened.
        state = gitsafe.kind(root, p)
        if state == "file":
            targets.append(p)
        elif state == "missing":
            try:
                os.lstat(os.path.join(root, p))
            except FileNotFoundError:
                continue  # deleted in the diff, or listed but gone
            except OSError:
                inaccessible.append(p)  # exists but cannot be checked: coverage gap, not absence
    langs = collections.Counter(LANG[os.path.splitext(p)[1]] for p in targets if os.path.splitext(p)[1] in LANG)
    total = sum(langs.values()) or 1
    hits = {k: 0 for k in PATTERNS}
    unreadable, truncated = list(walk_errors) + list(inaccessible), []
    for p in targets:
        try:
            with open(os.path.join(root, p), encoding="utf-8", errors="ignore") as fh:
                text = fh.read(READ_LIMIT + 1)
        except OSError:
            unreadable.append(p)
            continue
        if len(text) > READ_LIMIT:
            truncated.append(p)
        for k, pat in PATTERNS.items():
            hits[k] += bool(re.search(pat, text))
    services = {os.path.dirname(p) for p in files if os.path.basename(p) in SERVICE and not set(p.split("/")) & SKIP}
    modules = {p.split("/")[0] if "/" in p else "." for p in targets}
    s = {"scope": scope, "files": len(targets), "repo_files": len(files), "languages": dict(langs.most_common()),
         "multi_lang": sum(n / total > 0.10 for n in langs.values()) >= 2, "diff_modules": len(modules) if scope == "diff" else None,
         "services": len(services), **hits,
         "incomplete": {"unreadable": unreadable, "truncated": truncated}}
    # A zero signal only means absent when every file was read in full; otherwise keep the recipe.
    complete = not unreadable and not truncated
    recipes = [r for r, k in (("R4", "serial"), ("R5a", "io_conc"), ("R5b", "retry")) if s[k] or not complete]
    if scope == "diff" and s["files"] <= 10 and s["diff_modules"] == 1:
        route = {"row": "diff-small", "recipes": ["R1", *recipes], "lanes": "none"}
    elif scope == "diff":
        route = {"row": "diff-wide", "recipes": ["R1", *recipes], "lanes": "per module only if modules share no changed contract"}
    elif s["files"] < 200 and not s["multi_lang"]:
        route = {"row": "repo-small", "recipes": ["R1", "R2", "R3", *recipes], "lanes": "none"}
    else:
        route = {"row": "repo-large", "recipes": ["R1", "R2", "R3", *recipes], "lanes": "phase A by dimension, phase B by module"}
    if s["services"] >= 2:
        route["contract_lane"] = True
    return {"root": os.path.abspath(root), "signals": s, "route": route}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("root")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--base", help="diff scope: files changed since this revision")
    g.add_argument("--paths", nargs="+", help="diff scope: these repo-relative files")
    a = ap.parse_args(argv)
    if not os.path.isdir(a.root):
        print(f"recon.py: no such directory: {a.root}", file=sys.stderr)
        return 2
    print(json.dumps(recon(a.root, a.base, a.paths), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
