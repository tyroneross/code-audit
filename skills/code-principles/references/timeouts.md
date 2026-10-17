# Choose timeouts from evidence or explicit assumptions

Use when adding or changing a timeout, investigating slow completion, or reviewing an unexplained timing constant. A timeout bounds waiting; it does not establish that underlying work stopped or that a write failed.

## State what the limit covers

Distinguish connection setup, request completion, idle/progress waiting and the total operation deadline. Check whether the implementation includes DNS, TLS, queueing, process startup and response reading. An idle timer that resets on progress does not by itself bound the whole operation.

A client timeout parameter may bound individual phases or inactivity rather than total elapsed time. Verify the actual client semantics and use the existing outer deadline mechanism when the operation requires a total budget.

For an intentionally long-lived stream or supervised process, define its lifecycle, liveness checks and shutdown behavior instead of copying a short request-completion timeout. Different phases can need different justified limits.

## Justify the value

Use observed latency distributions for the relevant workload, environment and load when available. Include cold starts and network conditions that affect intended users. Choose an acceptable rate of timing out work that would otherwise succeed, and reconcile it with the user's waiting tolerance and resource budget. A percentile from a different service or environment is not a justified default. AWS describes this latency-based method and its pitfalls. [Timeouts and retries](https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/)

When measurements are unavailable, record the assumed normal and slow behavior, the chosen limit, its rationale and what observation would justify revisiting it. A reasonable provisional assumption is acceptable; an unexplained copied value is not evidence.

## Budget the whole operation

Propagate remaining time through nested calls instead of restarting a full budget at each layer. Account for attempts, backoff and cleanup. Leave justified headroom below an external host deadline. Avoid retries that amplify overload or repeat uncertain side effects; a larger timeout must not conceal unbounded or redundant work. [Google SRE on cascading failures](https://sre.google/sre-book/addressing-cascading-failures/)

## Verify the choice and timeout behavior

Check normal completion, slow valid completion, a stalled dependency, cancellation and partial effects where applicable. Use controlled timing or existing timeout tools rather than long sleeps. Observe elapsed operation time, resource release and truthful result state. Monitor timeout frequency and retry load when runtime evidence is available; do not introduce an adaptive controller or telemetry system for every small change.

Keep the decision compact: covered operation; data source or assumption; chosen value; overall budget; timeout action; and a reason to revisit. Do not invent a latency measurement, universal duration or optimal value.
