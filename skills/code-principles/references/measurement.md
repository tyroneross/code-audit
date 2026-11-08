# Complexity, duplication and test strength

Use measurements when scoring is requested or complexity/refactoring is material. Scores select code to inspect; they do not confirm defects or assign a whole-repository quality grade. Prefer existing project analyzers. Do not install tools, run project code or start coverage/mutation jobs during a read-only review without authorization.

## Numerical evidence

Record revision, source digests, analyzer/version, exact command, selection, exclusions, languages and parse gaps. Separate production and test functions. Empty scope, unsupported languages and missing coverage never establish a clean review.

- **Cyclomatic complexity (CC):** count branch paths under the analyzer's documented convention. CC >= 10 is a configurable reading-order threshold. Different tools' counts are not interchangeable; clear dispatchers can be intentional.
- **CRAP:** `CC² × (1 − coverage)³ + CC`, where coverage is a fraction from zero to one. Compute only from compatible coverage of the same source/function. Missing coverage means unknown CRAP, distinct from measured zero coverage. CRAP >= 10 prompts examination of structure and behavioral protection.
- **Duplication:** structural similarity >= 0.8 is a candidate. Confirm that the fragments implement one policy that should change together before sharing them. Similar syntax can encode independent decisions.
- **Mutation:** report selected, executed, behaviorally killed, surviving, uncovered and inconclusive counts separately. Compilation/import failures, infrastructure errors and timeouts do not prove assertion sensitivity. Zero executed mutants is unavailable evidence, not a perfect score.

## Bundled Python scorer

Resolve `<cp>` to the installed `skills/code-principles` directory. The stdlib AST scorer reads Python without importing or executing the target. Consult `--help` for its counting rules and source-bound coverage schema:

```sh
python3 <cp>/scripts/complexity.py --help
python3 <cp>/scripts/complexity.py /absolute/project --paths src/module.py > /scratch/complexity.json
```

Output includes per-function CC, compatible coverage/CRAP or null, source digests and gaps. `--threshold 10` marks equality as a hotspot; `--fail-on-hotspots` explicitly enables the numerical gate. Unknown coverage does not become zero. Coverage percentages must come from actual compatible instrumentation, not an estimate; the supplied SHA256 binds each file to its measured source. Keep artifacts outside a reviewed repository. Directory walks exclude the generated/vendor directories listed in the report and do not follow symlinked subdirectories; select an intended source file explicitly when needed.

The scorer measures Python only. TypeScript, Rust and Swift need an available compatible analyzer and the same evidence fields. Report unsupported scope explicitly. Do not relabel a text heuristic as compiler-backed analysis.

## Optional companion tools

Crapper, Dryer and Mutator can supply additional measurements when available and applicable. Read the installed version's `--help`, language support and execution effects first. Coverage can install tooling or execute project commands; mutation executes tests against changed source. Use authorized scratch data and preserve an unchanged baseline. An overlay is not a security sandbox. No dependency is installed automatically by Code Audit.

At the [pinned revisions](../../../research/ub-mode.md), Crapper tests `> threshold`, while this recipe uses `>=`; Dryer exit zero means a report was written, not that duplicates are absent. Mutator can count nonzero exits/timeouts as kills, and its cache may retain old kills after test-only changes. Validate reports, force fresh results after source/test changes, and confirm imports resolve to each mutated worker rather than the baseline. Run a passing baseline and a known behavioral mutant before trusting results. Do not derive a mutation score from unclassified execution failures.

## Repair and compare

Pin observable behavior before restructuring. Observe a regression fail for the expected reason where practical, make the smallest adequate correction and rerun affected guarantees. An impractical honest test is a disclosed gap; a weak implementation-mirroring test is not a substitute.

Report entry-point CC and the largest related extracted helper together, compatible coverage/CRAP, before/after source digests and scope. Moving branches can improve comprehension without reducing total work. Preserve ordering, error behavior and ownership; do not split clear dispatch merely to cross a threshold.

If two repairs fail the same acceptance criterion, state their shared premise and test a discriminating counterexample before another patch. Prefer one decision owner and a suitable data shape. Separate independent mutable state and serialize state that must be shared. Add a glossary only when terminology creates real ambiguity. Use existing Code Audit/Build Loop ownership rather than another workflow.

End a scored review with numerical results, coverage gaps, candidate dispositions and executed checks. Fewer lines, lower CC and stronger tests support different claims. Measure comparable runtime/memory workloads before claiming a performance gain.
