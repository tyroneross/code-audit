"""Signals for checklist section F: frozen values that should be dynamic.

A hit is a place to look, not a defect. The question for F is "does this value have a source of truth, or vary by
context, while being frozen in code?", not "is this a literal". Protocol and policy constants are often correct, and a
model ID or date may encode facts newer than the reviewer's knowledge: confirm against the live source before calling
it wrong. Section G (path length) has no scanner signal: pass-through and single-implementation detectors were
measured and cut for low precision (references/frozen-values-and-path-length.md). Used by scan.py; read-only.
"""
import json
import os
import re
from collections import defaultdict

# Files that are the intended home of constants or configuration; their definitions are sources, not copies.
CONSTANTS_PATH = re.compile(r"(^|/)(constants?|consts|config|configs|settings|defaults?|env|environment|flags|models?_?(registry|catalog|taxonomy)?)(\.[\w-]+)?\.\w+$|(^|/)(config|settings|constants)/", re.I)
# A value read from the environment or configuration on the same line: the literal is a fallback, not the source.
READS_SOURCE = re.compile(r"process\.env|import\.meta\.env|os\.environ|os\.getenv|getenv\(|Deno\.env|env::var|ENV\[|\bconfig\.|\bsettings\.|\?\?|\|\||\bor\b\s*['\"]|\.get\(\s*['\"][A-Z_]+['\"]")

HOME_PATH = re.compile(r"['\"`](/Users/[^/'\"`\s$]+|/home/[^/'\"`\s$]+|[A-Za-z]:\\\\Users\\\\)")
ENV_HOST = re.compile(
    r"['\"`]https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\]|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(?:1[6-9]|2\d|3[01])\.\d+\.\d+)"
    r"|['\"`]https?://[\w.-]+\.(?:vercel\.app|netlify\.app|railway\.app|up\.railway\.app|herokuapp\.com|onrender\.com|ngrok(?:-free)?\.(?:io|app|dev)|fly\.dev|pages\.dev|workers\.dev|supabase\.co)\b")
ACCOUNT_ID = re.compile(r"arn:aws:[\w-]*:[\w-]*:\d{12}:")
YEAR_LOGIC = re.compile(r"\byear\b\s*(?:===?|[<>]=?)\s*20\d\d\b|\b20\d\d\s*(?:===?|[<>]=?)\s*\w*[yY]ear\b")
TOGGLE = re.compile(r"^(?:export\s+)?(?:const\s+|let\s+|var\s+)?_?[A-Z][A-Z0-9_]*(?:ENABLED|ENABLE|DISABLED|DISABLE|FEATURE|FLAG|USE_[A-Z][A-Z0-9_]*)\w*\s*(?::\s*\w+\s*)?=\s*(?:true|false|True|False)\s*;?\s*$")

# Lines that describe, detect or exemplify a value rather than use it: patterns, examples, assertions, deny lists.
NOT_A_USE = re.compile(r"/Users/\[|/home/\[|\bTextField\(|\bassert|\bexample\b|e\.g\.|\bplaceholder\s*[:=]|\bfictional\b|\bforbidden\b|\bdeny\b|re\.(?:compile|match|search|fullmatch|sub|findall)\(|RegExp|\bregex\b|_p\(r?['\"]|description\s*[:=]")
PLACEHOLDER_USER = re.compile(r"/(?:Users|home)/(?:\.\.\.|example|you|user|username|me|name|alice|bob|jdoe|john|jane|dev|devuser|runner|<[^>]*>|\$\{?\w+\}?)(?:/|['\"`])")
# A URL to a server this code just started on a local port is not an environment-specific host.
# `new URL(req.url, "http://localhost")` only supplies a parse base for a relative request path.
PARSE_BASE = re.compile(r"new URL\(\s*[\w.!]+\s*,\s*['\"`]https?://(?:localhost|127\.0\.0\.1)/?['\"`]")
OWN_SERVER = re.compile(r"(?:localhost|127\.0\.0\.1|0\.0\.0\.0):(?:\$\{|\{|\\\(|['\"`]\s*\+|%)")
FIXTURE_PATH = re.compile(r"(^|/)(fixtures?|examples?|samples?|mocks?|testdata)(/|\.|_)", re.I)

LINE_RULES = [
    # (item, label, regex, applies in constants files)
    ("F1", "home or machine-specific absolute path", HOME_PATH, True),
    ("F2", "environment-specific host in code", ENV_HOST, False),
    ("F5", "cloud account ID in code", ACCOUNT_ID, False),
    ("F5", "year frozen into logic", YEAR_LOGIC, True),
    ("F6", "feature toggle fixed in code", TOGGLE, False),
]

# Shared identifiers that must match exactly wherever they appear: file names, paths, keys, URLs, env-var names.
IDENTIFIER_VALUE = re.compile(r"^['\"](?:[\w.-]+\.[A-Za-z]{2,5}|[\w.-]*/[\w./-]+|https?://\S+|[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)['\"]$")
CONST_DEF = re.compile(r"^\s*(?:export\s+)?(?:(?:const|let|var|final|static|public|private|readonly)\s+)*([A-Z][A-Z0-9_]{2,})\s*(?::\s*[\w<>\[\]|. ]+)?\s*[:=]\s*(-?\d[\d_.]*\b|'[^'\n]{1,200}'|\"[^\"\n]{1,200}\")\s*[;,]?\s*(?:#.*|//.*)?$")
TRIVIAL = {"0", "1", "-1", "2", "''", '""', "'utf-8'", '"utf-8"', "'utf8'", '"utf8"', "True", "False"}
VERSION = re.compile(r"""['"](\d+\.\d+\.\d+(?:-[\w.]+)?)['"]""")

def line_hits(rel, no, line, in_test=False):
    """Line-level F hits for one source line; `in_test` marks an inline test module (Rust #[cfg(test)])."""
    if in_test:
        return []
    in_constants = bool(CONSTANTS_PATH.search(rel))
    if FIXTURE_PATH.search(rel) or NOT_A_USE.search(line):
        return []
    out = []
    for item, label, rx, everywhere in LINE_RULES:
        if not rx.search(line) or (in_constants and not everywhere):
            continue
        if item in ("F2", "F5") and READS_SOURCE.search(line):
            continue
        if item == "F1" and PLACEHOLDER_USER.search(line):
            continue
        if item == "F2" and (OWN_SERVER.search(line) or PARSE_BASE.search(line)):
            continue
        out.append((item, label))
    return out


def collect(rel, lines, store):
    """Gather cross-file data: shared-identifier constant definitions and version literals."""
    for no, line in enumerate(lines, 1):
        m = CONST_DEF.match(line)
        if m and m.group(2) not in TRIVIAL and IDENTIFIER_VALUE.match(m.group(2)):
            store["consts"][m.group(2).strip("'\"")].append((rel, no, m.group(1), line.strip()[:160]))
        for v in VERSION.finditer(line):
            store["versions"][v.group(1)].append((rel, no, line.strip()[:160]))


def new_store():
    return {"consts": defaultdict(list), "versions": defaultdict(list)}


SELF_VERSION = re.compile(r"__version__|\b(?:APP|SERVER|CLIENT|PACKAGE|PLUGIN|SERVICE|CLI|TOOL)_VERSION\b|\bVERSION\s*=|service\.version|clientInfo|serverInfo|CLIENT_INFO|SERVER_INFO|userAgent|User-Agent", re.I)


def manifest_versions(roots):
    """Versions declared by package manifests at the scan roots: the source of truth a code literal may copy."""
    found = {}
    for root in roots:
        base = root if os.path.isdir(root) else os.path.dirname(root)
        for name in ("package.json", "plugin.json", ".claude-plugin/plugin.json", "pyproject.toml", "Cargo.toml"):
            path = os.path.join(base, name)
            try:
                text = open(path, encoding="utf-8").read()
            except OSError:
                continue
            if name.endswith(".json"):
                try:
                    v = json.loads(text).get("version")
                except ValueError:
                    v = None
            else:
                m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
                v = m.group(1) if m else None
            if isinstance(v, str) and re.fullmatch(r"\d+\.\d+\.\d+(?:-[\w.]+)?", v):
                found[v] = name
    return found


def cross_file_hits(store, roots):
    """F3 copied manifest version and F7 shared identifiers defined in several files."""
    hits = []
    for version, manifest in manifest_versions(roots).items():
        for rel, no, text in store["versions"].get(version, []):
            if not CONSTANTS_PATH.search(rel) and SELF_VERSION.search(text):
                hits.append(("F3", f"copies {manifest} version {version}", rel, no, text))
    for value, defs in store["consts"].items():
        files = {d[0] for d in defs}
        if len(files) < 2:
            continue
        label = f"`{value}` is defined as a constant in {len(files)} files; a change must reach all"
        for rel, no, _, text in defs:
            if not CONSTANTS_PATH.search(rel):
                hits.append(("F7", label, rel, no, text))
    return hits
