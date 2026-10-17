---
name: plan
description: Structured thirty-principle plan packet before a large change. Use only when the user explicitly asks for a principles plan; otherwise apply the code-principles checklist while planning.
user-invocable: false
---

# Incorporate engineering principles before writing code

Produce a concrete implementation plan grounded in the actual request and code. The host agent makes the decisions; the checker rejects incomplete decisions but cannot prove optimality. User instructions and repository authority prevail.

Read [outcome guidance](../audit/references/outcome-guidance.md) before choosing an improvement. Name the operation, required result, representative workload, baseline, desired improvement and preserved constraints. “Accurate” needs a defined oracle. Use plan context to label observed baseline facts and unknowns; preserve their source locators. A missing performance baseline may justify a measurement step, but does not justify claiming an optimization or ignoring a material unresolved premise.

For optimization, use the [playbook](../audit/references/optimization-playbook.md). A routine local patch needs a short plan naming the wasted work, simplest fix, relevant principle/tradeoff and existing verification. Use the structured thirty-decision plan below for an explicit comprehensive plan or broader change where it adds value. Compact rendering retains actual decisions, rationale, citations and checks while linking full options/adaptations; all thirty dispositions remain in a structured plan.

## Load only the needed context

The remaining sections describe structured planning. A routine local patch can use the short plan above and continue through the host's existing build process; do not create a snapshot and thirty-decision artifact merely to satisfy procedure.

Resolve this skill's real filesystem location through symlinks. Its sibling `../audit/` contains the shared scripts and source catalog. Read [audit interpretation](../audit/references/audit-interpretation.json) and the [thirty-rule index](../audit/references/rule-index.md). Read the actual repository contracts, target source, callers and relevant tests. Ask only about unresolved information that materially changes the decision; continue independent work while waiting.

Prepare a bounded source snapshot through the [audit skill](../audit/SKILL.md). For a large repository, use the [improve workflow](../improve/SKILL.md) to discover relevant boundaries, then select a focused snapshot including dependencies. A path-order batch is not an architecture or call graph.

Save the actual goal in a text file outside the target and run:

```text
python3 <plugin-root>/skills/audit/scripts/planning.py prepare --root <repo> --snapshot <snapshot> --goal-file <goal.txt> --out <new-plan-folder>
```

Read `context.md` before designing implementation steps. It states every principle's rule, purpose, mechanism, applicability and premises. Review unsafe uses as well as justified techniques: unsafe retries remain relevant, and value-validation examples are not mandatory wrappers or unit tests in unrelated code.

## Decide, then connect decisions to work

Save a new `plan.json` from `plan-template.json`. Preserve all thirty IDs. Each decision is `apply`, `exclude` with a contextual reason, or `needs_context`; leave `unreviewed` when work has not happened. Do not mark a principle applicable because a keyword appears, or exclude it just because the recommended technique's prerequisites are absent.

Record source observations with exact snapshot locators, user statements as such, and assumptions explicitly. For every applied principle, record the actual premises, chosen approach, cost/tradeoff, what change would invalidate it, and verification with an observable expected result and boundary. Adapt the approach when assumptions change. Options may combine or form stages.

Define concrete acceptance outcomes and proposed scope. Each implementation step names its action, paths and applied principle IDs. Every applied principle must affect at least one real step; listing a rule without changing any decision does not complete the plan. An exclusion or unresolved rule cannot be attached as if it were implemented. Missing context that changes the plan remains unresolved.

```text
python3 <plugin-root>/skills/audit/scripts/planning.py check --snapshot <snapshot> --plan <plan.json> --require-ready --check-current-root <repo>
python3 <plugin-root>/skills/audit/scripts/planning.py render --snapshot <snapshot> --plan <plan.json> --require-ready --check-current-root <repo> --compact --out <new-agent-plan.md>
```

Before implementation, read the rendered plan and the selected rule cards. The packet preserves the why, alternatives/costs and adaptation triggers as well as this plan's actual choices. Run the [specialist reviewer procedure](../audit/references/reviewer-role.md) against the reasoning, accepted behavior, scope and verification. Use an independent worker only when the session authorizes delegation and the host supports it; otherwise perform an explicit lead-session review and report that boundary honestly.

Begin code changes only when the required plan check passes and meaningful unresolved choices are settled. A checked plan does not grant permissions or prove that an assumption is true. The actual user's goal and existing repository process determine allowed effects.

## Keep the plan connected during execution

Give implementers the rendered packet and source locators, not just principle names. Use the host's existing build workflow. When a dependency, failure model, consumer or constraint changes, revisit the affected decision and its verification before proceeding. Do not add layers, services, wrappers, retries or tests merely to display compliance.

After code changes, verify the promised outcome at the stated boundary and perform the focused audit. Treat planned checks and executed receipts separately. Summarize what changed, which principles altered a decision, the observed verification, and remaining gaps. Never report structural plan readiness as a successful implementation.

The post-change audit uses version-2 objectives and recommendations. Explain code/user impact and viable alternatives before implementation; compare numeric outcomes on comparable work afterwards. Keep an expected benefit labeled expected until the required actual checks establish it. The current plan checker validates structural readiness, not measurement representativeness or causal improvement.
