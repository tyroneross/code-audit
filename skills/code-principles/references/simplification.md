# Simplify working code without changing what it does

Use when the request is to simplify, clean up, flatten or reduce debt in code that already works, and that change is authorized. The goal is code the next reader understands and changes faster. Fewer lines is not the goal. A review-only request stays read-only: report candidates and stop.

Do not simplify code that is already clear, code you cannot yet explain, a module about to be replaced, or a hot path where the simpler form is measurably slower. Signals and pattern leads below are places to read. None is a defect by itself and none blocks work.

## 1. Find where it pays

Resolve `<cp>` to the installed `skills/code-principles` folder. All three tools only read; keep their output outside the repository.

```sh
python3 <cp>/scripts/hotspots.py <root> > <scratch>/hotspots.json        # files that change often and carry flagged functions
python3 <cp>/scripts/complexity.py <root> --paths <files> > <scratch>/before.json   # per-function signals and pattern leads
```

Start with the top hotspot files, then the functions in their `read_first` lists. Flagged code that never changes can wait. Without Git history, rank by the scorer alone. Default scope is the code the current task touched; widen only when asked. Definitions, thresholds and limits: [measurement](measurement.md).

## 2. Understand before touching

For each function you intend to change, answer from source: what it is responsible for, who calls it, which errors and edge cases it handles, which tests pin it, and why it may look this way (performance, platform, history; `git log -L` or blame shows the original change). List references before renaming, inlining, extracting or removing a symbol: `rosslabs-lsp refs --symbol <name> --path <root>`; when it reports `ready: false` or no server covers the language, use `rg -nw <name>` and say the search was textual. Code that looks unused follows [removal evidence](removal-evidence.md). If a question stays open, read more or leave the code alone.

## 3. Choose the correction

| Signal or lead | Usual correction | Leave it when |
|---|---|---|
| `max_nesting` at or above the threshold | Guard clauses and early returns; extract the inner block under a name | The nesting mirrors the data shape and each level is short |
| `bumps` (several nested chunks) | One named function per chunk | The chunks share mutable state that extraction would thread through parameters |
| `lines` | Split by responsibility | It is a flat table, a dispatcher or generated code |
| `condition_operators` | Name the condition, or the parts that mean something | The operands are already named predicates |
| `params` | Group values that travel together; replace a boolean flag with two functions or a named option | The signature is a stable public contract |
| CC hotspot | Reduce decisions with a lookup, a data shape or one owner for the rule | A clear dispatcher (see measurement) |
| Chained conditional expressions | `if`/`else`, `switch`/`match` or a lookup | Two short arms |
| `duplicate_branches`, `identical_operands`, `self_assignment`, `repeated_condition` | Decide which arm, operand or condition was intended; if none, delete the dead test | The lead is in generated code or a deliberate NaN test |
| Duplicate candidates (`--duplicates`) | Share the code only when the fragments are one policy that must change together | Similar syntax encodes independent decisions |
| Names that hide meaning (`data`, `tmp`, a `get` that mutates), comments that restate the code | Rename to the project's vocabulary; delete the comment and keep comments that say why | The name is a project convention |

Follow the project's own conventions (its instruction file such as AGENTS.md or CONTRIBUTING, its linter and formatter, neighbouring code). A change that imposes an outside style is churn.

## 4. Change in small steps

1. Pin behaviour first. Run the existing tests; where a function has none, add a characterization test before touching it and keep it.
2. Make one simplification. Run the tests. Commit, or revert and reconsider.
3. Keep simplification separate from features and fixes: its own commit or change request.
4. When a change would touch more than the size budget (default 500 lines), use an automated transform (codemod, compiler-assisted rename, formatter) and review it in parts.

Preserve outputs, error types and messages, side effects and their order, and concurrency behaviour. The contract gate D1 to D5 in the [focused checklist](focused-checklist.md) lists the cases to compare.

## 5. Check the result

```sh
python3 <cp>/scripts/structure_delta.py <root> [--base <rev>] > <scratch>/delta.json
```

Then run the project's tests, build and linter. `structure_delta.py` reports what the tests cannot: `tests_changed` (a simplification that needs an edited test probably changed behaviour; a renamed symbol is the usual exception), `function_got_worse`, `new_hotspot` (complexity moved into a helper, not removed), `pattern_introduced`, `large_change` and `protected_region_changed`. Read each flag and state why it stands or what you changed. No flag does not prove behaviour is preserved.

Revert a step when the result is harder to read. The common ways simplification fails: inlining a helper whose name carried the concept, merging two simple functions into one complex one, removing an abstraction that exists for testing or a real second implementation, removing error handling to look cleaner, and compressing clear code into a dense expression.

## Protected regions

Code between a comment containing `simplify-ignore-start` and one containing `simplify-ignore-end` is left byte-for-byte unchanged; add the reason after the start marker. Use it for hand-tuned hot paths, vendored blocks and generated sections. `structure_delta.py` reports any difference from the base and any unbalanced marker. The marker is checked after the change; it does not hide code from the agent.

## Report

Scope and base revision; functions changed with before and after signals; flags raised and their disposition; tests, build and lint commands with results; steps reverted; what was left alone and why. Separate measured structure from claims about readability, and do not claim a speed gain without a comparable measurement.

## Source boundary

Adapted from three simplification skills and two analysis tools, recorded with revisions, licences and the reasons for each adoption or rejection in [code health sources](../../../research/code-health-sources.md). The sources describe practices; none establishes that this workflow improves an agent's output, and earlier matched comparisons in this repository found guidance tied with no guidance on review and repair tasks. The checks above are the part that is measured.
