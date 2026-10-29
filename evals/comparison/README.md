# Source-retirement comparison (pre-registered 2026-10-28)

Question: does Code Audit match or outperform each source it absorbed — Coding Debugger 1.9.1 and Code Principles Audit — on the same tasks? The answer gates a retirement **recommendation** only. Uninstalling or archiving either source still needs the owner's explicit approval.

This file was committed before any trial ran. Its commit timestamp is the record that the tasks, metrics and verdict rule were fixed in advance. Results go to `results/<date>/`, with raw model output kept outside the repository.

## Arms

| Arm | What the model receives |
|---|---|
| `code-audit` | `matched/guidance/code-audit.txt`: entry, code-principles, debug and debug-loop skills at fabd2d9. |
| `coding-debugger` | `matched/guidance/coding-debugger.txt`: debug-loop and debugging-memory skills at de0d613 (source 8cc675e plus captured local edits). |
| `code-principles-audit` | `matched/guidance/code-principles-audit.txt`: the single entry skill at 1cd1ac7 (source 4361bd3 plus captured local edits). |
| `none` | Empty guidance: the no-guidance control. |

Each bundle is the skill text the plugin loads for these tasks. No plugin is installed or loaded, so arms cannot see each other: every trial is a fresh `codex exec --ephemeral --ignore-user-config` process in a new temporary `CODEX_HOME` that holds only a symlink to the existing file-based auth. A macOS `sandbox-exec` profile denies reads of this repository, other temporary workspaces and Keychain files (the existing `matched/isolation.py` and `repository/trial.py` boundary). Bundle hashes are recorded per trial.

Every arm uses the same model and effort: `gpt-6.1-sol`, `model_reasoning_effort="medium"`. The runner refuses to launch when the command lacks either value. Codex does not report the served model, so identity is the asserted request, not a served receipt.

Claude-hosted arms (`claude -p --plugin-dir`) were not run. The claude CLI loads its login from the macOS Keychain, which the owner's standing rule forbids. A local hook blocks the call. Consequently the bundled `agents/` and real plugin loading are not measured here.

## Task families

**F1 — code review, precision and recall against an answer key.** Uses the existing `repository/cases.json` packets: P01 is four full runtime modules (~2,900 numbered lines) at 91c2520, with four source-confirmed historical defects D1–D4 in `repository/private/oracles.json`. P02 is the same modules after their repair at 082621d, a control for those classes. There are 4 arms × 2 cases × 2 repetitions, giving 16 tool-less reviews. Arm order alternates per repetition.

Grading uses the existing `repository/experiment.py judge_prompt`, run by a blinded Opus-tier judge (claude-opus-5-5 subagent, a vendor separate from the reviewer), one judge per case. Arm labels are replaced by random blind labels, and the mapping is withheld from the judge. Metrics are computed from the judgments by script:
- **Recall** = distinct D1–D4 covered by valid findings on P01, out of 4, per trial.
- **Precision** = valid findings ÷ all findings, pooled over P01 and P02 per trial. A valid finding outside the named classes counts as valid.
- **Harmful** = findings judged harmful.

**F2 — debugging / root cause, fix verified by withheld tests.** Two cases, each 4 arms × 2 repetitions (16 repair trials):
- **R1** `timeout-retry` (existing `matched/repair.py`): a bounded adaptation of confirmed checkout failures. The parent runs all 18 withheld behavioral checks.
- **R2** `scan-skipped` (new, real history): code-principles-audit commit 4361bd3 fixed `scan.py` counting unreadable and non-UTF-8 files as scanned and silently skipping unlistable directories, which made a partial scan look clean. The workspace holds the three pre-fix script files from 4361bd3^. The prompt states the symptom and the public output contract, never the fix. The parent then runs the withheld `test_code_principles.py` from 4361bd3 against the candidate inside the sandbox. Before any trial, that file fails on the pre-fix code (1 failure) and passes on the historical fix (9/9).
- **Pass** = every withheld check passes, protected files are unchanged, and the host completed. Anything else fails, including timeouts.

Known confound: the code-principles bundle (and code-audit's) contains rule C6, "report what was skipped", which was written from this same fix. A guidance advantage on R2 is partly learned from R2 itself, so R2 is reported separately as well as pooled.

**F3 — incident-memory retrieval, deterministic.** The corpus is a read-only temporary copy of the 102 real incidents in one project's `.claude/memory/incidents` (`atomize-ai`). The queries are frozen by `memory_arms.py` from a fixed seed (20261028), before any arm runs:
- 20 target incidents, each with three queries: exact symptom, first six content words of the symptom, and the first sentence of the recorded root cause.
- 10 off-corpus negative queries.

Relevance = the target plus any incident with an identical normalized symptom. Arms:
- `code-audit`: its `runtime/debugger/dist` `checkMemory` and `checkMemoryScaled`.
- `coding-debugger`: its own `dist` with the same two functions and the same config (threshold 0.5, max 5).
- `code-principles-audit`: no memory capability, scored as zero recall and reported as a capability gap.
- `none`: a keyword baseline an agent without the tool could run, counting overlapping content tokens in the symptom and root cause, top 5, at least 2 overlaps.

Metrics: recall@5 and MRR on the 60 positive queries, and the false-return rate (any result) on the 10 negatives. Query and incident text stay outside the repository because the corpus is private project data. Only IDs, hashes and scores are committed.

## Verdict rule (fixed before running)

Each source arm is compared against `code-audit`. Let Δ = code-audit − source.

| Family | Outperforms | Worse | Otherwise |
|---|---|---|---|
| F1 | mean recall Δ ≥ +0.25 (one defect class) **and** precision Δ ≥ −0.10 | recall Δ ≤ −0.25 **or** precision Δ ≤ −0.15 | parity |
| F2 | pooled passes Δ ≥ +2 of 4 trials (2 cases × 2 repetitions) and no case Δ ≤ −1 | pooled Δ ≤ −2, or a case Δ = −2 | parity |
| F3 | recall@5 Δ ≥ +0.10 **and** negative false-return Δ ≤ +0.10 | recall@5 Δ ≤ −0.10 **or** false-return Δ ≥ +0.20 | parity |

The `none` arm is reported against every arm. If `none` ties every guided arm, the family does not discriminate between guidance bundles, and parity there is weak evidence.

**Retirement recommendation for a source** requires all of the following:
1. Code Audit is parity-or-better on every family where the source has the capability.
2. No capability the source provides is missing from Code Audit or left unaccounted for (see `docs/source-provenance.json` `removed_imports`).
3. The owner approves.

Two repetitions describe spread; they do not estimate a population rate. A tie at saturation is parity, not superiority.

## Bounds

- Each model call is capped at 300 s (review 240 s), about 32 calls in total.
- Calls consume Codex usage. Token usage and wall time are recorded per trial; dollar cost is unavailable from the Codex CLI.
- No installation, mining, global memory or credential change.
