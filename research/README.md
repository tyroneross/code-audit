# Research catalog

Start with the challenge and load the smallest useful reference. These sources support contextual engineering judgment, not universal mandates or proof of plugin effectiveness. Guidance checked October 16, 2026; refresh version-specific claims when used.

| Challenge | Packaged guidance | Source and boundary |
|---|---|---|
| Simplicity | [Foundations](../skills/code-principles/references/engineering-foundations.md) | [Google review guidance](https://google.github.io/eng-practices/review/reviewer/looking-for.html): assess consequences and avoid speculative generality. |
| Systems engineering | [Foundations](../skills/code-principles/references/engineering-foundations.md) | [NASA system design](https://www.nasa.gov/reference/4-0-system-design-processes/), [verification/validation](https://www.nasa.gov/reference/5-0-product-realization/): adapt requirements and intended-use checks proportionately. |
| Usability and human factors | [Foundations](../skills/code-principles/references/engineering-foundations.md) | [Nielsen's heuristics](https://www.nngroup.com/articles/ten-usability-heuristics/): risks need contextual inspection or observation. |
| Whole-system repair | [Mechanism repair](../skills/code-principles/references/whole-system-repair.md) | [Google review guidance](https://google.github.io/eng-practices/review/reviewer/looking-for.html): fix demonstrated shared causes without speculative frameworks. |
| Timeouts and retries | [Timeouts](../skills/code-principles/references/timeouts.md) | [AWS Builders' Library](https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/): relevant latency, assumptions, deadlines and effect identity. |
| Failure isolation | [Isolation](../skills/code-principles/references/change-isolation.md) | [Azure bulkhead](https://learn.microsoft.com/en-us/azure/architecture/patterns/bulkhead), [SQLite WAL](https://www.sqlite.org/wal.html): modular source does not prove independent runtime/storage. |
| Data structures and performance | [Data structures](../skills/code-principles/references/data-structures.md), [research evidence](../skills/audit/references/research-evidence.md) | Growth/work-count evidence is distinct from measured production latency. |
| Thirty contextual principles | [Rule index](../skills/audit/references/rule-index.md), [frozen sources](../skills/audit/references/rules.json) | Read the applicable card's premise, options, costs, sources and counterevidence; no universal compliance score. |

## Add research

Record the problem, source title/URL and retrieval date, supported claim, applicable environment/version, limits and counterevidence. Distinguish source fact, inference, hypothesis and observed outcome. Keep private code and incidents out of shared research. Add checks for consequential defects and meaningful inefficiencies rather than checklist growth.
