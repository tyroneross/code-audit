# Observed verification

These checks were recorded on October 16, 2026. They describe source, test and host boundaries; public source availability does not establish global plugin installation.

| Boundary | Observed result | Limit |
|---|---|---|
| Audit tooling | 88 tests pass | Includes report integrity, contextual rules and workflow contracts; does not establish finding recall. |
| Focused scanner/outcome tooling | 9 tests pass | Scanner hits remain candidates, not confirmed defects. |
| Combined package | 15 integration checks pass | Manifest/reference integrity, relocated memory, seeded read-only behavior, concurrent stdout, known-fix wording, log boundaries/budgets, FIFO handling, timestamps, protocol and provenance. |
| Debugger runtime | TypeScript build succeeds; 45 + 58 existing tests pass | Development dependencies were reused locally after matching lockfile versions; none downloaded. |
| MCP | Relocated launcher starts without node_modules; eight tool schemas listed; store/detail/search/outcome/list work | Temporary project memory, not real user incidents or production durability. |
| Claude host | Manifest validator passes; the actual Skill tool loads code-audit:code-audit | MCP status was separately registered in an isolated host and reported its actual working directory, memory path and absent index. Automatic plugin MCP registration is not established by this smoke test. |
| Opus 5.5 repair | Exact claude-opus-5-5 receipt; 18 of 18 held-out behavior checks pass | One synthetic checkout task. Public contract, simulator and existing public test preserved. |
| Codex host | Portable and compatibility manifests plus local marketplace packaged | Desktop installation/loading not performed. |
| Publication/deployment at the recorded test date | Not performed | Original repositories and installations remain intact. Public source publication is separate from application deployment. |

The [replayable fixture](../evals/README.md) includes the observed model identity, frozen guidance hashes and repaired example. Passing tests establish the observed boundary, not production acceptance or a universal prompt-format advantage.

Independent Opus 5.5 source review approved the repaired package after identifying and correcting inherited defects. A separate final review approved the additional home-ancestor scope guard. The source-only reviewers did not execute the supplied receipts. A broader live recheck reached its 420-second budget without a verdict; its probes were retained and it is not counted as approval. Host-run regression checks and the earlier independent live probes remain separate execution evidence.

Fresh compilation matched all 76 JavaScript/declaration files exactly. Development dependencies and local build records were moved outside the plugin; the relocated MCP and all 15 integration checks pass with no node_modules in the plugin tree. Ignored local state is excluded from the Git archive distribution.

Remaining limits: full Codex desktop installation and automatic plugin MCP registration were not exercised. Actual Claude skill loading and explicitly registered MCP status were exercised separately. Memory scope is the reported server working directory/configured path; verify those in the target host. Undated logs are labeled time unknown and omitted from time-filtered results with a visible count. Production behavior, broad defect recall and universal prompt-format advantages remain unestablished.


## Review-feedback update — October 17, 2026 (0.2.0)

This update changes instructions, references, evaluation fixtures and their scorer; it does not change debugger runtime source/build outputs or MCP schemas. The affected audit suite (88), focused tooling suite (9), combined integration suite (15) and review-scorer suite (10) pass: 122 checks in this run. The saved timeout repair also replays 18 of 18 behavioral checks. The 103 historical debugger runtime tests above were not rerun for this instruction/evaluator change and are not included in the current count.

The new [nine-case review comparison](../evals/review/results/comparison.md) used fresh matched Opus 5.5 contexts, withheld labels and separate blinded source adjudication. Both baseline and candidate found eight seeded defect classes and left three clean controls unchanged, with no adjudicated harmful advice or unnecessary duplicates. This is a regression baseline, not an observed improvement in overall review quality, rounds-to-pass, human effort or memory benefit. Scorer replay checks supplied judgment/accounting; it does not authenticate evidence or execute proposed repairs.

Initial independent oracle review exposed an ambiguous deadline representation and an overly strict ID-spelling criterion. The contract and scoring were corrected fairly, then both arms and adjudication were rerun; earlier artifacts remain separate local build records. Exact tested guidance is frozen in the evaluation results. The final selected review/memory guidance was rerun after source-review corrections; debug-loop routing and storage-path instructions received source review and package checks rather than behavioral evaluation of every host path. Full desktop installation, automatic MCP discovery, real incident recall and production/user acceptance remain untested in this update.

Independent Opus 5.5 source critique requested changes, then targeted closure approved the corrections. The [review record](review-feedback-review.json) lists closed issues and limits. A real temporary-project MCP check stores a linked invalidation, retrieves it by the original incident ID and inspects its narrative; it does not establish ranking on a large corpus.


## Combined audit/debugger update — October 20, 2026 (0.3.0)

This update repairs temporal ranking, surfaces skipped-corpus coverage and historical verification, and adds per-call project selection to memory tools. Both retrieval paths now compare timestamps against the same cutoff, preserve a zero-day preference and exclude future timestamps from recency boost. Partial reads qualify NO_MATCH; patterns and indexed list retain usable records and report skipped reasons. Invalid list dates and limits receive explicit handling. Ranking scores and retrieval tiers are not calibrated repair confidence.

Actual isolated Claude Code 2.1.306 and Codex CLI 0.163.0 hosts loaded the combined entry and automatically discovered the MCP. Status/store/list/search/detail roundtrips used separate temporary project corpora. Codex exported PLUGIN_ROOT and launched from its installed package directory; explicit project_root selected the intended corpus. Home/package implicit scope is guarded. These are CLI integration results, not desktop UI acceptance or production durability. No user global setup, shared memory or automatic mining was enabled.

The [matched comparison](../evals/matched/results/2026-10-20/comparison.md) includes no-added-guidance/current/trimmed arms, two repetitions per host: all review trials found 13/13 seeded defect classes with no adjudicated false positives or harmful advice; all primary saved repairs pass 18/18 parent-owned behavioral assertions. The comparison shows a tie, with insufficient evidence for broad efficacy, latency, human-effort or memory benefit. Detailed guidance remains conditional. Frozen packets, source provenance, per-trial usage, blind judgments and oracle caveats are retained.

Candidate execution is separated from the trusted oracle by an OS sandbox and constrained JSON worker. Tests cover links/special files, forged receipts, child processes, frozen source, failed/malformed host results and actual access canaries. Earlier prompt-only and failed infrastructure trials are excluded from primary comparisons and retained as local build evidence. Independent Claude reviews required these corrections; final closure receipts and executed test totals accompany this build's local report. Source/build checks, CLI integration, synthetic behavior and desktop acceptance remain separate evidence boundaries.

Final source closure was approved separately for runtime/debugger and evaluator corrections by Claude Opus 5.5. The [review record](combined-review.json) preserves exact scope and limitations. The complete affected suite runs 284 tests: 28 package/runtime-boundary, 103 legacy runtime, 99 audit, 9 focused tooling, 30 matched-harness, 10 review scorer and 5 cleanup checks. Exact source/build parity and recorded-host/trial evidence checks are additional gates.
