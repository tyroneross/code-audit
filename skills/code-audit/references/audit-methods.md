# Audit methods: what to run, when, and how to adapt

Reading rules does not change what a reviewer finds; running a check does. This file names the checks. `<cp>` is the absolute path of the plugin's `skills/code-principles` folder (resolve symlinks). Every command here only reads the audited repo. Put scripts, packets and logs in a scratch folder outside it, never import or run the repo's own code unless execution is authorized, and skip `dist/`, generated, vendored and fixture paths.

**Output of any recipe or scan is candidates, never findings.** A candidate becomes a finding only after the verification in section 5.

## 1. Recon (one step, about 30 s)

Run `python3 <cp>/scripts/recon.py <root> [--base REV | --paths FILE...]`. It prints the signals below and the starting route as JSON. Without it, collect them by hand:

- `files`: `git ls-files | wc -l`, or the changed-path count for a diff.
- `languages`, `multi_lang`: extension counts; `multi_lang` when ≥2 languages each hold >10% of files.
- `scope`: `diff` (paths or `git diff --name-only BASE`) or `repo`; `diff_modules` = distinct top-level folders touched.
- `services`: separate roots holding a manifest, Dockerfile or deploy config.
- `io_conc`: files with append/rename/lock/flock/O_APPEND/appendFile/writeln!/spawn/create_task/Promise.all/asyncio.gather.
- `retry`: files with retry/backoff/timeout/deadline/retryable.
- `serial`: files with json.dumps/JSON.stringify/serde/pydantic/zod/schema.

## 2. Starting route

| Signals | Generate candidates with | Lanes | Who verifies |
|---|---|---|---|
| `diff`, ≤10 files, 1 module | `scan.py <changed files>`; callers of each changed public symbol; R1 if literals or config changed, R4 if `serial`, R5a if `io_conc`, R5b if `retry` | none | lead |
| `diff`, otherwise (≥2 modules or >10 files) | as above, plus `architect impact <file>::<symbol>` per changed public symbol to pull in unchanged callers | one per module only if the modules share no changed contract; otherwise one agent | each lane its own; lead re-verifies cross-lane findings |
| `repo`, <200 files, not `multi_lang` | `scan.py .`, R1, R2, R3; R4/R5a/R5b when their signal is present | none | lead |
| `repo`, ≥200 files or `multi_lang` | Phase A by dimension, repo-wide: lane F (`scan.py` F rules + R1), lane N (R2 + R4), lane S (R3 + hop count), lane E (R5a/R5b when signalled). Never split a cross-cutting class by module. | Phase B by module (`campaign.py batch`): read the module for checklist A–D and check the Phase A candidates that land in it | module lane, never the lane that generated the candidate |
| `services` ≥2 | add R4 across each service boundary; NavGator `connections`/`trace` only if `.navgator/` already exists (its scan writes into the repo, so ask first) | add one contract lane | both sides cited |
| a tool is missing | use the next method for that dimension (LSP → `architect` → import grep) or mark the cell `UNAVAILABLE` | — | — |

Callers: `rosslabs-lsp refs --symbol <name> --path <root>`; when it reports `ready: false`, use `architect impact` or `rg -nw <name>`. Brief every lane with the lane section of [reviewer role](../../audit/references/reviewer-role.md#lane-briefs).

## 3. Recipes

Each recipe prints `file:line` plus the question the reviewer must answer at that site. Answer the question by reading the site; the hit alone proves nothing. Use `rg` where it exists, else `git grep -nE` with the same pattern.

**R1 — literals that copy a source of truth.** Harvest the owned values: manifest versions (`package.json`, `pyproject.toml`, `Cargo.toml`, plugin manifests), config keys, env-var names (`process.env.X`, `os.environ["X"]`, `getenv("X")`). For each value, list literal copies outside its owner file: `rg -nF '"<value>"' -g '!<owner>' -g '!**/dist/**'`. Question: *does this copy follow its source when the source changes, and in which context does it break?*

**R2 — naming and wire-key variants.** Collect quoted wire keys (not every identifier), normalize each by splitting camel/snake/kebab and lowercasing, group, and print groups with ≥2 spellings. Question: *do producer and consumer use the same spelling for the same field?* Identifier-level grouping is mostly legitimate Type/instance and language-convention pairs; stay at wire-key granularity.

**R3 — structure nodes.** `architect scan <root> --out <scratch>/arch`, then from `graph.json` count `calls` edges per function: hubs (top fan-in), entry points (fan-in 0, fan-out >0), pass-throughs (fan-in 1, fan-out 1). Exclude test files. Hubs are reading order for shared state and contracts; pass-throughs are reading order for checklist G1–G3, not findings (pass-through detectors measured about 20% precision). Question: *what capability does this layer add, and how many hops does the request take?*

**R4 — contract field diff.** For a producer/consumer pair (paired by message or type name, file name or an R2 group), list keys the producer writes (`json.dumps({...})`, struct fields, `JSON.stringify({...})`, schema fields) and keys the consumer reads (`.get("k")`, `["k"]`, `.k`, destructuring). Print consumer-reads minus producer-writes and the reverse. Question: *which side owns the contract, and is the missing field optional by that contract?*

**R5a — effect sites (concurrency, atomic writes).** `rg -n "open\([^)]*['\"]a|O_APPEND|appendFile|writeln!|write_all|\.rename\(|os\.replace|flock|lockf|Lock\(|tmp|temp"` in scope. Per site: *is the record written in one call? is a lock held across read-modify-write? is the temp name unique per call or only per clock tick? who else writes this path?*

**R5b — error classification (failure, retry, timeout).** `rg -n "retryable|Timeout|timed out|ETIMEDOUT|except .*Timeout|catch|status\s*=\s*\W?(failed|error|ok)"` in scope. Per site: *could the effect have completed before this branch ran? which status does the code report then? who retries, and is the effect idempotent?*

**R6:<slug> — class sweep.** Written mid-audit from a confirmed finding (section 4): the smallest regex or AST query matching the finding's site shape, run repo-wide. Name it `R6:<slug>`, e.g. `R6:two-write-append`, and keep the script beside the audit output.

## 4. Adapt during the audit

The starting route is a plan. After each recipe or lane returns, apply the first matching row and record what you did.

| Trigger | Do | Record |
|---|---|---|
| A confirmed finding whose mechanism is a class (non-atomic append, timeout reported as failure, copied version) | Write R6 for its site shape and run it on the whole repo, not just the current module. | sweep command, hits, confirmed |
| A repo convention seen while reading (own config loader, env accessor, lock or atomic-write helper) | Grep for sites that bypass it, e.g. `open(..., "a")` where `locked_append` exists. | convention, grep, hits |
| A planned method does not apply (LSP `ready: false`, architect parse gaps, no manifests) | Swap to the next method for that dimension, or mark the cell not covered. | method dropped and why |
| More than ~30 hits with fewer than ~1 in 5 confirmed on a 10-hit sample | Narrow once by repo convention (exclude tests/fixtures, restrict to wire keys). Still noisy: stop and report the dimension as low precision. | sample size, confirmed |
| Budget or time runs out | Stop and fill the coverage matrix with what remains uncovered. | matrix |

## 5. Verify each candidate

1. **Control the instrument first.** Before reporting a count, a "none found" or a hit, run the same grep or script on a known positive (a planted line or a site you already confirmed) and check its exit status. Never infer absence from truncated output, an errored glob or a pipe's exit code. Run `scan.py --self-test` before trusting a scan in a new environment.
2. Read the site and its callers (`rosslabs-lsp refs` or `architect impact`).
3. Name the source of truth or the violated contract. If you cannot name one, drop the candidate.
4. Look for counterevidence: an existing lock, a reader that tolerates the field, a test asserting the behavior, a documented policy constant.
5. **Probe when execution is authorized.** Write the cheapest discriminating check outside the repo (two processes appending to one file, comparing two version values, calling the classifier with a timeout raised after delivery) and keep its output. Label every finding `probed` (a check you ran confirmed it) or `read` (source reading only).
6. Re-open every cited line, yours and every lane's (`sed -n '<line>p' <file>`), before reporting. Reject a citation that lands on a comment or a different statement.
7. Log the outcome (section 7) under the checklist id or the recipe id that produced the candidate.

## 6. Coverage matrix

End the report with one table: rows are modules (or `repo-wide`), columns are the dimensions frozen, naming, structure, efficiency, failure/retry, concurrency, contract. Each cell uses the report vocabulary:

- `PASS (method)` — covered by the named method, no finding; `FAIL (ids)` — covered, findings listed by id.
- `N/A (reason)` — the dimension does not apply here.
- `UNAVAILABLE (missing tool or input)` — not covered, and why.
- Append `low precision n/N` when the noise rule in section 4 stopped the method.

State what was searched and what was not. A blank or missing cell is not coverage.

## 7. Tool commands, repair and logging

1. **Scan.** `python3 <cp>/scripts/scan.py <path> [<path>...]` lists signals by checklist section with `file:line`. Point it at the changed files or the operation under review, and at code you are about to write. A hit is a place to look; the main path still needs reading when there are no hits.
2. **Trace the operation, then read the hits.** Follow its entry point, helpers, callers and observable boundaries. Count how many times each input is fetched, parsed, queried or scanned per operation. Read the matching section of the [focused checklist](../../code-principles/references/focused-checklist.md).
3. **Repair (only when authorized) at the simplest adequate boundary.** Compare a symptom patch with a repair at the existing common owner; see [whole-system repair](../../code-principles/references/whole-system-repair.md). Remove work before adding caches, concurrency or layers. A fast path must pass the [contract gate](../../code-principles/references/focused-checklist.md#d-contract-gate--must-pass-before-any-fast-path-ships).
4. **Verify with the repo's tools.** Run the original case and the relevant tests. A fix counts as verified only when its test fails on the pre-fix code or on a one-line mutant; see [review feedback](../../code-principles/references/review-feedback.md#verify-the-recommendation-and-the-oracle). For a speed claim, time the same workload before and after on the same machine in the same session.
5. **Log.** `python3 <cp>/scripts/outcome.py add --repo <abs repo> --item <id> --where <file:line> --decision <fixed|accepted|kept|rejected> [--gain "-27% p50"] [--log-file <path outside the repo>]`. `<id>` is a checklist id (`B7`, `F3`) or the recipe id (`R1`…`R5b`, `R6:<slug>`) that produced the candidate. Do not invent an id; keep findings without one in the report only. Decisions: `fixed` changed and verified, `accepted` real and not yet fixed, `kept` real tradeoff where the current code is right, `rejected` not a real issue. Without `--log-file` the log goes to `<repo>/.code-principles/outcomes.jsonl`, so a read-only review must pass `--log-file`. `outcome.py score` shows each id's hit rate.

## 8. Self-update: from recipe to rule

A method that keeps finding real defects should become a rule; one that stops should go. Follow build-loop's experimental → promotion pattern (`build-loop/skills/self-improve/SKILL.md`, promotion-reviewer agent); do not build a new store.

1. **Capture.** Log every recipe, sweep and convention grep that produced a confirmed finding with `outcome.py add --item <recipe id>`; keep the script beside the audit output.
2. **Candidate.** `outcome.py candidates --min-repos 2` lists recipe ids with confirmed outcomes (`fixed`, `accepted` or `kept`) on at least 2 distinct repos; pass every log with `--repo` or `--log-file`.
3. **Experimental rule.** Implement the candidate behind `scan.py --experimental`; nothing enters the default scan at this stage.
4. **Measure precision.** Use the section F method: run on the pinned public repos, sample and label hits, and record them in a `*-precision.json` like [frozen-values-precision.json](../../code-principles/references/frozen-values-precision.json). Cut a rule whose measured precision is below ~0.7, at any sample size, and record the numbers (owner rule, 2026-11-01). Promote only at ≥ ~0.7 on ≥8 labelled hits; a rule with fewer hits and no measured shortfall stays experimental.
5. **Pre-registered eval.** Commit the decision rule first, then test on cases mined after the rule froze. Wins on cases known while writing the rule do not count.
6. **Promote.** build-loop's promotion-reviewer agent gives a verdict; the owner approves the move into the default scanner or checklist. Neither step is automatic.
7. **Retire.** A rule or recipe whose `outcome.py score` hit rate falls below the keep threshold over a rolling window is flagged for removal.
