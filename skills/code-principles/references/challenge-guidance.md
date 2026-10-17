# Guidance selected by the challenge

Read the relevant section when the operation requires deeper analysis. Define a term only when it changes the decision; do not require every task to traverse every topic.

If the contract is ambiguous, distinguish a conservative design choice from a confirmed defect. State the interpretation and seek clarification when it materially changes required behavior.

## Data structures and algorithms

Use when repeated lookup, membership, grouping, ordering or growth dominates the operation. A list preserves sequence and duplicates; a set represents unique membership; a mapping associates keys with values. An index trades construction work and memory for cheaper repeated lookup. Specify which duplicate wins, whether order is observable, whether keys are hashable and stable, and whether missing differs from null or zero. Compare total build-plus-query work at realistic sizes. Preserve value types and numerical precision. Do not introduce an index for a single cheap lookup without a reason. Check empty inputs, duplicate keys, unknown keys and equivalence to the original behavior. Operation counts can demonstrate reduced repeated work; they are not wall-clock speed measurements.

For deeper structure selection, cost definitions and contract traps, read [data structures](data-structures.md).

## Async state and concurrency

Use when requests overlap, finish out of order, time out or are cancelled. Cancellation requests termination; it is not proof that no later result or side effect can occur. Define which operation owns current state. Recheck ownership after suspension before publishing success, errors or cleanup. Distinguish newest-request-wins from process-every-request behavior. Test controlled completion order, stale success, stale failure and cancellation while another operation owns the state. Prefer existing task ownership or identity mechanisms over a new scheduler.

## CLI usability and human factors

Use when people operate commands, recover failures or authorize persistent effects. A preview describes intended effects without applying them. Explicit application separates inspection from mutation. Make scope, current mode and result visible. Avoid requiring memory of hidden defaults. Return useful failure status and preserve diagnostic context without leaking secrets. Test help, default invocation, deliberate application, mistaken input and a representative failure using temporary data. Do not claim a write succeeded until its result is known. A CLI walkthrough supports command behavior; it does not establish general human usability.

## Timeouts, deadlines and retries

For missing, arbitrary or repeatedly increased limits, read [timeout guidance](timeouts.md). Select a value from relevant observations or a stated assumption, budget the whole operation, and verify cancellation and uncertain effects. Raising the limit is not a repair for duplicate work, a stalled dependency or incorrect ownership.
