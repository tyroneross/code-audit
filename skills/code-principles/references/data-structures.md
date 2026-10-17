# Data structures selected for the operation

Use this reference when lookup, membership, grouping, ordering, queueing or repeated scans matter to the task. Start with the actual operation and required behavior; choosing a fashionable structure is not an improvement.

## Define the problem before choosing a structure

- **Data shape:** what each record means, how identity is defined, and whether duplicates are meaningful.
- **Operations:** which reads, writes, membership checks, insertions, removals and traversals occur, and how often.
- **Workload:** typical and difficult input sizes, distribution of keys, ordering, and mutation frequency.
- **Constraints:** output order, numerical precision, memory budget, concurrency and supported input types.

A scan visits entries to find a match. An index stores a relationship that makes later queries cheaper, at the cost of construction, memory and maintenance. A per-operation index expires when that operation ends; a persistent cache needs explicit freshness and invalidation behavior. Do not turn a temporary lookup table into a cache without a requirement.

## Select a candidate

| Operation | Candidate | Contract questions |
|---|---|---|
| Sequential traversal, preserve order and duplicates | List or array | Are position and duplicate entries observable? What are the runtime's insertion and allocation costs? |
| Repeated lookup by identity | Map or dictionary | Are keys stable and supported? Which duplicate wins? What happens when the key is missing? |
| Membership or uniqueness | Set | May duplicates and sequence be discarded? How does equality work? |
| Process first-in-first-out or both ends | Queue or deque | Is capacity bounded? What happens on overload? Does processing order matter? |
| Repeatedly select the next priority item | Heap or priority queue | How are ties, changed priorities and cancelled entries handled? A heap is not a fully sorted sequence. |
| Ordered lookup or range queries | Sorted sequence, ordered tree or database index | How often is the collection updated? Is the order compatible with the required comparison semantics? |

Prefer an existing language or database facility. These are candidates to compare, not requirements to introduce a new abstraction. Python's [built-in types](https://docs.python.org/3/library/stdtypes.html), [deque](https://docs.python.org/3/library/collections.html#collections.deque) and [heap operations](https://docs.python.org/3/library/heapq.html) document concrete behavior; consult the actual target runtime for other languages.

## Understand cost without confusing it with elapsed time

Time complexity describes how work grows with input size under stated assumptions. Space complexity describes storage growth. Amortized cost spreads a bound across an operation sequence; it does not guarantee the cost of each operation or describe an expectation over random inputs. None of these by itself establishes production latency.

For repeated searches through a catalog of n records across m items, a full scan per item can perform work proportional to n times m. Building one hash index can instead make total work approximately proportional to n plus m under ordinary hashing assumptions. Include index construction and memory in the comparison. One lookup in a tiny catalog may not justify a new index.

## Preserve meaning during optimization

Replacing a first-match scan with a dictionary comprehension can silently change duplicate handling to last-match-wins. Preserve the first match deliberately when that is the contract. Likewise, converting a sequence to a set can lose duplicates and order; replacing Decimal values with floats can change numerical behavior.

Check missing versus null versus zero, stable output order, repeated records, empty input and supported custom types. Eager indexing can also inspect records that the original lazy scan never touched, changing error timing or side effects. Bound the supported contract before making that change.

## Verify the candidate

Compare original and candidate outputs on the same representative and boundary inputs, including types, order and errors that callers rely on. Count repeated work at several input sizes when testing a growth hypothesis. For a speed claim, measure both versions on the same workload and environment, including setup costs. Check memory when additional storage matters. Keep reduced operation count, measured runtime and end-user improvement as separate observations.
