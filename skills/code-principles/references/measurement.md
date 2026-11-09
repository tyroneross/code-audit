# Complexity, duplication and test strength

Use measurements when scoring is requested or complexity/refactoring is material. Scores select code to inspect; they do not confirm defects or assign a whole-repository quality grade. Prefer existing project analyzers. Do not install tools, run project code or start coverage/mutation jobs during a read-only review without authorization.

## Numbers come from a computation

Every figure in a report is quoted from the tool that produced it or computed with a script. Totals, percentages, ratios, differences and threshold comparisons are not done by the model: language models make arithmetic errors that read as confident facts. The calculator evaluates arithmetic exactly (integers and fractions stay exact) and `--check "<left> == <right>"` exits 1 when a claimed equality or bound does not hold. It accepts numbers, names, operators and a fixed list of numeric functions and nothing else, so an expression copied from a repository under review cannot run code. Two forms take the same arguments and print the same report:

```sh
<plugin>/runtime/complexity/target/release/code-audit-complexity calc "99 + 124" --check "21 / 47 < 1/2"   # when the analyzer is built
python3 <cp>/scripts/calc.py "99 + 124" --check "21 / 47 < 1/2"                                            # no build needed
```

Prefer the binary when it exists: measured on one Mac it answers in 7.3 ms with 2.6 MB against 54.5 ms and 21.7 MB for the script. `calc_vectors.json` holds hand-worked answers that both must give, and a seeded test runs 600 random expressions through both and requires agreement. For arithmetic inside reviewed code, see item E10 of the [focused checklist](focused-checklist.md).

The binary also does the mathematics a review meets beyond arithmetic: names, equations, derivatives, integrals, time value of money and small linear programs. `calc.py` stays the arithmetic fallback and says so when asked for more.

```sh
calc "pmt(rate/12, 360, 400000)" --set rate=65/1000              # names; finance functions (cash paid out is negative)
calc --solve "x**3 - 6*x**2 + 11*x == 6"                         # every distinct real root of a polynomial
calc --solve "2*x + 3*y == 7" --solve "x - y == 1"               # a linear system, exact
calc --solve "cos(x) == x" --between 0 1                         # any other equation: one root inside a bracket
calc --derivative "sin(x)*exp(2*x)" --at 1/2
calc --integral "exp(-x**2)" --from 0 --to 1
calc --expand "(x + 1)**3"
calc --maximize "3*x + 2*y" --subject "x + y <= 4" --subject "x >= 0" --subject "y >= 0"   # add --integer x,y for whole numbers
```

Each answer states how far it is established, and a report quotes that with the number:

| Field | True or present means |
|---|---|
| `exact` | The value is an exact integer or fraction, proved by substitution. False: a float correct to rounding, with its `residual` beside it |
| `agrees` (derivative) | The rule-based value matches an independent central difference |
| `converged`, `error_estimate` (integral) | The numeric integral met its tolerance; exit 1 when it did not |
| `proved_optimal` (linear program) | The optimum satisfies every constraint exactly and the optimality conditions hold exactly. False: feasibility is exact but optimality rests on the solver, always the case with `--integer` |
| `note` | No real root, a contradictory or under-determined system, an infeasible or unbounded program |

Limits: `--solve` finds all real roots only for polynomials up to degree 32, and one root per bracket otherwise; complex roots are not reported. A bracketed root is accepted only where the expression passes through zero (small at the root, opposite signs beside it, shrinking toward it); a jump across zero is refused unless it is no larger than a few times the expression's own change between neighbouring floats there, which floats cannot show. Derivative rules cover `+ - * / **`, `sqrt`, `exp`, `log`, `sin`, `cos` and `tan`. Only a polynomial gets a written antiderivative; a numeric integral first scans the range at `scan_points` evenly spaced points (up to about a million, fewer for a long expression), cuts panels where the scan is rough and halves each panel until it agrees with its halves; a feature narrower than the range divided by `scan_points` can still be missed, and an integral still unsettled after three seconds is reported as not converged. A name in a linear program is unbounded unless a constraint bounds it, so write `x >= 0`; a whole-number name needs a lower and an upper limit from the constraints, within two billion either way, and is refused otherwise. A root or value that no float can hold (smaller than about 1e-308 or larger than 1e308), two roots closer than floats can separate, a program whose coefficients do not fit floats and whose optimum cannot be proved, and a solver answer that cannot be confirmed exactly against the constraints are refused instead of reported. `npv` takes its first value at time 0, where a spreadsheet's NPV discounts the first value one period. `irr` returns one rate chosen by numpy-financial's rule when several exist, and refuses flows longer than 32 periods whose sign changes more than once. An equation that is not a polynomial, a rule-based derivative and a numeric integral are evaluated in floats, so cancellation between large terms limits them. An exact value beside a float in `+ - * /` is combined exactly and rounded once, so `(1 + 1/2**60) - 1.0` is 2**-60. Where an exact value has to become a float (inside `exp`, `sin`, a fractional power, or as a result) both calculators refuse one too small for a float instead of treating it as zero; `sqrt` and `log` of exact values keep their digits (`sqrt(1/2**2000)`, `log(1 + 1/2**60)`). An exact argument that is not itself a float lies between two floats; when a function or power gives those two materially different results (`sin(10**30 + 1)`), the call is refused, because floats cannot say what the value is. `fv`, `pv` and `pmt` with a whole number of periods are computed in exact fractions even from float inputs and rounded once; with a fractional number of periods they are computed in floats and refused when the answer is a small difference of large amounts. Money amounts typed as decimals are floats; write `1995/100` or whole cents when the cents must be exact. Run `calc --help` for the argument order of each function.

The binary uses exact big rationals (`num-rational`); `calc.py` uses the Python standard library (`fractions`, `math`, `statistics`) and needs no install. The choice was measured, and the libraries behind each command were tested against independent methods before being adopted; both are recorded in [code health sources](../../../research/code-health-sources.md#calculation-engine). For statistics over measurement samples (comparing two timing runs, quantiles, a significance test) use R or another statistics tool when it is installed; do not use base R for exact integer arithmetic, where it loses precision above 2^53.

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

`patterns` lists parser-backed leads, each compared token by token (spacing and comments ignored, string contents exact) and reported only when no operand calls a function, awaits, allocates or mutates:

- `identical_operands`: a comparison, `&&`, `||`, `-`, `/` or `%` whose two sides are the same expression. Skipped as the usual NaN test when the line names a float, NaN or infinity as a whole word. Not run for Swift.
- `self_assignment`: `x = x`. In Python only inside a function, because `NAME = NAME` at module level rebinds on purpose.
- `duplicate_branches`: both arms of an `if`/`else` or conditional expression are the same code. Skipped when the condition binds a name (`if let`, `if case`, an `instanceof` pattern).
- `repeated_condition`: a condition repeats an earlier one in the same `else if` chain, with no condition between them that calls or mutates.

Each lead has `kind` (production or test) and `tier`. A rule is `measured` with at least 8 labelled hits at precision 0.7 or higher, otherwise `experimental`; the record with every labelled hit, the six corrected false-positive causes and its limits is [pattern precision](pattern-precision.json). On six repositories (8,776 files, 110,791 functions) `duplicate_branches` was 21 true of 21; the other three rules had one hit between them. A file with a line over 2000 bytes is treated as minified: its leads are withheld and counted in `patterns_withheld`. Confirm a lead against its callers before reporting it. An analyzer built before these fields existed yields null values and one gap; rebuild it.

## Change frequency and before/after

```sh
python3 <cp>/scripts/hotspots.py /absolute/project [--since "12 months ago"] [--top 20] > /scratch/hotspots.json
python3 <cp>/scripts/structure_delta.py /absolute/project [--base <rev>] > /scratch/delta.json
```

`hotspots.py` scores each file as non-merge commits in the window times its flagged production functions (CC hotspot or structural signal). Commits made under an earlier file name count for the present name where Git's rename detection links them. Code that changes often and carries flagged structure is where simplification pays back first; flagged code that never changes and clean code that changes often score 0. Git never rejects `--since` text, so read `since_resolved_utc`, the start it used. A shallow clone is a gap.

`structure_delta.py` compares the working tree, uncommitted and untracked files included, with a base revision. The default base is the merge base of HEAD with the first existing of the `origin/HEAD` target, `origin/main`, `origin/master`, `main`, `master`. It measures changed source files on both sides, pairs functions by path and name (when a name repeats, an unchanged function pairs with itself first, then by line order), and flags `tests_changed`, `protected_region_changed`, `protected_region_unbalanced`, `large_change`, `function_got_worse`, `new_hotspot` and `pattern_introduced`. Flags are places to look and exit 1 only with `--fail-on-flags`. No flag does not show that behaviour is preserved; the project's tests do that. The workflow that uses both tools is [simplification](simplification.md).

All scripts read Git through one guarded helper. It overrides `core.fsmonitor` and `log.showSignature` (which would run the repository's `gpg.program`), turns off lazy fetching (which in a partial clone runs the repository's remote command), passes `--no-ext-diff --no-textconv` to log and show, and never asks Git to compare with the working tree, because that runs the clean and process filters a repository's configuration names. Changed files are found by hashing working files with filters off, and lines are counted from two scratch copies outside the repository. A repository that relies on filters (LFS, line-ending conversion) therefore lists those files as changed; submodules are skipped. Only regular files inside the source root are opened; a link (in the working tree or at the base), a FIFO, a device, or a path under a directory that resolves outside the root is reported as unreadable. A source file that cannot be read on either side is a gap, so the report is incomplete, never clear. The fsmonitor, filter, signature and lazy-fetch cases have tests that fail when the guard is removed. No read asks Git for patch output of repository content, so the external-diff and textconv flags are defence in depth; the tests plant both drivers and neither runs.

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
