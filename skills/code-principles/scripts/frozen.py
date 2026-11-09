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
# Typed constants count: Rust `pub(crate) const X: &str` / `static X: &'static str`, Go `const X string =`, Kotlin
# `const val X`, TypeScript `const X: string`. Swift names type constants in lowerCamelCase, so a Swift `static let`
# with a string value is a constant whatever its case (SWIFT_CONST_DEF, .swift files only).
CONST_DEF = re.compile(r"^\s*(?:export\s+)?(?:(?:pub(?:\([\w:]+\))?|const|let|var|val|final|static|public|private|internal|readonly)\s+)*([A-Z][A-Z0-9_]{2,})\s*(?::\s*&?(?:'static\s+)?[\w<>\[\]|. ]+|\s+string)?\s*[:=]\s*('[^'\n]{1,200}'|\"[^\"\n]{1,200}\")\s*[;,]?\s*(?:#.*|//.*)?$")
SWIFT_CONST_DEF = re.compile(r"^\s*(?:(?:public|private|fileprivate|internal|open|nonisolated)\s+)*static\s+let\s+([A-Za-z_]\w*)\s*(?::\s*String\s*)?=\s*(\"[^\"\n]{1,200}\")\s*(?://.*)?$")


def const_def(rel, line):
    """(name, quoted value) when the line defines a named string constant, else None."""
    m = CONST_DEF.match(line) or (rel.endswith(".swift") and SWIFT_CONST_DEF.match(line))
    return (m.group(1), m.group(2)) if m else None
VERSION = re.compile(r"""['"](\d+\.\d+\.\d+(?:-[\w.]+)?)['"]""")

def line_hits(rel, no, line, in_test=False, experimental=False):
    """Line-level F hits for one source line; `in_test` marks an inline test module (Rust #[cfg(test)])."""
    if in_test:
        return []
    if experimental:
        return _line_hits(rel, line) + limit_hits(rel, line)
    return _line_hits(rel, line)


def _line_hits(rel, line):
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
        n, i, kept = 0, 0, []
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
            kept.append(ch)
            raw = re.match(r'b?r(#*)"', text[i:])
            if raw and (i == 0 or not (text[i - 1].isalnum() or text[i - 1] == "_")):
                self.string_end = '"' + raw.group(1); i += len(raw.group(0)); continue
            if ch == '"': self.string_end = '"'; i += 1; continue
            if ch == "'":
                m = re.match(r"'(?:\\.|[^'\\])'", text[i:])
                if m: i += len(m.group(0)); continue
            n += {"{": 1, "}": -1}.get(ch, 0); i += 1
        self.last_code = "".join(kept).strip()  # code outside comments on this line (string bodies excluded)
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
            opened = self._braces(rest)  # also tracks comments, so an item after `*/` on the same line is seen
            code = self.last_code
            while code.startswith("#["):  # attributes on the item's line; balanced brackets
                depth, k = 0, 0
                for k, c in enumerate(code):
                    depth += {"[": 1, "]": -1}.get(c, 0)
                    if depth == 0 and k: break
                code = code[k + 1:].strip() if depth == 0 else ""
            if not code:
                return True
            if opened > 0:
                self.pending = False; self.depth = opened
            elif not self.in_string and (";" in code or "{" in code):
                self.pending = False  # a one-line item (`use ...;`, `mod x;`, `fn f() {}`) ends here
            return True
        return False


def collect_line(rel, no, line, store, in_test=False, root=None):
    """Gather cross-file data from one source line: shared-identifier constants and this package's version claims.
    Fixture files and inline test code are not sources and not copies."""
    if in_test or FIXTURE_PATH.search(rel):
        return
    d = const_def(rel, line)
    if d and IDENTIFIER_VALUE.match(d[1]) and not PROTOCOL_VALUE.match(d[1]):
        store["consts"][d[1].strip("'\"")].append((rel, no, d[0], line.strip()[:160]))
    if store.get("experimental") and not RUST_TEST_FILE.search(rel):
        collect_copies(rel, no, line, d, store)
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


def new_store(experimental=False):
    return {"consts": defaultdict(list), "self_versions": [], "version_context": {}, "server_context": {},
            "experimental": experimental, "copy_consts": defaultdict(list), "literals": defaultdict(list)}


# ---- Experimental (scan.py --experimental): inline copies of shared identifiers, and inline numeric limits. ----
# A shared value worth one owner: a key/marker (`lease_expires_at:`, `protocol:session_state=closed`), a dotted key or
# file name (`rallyd.pid`, `alerts.soundEnabled`), a path, a URL or an UPPER_SNAKE name. Plain words are left out:
# they collide with unrelated uses. Format templates and escapes are not values.
MARKER = re.compile(r"^[A-Za-z_][\w.-]*(?::[\w.=-]*)+$|^[A-Za-z_][\w.:-]*=[\w.:-]+$")
DOTTED_KEY = re.compile(r"^[A-Za-z_][\w-]*(?:\.[A-Za-z_][\w-]*)+$")
COPY_VALUE_BAD = re.compile(r"::|[{}%\\\s]|^https?:$")
STRING_LIT = re.compile(r'"((?:[^"\\\n]|\\.){4,200})"')
STRING_LIT_SQ = re.compile(r"'((?:[^'\\\n]|\\.){4,200})'")
RUST_TEST_FILE = re.compile(r"(^|/)(test_\w+|\w+_tests?)\.rs$")  # included from a `#[cfg(test)] mod x;` line elsewhere
COPY_LABEL = "copies constant"
MARKER_LABEL = "marker repeated with no constant"
MARKER_MIN_SITES = 3


def copy_value(value):
    """True for a value distinctive enough that two equal literals are one shared identifier."""
    if len(value) < 4 or COPY_VALUE_BAD.search(value) or PROTOCOL_VALUE.match(f'"{value}"'):
        return False
    return bool(MARKER.match(value) or DOTTED_KEY.match(value) or IDENTIFIER_VALUE.match(f'"{value}"'))


def code_literals(rel, line):
    """String literal values on one line, outside a trailing comment; single quotes count except in Rust/Swift/Go."""
    rx = [STRING_LIT] if rel.endswith((".rs", ".swift", ".go")) else [STRING_LIT, STRING_LIT_SQ]
    out = []
    for r in rx:
        for m in r.finditer(line):
            before = line[:m.start()]
            if "//" in before.replace("://", "") or (rel.endswith(".py") and "#" in before):
                continue
            out.append(m.group(1))
    return out


def collect_copies(rel, no, line, defined, store):
    if FIXTURE_PATH.search(rel) or NOT_A_USE.search(line):
        return
    if defined:
        value = defined[1].strip("'\"")
        if copy_value(value):
            store["copy_consts"][value].append((rel, no, defined[0]))
        return
    for value in dict.fromkeys(code_literals(rel, line)):  # a value twice on one line is one site
        if copy_value(value):
            store["literals"][value].append((rel, no, line.strip()[:160]))


def copy_hits(store):
    """F7 (experimental): a literal equal to a named constant's value, away from its definition; and a key:value marker
    used in MARKER_MIN_SITES places across at least two files with no constant anywhere in the scan."""
    hits = []
    for value, sites in store["literals"].items():
        owners = store["copy_consts"].get(value)
        if owners:
            rel0, no0, name = owners[0]
            for rel, no, text in sites:
                hits.append(("F7", f"{COPY_LABEL} {name} ({rel0}:{no0}) value `{value}` inline", rel, no, text))
        elif MARKER.match(value) and len(sites) >= MARKER_MIN_SITES and len({s[0] for s in sites}) >= 2:
            for rel, no, text in sites:
                hits.append(("F7", f"{MARKER_LABEL}: `{value}` in {len(sites)} places", rel, no, text))
    return hits


# Inline numeric limits in a decision position. N is an integer literal (Rust suffixes and `_` separators allowed).
_N = r"(\d[\d_]*)(?:u8|u16|u32|u64|u128|usize|i32|i64|isize)?(?![\w.])"
LIMIT_FORMS = [
    re.compile(r"\.take\(\s*" + _N),
    re.compile(r"\bunwrap_or\(\s*" + _N),
    re.compile(r"\.(?:min|max)\(\s*" + _N),
    re.compile(r"\.clamp\(\s*" + _N + r"\s*,\s*" + _N),
    re.compile(r"(?<![\w.])(?:Math\.)?(?:min|max)\([^()]*,\s*" + _N + r"\s*\)"),
    re.compile(r"Duration::from_(?:secs|millis|micros)\(\s*" + _N),
    re.compile(r"\bsetTimeout\([^;]*,\s*" + _N + r"\s*\)"),
    re.compile(r"\btimeout\w*\s*(?:=(?!=)|:)\s*" + _N, re.I),
    re.compile(r"\[\s*-?" + _N + r"\s*:\s*\]|\[\s*:\s*" + _N + r"\s*\]"),
    re.compile(r"<<\s*\(\s*\w+\s*-\s*" + _N),
]
UNIT = {60, 1000, 1024, 3600, 86400, 1_000_000}
NUM_CONST_LINE = re.compile(r"^\s*(?:export\s+)?(?:(?:pub(?:\([\w:]+\))?|const|let|var|val|final|static|public|private|internal|readonly)\s+)*[A-Z][A-Z0-9_]+\s*(?::[^=]+)?=")
LIMIT_LABEL = "inline numeric limit in a decision position"
# A poll or spin wait (`sleep(Duration::from_millis(10))`, `.timer(..)`) sets a cadence, not a limit: 3 of the 5 false
# positives in the first labelled sample (2026-11-09).
POLL_WAIT = re.compile(r"\bsleep\(|\.timer\(")


def _code_only(line):
    """The line with string bodies emptied and a trailing comment dropped."""
    line = re.sub(r'"(?:[^"\\]|\\.)*"', '""', line)
    line = re.sub(r"(?<![\w])'(?:[^'\\\n]|\\.)*'", "''", line)
    return re.split(r"//|(?<![\w\[])#(?!\[)", line, maxsplit=1)[0]


def limit_hits(rel, line, in_test=False):
    """F4 (experimental): one hit per line with an integer >= 2 in a decision position, not on a named-constant line."""
    if in_test or RUST_TEST_FILE.search(rel) or FIXTURE_PATH.search(rel) or CONSTANTS_PATH.search(rel) or NOT_A_USE.search(line):
        return []
    code = _code_only(line)
    if NUM_CONST_LINE.match(code) or POLL_WAIT.search(code):
        return []
    for rx in LIMIT_FORMS:
        for m in rx.finditer(code):
            for g in range(1, (m.lastindex or 0) + 1):
                raw = m.group(g)
                if raw is None:
                    continue
                n = int(raw.replace("_", ""))
                after = code[m.end(g):].lstrip()
                before = code[:m.start(g)].rstrip()
                if n < 2 or (n in UNIT and (after[:1] in "*/" or before[-1:] in "*/")):
                    continue
                return [("F4", LIMIT_LABEL)]
    return []


# Labels of the experimental rules above; their precision is recorded under `experimental` in frozen-values-precision.json.
EXPERIMENTAL_LABELS = (COPY_LABEL, MARKER_LABEL, LIMIT_LABEL)


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
    if store.get("experimental"):
        hits.extend(copy_hits(store))
    for value, defs in store["consts"].items():
        files = {d[0] for d in defs}
        if len(files) < 2:
            continue
        label = f"`{value}` is defined as a constant in {len(files)} files; a change must reach all"
        for rel, no, _, text in defs:
            if not CONSTANTS_PATH.search(rel):
                hits.append(("F7", label, rel, no, text))
    return hits
