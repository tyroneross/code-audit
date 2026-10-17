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
