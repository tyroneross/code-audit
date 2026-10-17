# Repair the shared cause within the relevant system

Use this check when a proposed fix handles one literal value, route, screen, caller or input size; repeats an earlier exception; or improves a component while worsening the user's whole task. A bounded fix can be correct. The question is whether its boundary follows the actual cause and supported requirements.

## Define what is being improved

State the user's outcome, affected operation, relevant state owners and downstream consumers. Include correctness, end-to-end work, resource limits, operator effort and maintenance where they matter. A symptom-level improvement can leave avoidable work or failure elsewhere in the operation; compare feasible alternatives against the combined requirements. Do not claim a mathematical global optimum without a defined objective and search space.

## Compare feasible approaches

Consider the best simple structure if the current implementation did not constrain the choice, the best repair under actual compatibility and delivery constraints, and the smallest credible path between them. When they are the same, say so. For a routine obvious fix, a short comparison is enough; do not invent three designs or a migration project.

Compare the visible symptom patch with a correction at the existing common owner. Identify which supported callers and cases each approach covers, what guarantees it preserves, where it moves work, and its complexity and migration costs. Prefer the shared causal correction when it is comparably simple and compatible. Reuse an existing interface, data structure or ownership boundary before introducing a framework.

Hardcoded values can represent real policy or protocol requirements. Do not remove them solely because they are constants. Flag a constant when its specific value substitutes for an inferred rule without evidence—for example, suppressing one failing account rather than repairing identity handling.

## Verify mechanism and coverage

Reproduce the reported failure when feasible. Otherwise record the causal evidence, missing reproduction conditions and limits, and verify a controlled case that distinguishes the proposed mechanism. Keep a verified controlled repair distinct from reproduction of the original incident. Vary relevant identity, caller, input size, ordering, failure timing or environment to test the mechanism. Include valid counterexamples that should remain unchanged. Search related occurrences after establishing the cause, and inspect each context before applying a mechanical change. Check the whole operation for shifted latency, load, stale state or manual cleanup.

Example: if several views disagree after updates, refreshing the one visible view may hide the symptom. Check whether they read different authorities or whether the common state owner publishes an incomplete update. Repairing that owner may remove several special refresh paths. Verify supported subscribers, an unrelated update and an out-of-order update; do not infer that every application needs a new event system.

## Keep action proportional and authorized

Understanding a wider cause does not authorize changing unrelated products or production state. Complete feasible causal repairs within the authorized scope. If a broader repair needs incompatible migration or unavailable authority, explain the constraint, implement only justified containment, and label the remaining cause unresolved. Do not present containment as a complete repair or use imagined future scale to justify speculative abstraction.
