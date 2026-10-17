# Investigate change and failure isolation

Use when a bug, repair or restart can interrupt unrelated work. Identify the component, state owner, process/restart boundary, affected clients and shared resources before choosing recovery. Source modules and static libraries do not establish independent process lifecycles.

Trace how a failure propagates through queues, locks, storage, supervision and dependent calls. A shared state owner can be the correct repair site; an independent process or bounded resource pool can be appropriate when containment is an actual requirement. Include compatibility, operating cost and rollback in that comparison rather than splitting every component. [Bulkheads](https://learn.microsoft.com/en-us/azure/architecture/patterns/bulkhead), [service-boundary costs](https://martinfowler.com/bliki/MonolithFirst.html)

Keep reachable, healthy, compatible and feature-available separate. A parsed RPC error is not a compatibility success. Check actual server identity/version/capabilities; do not substitute local client constants. Avoid global teardown as a reflex response to an unknown or feature-specific failure.

Storage behavior needs separate evidence from process isolation. SQLite WAL permits concurrent readers and a writer but only one writer at a time. Moving code into another process does not automatically remove writer or queue contention. [SQLite WAL](https://www.sqlite.org/wal.html)

For an isolation claim, use an authorized controlled test that stalls or restarts the affected component while unrelated work continues. Observe identities, live progress and usable output; persisted history or passing unit tests alone do not establish continuity. Include intentional timeout, bounded restart/backpressure and commit-before-lost-response behavior where relevant. Do not inject failures into production without authorization.

Check whether existing tests encode an older policy that the approved goal supersedes. State the conflict, retain unrelated guarantees and update the specific acceptance checks; neither blindly preserving the old behavior nor deleting failing tests is adequate. Record the exact source revision, controlled reproduction and untested runtime boundaries with any debugger incident.
