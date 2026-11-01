# Full-guidance arm (pre-registered 2026-11-01)

Every earlier arm received a frozen bundle of four SKILL.md files, about 26 KB. Those files link to the focused checklist and the 30 principle cards, but tool-less reviewers cannot follow links. So the material that carries most of Code Audit's guidance never reached the model. This run gives it that material and asks whether it helps.

This file, `cases.json` and the bundle `../../matched/guidance/code-audit-full.txt` were committed before any trial of this run.

## Arms

| Arm | Guidance |
|---|---|
| `code-audit-full` (subject) | The four SKILL.md files at 405a6b0, plus `focused-checklist.md` and all 30 cards P01–P30, in that fixed order. About 162 KB. Built with `w3/build_bundle.py --full`. The cards were not chosen per case, because choosing them that way would leak the answer key. |
| `code-audit-w3b` | The same four SKILL.md files with no references. The SKILL.md text is unchanged between 2389d96 and 405a6b0. This arm isolates the effect of the references. |
| `coding-debugger`, `code-principles-audit` | The source bundles, unchanged. |
| `none` | No guidance. |

Every arm runs fresh in this run, so all five share the same time window and model state. The model and effort are unchanged: `gpt-6.1-sol` with `model_reasoning_effort="medium"`, asserted at launch.

Not run: the optional variant that adds each packet's `scan.py` hits. It needs per-case prompt changes, and it is left for a later pre-registration.

## Cases, metrics and verdict

These are the hard-benchmark cases unchanged: H01–H10, C01–C02 and X01–X06. Each runs twice per arm.

- **Primary set:** as already fixed by the hard-benchmark pilot (9f066c9), review H01, H02, H03, H04, H07, H08 and repair X01–X04. No new pilot is run.
- **Metrics, validity rules and judging:** as in [../README.md](../README.md) and its addenda. That includes schema-constrained output, the command audit, exclusion of invalid trials with one rerun, and location AND blinded Opus-tier judgment.
- **Judging:** one packet per case holds all five arms' findings under random labels.
- **Verdict:** the hard-benchmark rule, with Δ = `code-audit-full` − comparator for each comparator.
  - **Review:** outperforms if detection Δ ≥ +0.15 and control false-positive Δ ≤ +1. Worse if detection Δ ≤ −0.15 or control false-positive Δ ≥ +2.
  - **Repair:** ±3 passes, with a per-case guard of −2.

The question this answers: does the full guidance outperform the bundle-only Code Audit arm and both sources? Earlier runs saw every arm miss H01, H07 and H08. Of these, checklist item C3 and cards P14 and P19 cover H08 and H01; nothing covers H07. A gain on those cases would show the references reaching the model. No checklist or card text is changed for this run.
