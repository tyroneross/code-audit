# Fresh-case benchmark (pre-registered 2026-11-01)

Earlier benchmarks could not separate any arms: detection was all-or-nothing per case, 6–12 cases gave power near 0.14, and two repetitions added almost no information (`.build-loop/reviews/2026-11-01-rca-guidance-ties.md`, untracked). This benchmark fixes the instrument before testing guidance. It uses many more cases, one repetition, a paired per-case test, and a positive control that must separate before any guidance arm is scored.

This file, `run.py`, `stats.py`, the guidance files named below and the case set were committed before any trial on these cases ran. Cases are never edited after a trial; a broken case can only be removed, with the reason reported.

## Cases

- **Provenance.** Three mining lanes (Claude Opus subagents) took defects from the public history of build-loop, NavGator, interface-built-right, agent-rally-point, spectra, decision-doctor and local-smartz. A later fix commit confirms each defect and changes the oracle lines. Each lane worked from one brief that forbade opening the code-audit repository or any review-guidance document. Commits already used by code-audit's evals or cited in its skills were excluded by sha prefix. Lanes took qualifying defects in the order they met them, without selecting by difficulty, with at most 3 per defect class per lane.
- **Packets.** Each case holds 2–4 files from the parent of the fix commit. Files over 700 lines keep line-numbered ranges around the defect and related functions. The answer key is `private/oracles.json`: file, pre-fix line windows, class and mechanism.
- **Controls.** A seeded draw (`random.Random(20261101)`) picks 8 defect cases. Each one is also reviewed at its fix revision as a control. A control finding counts as a false positive only when the judge rules that it claims the fixed defect is still present.
- **Disclosed non-independence.** The orchestrator that wrote this protocol saw each lane's case keys and one-line class labels, never the mechanisms or windows, before the methods were frozen. The methods text (`skills/code-audit/references/audit-methods.md`) comes from a design spec written before any case was mined, by a lane told not to read the cases. The new scanner rules come from a lane told the same. They target the classes of the old hard cases H01, H07 and H08, not these cases. The scanner precision sample was drawn from the same seven repositories at later pinned commits.

## Model, isolation, bounds

Every trial is a fresh `codex exec` running `gpt-6.1-sol` at `model_reasoning_effort="medium"`. Both values are asserted at launch and recorded per trial. Trials run in the hard benchmark's lane sandbox (`evals/matched/isolation.py`): a minimal environment, no read access to any local checkout, the home folder or the raw-output folder, and a canary check before every trial. Each case runs **one repetition** per arm.

- **Tool-less arms** get the line-numbered packet. They must not use tools, with the same refusal as `evals/hard`. Bound: 300 s.
- **Tool arms** get `git archive <revision>` of the whole repository, with no history, in `./repo`, plus the same tools in every arm:
  - a shell with rg, grep, find, sed and python3;
  - `tools/scan.py` and `tools/frozen.py` (the scanner at the commit that adds the new rules);
  - `tools/recon.py`;
  - the `architect` binary.

  The prompt names the starting files, gives the packet's ranges as lines of interest, and describes every tool, so the `none+tools` arm knows the tools exist. Bound: 600 s.
- **Logging.** Every command a tool arm runs is logged. Any command the `evals/hard` network audit flags makes the trial invalid. Codex has no per-run token cap, so tokens are recorded and compared instead of capped.

## Arms

| Arm | Round | Tools | Guidance |
|---|---|---|---|
| `none` | 1 | no | none (the anchor) |
| `hint` | 1 | no | positive control: "the supplied files contain a material defect of class '<oracle class>' in <oracle file>". Defect cases only. |
| `none-2pass` | 2 | no | `none`'s answer plus one second call: re-review the touched functions for a different defect on another return, error, timeout or concurrency path. Scored on the union of both answers. |
| `none+tools` | 2 | yes | none |
| `bundle+tools` | 2 | yes | the four code-audit SKILL.md files at 6168d75 (pre-methods main), joined like earlier bundles |
| `adaptive` | 2 | yes | the same four files at the methods commit, plus `audit-methods.md` |
| `fixed-plan` | 2 | yes | `adaptive` with the adaptation rules and recipe R6 removed, so the agent runs the starting route only |
| `principles+tools` | 2 | yes | the source plugin bundle `evals/matched/guidance/code-principles-audit.txt` |

The other source plugin, Coding Debugger, is not run. It tied the code-audit bundle in every earlier run, and each tool arm costs about 58 trials. No API key exists for Claude-hosted reviewer arms, so every reviewer is Codex. The guidance files and their sha256 values are recorded in Addendum 1 before any round-2 trial.

## Judging and metrics

`grade.py judge-packets` writes one blinded packet per case. It holds the oracle mechanism, the pre-fix lines and every finding that cites the defect file, under random labels. Judges are Claude Opus-tier subagents. They see no arm names and run nothing. Round 1 is judged and its positive-control result computed before any round-2 trial runs.

- **Detection** (primary, one 0/1 per case): one finding is judged to describe the oracle mechanism and cites a line within ±10 of a window.
- **Located**: the finding's primary location falls in the window.
- Also reported: control false positives, findings, tokens and seconds per trial; for tool arms, tool calls and which tools ran.

## Tests and verdict rule

Comparisons are paired by case: an exact two-sided McNemar test on discordant cases (`stats.py`). A case invalid in either arm is dropped from that comparison and counted. Host failures and timeouts are rerun once.

**Positive control (gate).** `hint` must beat `none` with p < .05. If it does not, guidance testing stops. Round 2 then runs only to report the instrument limit, and the methods ship on their own merits.

**Primary family.** Holm-adjusted across four comparisons:
- `adaptive` vs `none+tools`
- `adaptive` vs `bundle+tools`
- `adaptive` vs `fixed-plan` (the adaptation effect)
- `adaptive` vs `principles+tools` (the source)

**Secondary**, unadjusted:
- `none+tools` vs `none` (what tools alone add)
- `none-2pass` vs `none` (single vs two pass)
- `bundle+tools` vs `none+tools`

**Verdict per comparison.**

| Verdict | Rule |
|---|---|
| helps | detection Δ ≥ +0.10, p < .05 and control-FP Δ ≤ +1 |
| helps at cost | the same as helps, with tokens or seconds above 2× the comparator |
| worse | Δ ≤ −0.10 with p < .05, or control-FP Δ ≥ +2 |
| parity | anything else; it means no detectable difference, not equivalence |

**Power and discrimination.** With about 50 defect cases, p < .05 needs at least 6 discordant cases in one direction and none in the other, or about 9 to 1. A comparison is informative only when `none+tools` detects at most 75% of cases. Above that the arms sit near the ceiling, and parity there is weak evidence.

## Addendum 1: frozen round-2 guidance (committed before any round-2 trial)

`make_guidance.py --methods-rev de06478` writes `guidance/*.txt` from git. Round 1 (`none`, `hint`) had started, but no round-1 output had been judged or read. Tool arms run `scan.py`, `frozen.py` and `recon.py` from de06478. At that commit the two new failure-path rules left in the scanner are experimental and run only with `--experimental`, which no prompt mentions except through `audit-methods.md` text in the `adaptive` and `fixed-plan` arms.

| Arm | sha256 |
|---|---|
| `bundle+tools` | 3f670fb50eaef32c5cff76230407a45bbdc32928f63df2d1df45eb618dabd3ed |
| `adaptive` | 685206535e984ca99a9c3967c876cf09f56ee047a179edeb8eee01b997464ac8 |
| `fixed-plan` | 2658f8f8f77e45b69f5c0e294d2752ebc9f94c7a0044af823785726fc7a6d679 |
| `principles+tools` | a915a052cb306d6e6f76af84b8b5ef55009c3092450b9fdae371353d95bbabd5 |

`adaptive` differs from `bundle+tools` by every change in de06478 to the four SKILL.md files (route line, probe-before-concluding, positive-control rule) plus `audit-methods.md`. It is the whole method package, not an ablation. `fixed-plan` removes section 4 (adaptation), recipe R6 and every R6 mention, and rewrites the router's "adapt per its rules" as "without changing it".
