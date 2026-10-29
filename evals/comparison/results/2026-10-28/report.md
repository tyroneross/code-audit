# Source-retirement comparison: results, 2026-10-28

Code Audit tied both sources wherever the tasks could tell arms apart. It also tied the no-guidance control on review and repair, so those two families do not discriminate between guidance bundles. The only family with a real gap is incident retrieval. There Code Audit is 0.033 recall@5 behind Coding Debugger on one real corpus, which counts as parity under the pre-registered rule. The difference traces to two deliberate contract changes, not to lost function.

Method, arms and verdict rule: [README](../../README.md), committed in 38f7709 before any trial ran. Per-trial scores: [scores.json](scores.json). Retrieval runs: [run 1](memory-run1-before-timestamp-fix.json), [run 2](memory-run2-after-timestamp-fix.json) and [run 3, the scored run](memory-run3-after-legacy-id-fix.json). Raw host output, prompts and judgments are kept outside the repository.

## Scores

| Family | Metric | code-audit | coding-debugger | code-principles-audit | none | n per arm |
|---|---|---|---|---|---|---|
| F1 review | recall of D1–D4 on P01 | 1.00, 1.00 | 1.00, 1.00 | 1.00, 1.00 | 1.00, 1.00 | 2 trials |
| F1 review | precision, P01+P02 pooled | 1.00 | 1.00 | 1.00 | 1.00 | 2 repetitions |
| F1 review | findings, P01 / P02 | 15,16 / 11,14 | 14,13 / 14,10 | 15,14 / 14,14 | 11,14 / 13,9 | — |
| F1 review | valid JSON before recovery | 3/4 | 0/4 | 1/4 | 2/4 | 4 |
| F2 repair | R1 timeout-retry, 18 withheld checks | 2/2 | 2/2 | 2/2 | 2/2 | 2 |
| F2 repair | R2 scan-skipped, withheld historical test | 2/2 | 2/2 | 2/2 | 2/2 | 2 |
| F3 memory | recall@5, standard path | 0.350 | 0.383 | capability absent | 0.650 | 60 queries |
| F3 memory | recall@5 exact / partial / cause | 0.80 / 0.25 / 0.00 | 0.85 / 0.30 / 0.00 | — | 1.0 / 1.0 / 1.0 | 20 each |
| F3 memory | recall@5, indexed path | 0.183 | 0.183 | — | — | 60 |
| F3 memory | false returns on 10 negatives | 0.0 | 0.0 | — | 0.1 | 10 |
| F3 memory | corpus records loaded | 87 / 100 | 100 / 100 | — | 100 | — |

The F3 control is a keyword search over the same symptom and root-cause fields that the queries were derived from. It is an upper bound for this query design, not evidence that keyword search beats the runtime.

Cost covers the 16 review and repair trials per arm, using Codex input plus output tokens. Dollar cost is unavailable.

| Arm | Time | Tokens |
|---|---|---|
| code-audit | 817 s | 1.11 M |
| coding-debugger | 675 s | 1.32 M |
| code-principles-audit | 742 s | 1.12 M |
| none | 645 s | 0.87 M |
| **All arms** | 2,879 s of model time | — |

## Verdicts (pre-registered rule)

| Source | F1 review | F2 repair | F3 memory |
|---|---|---|---|
| coding-debugger | parity (Δ recall 0, Δ precision 0) | parity (Δ 0 of 4) | parity (Δ recall@5 −0.033, Δ false returns 0) |
| code-principles-audit | parity (Δ 0, Δ 0) | parity (Δ 0 of 4) | not applicable: no memory in source; code-audit adds it |

Neither source outperforms Code Audit on any family. Code Audit outperforms neither source either: every review and repair task saturated, including the no-guidance control.

## Why Code Audit trails the debugger on F3

Code Audit misses two queries the debugger answers.

- **T04-partial: the debugger's recency bug.** The incident is more than 90 days old. The debugger boosts it above the threshold only because of the recency bug that Code Audit fixed (defect D1). Raising the window to 100,000 days flips both runtimes: Code Audit then retrieves the incident and the debugger loses it.
- **T11-exact: a filename that does not match the record's ID.** Code Audit refuses records whose filename differs from their `incident_id`, an integrity rule. The debugger reads them without validation.

The comparison also surfaced two real regressions, both repaired during this run:
- Legacy `INCIDENT_` IDs were rejected (017116e).
- Legacy ISO-string timestamps were rejected (cca1aa5). This commit's message claimed an effect on the corpus, but on this corpus the change loaded no additional records. 017116e corrects that claim.

The 13 records still skipped are legacy schema variants. They are filed as CODE-RUNTIME-m62jfj5t87betr4c7qb90.

## Isolation and pinning

- **Launch:** all 32 model calls ran `codex exec` with `-m gpt-6.1-sol` and `model_reasoning_effort="medium"`, asserted before launch and recorded per trial. The served model identity is not reported by Codex.
- **Process:** each call ran in a fresh ephemeral process with a temporary `CODEX_HOME` and file-based credentials only.
- **Sandbox:** R2 sandbox canaries passed: own read allowed; protected, foreign-temp and outside-write all denied.
- **R2 oracle:** before any trial, the withheld test failed on the pre-fix code and passed on the historical fix.
- **Plugins:** arms received frozen skill text, not installed plugins, so they could not see each other's plugins.
- **Judging:** two blinded claude-opus-5-5 subagents judged F1, one per case. The vendor differs from the reviewers, and the label map was kept in a separate folder.

## Deviations and limits

- **F1 output recovery.** 10 of 16 reviews omitted the final `]}` of otherwise complete JSON. `score.py recover` appended only closing brackets and accepted the result only when the existing validator passed, applied to every arm (740372b). This deviation was decided after the outputs were seen.
- **F1 judge leniency.** The judges marked 211 of 211 findings valid and none harmful, filing 32 oracle challenges. Precision therefore carries no signal, and judge leniency is possible. Each judge saw one case only, and nothing was executed.
- **Saturation and sample size.** Every arm, including no guidance, found all four named defects and passed every repair. Two repetitions per arm per case show spread only. These results cannot rank the bundles; harder tasks are needed.
- **R2 confound.** The code-principles and code-audit bundles contain rule C6, which was written from the R2 fix. It did not matter, because every arm passed.
- **Unmeasured surfaces.** Installed-plugin behavior in Claude Code was not measured: skill routing, MCP memory use and the bundled `agents/`. The claude CLI's login reads the macOS Keychain, which the owner rule forbids (CODE-EVALS-m62jfjbmbr1w2grehjmqt).
- **F3 scope.** F3 used one project corpus. Partial and cause queries are rule-derived, and relevance counts exact duplicate symptoms only.
- **Sandbox gaps.** Review trials protected only this repository, and repair lanes inherit the environment and can read the home folder (CODE-EVALS-m62jfj8m5c0sm2k23dz3t). Recorded tool use invalidates a review, which bounds this risk.

## Retirement recommendation (owner approval required; nothing was uninstalled)

- **code-principles-audit: eligible to retire.** Parity on review and repair. Its scanner, audit, plan and improve skills and its rules are all imported, and its 63 imported files are tracked in provenance. No capability gap was found.
- **coding-debugger: eligible to retire after one decision.** Parity on all three families. Its agents are imported, and every command and the hook are dispositioned in provenance.
  - The decision: the debugger reads 13 legacy-schema incident records that Code Audit skips visibly (CODE-RUNTIME-m62jfj5t87betr4c7qb90). Either repair that first, or accept it for corpora written by debugger versions older than the current schema.
  - The deliberately dropped Stop-hook mining and npx CLI commands remain the designed behavior difference.
