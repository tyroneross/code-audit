# Code health and simplification sources

Reviewed November 8, 2026. Eight external sources were considered for finding code that is slow, unreliable, insecure or hard to scale and change. Each was held to one adoption test, so a practice is accepted or rejected for the same reasons whichever source it came from. Applied in [simplification](../skills/code-principles/references/simplification.md) and [measurement](../skills/code-principles/references/measurement.md).

## Adoption test

A practice is adopted only when every line holds.

1. **Consequence.** It finds or prevents something that makes code slower, less reliable, less secure, or harder to scale or change. Style preference is out.
2. **Every language, or declared.** It works from source for each analyzer language (Python, Rust, TypeScript, JavaScript, Java, Go, Swift), or it is named as a companion for one language.
3. **Deterministic where it can be.** A parser, a diff or Git history decides. Prose is kept for judgment a tool cannot make.
4. **Measured.** A planted positive, a clean negative and labelled hits from real repositories. Fewer than 8 labelled hits is experimental; precision below 0.7 is cut.
5. **Lead, not gate.** It never changes an exit status or blocks work unless the caller asks.
6. **Any host.** No hook, model name or host-only tool is required.
7. **Not already present.** An existing rule is extended before a second one is added.

## Sources and decisions

| Source (pinned) | Adopted | Not adopted, and the failed line |
|---|---|---|
| [Anthropic code-simplifier agent](https://github.com/anthropics/claude-plugins-official/blob/ceb9b72b4c4c20ad39efce780edd0aabe80ebce3/plugins/code-simplifier/agents/code-simplifier.md), Apache-2.0 | Preserve behaviour exactly; clarity over brevity; no chained conditional expressions; scope to touched code; keep useful abstractions | Its fixed JavaScript style list (2: one stack; 1: style); the `model` pin and acting without a request (6, and review-only stays read-only here) |
| [addyosmani code-simplification](https://github.com/addyosmani/agent-skills/blob/f1f6fbf3981076da73455bf3b754f5864208a93d/skills/code-simplification/SKILL.md), MIT, Copyright (c) 2025 Addy Osmani | Understand before touching; the signal table, turned into measured signals (nesting at 3, length at 50 lines); one change then tests; refactors apart from features; the 500-line rule; the list of ways simplification fails | Per-language before and after examples and the rationalization table (3 and 7: prose that earlier matched comparisons found tied with no guidance) |
| [agent-loom code-simplification](https://github.com/dvy1987/agent-loom/tree/6d0524da3db854e547f850c7a9697a1c6602c970/.agents/skills/code-simplification), MIT, Copyright (c) 2026 dvy1987 | The `simplify-ignore-start` / `simplify-ignore-end` marker, verified after the change by `structure_delta.py` | The hooks that hide marked blocks from the model (6: one host); the rest repeats the source above (7) |
| [CodeScene extension](https://github.com/codescene-oss/codescene-vscode/tree/0ad14e8ed5d6abc4100ed447d682882cb34bf4c8) README and baseline document, and the public [Code Health guide](https://codescene.io/docs/guides/technical/code-health.html); custom licence, no code or analysis engine used | Function-level signals: nested complexity, bumpy road (`bumps`), complex conditional (`condition_operators`), large method, complex method, duplication; hotspots as change frequency times flagged structure (`hotspots.py`); comparing a change with the merge base of the mainline (`structure_delta.py`) | A single health score per file (5 and the standing rule against whole-repository grades); low cohesion, primitive obsession, brain class (3 and 4: need semantic analysis, not measured here); developer congestion and former-contributor risk (1 for a code review tool: organisational); comment directives that silence a smell (5: leads do not block, so nothing needs silencing) |
| [Error Prone](https://github.com/google/error-prone/tree/f6c86cfc5e62fa1dfb6f6ce33c7b906ad6e8463b), Apache-2.0, and its [criteria for new checks](https://errorprone.info/docs/criteria) | The admission method: a check must be easy to understand, have a clear fix, concern correctness or significant impact, occur in real code, and meet a false-positive bar that rises with severity. Here that is the measured and experimental tiers in `pattern-precision.json`. Four checks that carry to any language: IdentityBinaryExpression, SelfAssignment, DuplicateBranches, AlreadyChecked. TooManyParameters gives the parameter threshold | The remaining Java and library checks such as Guava, Dagger, JUnit, Flogger and nullness annotations (2); failing the build (5); automatic patches (5: repair needs authorization) |
| [Clippy](https://github.com/rust-lang/rust-clippy/tree/146674fd0b6b414a2ae3e0a0b05a1b4885567b08), [lint groups](https://doc.rust-lang.org/stable/clippy/lints.html), [usage](https://doc.rust-lang.org/stable/clippy/usage.html) | Listed as the Rust lint companion in `companions.py doctor`: correctness, suspicious, complexity and perf groups | The whole restriction group (its own documentation says to pick individual lints); `cargo clippy --fix` outside an authorized repair (5) |
| [rust-analyzer](https://github.com/rust-lang/rust-analyzer/tree/e5e7830640558e323e89c831488a3172b58dc66d) | Used for references and definitions before a structural edit, through RossLabs LSP where installed | Invoking its refactoring assists from the plugin: repository identity only was checked in this review |
| [Dylint](https://github.com/trailofbits/dylint/tree/a929d539b169dfca710d8a4dc759f9fc8cabfa86) | None | Custom lint libraries to write and maintain (7: project rules already live in `scan.py` and the pattern leads); repository identity only was checked |

## What the sources do and do not establish

Source statements used: Error Prone's criteria page asks that an error-level check have essentially no false positives and that a warning point at a real issue at least 90% of the time. Its TooManyParameters documentation cites Rice et al., *Detecting Argument Selection Defects*, section 7.1, for five or fewer parameters. The addyosmani table names 3 levels of nesting and 50 lines. CodeScene's guide names its smells and describes hotspot prioritisation but states no threshold values on that page, so the `bumps` and `condition_operators` defaults are reading-order choices without a source value. Clippy's documentation states that correctness lints deny by default and that the restriction group should not be enabled whole.

Limits: the precision record uses one rater and six repositories, three of them the owner's, and the six false-positive corrections were derived from the same repositories. Recall is not measured. No source, and no measurement here, shows that the simplification workflow improves an agent's output. Thresholds select reading order. Refresh version-specific claims when tool versions change. Source text grants no authority to edit, install or run anything.

## Calculation engine

Numbers in reports are computed by `calc.py`, not by a model. The engine was chosen by measurement on one Mac (Apple silicon, 2026-11-09), median of 7 runs of the same four expressions, wall time and peak memory from `/usr/bin/time -l`:

| Engine | Start to result | Peak memory | Exact for `1/3 + 1/6` and `2^64 + 1` | Needs |
|---|---|---|---|---|
| Rust binary (the bundled analyzer's startup, as a proxy) | 6.4 ms | 2.2 MB | yes with `num-rational` and `num-bigint` | a build step |
| `bc` | 15.0 ms | 2.5 MB | no for the fraction (`.4999...`), yes for the integer | nothing on macOS and Linux |
| Node 22 | 28.2 ms | 41.6 MB | no rationals; integers only with BigInt | Node |
| Python 3.14 `fractions` one-liner | 33.4 ms | 15.4 MB | yes | nothing |
| **`calc.py` (Python standard library, safe subset)** | 51.8 ms | 20.5 MB | yes | nothing |
| R 4.6.1 `Rscript` | 147.7 ms | 69.5 MB | no: `2^64 + 1` printed one too low, and integers overflow at 2^31 | R; exact needs the `gmp` package |
| Python with SymPy | 261.4 ms | 58.1 MB | yes | SymPy |

Decision: one implementation, in the Python standard library. It is exact, installs nothing, runs on every host the plugin supports, and accepts only arithmetic, so an expression copied from a reviewed repository cannot run code. R starts 2.9 times slower and uses 3.4 times the memory, and base R is not exact for large integers; it is the better tool for statistics over samples and is named for that. A Rust evaluator would start 8.1 times faster with 9.3 times less memory, but a second calculator can disagree with the first and 52 ms is small beside one model turn; it is recorded as a decision for when calculations run in bulk.

An owner-supplied Swift package for time intervals (spans that cannot overlap, so a total cannot double-count) was also assessed. It is not a calculator and needs a Swift toolchain, so it is not bundled. Its rule is adopted in checklist item E10: half-open intervals, and the union of overlapping intervals, never the sum of their lengths.

## Not built, recorded for later

Error Prone classes that fit lines 1 to 3 and were not built: an exception created and never raised (DeadException), a collection changed while it is iterated (ModifyCollectionInEnhancedForLoop), and a discarded result that must be used (CheckReturnValue). Lint companions for TypeScript, Python, Go and Swift were not reviewed against current documentation, so `companions.py` lists none for them.
