# Complexity, duplication and test strength

Use measurements when scoring is requested or complexity/refactoring is material. Scores select code to inspect; they do not confirm defects or assign a whole-repository quality grade. Prefer existing project analyzers. Do not install tools, run project code or start coverage/mutation jobs during a read-only review without authorization.

## Numerical evidence

Record revision, source digests, analyzer/version, exact command, selection, exclusions, languages and parse gaps. Separate production and test functions. Empty scope, unsupported languages and missing coverage never establish a clean review.

- **Cyclomatic complexity (CC):** count branch paths under the analyzer's documented convention. CC >= 10 is a configurable reading-order threshold. Different tools' counts are not interchangeable; clear dispatchers can be intentional.
- **CRAP:** `CC² × (1 − coverage)³ + CC`, where coverage is a fraction from zero to one. Compute only from compatible coverage of the same source/function. Missing coverage means unknown CRAP, distinct from measured zero coverage. CRAP >= 10 prompts examination of structure and behavioral protection.
- **Duplication:** structural similarity >= 0.8 is a candidate. Confirm that the fragments implement one policy that should change together before sharing them. Similar syntax can encode independent decisions.
- **Mutation:** report selected, executed, behaviorally killed, surviving, uncovered and inconclusive counts separately. Compilation/import failures, infrastructure errors and timeouts do not prove assertion sensitivity. Zero executed mutants is unavailable evidence, not a perfect score.

## Bundled scorers

Resolve `<cp>` to the installed `skills/code-principles` directory. One entry point measures Python with the stdlib AST and Rust, TypeScript/TSX, JavaScript/JSX, Java, Go and Swift with the bundled tree-sitter analyzer in `runtime/complexity` (JavaScript is read with the TSX grammar). Neither imports, builds nor runs the target. Consult `--help` and `runtime/complexity/src/main.rs` for the per-language counting rules:

```sh
cargo build --release --offline --manifest-path <plugin>/runtime/complexity/Cargo.toml   # once; or cargo install --offline --path <plugin>/runtime/complexity
python3 <cp>/scripts/complexity.py /absolute/project --paths src > /scratch/complexity.json
python3 <cp>/scripts/complexity.py /absolute/project --paths crates/x/src --duplicates > /scratch/complexity.json
python3 <cp>/scripts/companions.py doctor
```

Each function row records language, CC, coverage/CRAP or null, `kind` (`production` or `test`) and `test_reason`. Read production hotspots (`production_hotspot_count`) before test code. Test code is identified by path convention, by attributes (`#[test]`, `#[cfg(test)]` items and out-of-line `#[cfg(test)] mod x;` files, JUnit and Swift Testing `@Test`, XCTestCase `test*` methods), TypeScript `describe`/`it`/`test` callbacks, or Go `_test.go` files. A Rust `cfg` marks test code only when its predicate cannot hold without `test` (`all(test, unix)` yes; `any(test, feature = "x")`, `not(any(test, miri))` and `feature = "test-util"` no). Out-of-line Rust modules resolve only when the declaring file is selected; select the crate's `src` (and `tests`, `examples` or `benches`, whose files are crate roots like `lib.rs`, `main.rs` and `src/bin/*.rs`). Anonymous functions with no enclosing function (top-level callbacks, `export default () => {}`, Go package-level `func` literals, Java field lambdas and initializer blocks, Rust closures in a `static`) are rows named `<anonymous@LINE>`; Swift computed properties are rows named for the property or accessor (`V.body`, `V.label.get`). Decisions outside every function (top-level statements, field or constant initializers) are counted per file and reported as a gap. Python module-level code is not measured. `analyzers` names the parser and grammar versions that ran. An unbuilt analyzer, unsupported language, unreadable file or parse error is a reported gap with `status: incomplete`, never a clean result. `--threshold 10` marks equality as a hotspot; `--fail-on-hotspots` explicitly enables the numerical gate. Keep artifacts outside a reviewed repository. Directory walks exclude the generated/vendor directories listed in the report, do not follow symlinked subdirectories and count a file once even when a case-insensitive volume spells it two ways.

Cyclomatic complexity undercounts branching hidden in combinators. Rust `Option`/`Result` chains (`and_then`, `unwrap_or`, `map_or`), Swift optional chaining and TypeScript `?.` carry decisions the count omits, so a low score is not evidence of simple logic. Read the code before calling a function simple.

`--duplicates` adds structural candidates for the tree-sitter languages: Jaccard similarity of node-kind shingles, inclusive at 0.8 by default, reported with each side's `kind`. Python is not compared, which the duplicates section states as a gap. MinHash banding is derived from the threshold so a pair exactly at the threshold is found with probability at least 0.98 (`estimated_recall_at_threshold`); below about 0.03 every pair is compared. `candidate_pairs_found` is therefore a near-complete count, not an exact one. Identical boilerplate (`as_str` matches, test setup) scores 1.0 legitimately; confirm shared policy before merging anything.

## Structural signals and pattern leads

Every function row also carries the signals below, and `signals` names those at or above their threshold. `hotspot` remains the CC rule. Signals choose reading order; none is a defect and none changes the exit status. Override with `--structure max_nesting=4 lines=80`.

| Signal | Counts | Default | Where the default comes from |
|---|---|---|---|
| `max_nesting` | Deepest nested control flow. An `else if` stays on its chain's level; a conditional expression inside another opens one, so a chained ternary reads as nested. Early exits (`guard`, `let ... else`) and single-expression closures (`.filter(|x| x.ok())`) open none; a closure with a block body opens one | 3 | "Deep nesting (3+ levels)" in the adapted simplification skill |
| `lines` | Name line to closing line, inclusive, comments and blanks included | 50 | "Long functions (50+ lines)" in the same skill |
| `params` | Declared parameters without the receiver (`self`, `cls`, Rust `self`) | 6 | Error Prone TooManyParameters: five or fewer |
| `bumps` | Top-level control-flow blocks that themselves contain nested control flow: separate chunks of nested logic | 2 | Reading-order choice; the source names the smell and no value |
| `condition_operators` | Most `and`/`or` (`&&`/`||`) operators combined in one expression | 3 | Reading-order choice; the source names the smell and no value |

`patterns` lists parser-backed leads, each compared as source text and reported only when no operand calls a function, awaits, allocates or mutates:

- `identical_operands`: a comparison, `&&`, `||`, `-`, `/` or `%` whose two sides are the same expression. Skipped as the usual NaN test when the line names a float, NaN or infinity as a whole word. Not run for Swift.
- `self_assignment`: `x = x`. In Python only inside a function, because `NAME = NAME` at module level rebinds on purpose.
- `duplicate_branches`: both arms of an `if`/`else` or conditional expression are the same code. Skipped when the condition binds a name (`if let`, `if case`, an `instanceof` pattern).
- `repeated_condition`: a condition repeats an earlier one in the same `else if` chain.

Each lead has `kind` (production or test) and `tier`. A rule is `measured` with at least 8 labelled hits at precision 0.7 or higher, otherwise `experimental`; the record with every labelled hit, the six corrected false-positive causes and its limits is [pattern precision](pattern-precision.json). On six repositories (8,776 files, 110,791 functions) `duplicate_branches` was 21 true of 21; the other three rules had one hit between them. A file with a line over 2000 bytes is treated as minified: its leads are withheld and counted in `patterns_withheld`. Confirm a lead against its callers before reporting it. An analyzer built before these fields existed yields null values and one gap; rebuild it.

## Change frequency and before/after

```sh
python3 <cp>/scripts/hotspots.py /absolute/project [--since "12 months ago"] [--top 20] > /scratch/hotspots.json
python3 <cp>/scripts/structure_delta.py /absolute/project [--base <rev>] > /scratch/delta.json
```

`hotspots.py` scores each file as non-merge commits in the window times its flagged production functions (CC hotspot or structural signal). Commits made under an earlier file name count for the present name where Git's rename detection links them. Code that changes often and carries flagged structure is where simplification pays back first; flagged code that never changes and clean code that changes often score 0. Git never rejects `--since` text, so read `since_resolved_utc`, the start it used. A shallow clone is a gap.

`structure_delta.py` compares the working tree, uncommitted and untracked files included, with a base revision. The default base is the merge base of HEAD with the first existing of the `origin/HEAD` target, `origin/main`, `origin/master`, `main`, `master`. It measures changed source files on both sides, pairs functions by path and name (when a name repeats, an unchanged function pairs with itself first, then by line order), and flags `tests_changed`, `protected_region_changed`, `protected_region_unbalanced`, `large_change`, `function_got_worse`, `new_hotspot` and `pattern_introduced`. Flags are places to look and exit 1 only with `--fail-on-flags`. No flag does not show that behaviour is preserved; the project's tests do that. The workflow that uses both tools is [simplification](simplification.md).

All scripts read Git through one guarded helper. It disables `core.fsmonitor`, passes `--no-ext-diff --no-textconv` to log and show, and never asks Git to compare with the working tree, because that runs the clean and process filters a repository's configuration names. Changed files are found by hashing working files with filters off, so a repository that relies on filters (LFS, line-ending conversion) lists those files as changed. Only regular files are opened; a link, FIFO or device is reported as unreadable. The fsmonitor and filter cases have tests that fail when the guard is removed; the external-diff and textconv flags do not.

## Coverage and mutation companions

`companions.py doctor` lists, per language, the coverage and mutation tools on PATH, their install line, the command to run and the converter, plus a lint companion for Rust (Clippy) and Java (Error Prone, which runs only inside the project's build). A lint run compiles the project, so it needs the same authorization as its tests; keep to the correctness, suspicious, complexity and perf groups and apply `cargo clippy --fix` only in an authorized repair. StrykerJS counts as available only when `@stryker-mutator/core` resolves from `--project <dir>`; otherwise it reports `requires_project_dependency`, because `npx` would fetch it from the network. It never runs project code. Coverage and mutation runs execute the project's tests: run them only with authorization, from a passing baseline, writing to scratch outside the repository.

| Language | Coverage, then `coverage_convert.py --format` | Mutation, then `mutation_report.py --format` |
|---|---|---|
| Rust | `cargo llvm-cov --lcov`, `lcov` | `cargo mutants --in-diff <diff>`, `cargo-mutants` |
| TypeScript | c8, Jest or Vitest lcov, `lcov` | StrykerJS JSON, `stryker` |
| Java | JaCoCo XML, `jacoco` | PIT with the mutation-testing-elements plugin, `stryker` |
| Go | `go test -coverprofile`, `go` | no normalizer; raw counts stay unverified |
| Swift | `swift test --enable-code-coverage` then `llvm-cov export -format=lcov`, `lcov` | no normalizer; raw counts stay unverified |
| Python | `coverage lcov`, `lcov` | no normalizer; follow the Mutator notes below |

`coverage_convert.py <root> <report> --format <f>` maps line hits to each measured function's span, removes nested named functions' lines and binds every file to its current source SHA256. A source file modified after the report is a gap. Coverage is line-based: branch-level partial coverage is not measured, so a one-line function reads 0% or 100%. Report files that match no measured source are listed, not dropped silently. Go import paths resolve through the module path in the nearest `go.mod`; a report path that shares only its file name with several measured files stays unmatched. The modification-time check cannot detect a report re-exported later from old profile data, so regenerate coverage from a current test run. Pass the output to `complexity.py --coverage`.

`mutation_report.py <report> --format <f>` counts selected, executed (killed plus surviving), killed, surviving, uncovered, inconclusive (timeouts, unviable or compile failures, runtime errors) and not-run mutants separately. Only behavioral kills count. The score is null when nothing executed. It leaves out uncovered mutants, so `score_including_uncovered` (killed over killed, surviving and uncovered) sits beside it with a warning whenever a mutant was uncovered. cargo-mutants records its baseline and a failed or missing baseline makes the report untrusted (`trusted: false`, exit 1); Stryker-format reports record no baseline, so a valid one has `trusted: null` and exits 0 with a warning: confirm the baseline separately. For a change review, mutate only the diff (`cargo mutants --in-diff`, Stryker `--mutate <files>`) and list the surviving mutants by function.

## Optional UB companion tools

Crapper, Dryer and Mutator can supply additional measurements when available and applicable. Read the installed version's `--help`, language support and execution effects first. An overlay is not a security sandbox. No dependency is installed automatically by Code Audit.

At the [pinned revisions](../../../research/ub-mode.md), Crapper tests `> threshold`, while this recipe uses `>=`; Dryer exit zero means a report was written, not that duplicates are absent. Mutator can count nonzero exits/timeouts as kills, and its cache may retain old kills after test-only changes. Validate reports, force fresh results after source/test changes, and confirm imports resolve to each mutated worker rather than the baseline. Run a passing baseline and a known behavioral mutant before trusting results. Do not derive a mutation score from unclassified execution failures.

## Repair and compare

Pin observable behavior before restructuring. Observe a regression fail for the expected reason where practical, make the smallest adequate correction and rerun affected guarantees. An impractical honest test is a disclosed gap; a weak implementation-mirroring test is not a substitute.

Report entry-point CC and the largest related extracted helper together, compatible coverage/CRAP, before/after source digests and scope. Moving branches can improve comprehension without reducing total work. Preserve ordering, error behavior and ownership; do not split clear dispatch merely to cross a threshold.

If two repairs fail the same acceptance criterion, state their shared premise and test a discriminating counterexample before another patch. Prefer one decision owner and a suitable data shape. Separate independent mutable state and serialize state that must be shared. Add a glossary only when terminology creates real ambiguity. Use existing Code Audit/Build Loop ownership rather than another workflow.

End a scored review with numerical results, coverage gaps, candidate dispositions and executed checks. Fewer lines, lower CC and stronger tests support different claims. Measure comparable runtime/memory workloads before claiming a performance gain.
