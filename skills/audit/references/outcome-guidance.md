# Improve a defined operation and verify the actual result

Recommend the least costly change that improves a required outcome while preserving the behavior users and callers need. Principles guide the choice; they are not a score or a demand to change every applicable component.

Use the [optimization playbook](optimization-playbook.md) for the shortest adequate improvement workflow. Its [research register](research-evidence.md) separates academic findings from engineering decisions. Reuse the codebase's existing tests, profilers and analysis; routine fixes do not require new measurement machinery or a formal thirty-rule report.

## Define what improvement means here

| Outcome | Establish before choosing a change | Useful observation |
|---|---|---|
| Scalability | Which input size, concurrency, data volume or ownership growth must work, under what resource constraints | Supported workload and failure behavior at that scale; capacity or throughput when claiming a numeric gain |
| Speed | Which user operation is too slow, under which workload and runtime conditions | End-to-end latency, including the relevant cold/warm and failure paths; repeated samples when noise matters |
| Correctness or accuracy | The required result and a credible oracle: examples, invariants, real fixtures or reviewed ground truth | Before/after behavioral checks; measured error rates when the claim is quantitative |
| Efficiency | Which resource or recurring cost matters: memory, CPU, I/O, calls, tokens, operating effort or maintenance | Resource use for the same meaningful work; retain the required result and failure guarantees |

“More accurate” can mean correct application logic, faithful data extraction, fewer model errors, or a better source-grounded recommendation. Name the meaning. A model's confidence, test count or schema pass is not accuracy against ground truth. A semantic-quality claim needs a representative, labeled evaluation; this plugin does not supply a universally calibrated evaluator.

Do not impose a numeric target on an ordinary correctness repair when a concrete behavioral contract is sufficient. Do not invent workload, baseline or user preferences. Record missing information and collect the evidence that could change the decision. If missing context blocks one optimization, continue other authorized improvements whose required outcomes are established.

## Establish the baseline and preserve required behavior

Name the operation, relevant caller, actual input/workload, baseline state, desired outcome, constraints and verification boundary. Baseline is `observed` with exact evidence or `unknown` with a specific explanation. A source observation can establish a static correctness problem; it cannot establish a latency or memory gain. Record required compatibility, results, ordering, recovery and resource guarantees before changing them.

Use the repository's existing tests, type checks, linters, profilers and benchmark runner when they address the required boundary. Read commands and their effects before execution. The deterministic collector/checker never executes discovered commands, benchmarks or repairs. A scan alone is read-only; an authorized improvement proceeds through the host's existing build process.

For a performance comparison, keep workload, operation semantics, units, build/runtime configuration and relevant environment comparable. Separate baseline and after source identities. Account for warm-up, caching, concurrency and measurement variation when they could alter the conclusion. A single noisy timing is not a reliable gain; faster work that silently skips required results is not an improvement. Report regressions and resource costs as well as the selected gain.

## Recommend a context-dependent decision

For each material decision, state:

1. `change`, `keep` or `investigate`, with a concrete priority.
2. The relevant principles and their applicable best practice in plain language.
3. The preferred approach and why it beats the viable alternatives here.
4. Separate code impact and user impact, each labeled `observed`, `expected` or `unknown` and cited when observed.
5. The main cost and alternatives with the conditions under which each would be preferable.
6. The assumption change that would reopen the decision.
7. A verification plan with an observable result and the boundary it proves.

“User” may mean an end user, operator, developer or receiving coding agent; name the actual actor. A maintainability change can benefit maintainers without establishing a direct end-user benefit. Do not invent that benefit to fill a field. Keep a good current design when another abstraction, service or optimization adds cost without a required guarantee.

Alternatives may combine or form stages. Do not invent options or numerical benefit estimates merely to populate a table. Mechanical checks establish completeness and internal consistency; the host reviewer still judges context, causality, evidence quality and whether the preferred approach is justified.

## Verify improvements without overstating them

New audit packets use report version 2. Run `audit.py validate --require-complete --require-outcomes --check-current-root` before using an outcome-based report. Existing version-1 reports remain readable, but do not acquire the new checks merely by validating successfully.

A `proposed` decision is advice. `implemented_unverified` means code changed but required evidence is missing. `verified` requires an actual change, observed baselines, before/after evidence and an executed check at the stated boundary. Every numeric objective needs comparable, evidence-bearing before/after measurements that improve the declared direction. This arithmetic check does not authenticate receipts, establish statistical significance or decide whether the workload represents users.

Before calling a repair verified, reproduce the original failure on the prior source, observe the intended result on the changed source, and check relevant old behavior. Before claiming faster, more scalable or more efficient, observe that outcome under the specified workload. Before claiming better model accuracy, compare against the stated oracle and evaluation population. Preserve unknowns instead of upgrading a prediction to an observed gain.

Use the [version-2 decision contract](recommendation-contract.md), [audit report contract](report-contract.md), [specialist reviewer](reviewer-role.md), and [improve workflow](../../improve/SKILL.md). Planning uses the same operation, baseline, workload and verification context before implementation; record unresolved material premises rather than using a structurally ready plan as proof they are true.
