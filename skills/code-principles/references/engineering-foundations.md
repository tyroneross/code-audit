# Engineering foundations for debugging and review

Improve the user's whole task with the simplest adequate system. Review implementation correctness, system behavior and human use together. Apply the relevant criteria below; a small repair does not require a full audit or a new framework.

## Simplicity

| Criterion | Failure pattern to investigate | Useful check |
|---|---|---|
| Remove unnecessary work and concepts | Duplicate state, unused options, repeated transformations, wrappers that only forward calls | Trace one real task. Identify what can be removed without losing required behavior or useful isolation. |
| Keep the main sequence understandable | Vague names, hidden effects, scattered conditions, excessive indirection | Follow the normal and failure paths from the entry point. Name each decision and effect using domain terms. |
| Give each fact a clear authority | Multiple editable copies of configuration or status drift apart | Identify who owns the value, who may change it, and how derived copies are refreshed. |
| Add abstraction for a demonstrated need | A generic framework for one case; functions split only to reduce line count | Compare the direct implementation with the abstraction, including caller complexity and maintenance. Keep the one that makes the required operation easier to understand. |

Simplicity means less total burden, not fewer visible lines. Removing validation, diagnostic context or a needed isolation boundary can make a system harder to operate. Repeated code is not automatically duplicated policy; combine it when it represents the same rule and should change together. Google reviews specifically examine unnecessary complexity and speculative generality. [Google code review guidance](https://google.github.io/eng-practices/review/reviewer/looking-for.html)

## Systems engineering

| Criterion | Failure pattern to investigate | Useful check |
|---|---|---|
| Trace the requirement to observable success | A component passes its tests while the user's task remains impossible | State actor, task, environment and success condition. Check the integrated outcome as well as component requirements. |
| Define boundaries and interfaces | Two components disagree about units, identity, timing, permissions or failure semantics | Inspect both ends of the interface, including inputs, outputs, errors and ownership. |
| Make state and ownership explicit | Old work overwrites current state; a background task survives its owner; retry repeats an uncertain write | Walk start, success, failure, timeout, cancellation, retry and restart. Identify who may publish each transition. |
| Assess whole-system effects | Faster local processing overloads a downstream queue or shifts work to the user | Compare end-to-end latency, resource use, errors and human effort under the same relevant workload. |
| Contain failure and support recovery | One dependency failure corrupts unrelated work; partial success cannot be reconciled | Follow a representative failure through its effects. Check isolation, durable state and a feasible recovery path. |

NASA connects intended use to requirements and interfaces, and distinguishes verification of requirements from validation against intended operation. These checks adapt that approach to small software changes; they do not import an aerospace documentation process. [System design](https://www.nasa.gov/reference/4-0-system-design-processes/), [product verification and validation](https://www.nasa.gov/reference/5-0-product-realization/)

For upgrades, shared daemons or claims that unrelated work survives a change, use [change and failure isolation](change-isolation.md). Distinguish source modularity from observed runtime continuity.

For agent lifecycle hooks, use [hook boundary checks](hook-boundaries.md). Verify host invocation, decision handling, scoped evidence and any required human approval before crediting a hook with enforcing the workflow.

## Usability

| Criterion | Failure pattern to investigate | Useful check |
|---|---|---|
| Make the next action discoverable | Hidden controls, unexplained arguments, inconsistent names or units | Attempt the intended task from its real starting point using only the available interface and help. |
| Show actual state and action results | A spinner never ends; success is shown before persistence; stale data looks current | Exercise pending, complete, partial, empty, stale and failed states that the operation supports. Check what the user sees at each point. |
| Prevent mistakes and make recovery practical | Destructive defaults, accidental repeat submission, errors that discard valid input | Try a plausible mistake. Check preservation of work, actionable feedback and undo or reconciliation where appropriate. |
| Support the actual access conditions | Clipped text, keyboard traps, unlabeled controls or instructions conveyed only by color | Inspect the rendered surface and relevant keyboard/assistive access at constrained sizes and with representative content. |

Apply these to command-line help, API error responses and agent tools too. A useful error names the failed operation, its consequence and an available next action. Nielsen's heuristics provide the basis for visibility, consistency, prevention, user control and recovery. [Usability heuristics](https://www.nngroup.com/articles/ten-usability-heuristics/)

## Human factors

| Criterion | Failure pattern to investigate | Useful check |
|---|---|---|
| Reduce memory burden | Users must remember IDs, previous values, hidden modes or instructions from another screen | Keep required context visible or easily retrievable. Check whether someone can resume after an interruption. |
| Match controls to expectations | The same label has different effects; current scope or mode is ambiguous | Check naming, control behavior and visible scope across adjacent tasks. |
| Allocate attention proportionately | Routine alerts crowd out consequential failures; confirmations become automatic clicking | Check that messages distinguish actionable problems, communicate consequence and arrive when action is useful. |
| Preserve human control over automation | Silent scope expansion, opaque recommendations, no way to stop or correct work | Show intended effects and current status. Provide cancellation or correction appropriate to the operation's consequences. |
| Evaluate total effort | Automation saves CPU time but creates repeated manual cleanup or checking | Observe task completion, errors, recovery effort and operator intervention; do not infer usability from implementation elegance. |

Recognition reduces recall demands; predictable controls and recovery support people who make mistakes or get interrupted. These are design criteria, not claims that a fixed number of choices or clicks is universally optimal. [Nielsen's heuristics](https://www.nngroup.com/articles/ten-usability-heuristics/). NASA includes the allocation of functions between people and systems in system design. [Human and system roles](https://www.nasa.gov/reference/4-0-system-design-processes/)

## Use with the existing debugger and audit records

For a finding, record the actual consequence, triggering conditions, affected boundary, smallest adequate correction and the check that distinguishes broken from corrected behavior. Use an existing checklist ID only when its premise fits. Foundation criteria without a matching ID can remain named findings in the review; do not invent IDs for the existing outcome logger.

When Coding Debugger is available, retrieve relevant incidents before diagnosis and link an applicable incident in the finding. Record a verified repair as an incident using the debugger's existing schema and verification fields. Keep a suspected usability problem or an untested recommendation distinct from a verified incident. Search related occurrences only after confirming the mechanism, and check each occurrence's context before applying a mechanical fix.

The tables are an engineering synthesis of the cited guidance, checked October 16, 2026. They do not establish that the combined workflow improves defect detection or repair quality; evaluate those outcomes on representative tasks.
