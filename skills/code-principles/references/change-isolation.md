# Check change, restart and failure boundaries

Use when a component is changed, restarted, upgraded or moved, especially when unrelated work must continue. A folder, class, crate or static library is a source boundary; it does not by itself establish an independent process lifecycle or fault boundary.

## Choose a boundary that fits the required outcome

Hide design decisions behind a small contract so callers need not change with the implementation. That supports independent source changes; runtime isolation needs its own mechanism and evidence. [Parnas on decomposition](https://www.cs.lafayette.edu/~gexia/cs301/resources/parnas.html)

Identify the component owner, state owner, affected clients, process owner and restart scope. Check which resources remain shared: queues, pools, locks, storage and supervision. Partition a demonstrated failure path or resource bottleneck when the continuity requirement warrants the cost. Do not split every view into a service. [Bulkheads](https://learn.microsoft.com/en-us/azure/architecture/patterns/bulkhead), [service-boundary costs](https://martinfowler.com/bliki/MonolithFirst.html)

Separate process isolation from storage concurrency. For example, SQLite WAL supports concurrent readers and a writer but still permits only one writer at a time; separate processes do not remove that contention. [SQLite WAL](https://www.sqlite.org/wal.html)

## Verify compatibility and recovery

Distinguish reachable, healthy, compatible and feature-available. Parsing a reply—even a valid RPC error—does not establish server compatibility. Observe server identity, protocol version and required capabilities rather than reporting client-local constants as server facts. Unknown must remain unknown.

Check version/schema transition, state handover, bounded admission, intentional deadlines, idempotent retry and uncertain outcomes. Define which component can restart or roll back and whether its saved data remains usable afterward. A local failure must not automatically trigger a global replacement unless the approved recovery policy requires it.

## Test continuity at the claimed boundary

When claiming isolation, stall or restart the affected component in an authorized controlled environment while unrelated work continues. Assert actual continuity—identity, work progress and usable output—rather than merely process presence or restored history. Exercise a representative incompatible reply, missing capability, saturated queue or commit-before-lost-response case when that mechanism matters. Reuse existing test and fault-injection tools.

Passing tests can preserve an old policy that conflicts with a new requirement. Identify that conflict explicitly, update tests to the approved contract, and retain unrelated guarantees; do not delete failing checks merely to make a change pass. Source tests, component tests and observed runtime continuity support different claims. None alone establishes zero downtime for every component.
