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
TOGGLE = re.compile(r"^(?:export\s+)?(?:const\s+|let\s+|var\s+)?_?(?:[A-Z][A-Z0-9]*_)*(?:ENABLED|ENABLE|DISABLED|DISABLE|FEATURE|FLAG|USE_[A-Z][A-Z0-9_]*)\w*\s*(?::\s*\w+\s*)?=\s*(?:true|false|True|False)\s*;?\s*$")

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
# Protocol constants such as MIME types are the same everywhere by definition; they are not shared project identifiers.
PROTOCOL_VALUE = re.compile(r"^['\"](?:application|text|image|audio|video|multipart|font|message|model)/(?![\w.-]*\.[A-Za-z0-9]{2,5}['\"])[\w.+-]+['\"]$")
IDENTIFIER_VALUE = re.compile(r"^['\"](?:[\w.-]+\.[A-Za-z]{2,5}|[\w.-]*/[\w./-]+|https?://\S+|[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)['\"]$")
CONST_DEF = re.compile(r"^\s*(?:export\s+)?(?:(?:const|let|var|final|static|public|private|readonly)\s+)*([A-Z][A-Z0-9_]{2,})\s*(?::\s*[\w<>\[\]|. ]+)?\s*[:=]\s*('[^'\n]{1,200}'|\"[^\"\n]{1,200}\")\s*[;,]?\s*(?:#.*|//.*)?$")
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


class RustTestScope:
    """Tracks `#[cfg(test)]` scope: the attributed item, through the end of its block when it opens one (`mod`, `fn`,
    `impl`, ...). Comments and further attributes between the attribute and its item are skipped, and braces inside
    string and char literals are not counted."""
    LITERALS = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])\'')

    def __init__(self):
        self.pending = False; self.depth = 0; self.comment_depth = 0; self.string_end = None

    @property
    def in_comment(self):
        return self.comment_depth > 0

    @property
    def in_string(self):
        return self.string_end is not None

    def _braces(self, text):
        """Net { minus } outside comments, strings and char literals. Block comments nest, and strings (including
        raw strings r#"..."#) may span lines; that state carries to the next line."""
        n, i = 0, 0
        while i < len(text):
            ch = text[i]
            if self.comment_depth:
                if text.startswith("/*", i): self.comment_depth += 1; i += 2; continue
                if text.startswith("*/", i): self.comment_depth -= 1; i += 2; continue
                i += 1; continue
            if self.string_end is not None:
                if self.string_end == '"' and ch == "\\": i += 2; continue
                if text.startswith(self.string_end, i): i += len(self.string_end); self.string_end = None; continue
                i += 1; continue
            if text.startswith("//", i): break
            if text.startswith("/*", i): self.comment_depth = 1; i += 2; continue
            raw = re.match(r'b?r(#*)"', text[i:])
            if raw and (i == 0 or not (text[i - 1].isalnum() or text[i - 1] == "_")):
                self.string_end = '"' + raw.group(1); i += len(raw.group(0)); continue
            if ch == '"': self.string_end = '"'; i += 1; continue
            if ch == "'":
                m = re.match(r"'(?:\\.|[^'\\])'", text[i:])
                if m: i += len(m.group(0)); continue
            n += {"{": 1, "}": -1}.get(ch, 0); i += 1
        return n

    def update(self, stripped):
        """Feed one stripped line; return True when the line belongs to test-only code."""
        if self.depth:
            self.depth = max(0, self.depth + self._braces(stripped))
            return True
        rest = stripped
        if rest.startswith("#[cfg(test)]"):
            self.pending = True
            rest = rest[len("#[cfg(test)]"):].strip()
            if not rest:
                return True
        if self.pending:
            if self.in_comment or rest.startswith("/*"):
                self._braces(rest)  # keep block-comment state while waiting for the item
                return True
            if not rest or rest.startswith(("//", "#[", "*")):
                return True
            opened = self._braces(rest)
            if opened > 0:
                self.pending = False; self.depth = opened
            elif not self.in_comment and not self.in_string and (";" in rest or "{" in self.LITERALS.sub('""', rest).split("//", 1)[0]):
                self.pending = False  # a one-line item (`use ...;`, `mod x;`, `fn f() {}`) ends here
            return True
        return False


def collect_line(rel, no, line, store, in_test=False, root=None):
    """Gather cross-file data from one source line: shared-identifier constants and this package's version claims.
    Fixture files and inline test code are not sources and not copies."""
    if in_test or FIXTURE_PATH.search(rel):
        return
    m = CONST_DEF.match(line)
    if m and IDENTIFIER_VALUE.match(m.group(2)) and not PROTOCOL_VALUE.match(m.group(2)):
        store["consts"][m.group(2).strip("'\"")].append((rel, no, m.group(1), line.strip()[:160]))
    context = SELF_VERSION.search(line)
    if context:
        store["version_context"][rel] = no
        if SERVER_VERSION.search(line): store["server_context"][rel] = no
    near = no - store["version_context"].get(rel, -99) <= 4 and VERSION_KEY.search(line)
    if context or near:
        server = bool(SERVER_VERSION.search(line)) or (near and store["server_context"].get(rel) == store["version_context"].get(rel))
        if SERVER_VERSION.search(line):
            store["server_context"][rel] = no
        for v in VERSION.finditer(line):
            store["self_versions"].append((rel, no, v.group(1), line.strip()[:160], server, root))


def new_store():
    return {"consts": defaultdict(list), "self_versions": [], "version_context": {}, "server_context": {}}


# The version a CLI or server reports about itself. Script-local `__version__` values and the versions that test or
# helper clients give themselves are often independent, so only these are compared with the manifest for drift.
SERVER_VERSION = re.compile(r"\.version\(\s*['\"]|serverInfo|SERVER_INFO", re.I)
VERSION_KEY = re.compile(r"\bversion['\"]?\s*[:=]", re.I)
SELF_VERSION = re.compile(r"\.version\(\s*['\"]|__version__|\b(?:APP|SERVER|CLIENT|PACKAGE|PLUGIN|SERVICE|CLI|TOOL)_VERSION\b|\bVERSION\s*=|service\.version|clientInfo|serverInfo|CLIENT_INFO|SERVER_INFO|userAgent|User-Agent", re.I)


MANIFESTS = ("package.json", "plugin.json", ".claude-plugin/plugin.json", "pyproject.toml", "Cargo.toml")


def _manifest_versions_in(base):
    found = {}
    for name in MANIFESTS:
        try:
            text = open(os.path.join(base, name), encoding="utf-8").read()
        except OSError:
            continue
        if name.endswith(".json"):
            try:
                v = json.loads(text).get("version")
            except (ValueError, AttributeError):
                v = None
        else:
            data = _toml_tables(text)
            v = next((t.get("version") for t in (data.get("project"), data.get("package"), (data.get("tool") or {}).get("poetry")) if isinstance(t, dict) and isinstance(t.get("version"), str)), None)
        if isinstance(v, str) and re.fullmatch(r"\d+\.\d+\.\d+(?:-[\w.]+)?", v):
            found[v] = name
    return found


def _toml_tables(text):
    """[project]/[package]/[tool.poetry] tables: tomllib when available (Python 3.11+), else a section-aware scan."""
    try:
        import tomllib
        return tomllib.loads(text)
    except ModuleNotFoundError:
        pass
    except Exception:
        return {}
    data, section = {}, None
    for line in text.splitlines():
        m = re.match(r"\s*\[([\w.-]+)\]\s*$", line)
        if m:
            section = m.group(1); continue
        v = re.match(r'\s*version\s*=\s*"([^"]+)"', line)
        if v and section in ("project", "package", "tool.poetry"):
            node = data
            for part in section.split("."): node = node.setdefault(part, {})
            node.setdefault("version", v.group(1))
    return data


def nearest_manifest_versions(root, rel, cache):
    """Versions declared by the nearest directory, from the file up to the scan root, that has a package manifest:
    a nested package (for example a bundled runtime) owns its own version."""
    base = root if os.path.isdir(root) else os.path.dirname(root)
    parts = rel.split("/")[:-1]
    for depth in range(len(parts), -1, -1):
        d = os.path.join(base, *parts[:depth])
        if d not in cache:
            cache[d] = _manifest_versions_in(d)
        if cache[d]:
            return cache[d], "/".join(parts[:depth])
    return {}, ""


def cross_file_hits(store, roots):
    """F3 version claims that copy or contradict the owning manifest, and F7 shared identifiers defined in several files."""
    hits = []; cache = {}
    for rel, no, version, text, server, root in store["self_versions"]:
        root = root or (roots[0] if len(roots) == 1 else None)
        if root is None or CONSTANTS_PATH.search(rel):
            continue
        manifests, where = nearest_manifest_versions(root, rel, cache)
        if not manifests:
            continue
        name = lambda m: f"{where}/{m}" if where else m
        if version in manifests:
            hits.append(("F3", f"copies {name(manifests[version])} version {version}", rel, no, text))
        elif server:
            declared = ", ".join(f"{name(m)} {v}" for v, m in sorted(manifests.items(), key=lambda x: x[1]))
            hits.append(("F3", f"states version {version} but {declared}", rel, no, text))
    for value, defs in store["consts"].items():
        files = {d[0] for d in defs}
        if len(files) < 2:
            continue
        label = f"`{value}` is defined as a constant in {len(files)} files; a change must reach all"
        for rel, no, _, text in defs:
            if not CONSTANTS_PATH.search(rel):
                hits.append(("F7", label, rel, no, text))
    return hits
