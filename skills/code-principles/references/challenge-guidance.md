# Guidance selected by the challenge

Read the relevant section when the operation requires deeper analysis. Define a term only when it changes the decision; do not require every task to traverse every topic.

If the contract is ambiguous, distinguish a conservative design choice from a confirmed defect. State the interpretation and seek clarification when it materially changes required behavior.

## Data structures and algorithms

Use when repeated lookup, membership, grouping, ordering or growth dominates the operation. A list preserves sequence and duplicates; a set represents unique membership; a mapping associates keys with values. An index trades construction work and memory for cheaper repeated lookup. Specify which duplicate wins, whether order is observable, whether keys are hashable and stable, and whether missing differs from null or zero. Compare total build-plus-query work at realistic sizes. Preserve value types and numerical precision. Do not introduce an index for a single cheap lookup without a reason. Check empty inputs, duplicate keys, unknown keys and equivalence to the original behavior. Operation counts can demonstrate reduced repeated work; they are not wall-clock speed measurements.

For deeper structure selection, cost definitions and contract traps, read [data structures](data-structures.md).

## Async state and concurrency

Use when requests overlap, finish out of order, time out or are cancelled. Cancellation requests termination; it is not proof that no later result or side effect can occur. Define which operation owns current state. Recheck ownership after suspension before publishing success, errors or cleanup. Distinguish newest-request-wins from process-every-request behavior. Test controlled completion order, stale success, stale failure and cancellation while another operation owns the state. Prefer existing task ownership or identity mechanisms over a new scheduler.

## Agent communication and dependency handoffs

Use when one agent's work depends on another agent's output. Assess every dependency against four questions:

| Question | Evidence to inspect |
|---|---|
| Which exact artifact or revision must exist? | A resolvable artifact path or reference and its commit, content hash or version; the producer and consumer must refer to the same output. |
| Which validation must pass? | The required check, its actual result and the artifact or revision it covered. A planned check or worker's completion claim does not establish a pass. |
| What must the receiving agent read? | Explicit files, sections, decisions or result references needed for the dependent task, with evidence of reading before claiming the context was loaded. |
| What proves the receiving agent accepted the handoff? | Recipient-authored acceptance, or an authenticated recipient action defined by the existing protocol, tied to this handoff and artifact or revision. |

Trace the actual producer, dependency-readiness decision, receiver context and acceptance record. Scheduling order alone does not establish context transfer. Distinguish recorded, delivered, read, accepted and task-completed evidence; a queued message, successful send or sender-authored assertion does not prove recipient acceptance. If the artifact changes, reassess the affected validation, reading and acceptance evidence before reusing it.

Missing evidence remains unresolved, not a passed readiness check. If the dependency is inapplicable, explain why. Reuse existing task, artifact and receipt identifiers; these questions do not require a new scheduler, ledger or transport. Keep a review read-only unless repairs or communication are authorized.

Basis: Tyrone Ross's 2026-10-25 request to adopt the four questions following a source review of `affaan-m/claude-swarm`; this is adopted review guidance, not a claim of measured coordination improvement.

## CLI usability and human factors

Use when people operate commands, recover failures or authorize persistent effects. A preview describes intended effects without applying them. Explicit application separates inspection from mutation. Make scope, current mode and result visible. Avoid requiring memory of hidden defaults. Return useful failure status and preserve diagnostic context without leaking secrets. Test help, default invocation, deliberate application, mistaken input and a representative failure using temporary data. Do not claim a write succeeded until its result is known. A CLI walkthrough supports command behavior; it does not establish general human usability.

## Timeouts, deadlines and retries

For missing, arbitrary or repeatedly increased limits, read [timeout guidance](timeouts.md). Select a value from relevant observations or a stated assumption, budget the whole operation, and verify cancellation and uncertain effects. Raising the limit is not a repair for duplicate work, a stalled dependency or incorrect ownership.

## Unused code and stale configuration

For removal decisions, read [removal evidence](removal-evidence.md). Trace indirect consumers and operational safeguards; distinguish missing observations from evidence that removal preserves supported behavior.
