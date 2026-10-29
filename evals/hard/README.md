# Hard review and repair benchmark (pre-registered 2026-10-28)

The [source-retirement comparison](../comparison/README.md) could not separate its arms on review or repair: every arm, including no guidance, found all four planted classes and passed both repairs. This benchmark replaces those two families with real, subtle defects from the public history of five local repositories. It answers the same question with the same four arms: does Code Audit match or outperform Coding Debugger and Code Principles Audit?

This file, `cases.json`, `harness.py` and `grade.py` were committed before any trial ran. The pilot rule below fixes how pilot results may change the case list. The scored case list is then committed in a separate addendum before the scored runs start.

## Cases

All sources come from public repositories (build-loop, agent-rally-point, NavGator, interface-built-right, spectra, decision-doctor), read with `git show` at pinned commits. Each defect was confirmed by a later fix commit. The answer key is `private/oracles.json`. Review models run without tools, and repair models run in a sandbox that cannot read any local checkout, so neither can see it.

**Review: 10 defect packets, 2 control packets.** Each packet holds two to four files from the parent of the fix commit. A defect usually sits one call deeper than the file a reviewer starts from, and each packet includes relevant files that are clean with respect to that defect. Files over ~700 lines are excerpted, keeping their original line numbers.

| ID | Repository @ parent | Class |
|---|---|---|
| H01 | NavGator @ 3723d05 (fix 765c027) | retry/timeout: gate contention reported non-retryable |
| H02 | NavGator @ 6f0f4d9 (fix 0cc7d77) | cross-process non-atomic registry write |
| H03 | interface-built-right @ fba2470 (fix 96318f6) | cache invalidation: binary freshness ignores most sources |
| H04 | spectra @ 3fcc083 (fix 486cafb) | cross-language contract drift: envelope lacks `operation` |
| H05 | build-loop @ 3431a18 (fix 4d5bf82) | partial coverage: display cap reported as queue count |
| H06 | build-loop @ 5ce58e4 (fix be96661) | partial dedup inflates experiment samples |
| H07 | agent-rally-point @ 25fc7e5 (fix 3e263c7) | torn append: `writeln!` issues two writes |
| H08 | agent-rally-point @ babc9b0 (fix 4840ce6) | timeout after delivery reported as failure |
| H09 | build-loop @ 0f06eb2 (fix 1d63c71) | unlocked read-modify-write of a JSONL file |
| H10 | NavGator @ 1f3a08a (fix 218cec0) | temp-file name unique per millisecond, not per call |
| C01 | NavGator @ 765c027 | control: H01 after its fix |
| C02 | build-loop @ 4d5bf82 | control: H05 after its fix |

**Repair: 6 cases.** The workspace holds the parent-revision files. The prompt states the user-visible symptom and the public contract, never the fix. The parent then runs a withheld test against the candidate in a fresh sandboxed directory. Before any trial, `harness.py preflight` must show every withheld test failing on the parent and passing on the fix commit. It did for all six on 2026-10-28.

| ID | Repository @ parent (fix) | Class | Withheld test |
|---|---|---|---|
| X01 | build-loop @ fcd1c1b (46b3bab) | unrepaired status overridden by closed flags | fix commit's `test_review_finding_gate.py` |
| X02 | build-loop @ 3b5c440 (2cf51fd) | producer/consumer edge-field drift | fix commit's `test_frontier_gate.py` |
| X03 | build-loop @ c6cec31 (834e661) | rank overridden by recency sort | fix commit's `test_model_overrides.py`, two classes |
| X04 | build-loop @ cc75031 (1a057e9) | concurrent id allocation loses items | fix commit's `test_backlog.py` |
| X05 | interface-built-right @ 3196ed6 (ed6e8a4) | lock ownership on close, FIFO | written `private/tests/pool.test.mjs` |
| X06 | decision-doctor @ 16818b7 (1522b23) | score-scale drift | written `private/tests/grounding.test.mjs` |

Workspaces keep the parent's own test file where one exists, so a repair can run it. Test files are editable; the withheld version replaces them at verification.

## Arms, model and isolation

Arms and guidance bundles are those of the comparison: `code-audit`, `coding-debugger`, `code-principles-audit` and `none`. Every trial is a fresh `codex exec --ephemeral --ignore-user-config` process with `-m gpt-6.1-sol` and `model_reasoning_effort="medium"`. The runner refuses to launch without both, and records the assertion per trial. Each trial has a new temporary `CODEX_HOME` holding only a symlink to the existing file-based auth.

Lanes get a minimal environment (`isolation.lane_env`). The sandbox denies reads of every local checkout, the raw-output folder, other temporary workspaces, the home folder (the auth file excepted) and Keychain files. The per-trial canary must pass, or the trial does not run. Review trials use `--output-schema` (constrained output), so a response cannot end in truncated JSON. Recorded tool use invalidates a review trial.

Bounds: review 300 s, repair 480 s per call, verification 180 s. Seconds and Codex input+output tokens are recorded per trial. Dollar cost is unavailable.

## Metrics

- **Review detection** (primary, per trial): the case counts as detected only when one finding meets both conditions. It cites the defect file at a line within ±10 of an oracle window, a deterministic check. And a blinded judge rules that it describes the oracle mechanism. Location-only hits are reported as well.
- **Control false positive** (per trial): a finding on C01 or C02 that the judge rules claims the fixed defect is still present.
- **Repair pass** (per trial): the host completed, no protected file changed and the withheld test passed.
- Findings per trial, seconds and tokens are descriptive.

**Judging.** Opus-tier Claude subagents (claude-opus-5-5, a different vendor from the reviewer) judge one packet per review case. A packet holds the oracle mechanism, the defect lines and every finding that cites the defect file, under random trial labels. Arm names, repetitions and the label map stay outside the judge folder. Judges see one case at a time and execute nothing.

## Pilot rule (fixed before the pilot)

The pilot runs the `none` arm once on every case and is not scored. After it:
- A review case that `none` missed stays in the primary set. Detected cases also stay in the primary set, in ID order, only while the primary set has fewer than 6 defect cases.
- A repair case that `none` failed stays in the primary set. Passed cases also stay, in ID order, only while the primary set has fewer than 4 cases.
- Cases are not edited after the pilot. Hardening means removal only.

Scored runs cover **all** cases. The primary verdict uses the pilot-selected set. The all-case result is also reported, because selecting on one control run biases the selected set against the control (regression to the mean).

## Scored runs and verdict rule

Two repetitions per arm per case. Arm order rotates per case and repetition. Let Δ = code-audit − source, computed over the primary set.

| Family | Outperforms | Worse | Otherwise |
|---|---|---|---|
| Review | detection-rate Δ ≥ +0.15 **and** control false-positive Δ ≤ +1 | detection Δ ≤ −0.15 **or** control false-positive Δ ≥ +2 | parity |
| Repair | passes Δ ≥ +3 trials **and** no case Δ ≤ −2 | passes Δ ≤ −3 **or** a case Δ = −2 | parity |

A family discriminates only if the `none` arm scores at most 0.75 on it. If it scores higher, the family is near ceiling and parity there is weak evidence. With 2 repetitions over 6–10 cases, a difference of one or two trials is within noise. The thresholds are set above that, but these runs estimate no population rate.

Retirement still needs, per source: parity or better on every family where the source has the capability; no unaccounted capability (`docs/source-provenance.json`); and the owner's approval.

## Addendum: pilot result and primary set (committed before scored runs)

The pilot ran the `none` arm once per case on 2026-10-28. All 12 reviews completed against the schema; none needed recovery. A single blinded Opus judge graded the pilot. Raw output and judgments are outside the repository.

- **Review.** `none` detected 7 of 10 defect cases and missed H01, H07 and H08. It raised no control false positive. Under the pilot rule, the primary set is **H01, H07, H08** plus H02, H03 and H04, the first detected cases in ID order, to reach 6.
- **Repair.** `none` passed all 6. Under the pilot rule, the primary set is **X01–X04**. The repair family is therefore expected to sit at ceiling. If it does, the result will say the family does not discriminate, rather than claim parity as evidence.

Cases were not edited. Scored runs cover all 12 review and 6 repair cases for all four arms, with 2 repetitions each.
