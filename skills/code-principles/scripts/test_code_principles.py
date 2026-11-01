import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import outcome  # noqa: E402
import scan  # noqa: E402

TS_SOURCE = """\
import { join } from 'path'
export async function crawl(urls: string[], file: File) {
  for (const u of urls) {
    const page = await fetch(u)
  }
  const ok = await fetch(url, {
    headers: {},
    signal: AbortSignal.timeout(5000),
  })
  const $ = cheerio.load(html)
  const dom = new JSDOM(html)
  const all = await Promise.all(urls.map(get))
  const out = zlib.inflateSync(buf)
  const capped = zlib.inflateSync(buf, { maxOutputLength: 1 << 20 })
  const tempPath = join(dir, `${Date.now()}-${file.name}`)
  const safePath = join(dir, basename(file.name))
  try { run() } catch (e) {}
}
"""

PY_SOURCE = """\
import asyncio, requests
q = asyncio.Queue()
bounded = asyncio.Queue(maxsize=100)
r = requests.get(url)
r2 = requests.get(url, timeout=5)
try:
    work()
except Exception:
    pass
"""


def run_scan(paths, *extra):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = scan.main([*paths, "--json", *extra])
    return code, json.loads(buf.getvalue())


def lines(result, item):
    return sorted(h["line"] for h in result["items"].get(item, []))


class ScanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "src").mkdir()
        (self.root / "src" / "crawl.ts").write_text(TS_SOURCE)
        (self.root / "src" / "worker.py").write_text(PY_SOURCE)

    def tearDown(self):
        self.tmp.cleanup()

    def test_planted_signals_are_found_and_safe_variants_are_not(self):
        code, r = run_scan([str(self.root)])
        self.assertEqual(code, 0)
        self.assertEqual(lines(r, "A3"), [4])                # await in loop
        self.assertIn(4, lines(r, "A2"))                     # fetch in loop
        self.assertEqual(lines(r, "A1"), [10, 11])           # two parses in one file
        self.assertEqual(lines(r, "B5"), [12])               # unbounded Promise.all
        self.assertEqual(lines(r, "B7"), [13])               # uncapped inflate only
        self.assertEqual(lines(r, "D6"), [15])               # raw upload name, not basename
        self.assertIn(17, lines(r, "C1"))                    # empty catch
        py = [h for h in r["items"]["B1"] if h["file"].endswith("worker.py")]
        self.assertEqual([h["line"] for h in py], [2])       # unbounded queue only
        b2 = sorted((h["file"], h["line"]) for h in r["items"]["B2"])
        self.assertEqual(b2, [("src/crawl.ts", 4), ("src/worker.py", 4)])  # multi-line signal is seen
        self.assertEqual(lines(r, "C2"), [8])

    def test_skips_tests_vendored_and_symlinked_code_by_default(self):
        (self.root / "tests").mkdir()
        (self.root / "tests" / "t.py").write_text(PY_SOURCE)
        (self.root / "node_modules").mkdir()
        (self.root / "node_modules" / "x.ts").write_text(TS_SOURCE)
        os.symlink(self.root / "src", self.root / "linked")
        _, r = run_scan([str(self.root)])
        files = {h["file"] for v in r["items"].values() for h in v}
        self.assertEqual(files, {"src/crawl.ts", "src/worker.py"})
        _, r2 = run_scan([str(self.root)], "--include-tests")
        files2 = {h["file"] for v in r2["items"].values() for h in v}
        self.assertIn("tests/t.py", files2)

    def test_retry_signal_ignores_declarations_and_output_puts_security_first(self):
        (self.root / "src" / "cfg.ts").write_text("interface O { maxRetries: number }\nconst MAX_RETRIES = 3\nawait withRetry(() => call())\n")
        (self.root / "src" / "loop.py").write_text("for attempt in range(retries):\n    call()\n")
        _, r = run_scan([str(self.root)])
        b3 = sorted((h["file"], h["line"]) for h in r["items"]["B3"])
        self.assertEqual(b3, [("src/cfg.ts", 3), ("src/loop.py", 1)])
        buf = io.StringIO()
        with redirect_stdout(buf):
            scan.main([str(self.root)])
        heads = [l.split()[0] for l in buf.getvalue().splitlines() if l and l[0] in "ABCDE" and "hits)" in l]
        self.assertEqual(heads[:2], ["D6", "B7"])

    def test_same_input_to_two_fetching_helpers_and_prefix_rescan(self):
        (self.root / "src" / "pages.ts").write_text("""\
class S {
  async run(urls: string[]) {
    for (const currentUrl of urls) {
      const items = await this.links(currentUrl)
      const next = await this.nextPages(
        currentUrl,
      )
    }
  }
  async fallback(url: string) {
    const html = await this.load(url)
    if (!html) {
      return await this.viaApi(url)
    }
  }
  private async links(u: string) {
    return this.load(u)
  }
  private async nextPages(
    u: string,
  ): Promise<string[]> {
    const html = await this.load(u)
    return []
  }
  private async load(u: string) {
    const r = await fetch(u)
    return r.text()
  }
  private async viaApi(u: string) {
    return fetch('https://api.example.com/x?u=' + u)
  }
}
""")
        (self.root / "src" / "lines.ts").write_text("let m\nwhile ((m = re.exec(src)) !== null) {\n  const line = src.substring(0, m.index).split('\\n').length\n}\n")
        _, r = run_scan([str(self.root)])
        cross = sorted((h["file"], h["line"]) for h in r["items"]["A1"] if "fetching helpers" in h["label"])
        self.assertEqual(cross, [("src/pages.ts", 4), ("src/pages.ts", 5)])   # not the return-fallback at 13
        self.assertNotIn(("src/pages.ts", 4), {(h["file"], h["line"]) for h in r["items"].get("A3", [])})
        self.assertEqual([(h["file"], h["line"]) for h in r["items"]["A4"]], [("src/lines.ts", 3)])

    def test_frozen_values_are_found_and_sources_examples_and_tests_are_not(self):
        files = {
            "pyproject.toml": '[project]\nname = "demo"\nversion = "1.2.3"\n',
            "app.py": "\n".join([
                'CORPUS = "/Users/alice2/dev/corpus"',            # F1: machine-specific path
                'EXAMPLE = "/Users/example/dev/x"',                # placeholder user
                'PATTERN = re.compile(r"/Users/[a-z]+/")',        # a detector, not a use
                'OLLAMA = "http://localhost:11434"',               # F2
                'url = f"http://127.0.0.1:{port}/x"',              # a server this code started
                'base = os.environ.get("BASE", "http://localhost:3000")',  # env read with fallback
                '_DISK_CACHE_ENABLED = False',                     # F7
                '__version__ = "1.2.3"',                           # F3: copies pyproject
                'LOCK_NAME = "projects.json.lock"',                # F8 with web/lock.ts
                'MAX_ITEMS = 5',                                   # numeric limits are not shared identifiers
            ]) + "\n",
            "web/lock.ts": "export const REGISTRY_LOCK = 'projects.json.lock';\nconst MAX_ITEMS = 5;\nconst u = new URL(req.url, 'http://localhost');\n",
            "config/settings.py": 'OLLAMA = "http://localhost:11434"\n',
            "src/lib.rs": 'fn a() {}\n#[cfg(test)]\nmod tests {\n    const P: &str = "/Users/real/x";\n}\n',
            "tests/test_x.py": 'P = "/Users/real/x"\n',
        }
        with tempfile.TemporaryDirectory() as d:
            for rel, text in files.items():
                path = Path(d, rel); path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text)
            _, out = run_scan([d])
        self.assertEqual([(h["file"], h["line"]) for h in out["items"]["F1"]], [("app.py", 1)])
        self.assertEqual([(h["file"], h["line"]) for h in out["items"]["F2"]], [("app.py", 4)])
        self.assertEqual([(h["file"], h["line"]) for h in out["items"]["F6"]], [("app.py", 7)])
        self.assertEqual([(h["file"], h["line"]) for h in out["items"]["F3"]], [("app.py", 8)])
        # app.py:4 copies the URL that config/settings.py owns; the config file itself is not flagged.
        self.assertEqual(sorted((h["file"], h["line"]) for h in out["items"]["F7"]), [("app.py", 4), ("app.py", 9), ("web/lock.ts", 1)])
        self.assertEqual(set(out["items"]) & {"F4", "F5", "G1", "G2"}, set())

    def test_frozen_value_review_fixes(self):
        files = {
            "package.json": '{"name": "demo", "version": "1.2.3"}',
            "src/cli.ts": "program\n  .name('demo')\n  .version('0.8.0');\nconst SERVER_INFO = {\n  name: 'demo',\n  version: '1.2.3',\n};\n",
            "src/latest/api.ts": "const BASE = 'http://localhost:3000';\n",            # source, not tests
            "lib/cache.py": "USE_CACHE = True\nCONTENT_TYPE = 'application/json'\n",
            "lib/other.py": "CONTENT_TYPE = 'application/json'\nLOCK = 'state.lock'\n",
            "samples/demo.py": "LOCK = 'state.lock'\n",                               # fixture, not a copy
            "src/lib.rs": '#[cfg(test)]\nuse helper::x;\nconst ROOT: &str = "/Users/realuser/data";\n#[cfg(test)]\nmod tests {\n    const P: &str = "/Users/other/x";\n}\nconst AFTER: &str = "/Users/realuser/after";\n',
        }
        with tempfile.TemporaryDirectory() as d:
            for rel, text in files.items():
                path = Path(d, rel); path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text)
            _, out = run_scan([d])
        f3 = {(h["file"], h["line"]): h["label"] for h in out["items"]["F3"]}
        self.assertIn("states version 0.8.0", f3[("src/cli.ts", 3)])      # a drifted copy is the consequential case
        self.assertIn("copies package.json version 1.2.3", f3[("src/cli.ts", 6)])
        self.assertEqual([(h["file"], h["line"]) for h in out["items"]["F2"]], [("src/latest/api.ts", 1)])
        self.assertEqual([(h["file"], h["line"]) for h in out["items"]["F6"]], [("lib/cache.py", 1)])
        self.assertNotIn("F7", out["items"])                               # MIME type and fixture copy are not shared identifiers
        self.assertEqual(sorted(h["line"] for h in out["items"]["F1"]), [3, 8])   # only the test module and the attributed item are skipped

    def test_rust_test_scope_and_multiple_roots(self):
        rust = "\n".join([
            '#[cfg(test)]', 'fn helper() {', '    let p = "/Users/one/x";', '}',             # body of an attributed fn: test-only
            '#[cfg(test)] mod inline {', '    const P: &str = "/Users/two/x";', '}',      # attribute on the item's own line
            '#[cfg(test)]', '// comment', 'mod commented {', '    const S: &str = "{";', '    const P: &str = "/Users/three/x";', '}',
            '#[cfg(test)]', 'fn wrapped(', '    a: u8,', ') {', '    let p = "/Users/four/x";', '}',  # rustfmt-wrapped signature
            '#[cfg(test)]', 'mod urls {', '    fn u() -> &\'static str { "https://x" }', '    /* { */', '    /*', '    { */', '    let s = "', '    {";', '}',   # braces in strings and comments, single- and multi-line
            'const REAL: &str = "/Users/realuser/data";',                                  # production code after the tests
        ]) + "\n"
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            Path(a, "lib.rs").write_text(rust)
            Path(b, "package.json").write_text('{"version": "2.0.0"}'); Path(b, "cli.ts").write_text("program.version('1.0.0');\n")
            with tempfile.TemporaryDirectory() as c:  # same relative path, correct version: must not borrow b's manifest
                Path(c, "package.json").write_text('{"version": "1.0.0"}'); Path(c, "cli.ts").write_text("program.version('1.0.0');\n")
                Path(c, "pyproject.toml").write_text('[tool.other]\nversion = "9.9.9"\n[project]\nname = "x"\n')
                Path(c, "consts.py").write_text("LOGO = 'image/logo.svg'\n"); Path(a, "img.py").write_text("LOGO = 'image/logo.svg'\n")
                _, out = run_scan([a, b, c])
        self.assertEqual([(h["file"], h["line"]) for h in out["items"]["F1"]], [("lib.rs", 29)])
        self.assertEqual(sorted(h["label"] for h in out["items"]["F3"]), ["copies package.json version 1.0.0", "states version 1.0.0 but package.json 2.0.0"])
        # a shared file path that merely starts like a MIME type; consts.py owns it, so only the copy is flagged
        self.assertEqual([(h["file"], h["line"]) for h in out["items"]["F7"]], [("img.py", 1)])

    def test_unreadable_input_is_reported_not_counted(self):
        (self.root / "src" / "bad.ts").write_bytes(b"\xff\xfe fetch(u)")
        locked = self.root / "locked"
        locked.mkdir()
        (locked / "a.ts").write_text("fetch(u)")
        locked.chmod(0)
        try:
            _, r = run_scan([str(self.root)])
        finally:
            locked.chmod(0o755)
        self.assertEqual(r["files_scanned"], 2)                       # crawl.ts, worker.py
        reasons = {s["reason"] for s in r["skipped"]}
        self.assertIn("not UTF-8", reasons)
        if os.geteuid() != 0:
            self.assertTrue(any(x.startswith("directory not readable") for x in reasons))

    def test_missing_path_is_an_error(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(scan.main([str(self.root / "nope")]), 2)


class OutcomeTest(unittest.TestCase):
    def test_add_then_score(self):
        with tempfile.TemporaryDirectory() as repo:
            with redirect_stdout(io.StringIO()):
                for item, decision in [("A1", "fixed"), ("A1", "rejected"), ("B7", "accepted"), ("A1", "kept")]:
                    self.assertEqual(outcome.main(["add", "--repo", repo, "--item", item, "--where", "x.ts:1", "--decision", decision]), 0)
            buf = io.StringIO()
            with redirect_stdout(buf):
                outcome.main(["score", "--repo", repo, "--json"])
            table = json.loads(buf.getvalue())
            self.assertEqual(table["A1"]["total"], 3)
            self.assertEqual(table["A1"]["hit_rate"], 0.67)
            self.assertEqual(table["B7"]["hit_rate"], 1.0)
            log = Path(repo, ".code-principles", "outcomes.jsonl").read_text().splitlines()
            self.assertEqual(len(log), 4)

    def test_log_file_keeps_repo_untouched(self):
        with tempfile.TemporaryDirectory() as repo, tempfile.TemporaryDirectory() as elsewhere:
            log = os.path.join(elsewhere, "o.jsonl")
            with redirect_stdout(io.StringIO()):
                outcome.main(["add", "--repo", repo, "--item", "D6", "--where", "r.ts:36", "--decision", "accepted", "--log-file", log])
            self.assertFalse(os.path.exists(os.path.join(repo, ".code-principles")))
            buf = io.StringIO()
            with redirect_stdout(buf):
                outcome.main(["score", "--log-file", log, "--json"])
            self.assertEqual(json.loads(buf.getvalue())["D6"]["accepted"], 1)

    def test_rejects_bad_item_and_missing_repo(self):
        with tempfile.TemporaryDirectory() as repo, redirect_stdout(io.StringIO()):
            self.assertEqual(outcome.main(["add", "--repo", repo, "--item", "Z9", "--where", "a", "--decision", "fixed"]), 2)
            self.assertEqual(outcome.main(["add", "--repo", repo + "/missing", "--item", "A1", "--where", "a", "--decision", "fixed"]), 2)


if __name__ == "__main__":
    unittest.main()
