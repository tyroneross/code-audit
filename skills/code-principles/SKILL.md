---
name: code-principles
description: Checklist for writing and reviewing code that is correct, fast, efficient and scalable. Use when implementing or reviewing non-trivial code, optimizing a slow path, adding remote calls/retries/queues/concurrency/caching, handling errors, or changing a contract other code depends on. Scans the code for signals, loads only the matching checklist sections, and logs whether each finding held up.
user-invocable: false
---

# Code principles checklist

Find wasted work and broken contracts, choose the simplest adequate fix for the underlying cause across affected paths, prove it with the repo's own checks, and log the outcome.

## Workflow

```text
READ intended outcome, scope, constraints, relevant code, callers and tests
IF debugger available: SEARCH past incidents
ELSE: STATE the incident-coverage gap
IF scanner available: SCAN relevant files; TREAT hits as leads
ELSE: STATE the scan-coverage gap; CONTINUE permitted manual review
SELECT applicable simplicity, systems, usability and human-factors checks
IF challenge-specific detail needed: READ its definitions and guidance
FOR each suspected problem:
    CONFIRM cause and consequence; REPRODUCE against baseline when feasible
    IF reproduction unavailable: RECORD causal evidence and its limits
    TRACE the cause across affected callers, state owners and boundaries
    COMPARE symptom patch with simple shared fix; CHECK wider effects and costs
    CHOOSE simplest adequate causal fix; SEARCH related occurrences if useful
    IF change within authorized scope: APPLY fix
    RERUN reproducer after fix; CHECK preserved behavior
    IF claiming speed/latency gain: TIME baseline and repair on same workload
    FOR work-count, growth or memory claims: PROVIDE matching evidence and limits
    RECORD evidence, relevant rule premises, tradeoffs, executed checks, uncertainty
    DISTINGUISH recommendations from verified fixes
STOP when scoped work complete OR required external dependency blocks progress
```

For command syntax and outcome logging, use [tool instructions](references/tool-use.md).

## Review criteria

Start with the required outcome and consider four engineering criteria: **simplicity** (few concepts and steps), **systems engineering** (boundaries, ownership and whole-system effects), **usability** (can the intended user complete the task), and **human factors** (memory, attention, mistakes and recovery). For concrete failure patterns and checks, read the relevant section of [engineering foundations](references/engineering-foundations.md). These apply to APIs, CLIs, agent tools and operating procedures as well as graphical interfaces. A scanner cannot establish these properties.

Read [challenge guidance](references/challenge-guidance.md) when the task needs deeper definitions or methods.

For hardcoded exceptions, repeated patches or a repair that shifts costs to another component, apply [whole-system repair](references/whole-system-repair.md). Smallest adequate means the simplest correction of the causal mechanism, not the fewest changed lines or the narrowest visible example.

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
- **B2 Choose timeouts intentionally and propagate the operation deadline.** Base the value on relevant latency data or a stated reasonable assumption, including user expectations and cleanup/retry costs. A timeout's presence alone does not justify its value. Inspect `fetch` without `signal`/`AbortSignal.timeout` and `requests.get` without `timeout=`; use [timeout guidance](references/timeouts.md) when selecting or changing limits.
- **B3 Retry at one layer only, under a retry budget.** Don't wrap an SDK or HTTP client that already retries. Never retry a non-idempotent write without an idempotency key reused across attempts.
- **B4 Shed excess load early and cheaply.** Reject before expensive work (auth lookups, parsing, logging) when overloaded.
- **B5 Cap fan-out.** `Promise.all(items.map(call))` or `asyncio.gather(*…)` over unbounded input needs a limit. For wide fan-out, check the slowest 1% of whole requests, not the average.
- **B6 Caches are bounded, coalesced and expire.** A plain map used as a cache needs eviction, a TTL, one in-flight fetch per missing key, and a plan for cold start.
- **B7 Cap untrusted sizes.** Decompressed size (`maxOutputLength`), upload size before `arrayBuffer()`, file size before parsing.

## C. Failure handling

- **C1 Test every error handler.** Most catastrophic failures in large distributed systems come from mishandled errors the code already caught. Empty, log-only and `TODO` handlers are defects.
- **C2 Handle a failure where something useful can be done; otherwise pass it up with context.** Don't catch broadly to continue with state you can't trust.
- **C3 A timeout is not proof nothing happened.** Reconcile uncertain writes before repeating them.
- **C4 Define what partial success leaves behind.** List each effect; publish only complete state or record what needs cleanup.
- **C5 Background work has an owner.** Every spawned task is awaited, cancelled or supervised; child failure cancels siblings when the parent needs all of them.
- **C6 Report what was skipped.** When code skips input it cannot read, decode, fit or access, count it and say so. A result of "nothing found" must never mean "didn't look". Check that files, rows or pages skipped by `except`/`continue` paths reach the summary.

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

## Quick pick: checklist item → cards

Read the referenced principle in the [canonical rule cards](../audit/references/cards/).

| Items | Cards |
|---|---|
| A1–A7 | P28 performance, P30 build vs. dependency |
| B1, B4, B5 | P21 concurrent failures, P28 |
| B2, B3, C3 | P19 retries, P14 failure classes, P07 hidden guarantees |
| B6 | P28, P18 state guarantees |
| B7, D6, D7 | P06 meaning and validation, P17 isolation, P07 |
| C1, C2, C6 | P15 error representation, P16 where to handle |
| C4 | P18 |
| C5 | P20 async ownership, P21 |
| D1–D5 | P10 substitution, P27 compatibility, P23 verification |
| E1–E8 | P08, P13, P22, P24, P25, P26, P30 |

For a full 30-principle audit of a codebase, a pre-build plan, or a multi-batch repository campaign, use the workflows at `../audit/SKILL.md`, `../plan/SKILL.md` or `../improve/SKILL.md` (relative to this skill's real folder).
