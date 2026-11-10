# Focused engineering checklist

Load only sections relevant to the operation. Pattern matches are investigation leads; establish a violated contract and consequence before reporting a defect.

## A. Speed and efficiency

- **A1 Same input fetched or parsed twice.** Look for a fetch, read, `JSON.parse`, `cheerio.load`, `JSDOM`, `BeautifulSoup` or `json.loads` on the same data in two helpers. Parse once and pass the result.
- **A2 Work inside a loop that could be batched (N+1).** A query, HTTP call or file read inside a loop over earlier results. Batch, prefetch, or eager-load.
- **A3 Sequential awaits over independent items.** `for … { await … }` where items don't depend on each other. Run with *bounded* concurrency (see B5).
- **A4 Repeated scans as data grows.** Nested loops, `.find`/`in list` inside a loop, or re-scanning the input from the start on every match (e.g. `source.substring(0, match.index).split('\n')` to get a line number). Build a lookup or running offset once.
- **A5 Synchronous blocking work on a request or event-loop path.** `readFileSync`, `execSync`, `inflateSync`, large `XLSX.read`, CPU-heavy parsing. Move it off the hot path or into a worker; wrapping sync code in `p-limit`/`Promise.all` does not parallelize it.
- **A6 Doing unrequested work.** Loading subresources (`resources: 'usable'`), computing fields nobody reads, copying whole collections to read one item.
- **A7 Measure before a big change; don't skip known-cheap wins.** Find the critical code with a profiler before restructuring. Compare several input sizes when investigating growth, and prioritize the measured cost of the whole task; linear work can still dominate it. Picking the efficient option when it is equally simple is not premature optimization (Knuth's full quote).

## B. Scale and load

- **B1 Every queue, buffer and request-fed collection has a size limit and a rejection path.** `asyncio.Queue()` with no `maxsize`, an unbounded channel, a list/map that grows per request.
- **B2 Choose timeouts intentionally and propagate the operation deadline.** Base the value on relevant latency data or a stated reasonable assumption, including user expectations and cleanup/retry costs. A timeout's presence alone does not justify its value. Inspect `fetch` without `signal`/`AbortSignal.timeout` and `requests.get` without `timeout=`; use [timeout guidance](timeouts.md) when selecting or changing limits.
- **B3 Retry at one layer only, under a retry budget.** Don't wrap an SDK or HTTP client that already retries. Never retry a non-idempotent write without an idempotency key reused across attempts.
- **B4 Shed excess load early and cheaply.** Reject before expensive work (auth lookups, parsing, logging) when overloaded.
- **B5 Cap fan-out.** `Promise.all(items.map(call))` or `asyncio.gather(*…)` over unbounded input needs a limit. For wide fan-out, check the slowest 1% of whole requests, not the average.
- **B6 Caches are bounded, coalesced and expire.** A plain map used as a cache needs eviction, a TTL, one in-flight fetch per missing key, and a plan for cold start.
- **B7 Cap untrusted sizes.** Decompressed size (`maxOutputLength`), upload size before `arrayBuffer()`, file size before parsing.

## C. Failure handling

- **C1 Test every error handler.** Most catastrophic failures in large distributed systems come from mishandled errors the code already caught. Empty, log-only and `TODO` handlers are leads. Confirm a lost guarantee, hidden failure or invalid continuation; intentional terminal and best-effort handling can be correct.
- **C2 Handle a failure where something useful can be done; otherwise pass it up with context.** Don't catch broadly to continue with state you can't trust.
- **C3 A timeout is not proof nothing happened.** Reconcile uncertain writes before repeating them.
- **C4 Define what partial success leaves behind.** List each effect; publish only complete state or record what needs cleanup.
- **C5 Background work has an owner.** Every spawned task is awaited, cancelled or supervised; child failure cancels siblings when the parent needs all of them.
- **C6 Report what was skipped.** When code skips input it cannot read, decode, fit or access, count it and say so. A result of "nothing found" must never mean "didn't look". Check that files, rows or pages skipped by `except`/`continue` paths reach the summary.
- **C7 One record, one write, one owner.** A log or state file shared by processes or threads loses or corrupts records when a record and its newline go out in separate writes, when a writer seeks to the end instead of opening with O_APPEND, or when a reader-writer rewrites the file (read, change, replace) without the lock every other writer takes. An atomic rename prevents torn bytes, not lost updates. Check every writer of the file, including retention, rotation and crash-recovery paths, and what a reader does with a partial last line.

## D. Contract gate — must pass before any fast path ships

- **D1 Empty, negative, zero and boundary inputs** behave exactly as before (compare old vs new on the same inputs).
- **D2 Output types and conversions are preserved,** not just values (e.g. library numeric types vs raw ints).
- **D3 Subclasses, alternate implementations and private storage** your fast path assumes are checked, or the fast path is guarded to the exact types it handles.
- **D4 Existing guards stay** unless removing them is required. A few-percent gain does not justify dropping a type or length check.
- **D5 Error types and messages callers rely on are unchanged.** Observable behavior is a contract even when undocumented (Hyrum's Law).
- **D6 Untrusted names never become paths.** `basename` plus a generated id; reject `..`.
- **D7 Untrusted URLs are checked where the connection is made.** Validate the resolved IP at connect time (or pin it), re-validate every redirect, and fetch once, passing the body on instead of letting a second component fetch again.

Write the comparison as a differential check: run old and new over the same inputs including D1–D3 cases and assert identical results.

## E. Structure and change hygiene

- **E1 Small, self-contained changes;** refactors separate from behavior changes.
- **E2 Total code size matters more than how it is split.** Split only when the whole operation gets easier to understand.
- **E3 Types catch some bugs, not most.** Use them for meanings that are easy to confuse (ids, units); still test behavior.
- **E4 Prefer real implementations, then fakes, then mocks** in tests; mock only at real system boundaries.
- **E5 Update or delete a comment in the same change that alters its code.**
- **E6 Replace in small steps** (strangler fig) rather than rewriting from scratch.
- **E7 Pin dependencies; read a dependency's code and transitive deps before adopting it.**
- **E8 Hand-written parsers of standard formats** (PDF, CSV, HTML, ZIP, dates, source code) need tests for escapes, nesting, string literals and encodings, or a maintained library. Regex over source code matches inside strings and comments unless it accounts for them.
- **E9 Built ≠ wired.** Every new export, guard, setting or delegation has a non-test production caller and is actually loaded (route manifest, registration, build output); every caller of the legacy path it replaces is migrated or exempted by name. Method: for each changed exported symbol run `rosslabs-lsp refs --symbol <name> --path <root>` and list symbols whose only references are tests or the definition; when LSP reports `ready: false`, use `rg -nw <name>` excluding tests.

- **E10 Check arithmetic by running it.** Formulas, unit and currency conversions, rounding, percentages, limits, offsets and date math: evaluate the changed expression on boundary inputs (zero, one, the largest allowed, a negative, a value that does not divide evenly) and compare with the contract. `python3 <cp>/scripts/calc.py --check "<expression> == <expected>"` evaluates arithmetic exactly and runs nothing else; use a scratch script outside the repository for code that needs the language's own integer or float behavior. A payment, rate, break-even point, root or optimum that the code or its documentation claims is reproduced with the analyzer binary's `calc` (finance functions, `--solve`, `--maximize`; see [measurement](measurement.md)), not accepted because the formula looks familiar. Integer division, float equality, rounding direction, overflow, unit mix-ups and off-by-one are the usual defects. For durations and ranges, use half-open intervals and total the union of overlapping intervals, never the sum of their lengths: two sources covering the same hour are one hour. Reading the arithmetic is not a check, and neither is a model's mental calculation. For guarded formulas, simultaneous equations or algorithm output, use the boundary and fixture checks in [measurement](measurement.md#check-equations-and-algorithms-against-independent-expectations).

## F. Frozen values that should be dynamic

A value is a lead when it has a live source of truth or varies by context but is frozen in code; a literal alone is not. Procedure, harm order and the scanner's measured precision: [frozen values and path length](frozen-values-and-path-length.md).

- **F1 No machine-specific absolute paths.** Home paths and checkout paths break on the next machine; derive them from the repo root, an argument or config.
- **F2 No environment-specific hosts in code.** `localhost`, ports, private IPs and preview-deploy hosts belong in config or env; a fallback after reading env must be safe where it applies.
- **F3 Don't copy the manifest version.** Read `__version__`, CLI `--version` and client/server info from the package manifest or generate them.
- **F4 Limits, timeouts and thresholds that differ by deployment come from config,** with the default justified (see B2).
- **F5 Model ids, prices, regions, account/project/tenant ids and dates have an owner.** Read the catalog, config or clock; check the live source before calling a recent-looking value wrong.
- **F6 Feature toggles read their flag.** A toggle fixed to a constant may be dead code, a hidden switch or a deliberate kill switch; check [removal evidence](removal-evidence.md) before calling it unused.
- **F7 One owner per shared identifier.** File names, schema ids, env-var names, wire names and URLs used by several modules or languages come from one definition, are generated from it, or are checked for drift.
- **F8 Nothing private leaves the machine.** Before a push or publish, run `python3 <cp>/scripts/publish_check.py --range <upstream>..HEAD --from-gh <owner>` (whole tree: drop `--range`). It reads every tracked text file, including data, docs, test fixtures and commit messages, for credentials in recognisable formats, machine-specific paths, and private repository names (kept in `~/.code-audit/private-names.txt`, never in the repo). Secrets and machine paths block (exit 1); private names are listed as warnings and the push proceeds, since a name is a secrecy concern and not a security one. Generated records are the usual source: a script that writes `repo/path:line` keys or quotes source lines publishes whatever repositories it measured, so label a private repository (`private-desktop-app`) before recording. Read the warnings before pushing: a private name already pushed needs a history rewrite, not a new commit, and a pushed secret needs rotation first. The secret patterns are a floor; run a dedicated scanner over whole history before a first publish.

## G. Path length and brittle structure

- **G1 Count the hops from request to outcome** and name the shortest correct path that meets the same requirements.
- **G2 Every layer names its capability:** isolation, independent scale or deploy (P29), a real alternative (P09), a real boundary seam, a stable contract, or a simpler whole operation (P13). Pass-through wrappers, single-implementation factories, speculative plugin systems, duplicate state owners and service splits without isolation or scale need are leads.
- **G3 Judge brittleness by failure points and coupling:** dropped fields at a serialization hop, two tie-break rules for one record set, partial updates between owners, version skew, retries at two layers. Taste is not a finding.

## Quick pick: checklist item → cards

Read the referenced principle in the [canonical rule cards](../../audit/references/cards/).

| Items | Cards |
|---|---|
| A1–A7 | P28 performance, P30 build vs. dependency |
| B1, B4, B5 | P21 concurrent failures, P28 |
| B2, B3, C3 | P19 retries, P14 failure classes, P07 hidden guarantees |
| B6 | P28, P18 state guarantees |
| B7, D6, D7 | P06 meaning and validation, P17 isolation, P07 |
| C1, C2, C6 | P15 error representation, P16 where to handle |
| C7 | P18 partial success, P21 concurrent failures |
| C4 | P18 |
| C5 | P20 async ownership, P21 |
| D1–D5 | P10 substitution, P27 compatibility, P23 verification |
| E1–E10 | P08, P13, P22, P23, P24, P25, P26, P30 |
| F1–F7 | P06 meaning and validation, P27 compatibility, P07 |
| G1–G3 | P09 extension points, P13 splitting, P29 separate services, P18 |

For a full 30-principle audit of a codebase, a pre-build plan, or a multi-batch repository campaign, use the workflows at `../../audit/SKILL.md`, `../../plan/SKILL.md` or `../../improve/SKILL.md` (relative to this skill's real folder).
