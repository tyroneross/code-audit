# Improve the operation users need, then verify the useful gain

Choose a change only when it addresses a required behavior or a supported bottleneck, preserves necessary guarantees, and is worth its implementation and operating cost. The thirty principles explain the choices and their premises. They do not require thirty techniques, a rewrite, or simultaneous improvement of every outcome. See the [research register](research-evidence.md) for evidence and transfer limits.

## Define the decision before searching for changes

Name the operation, required result, relevant workload and constraints. Inspect existing requirements, callers, tests and measurements first. Ask only for material facts or preferences that remain missing. State what improvement would be useful and when to stop; do not invent numerical targets.

A correctness defect can justify repair without a performance baseline. A performance hypothesis can justify a bounded investigation without justifying a rewrite. If the current implementation meets the required workload and guarantees, keep it unless another demonstrated benefit outweighs the change cost.

For a large repository, start with user-critical paths and shared boundaries, guided by actual incidents, profiles and dependencies. Reuse existing analysis tools. Syntactic signals and path order are attention leads, never defect or quality scores.

Read relevant or uncertain rule cards for context, options and changed assumptions; unsafe uses remain relevant when safe prerequisites are absent. Routine patches need a short plan and targeted review. Use the compact index and all thirty dispositions when a comprehensive review is selected. Reuse prior decisions only while source and dependency premises hold; targeted coverage is not whole-repository coverage.

## Locate the cause that limits the outcome

Trace the complete operation before optimizing a line. Profile using the repository's current tools under representative inputs. Separate CPU computation, allocations/memory, I/O or database/API calls, serialization, locks/queues and downstream waits. Check call counts as well as individual call costs. Compare relevant input sizes and concurrency levels; the bottleneck can move as the workload changes. Observe end-to-end behavior after changing a local component. An expensive but necessary operation is not automatically replaceable.

| Observed situation | First candidate to consider | Main cost or condition that changes the choice |
|---|---|---|
| Repeated scans dominate as data grows | Better algorithm/index or reuse a lookup within the operation | Index memory, construction and update cost; small/rare inputs can favor the simpler scan |
| Repeated identical work dominates | Reuse or cache at a proven stable boundary | Invalidation, tenant/identity scope, freshness and memory; do not cache unknown mutable semantics |
| Many remote/database calls dominate | Eliminate redundant calls or batch compatible work | Ordering, transaction boundaries, batch memory and failure isolation; measure the whole caller |
| Memory grows with input and causes failures | Stream/chunk or reduce retained data | Extra passes, I/O, partial-failure handling and ordering; retain required results |
| Queues or locks dominate under load | Bound concurrency, reduce shared work or shorten the actual critical section | Throughput, fairness, cancellation and dependency capacity; more parallelism can increase overload |
| CPU remains the demonstrated limit | Algorithm/data structure first; then a suitable existing optimized API or parallelism | API semantics, conversion overhead, allocation and runtime limits |
| Low-load latency is good, high-load tails fail | Load ladder with tail, queues, throughput, errors and saturation | Reject a median-only capacity claim; avoid universal hedging/retry advice |
| Results are wrong or model/extraction errors matter | Fix the actual invariant or decision path; evaluate against the oracle | False-positive/negative costs, valid input domain and representative held-out data |
| Only a code-shape preference is present | Keep or investigate | A preferred style, long function or missing abstraction is not an observed defect |

These are candidate strategies, not scanner verdicts. Apply the matching principle's actual context and counterevidence. Read neighboring callers and compatibility before editing. Prefer the smallest adequate change; add a service, dependency or migration only when the required guarantee justifies its cost.

## Compare candidates without losing correctness or resources

Before implementation, preserve the baseline, required behavior and compatible callers. Compare the relevant outcome and secondary costs such as memory, tail latency, error rate or dependency load. Explain the accepted tradeoff. A faster operation that omits required work fails the decision.

Use the repository's existing tests, profiler and benchmark runner. Profilers locate expensive work; comparable before/after runs check a performance claim. Inspect commands and effects through the authorized host process. The plugin never executes commands found in source or receipts.

Keep workload, behavior, build/runtime, data and warm/cold conditions comparable. Remeasure the baseline alongside the candidate and use enough independent runs to address meaningful noise. Inner-loop repetitions are not automatically independent runs. Retain adverse results and account for setup/order bias. Use the runner's suitable analysis rather than building another statistics system.

Confirm a chosen candidate on fresh representative work after exploratory search. Do not repeatedly sample until a favorable result appears. Label unmeasured or noisy benefits expected/uncertain. A formal report's valid structure does not prove runtime gains.

## Test behavior and stop proportionally

Re-run the original case and relevant regressions. Add boundary/property, differential, concurrency/failure or load checks only when they address a real risk. Valid input contracts matter; test counts and model confidence do not establish accuracy. Model/data accuracy needs an appropriate oracle and representative labeled examples.

Keep or investigate when the gain is within uncertainty, the practical benefit is too small, a guardrail fails/remains unknown, the oracle is missing, or migration/maintenance costs exceed demonstrated value. Record adverse results and rejected approaches so the next agent does not repeat them. Stop candidate search at its predeclared budget and reassess if new evidence changes expected value. Agent tokens, elapsed investigation time, review/rework and human effort are separate costs from the optimized program's runtime.

To evaluate the plugin, compare it with a plain review on the same blinded cases, including defects, safe exceptions and missing-context cases. Retain misses, unsupported findings and effort costs. Small authored scenarios diagnose interpretation; they do not establish general accuracy or productivity gains. Use held-out historical issues and human adjudication for stronger claims.
