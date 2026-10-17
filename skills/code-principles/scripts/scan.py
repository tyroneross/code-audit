#!/usr/bin/env python3
"""List code signals that map to code-principles checklist items.

Usage: scan.py PATH [PATH ...] [--json] [--max-hits N]

Each hit is a place to look, not a defect. Read-only: never executes scanned code.
"""
import argparse
import json
import os
import re
import sys
from collections import defaultdict

SKIP_DIRS = {
    ".git", "node_modules", "dist", "build", "out", ".next", "vendor", "target",
    "__pycache__", ".venv", "venv", ".tox", ".mypy_cache", ".pytest_cache",
    ".rally", ".build-loop", ".bookmark", ".code-principles", "coverage",
}
CODE_EXT = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".go", ".rs", ".java",
    ".kt", ".swift", ".rb", ".cs", ".php", ".scala",
}
MAX_FILE_BYTES = 2_000_000
LOOKAHEAD = 10  # lines checked for a timeout/limit set in a multi-line call
LOOKAHEAD_ITEMS = {"B2", "B5", "B7"}
TEST_PATH = re.compile(r"(^|/)(tests?|__tests__|fixtures?|spec|e2e)(/|$)|\.(test|spec)\.\w+$|(^|/)test_\w+\.py$|_test\.(py|go)$")

# Report order: untrusted input and security first, then load, then speed, then hygiene.
PRIORITY = ["D6", "B7", "C1", "A1", "A6", "A2", "B2", "B5", "A5", "B1", "B6", "B3", "C2", "C5", "A3", "A4"]

SECTIONS = {
    "A": "Speed and efficiency",
    "B": "Scale and load",
    "C": "Failure handling",
    "D": "Contract gate",
}

# (item, label, compiled regex, optional "unless" regex on the same line)
LINE_RULES = [
    ("A5", "sync blocking call", re.compile(r"\b(readFileSync|writeFileSync|execSync|spawnSync|inflateSync|inflateRawSync|gunzipSync|unzipSync)\s*\("), None),
    ("A6", "subresource loading", re.compile(r"resources\s*:\s*['\"]usable['\"]"), None),
    ("B1", "queue without size limit", re.compile(r"(asyncio\.Queue|queue\.Queue|LinkedBlockingQueue|ArrayDeque)\s*\(\s*\)"), None),
    ("B2", "HTTP call without visible timeout", re.compile(r"\brequests\.(get|post|put|patch|delete|request)\s*\(|\bhttpx\.(get|post|put|patch|delete)\s*\(|\burlopen\s*\("), re.compile(r"timeout\s*=")),
    ("B2", "fetch without visible abort/timeout", re.compile(r"(?<![\w.])fetch\s*\(\s*(?![`'\"]/)"), re.compile(r"signal|timeout|AbortSignal")),
    ("B3", "retry loop or wrapper", re.compile(r"for\s+\w+\s+in\s+range\(\s*\w*(retr|attempt)\w*|for\s*\(\s*(let|var)\s+\w*attempt\w*|@retry\b|\bretry\s*\(|\bwithRetry\s*\(|\bpRetry\s*\(|\btenacity\.|\bbackoff\.\w+\s*\(|while\s*\(?\s*\w*(attempt|retr)\w*\s*<", re.I), None),
    ("B5", "fan-out without visible limit", re.compile(r"\bPromise\.(all|allSettled)\s*\(|\basyncio\.gather\s*\(|\berrgroup\.|\bjoin_all\s*\("), re.compile(r"pLimit|p-limit|limit\(|Semaphore|semaphore|chunk")),
    ("B6", "map/dict used as cache", re.compile(r"\b\w*cache\w*\s*(:\s*\w[^=]*)?=\s*(new Map\s*\(|\{\s*\}|dict\s*\(\s*\)|\[\s*\])", re.I), re.compile(r"LRU|lru|ttl|TTL|maxsize|max_size")),
    ("B7", "decompression", re.compile(r"\b(inflate|inflateRaw|gunzip|unzip|decompress)(Sync)?\s*\(|zlib\.decompress|gzip\.decompress|ZipFile\s*\("), re.compile(r"maxOutputLength|max_length")),
    ("B7", "reads whole upload/body", re.compile(r"\.arrayBuffer\s*\(\s*\)|request\.body\.read\s*\(\s*\)|await\s+req\.text\s*\(\s*\)"), None),
    ("C1", "empty or log-only handler", re.compile(r"except(\s+\w[\w.,() ]*)?\s*:\s*(pass|\.\.\.)\s*$|catch\s*(\([^)]*\))?\s*\{\s*\}"), None),
    ("C1", "TODO in error path", re.compile(r"(catch|except).*(TODO|FIXME)|(TODO|FIXME).*(error|exception|catch)", re.I), None),
    ("C2", "broad catch", re.compile(r"except\s*:\s*$|except\s+(Exception|BaseException)\b|catch\s*\(\s*(e|err|error)\s*:\s*any\s*\)"), None),
    ("C5", "fire-and-forget task", re.compile(r"asyncio\.create_task\s*\(|ensure_future\s*\(|\bgo\s+func\b|tokio::spawn\s*\(|setTimeout\s*\(\s*async"), re.compile(r"=\s*(asyncio\.create_task|ensure_future|tokio::spawn)")),
    ("D6", "external name used in a path", re.compile(r"(join|resolve|open|writeFile\w*)\s*\(.*\b(file\.name|filename|originalname|file_name|upload\w*\.name)\b"), re.compile(r"basename|secure_filename|randomUUID|uuid")),
]

PARSE_CALL = re.compile(r"\b(cheerio\.load|new\s+JSDOM|JSDOM\s*\(|JSON\.parse|json\.loads|BeautifulSoup|parseFromString|xml\.etree\.ElementTree\.fromstring|yaml\.safe_load)\s*\(")
LOOP_START = re.compile(r"^\s*(for\b|while\b|async\s+for\b)|\.(forEach|map)\s*\(\s*(async\s*)?\(")
IO_CALL = re.compile(r"\b(fetch|axios\.\w+|requests\.\w+|httpx\.\w+|\.query|\.execute|\.findOne|\.findUnique|\.find\b|\.get\(|readFile|open)\s*\(")
AWAIT = re.compile(r"\bawait\b")
DEF = re.compile(r"^\s*(?:export\s+)?(?:(?:async|private|public|protected|static|override)\s+)*(?:function\s+|def\s+|fn\s+|func\s+)?(\w+)\s*(?:<[^>]*>)?\s*\((?:[^)]*\)[^;=]*?(?:\{|:)|[^)]*)\s*$")
FETCHY = re.compile(r"(?<![\w.])fetch\s*\(|\baxios\b|\brequests\.\w+\s*\(|\bhttpx\.|\burlopen\s*\(|\bhttps?\.get\s*\(|\breadFile\w*\s*\(|\.query\s*\(|\.execute\s*\(")
CALL = re.compile(r"(?:this\.|self\.)?(\w+)\s*\(\s*([A-Za-z_][\w.]*)\s*[,)]")
PREFIX_RESCAN = re.compile(r"\.(substring|slice|substr)\(\s*0\s*,|\[\s*:\s*\w+\.(start|index)|\[\s*0\s*:\s*\w+\.(start|index)")
KEYWORDS = {"if", "for", "while", "switch", "catch", "return", "function", "constructor", "with", "elif", "else"}
SAME_INPUT_WINDOW = 25


def call_window(lines, start):
    """Text of the statement starting at lines[start], until its brackets close."""
    depth, out = 0, []
    for line in lines[start:start + LOOKAHEAD]:
        out.append(line)
        depth += sum(line.count(c) for c in "([{") - sum(line.count(c) for c in ")]}")
        if depth <= 0:
            break
    return "\n".join(out)


def indent(line):
    return len(line) - len(line.lstrip(" \t"))


def scan_file(path, rel, skipped):
    try:
        if os.path.getsize(path) > MAX_FILE_BYTES:
            skipped.append((rel, "larger than 2 MB"))
            return None
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except UnicodeDecodeError:
        skipped.append((rel, "not UTF-8"))
        return None
    except OSError as e:
        skipped.append((rel, e.strerror or "unreadable"))
        return None
    hits = []
    parse_lines = []
    loop_stack = []  # (indent, line_no)
    for no, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "//", "*", "/*")):
            continue
        ind = indent(line)
        while loop_stack and ind <= loop_stack[-1][0] and not stripped.startswith(("}", ")", "]")):
            loop_stack.pop()
        in_loop = bool(loop_stack)
        for item, label, rx, unless in LINE_RULES:
            if not rx.search(line):
                continue
            window = call_window(lines, no - 1) if item in LOOKAHEAD_ITEMS else line
            if unless and unless.search(window):
                continue
            hits.append((item, label, rel, no, stripped[:160]))
        if PARSE_CALL.search(line):
            parse_lines.append((no, stripped[:160]))
        if in_loop and IO_CALL.search(line):
            hits.append(("A2", "I/O or query inside a loop", rel, no, stripped[:160]))
        if in_loop and PREFIX_RESCAN.search(line):
            hits.append(("A4", "re-scans input from the start inside a loop", rel, no, stripped[:160]))
        if in_loop and AWAIT.search(line):
            hits.append(("A3", "await inside a loop", rel, no, stripped[:160]))
        if LOOP_START.search(line):
            loop_stack.append((ind, no))
    if len(parse_lines) >= 2:
        for no, text in parse_lines:
            hits.append(("A1", f"one of {len(parse_lines)} parse calls in this file", rel, no, text))
    same = same_input_fetches(lines)
    if same:
        flagged = {no for no, _ in same}
        hits = [h for h in hits if not (h[0] == "A3" and h[3] in flagged)]
        for no, label in same:
            hits.append(("A1", label, rel, no, lines[no - 1].strip()[:160]))
    return hits


def function_bodies(lines):
    """(name, start, end) for each function-like definition, using indentation."""
    defs = []
    for i, line in enumerate(lines):
        m = DEF.match(line)
        if m and m.group(1) not in KEYWORDS:
            defs.append((m.group(1), i, indent(line)))
    out = []
    for j, (name, start, ind) in enumerate(defs):
        end = len(lines)
        for k in range(start + 1, len(lines)):
            s = lines[k].strip()
            if s and indent(lines[k]) <= ind and not s.startswith((")", "]")):
                end = k + (1 if s.startswith("}") else 0)
                break
        out.append((name, start, end))
    return out


def same_input_fetches(lines):
    """Lines where one input is passed to two different helpers that each do I/O."""
    bodies = function_bodies(lines)
    fetchers = {n for n, s, e in bodies if any(FETCHY.search(l) for l in lines[s + 1:e])}
    for _ in range(3):  # helpers that call helpers that fetch
        grown = {n for n, s, e in bodies if n not in fetchers and any(
            c.group(1) in fetchers for l in lines[s + 1:e] for c in CALL.finditer(l))}
        if not grown:
            break
        fetchers |= grown
    found = []
    for name, s, e in bodies:
        calls = []
        for i in range(s + 1, e):
            if lines[i].lstrip().startswith("return "):
                continue  # an early-return fallback is an alternative path, not a second fetch
            text = lines[i]
            if text.rstrip().endswith("(") and i + 1 < len(lines):
                text = text.rstrip() + lines[i + 1].strip()  # argument on the next line
            for c in CALL.finditer(text):
                if c.group(1) in fetchers and c.group(1) != name:
                    calls.append((i + 1, c.group(1), c.group(2)))
        for a in range(len(calls)):
            for b in range(a + 1, len(calls)):
                (la, fa, xa), (lb, fb, xb) = calls[a], calls[b]
                if xa == xb and fa != fb and lb - la <= SAME_INPUT_WINDOW:
                    label = f"same input `{xa}` goes to two fetching helpers ({fa}, {fb})"
                    found += [(la, label), (lb, label)]
    return sorted(set(found))


def iter_files(paths, include_tests=False, skipped=None):
    def on_error(err):
        if skipped is not None:
            skipped.append((err.filename, f"directory not readable: {err.strerror}"))
    for root in paths:
        if os.path.isfile(root):
            yield root, os.path.basename(root)
            continue
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False, onerror=on_error):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not os.path.islink(os.path.join(dirpath, d)))
            for name in sorted(filenames):
                full = os.path.join(dirpath, name)
                rel = os.path.relpath(full, root)
                if os.path.splitext(name)[1] in CODE_EXT and not os.path.islink(full) and (include_tests or not TEST_PATH.search(rel)):
                    yield full, rel


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--include-tests", action="store_true", help="also scan test and fixture files")
    ap.add_argument("--max-hits", type=int, default=5, help="hits shown per item in text output")
    args = ap.parse_args(argv)
    for p in args.paths:
        if not os.path.exists(p):
            print(f"scan.py: no such path: {p}", file=sys.stderr)
            return 2
    hits, files, skipped = [], 0, []
    for full, rel in iter_files(args.paths, args.include_tests, skipped):
        found = scan_file(full, rel, skipped)
        if found is not None:
            files += 1
            hits.extend(found)
    by_item = defaultdict(list)
    for h in hits:
        by_item[h[0]].append(h)
    if args.json:
        json.dump({"files_scanned": files, "skipped": [{"path": p, "reason": r} for p, r in skipped], "items": {k: [{"label": l, "file": f, "line": n, "text": t} for _, l, f, n, t in v] for k, v in sorted(by_item.items())}}, sys.stdout, indent=1)
        print()
        return 0
    print(f"Scanned {files} files. Read checklist sections: " + (", ".join(f"{s} {SECTIONS[s]}" for s in sorted({k[0] for k in by_item})) or "none matched"))
    print("Always apply section D before shipping a fast path, and section E to the change itself.")
    if skipped:
        print(f"NOT SCANNED ({len(skipped)}): " + "; ".join(f"{p} ({r})" for p, r in skipped[:10]) + (" …" if len(skipped) > 10 else ""))
    order = sorted(by_item, key=lambda i: (PRIORITY.index(i) if i in PRIORITY else len(PRIORITY), i))
    for item in order:
        rows = by_item[item]
        print(f"\n{item} ({len(rows)} hits)")
        rows = sorted(rows, key=lambda h: "fetching helpers" not in h[1])
        for _, label, f, n, text in rows[: args.max_hits]:
            print(f"  {f}:{n}  [{label}]  {text}")
        if len(rows) > args.max_hits:
            print(f"  … {len(rows) - args.max_hits} more (use --json for all)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
