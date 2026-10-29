# W3: frozen values and brittle paths (pre-registered 2026-10-28)

This tests whether the W3 guidance (commit 414009e: checklist sections F and G, the frozen-values and path-length procedure, and the inline tests in `code-principles/SKILL.md`) helps a reviewer find two defect classes in real history:
- **Class A:** values that have a source of truth or vary by context but were frozen in code.
- **Class B:** paths with more hops than needed, where the extra hop broke.

It reuses the hard-benchmark harness, isolation, schema-constrained review, blinded Opus-tier judging and validity rules ([../README.md](../README.md), including Addenda 2 and 3). This file, `cases.json`, `private/oracles.json` and the bundle `../../matched/guidance/code-audit-w3.txt` were committed before any W3 trial ran.

## Arms

| Arm | Guidance |
|---|---|
| `code-audit-w3` (subject) | entry, code-principles, debug and debug-loop SKILL.md at 414009e, built by `build_bundle.py`. The same builder reproduces the earlier `code-audit.txt` byte for byte. |
| `code-audit` | the earlier bundle at fabd2d9, kept to attribute any gain to W3 |
| `coding-debugger`, `code-principles-audit` | the source bundles, unchanged |
| `none` | no guidance |

Same model and effort as before: `gpt-6.1-sol`, `model_reasoning_effort="medium"`, asserted at launch.

## Cases

Real defects confirmed by later fix commits in public repositories. Every line window was printed from the parent revision and checked to be inside its packet.

| ID | Class | Repository @ parent (fix) | Defect |
|---|---|---|---|
| W01 | A | interface-built-right @ 720dfea (9d5cb19) | CLI and MCP server hard-code versions that disagree with package.json and each other |
| W02 | A | build-loop @ 0a7aa7e (1d476a1) | maintainer's home path as the default script location |
| W03 | A | NavGator @ e6034d5 (c76b9d8) | hand-written receiver regex duplicates the SDK call-pattern table and misses `openai.chat.completions` |
| W04 | A | agent-rally-point @ 78db6c9 (9c4bfe2) | hand-written kind spelling table drifts from serde wire names |
| W05 | A | build-loop @ 52adc29 (90b80b9) | release bump left one plugin manifest at the old version |
| W06 | A | build-loop @ 3276d12 (d5b192b) | another binary's accepted kinds copied as a literal set instead of probed |
| W07 | B | build-loop @ ebef1da (dbb9d9e) | two readers of one row set break ties differently (first vs last) |
| W08 | B | agent-rally-point @ 269800e (2a90ca8) | the daemon hop drops internal snapshot fields |
| WC1 | control | interface-built-right @ 9d5cb19 | W01 after its fix |
| WC2 | control | build-loop @ dbb9d9e | W07 after its fix |
| WX2 | B repair | build-loop @ 825c7a2 (03b082a) | detector and re-validator use two different "has a test" rules; written withheld test |
| WX3 | B repair | agent-rally-point @ 2e2b686 (7f04a2e) | generator drops the hidden-skill flag on regeneration; written withheld test |

Each withheld test fails on its parent and passes on its fix inside the lane sandbox (`HARD_CASES=evals/hard/w3/cases.json harness.py preflight`, run 2026-10-28). One candidate repair (build-loop 450812e) was dropped before any trial: its only withheld test needs pytest, which is installed only in the home folder that the lane denies.

Known confound: the same agent wrote the W3 guidance in the same session, after the mined case list had arrived. The guidance was not edited against these cases, but that exposure cannot be ruled out, so a W3 advantage here is weaker evidence than one on unseen cases. W07 and W08 are path-length cases that the earlier `code-audit` guidance also covers in part.

## Metrics and verdict rule

Metrics are those of the hard benchmark: review detection (a location within ±10 lines of an oracle window, including `also` windows for multi-file copies, AND a blinded judgment of the mechanism), control false positives, and repair passes, with invalid trials excluded and counted.

Two repetitions per arm per case. The **primary set** is chosen by the pilot rule of the hard benchmark (removal only, minimum 6 review cases; both repair cases are kept). Let Δ = `code-audit-w3` − comparator, for each comparator `none`, `coding-debugger`, `code-principles-audit` and `code-audit`:

| Family | Outperforms | Worse | Otherwise |
|---|---|---|---|
| Review | detection Δ ≥ +0.15 **and** control false-positive Δ ≤ +1 | detection Δ ≤ −0.15 **or** control false-positive Δ ≥ +2 | parity |
| Repair | passes Δ ≥ +2 of 4 trials | passes Δ ≤ −2 | parity |

**The claim under test:** `code-audit-w3` outperforms `none` and both sources on review. If it does not, one guidance iteration is permitted. The iterated bundle is rebuilt at a new commit and run on every case for the subject arm only, with the other arms' results reused. The iterated result is reported separately, as post-hoc: its author has seen these cases.

Bounds are those of the hard benchmark: review 300 s, repair 480 s per call. Seconds and tokens are recorded.

## Addendum: pilot result and primary set (committed before scored runs)

The `none` pilot (one run per case, 2026-10-28) detected 3 of 8 review defects, W02, W07 and W08. It raised no control false positive and passed both repairs. One review trial (W04) failed with "Selected model is at capacity" and was rerun once under the rule.

Under the pilot rule, the primary review set is **W01, W03, W04, W05, W06**, the cases `none` missed, plus **W02**, the first detected case in ID order, to reach 6. That makes the primary set all six class-A cases. W07 and W08 (class B) are scored in the all-case result only. Both repair cases stay; `none` passed them, so repair is expected near ceiling. Cases were not edited.
