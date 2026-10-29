# Hard review and repair benchmark: results, 2026-10-28

On the pre-registered primary set, all four arms scored the same: Code Audit, Coding Debugger, Code Principles Audit and the no-guidance control each detected 6 of 12 review trials and passed 8 of 8 repairs. Across all cases they differ only on H09, where `code-principles-audit` and `none` each detected one more trial (13/20 against 12/20) on a partial match. Both sources are at parity with Code Audit. The review family is now below ceiling (the control scored 0.50), but guidance bundles still made no measurable difference to which defects a reviewer found. Repair stayed at ceiling, so it does not discriminate.

Method, cases, pilot rule, validity rules and verdict rule: [README](../../README.md), committed in 2e6ef9d before any trial, with the pilot addendum (9f066c9) before the scored runs. Per-arm numbers: [scores.json](scores.json). Raw host output, prompts, judge packets and judgments are kept outside the repository.

## Scores

Primary set: review H01, H02, H03, H04, H07, H08; repair X01–X04. Two repetitions per arm.

| Metric | code-audit | coding-debugger | code-principles-audit | none |
|---|---|---|---|---|
| Review detection, primary (located + judged) | 6/12 = 0.50 | 6/12 = 0.50 | 6/12 = 0.50 | 6/12 = 0.50 |
| Review detection, all 10 cases | 12/20 = 0.60 | 12/20 = 0.60 | 13/20 = 0.65 | 13/20 = 0.65 |
| Location-only hits, all cases | 19/20 | 19/20 | 19/20 | 19/20 |
| Control false positives (C01, C02) | 0/4 | 0/4 | 0/4 | 0/4 |
| Findings per review trial, all 12 packets | 2.8 | 2.5 | 3.5 | 2.8 |
| Repair passes, primary / all | 8/8, 12/12 | 8/8, 12/12 | 8/8, 12/12 | 8/8, 12/12 |
| Invalid trials | 0 | 0 | 0 | 0 |

Per case, the arms agreed on every review trial except H09, where one repetition each of `code-principles-audit` and `none` counted as detected. Both of those detections rest on the judge's partial-match rule: each finding named only the missing-newline half of the two-part defect. Under a stricter reading, all four arms are identical on all 10 cases.
- **Every arm detected, both repetitions:** H02, H03, H04, H05, H06, H10.
- **Every arm missed, both repetitions:** H01, H07, H08.

Most reviewers did cite the defect lines (19 of 20 trials had a location hit). They described a different problem there, such as a dead-gate hang, recovery after an interrupted migration, or the lookup failing before delivery.

## Verdicts (pre-registered rule, primary set)

| Source vs Code Audit | Review | Repair |
|---|---|---|
| coding-debugger | parity (Δ detection 0.00, Δ control false positives 0) | parity (Δ 0 of 8) |
| code-principles-audit | parity (Δ 0.00, Δ 0) | parity (Δ 0 of 8) |

On all cases the verdicts do not change: Δ is 0.00 against Coding Debugger and −0.05 against Code Principles Audit (one H09 trial), both parity.

**Discrimination.** The control scored 0.50 on review, below the 0.75 ceiling, so the review family can separate arms; these bundles simply did not. On repair the control passed 8/8, so that family does not discriminate, and its parity is weak evidence.

## Cost

| Arm | Review s / tokens (24 trials) | Repair s / tokens (12 trials) |
|---|---|---|
| code-audit | 959 s / 0.74 M | 1,128 s / 3.20 M |
| coding-debugger | 1,152 s / 0.75 M | 1,039 s / 3.08 M |
| code-principles-audit | 1,171 s / 0.67 M | 1,381 s / 3.72 M |
| none | 1,097 s / 0.61 M | 1,024 s / 2.41 M |

Seconds are model wall time per trial, summed; six trials ran concurrently. The pilot added 18 trials, 983 s and 1.37 M tokens. The longest single call was 123 s for review and 230 s for repair, within the 300 s and 480 s caps. Dollar cost is unavailable from the Codex CLI.

## Isolation and pinning

- **Launch:** all 162 calls were `codex exec --ephemeral --ignore-user-config` with `-m gpt-6.1-sol` and `model_reasoning_effort="medium"`. Both were asserted before launch and recorded per trial. Codex does not report the served model.
- **Process:** each call ran with a fresh `CODEX_HOME` holding only the auth symlink, and a minimal environment (`isolation.lane_env`).
- **Sandbox:** every trial's six kernel canaries passed: own read allowed; protected checkout, foreign temporary data, outside write, home folder and parent environment all denied.
- **Output:** review answers used `--output-schema`. 96 of 96 scored reviews and 12 of 12 pilot reviews parsed with no repair, which fixes the earlier truncation at its source.
- **Repair oracles:** before any trial, each withheld test failed on the parent and passed on the fix commit (`harness.py preflight`). Every candidate was re-verified after the run under the stricter pass rule, which requires a parsed test count above zero with zero failures.

## Deviations and limits

- **Network was reachable from repair commands.** The lane cannot deny it without also blocking the Codex API; a nested sandbox is refused. Model commands were audited instead. The first audit flagged 10 of 48 trials, and all 10 were false positives; the audit was refined after those flags were seen and then expanded for recall (README Addendum 3). No version found any network access, but a text audit cannot rule out access it does not recognise.
- **Rules added during the run.** Addendum 2 was committed after scored runs began, before any grading. Addendum 3 was decided after repair pass results were visible in the run log, before review grading. Both apply to every trial alike. The first audit made 10 repair trials invalid; the refined and expanded audits make none. Excluding those 10 trials still leaves every verdict at parity: on the primary set code-principles-audit would be 7/7 against code-audit 8/8, Δ 1.
- **Pilot selection.** The primary set was chosen from a single control run, which biases it against the control. The all-case results are therefore reported too, and they lead to the same verdicts.
- **Judging.** Three blinded claude-opus-5-5 judges each saw four case packets. Each finding was judged once, with no second judge. The partial-match rule decided the H09 difference and two already-detected H02 trials.
- **Sample size.** Two repetitions over 6–10 cases describe spread; they do not estimate a population rate.
- **Confounds.** Case sources include build-loop and agent-rally-point, and the guidance bundles may have been written with knowledge of those repositories. No arm benefited measurably.
- **Unmeasured.** Claude-hosted arms and installed-plugin behavior were not run: there is no API key, and the Keychain is off-limits (CODE-EVALS-m62jfjbmbr1w2grehjmqt).

## Effect on the retirement recommendation

Neither source outperforms Code Audit on any family, and the review family can now discriminate. The [comparison report](../../../comparison/results/2026-10-28/report.md) still governs memory retrieval (F3). [Run 4](../../../comparison/results/2026-10-28/memory-run4-after-legacy-shapes.json) loads 98 of 100 legacy records, up from 87, while recall@5 is unchanged at 0.350 against 0.383 (parity). The gap is the two designed differences, not lost records.
