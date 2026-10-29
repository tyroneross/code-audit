---
name: code-principles
description: Review non-trivial code for broken contracts and wasted work; trace affected paths and verify proportionate corrections. Load detailed checks only for the actual challenge.
user-invocable: false
---

# Focused code review

Review the requested operation against its explicit contract. Inspect changed code and affected callers, state owners, registration and failure paths. Use source evidence, not a checklist hit alone, to confirm a trigger, cause and consequence. Consider counterevidence and intentional behavior; clean code needs no finding. Missing a preferred technique alone is not a defect.

Trace the simplest adequate correction across affected paths. Preserve output semantics, ordering, error contracts, supported consumers, operation identity, retry ownership, deadlines and recovery behavior. An error handler is defective when it loses required behavior or hides incomplete work; an intentional terminal or best-effort handler can be valid. Sequential work and fixed limits can be intentional. Only claim measured performance gains from actual comparable measurements.

For cleanup, check dynamic registrations, external consumers, flag prerequisite edges and emergency paths before calling code unused. Absence in sampled telemetry is not proof of disuse. Remove only behavior the supplied contract permits removing.

Keep severity separate from introduced/pre-existing origin. Reconcile prior findings: suppress unchanged resolved issues; reopen the same identity or explicitly link it when a closure premise changes. Cover unchanged callers affected by a changed contract. Group instances of one cause; do not invent nits or duplicates.

Historical memory offers hypotheses. Check applicability, invalidation and failed approaches before reuse; no retrieval score proves current causality. Missing tools or skipped inputs are coverage gaps, not clean reviews. Do not write incidents or repair code during review-only work. In an authorized repair, reproduce when feasible, correct the cause and verify affected guarantees. Distinguish proposed checks, executed tests, runtime and deployment.

Return material findings with trigger, causal explanation, location, consequence, smallest adequate action and discriminating verification. Report no material findings when supported. Do not fabricate execution or certainty.

## Load details when needed

- Re-review, disputed findings, changed closure premises or review-budget decisions: [review feedback](references/review-feedback.md).
- Agent communication, dependency readiness or handoff acceptance: [dependency handoff checks](references/challenge-guidance.md#agent-communication-and-dependency-handoffs).
- A concrete performance, retry, concurrency, failure or contract concern: the relevant section of [focused checklist](references/focused-checklist.md), then its linked rule cards. Do not load all cards for a small review.
- Choosing correction scope or engineering tradeoffs: [foundations](references/engineering-foundations.md), [whole-system repair](references/whole-system-repair.md) and [challenge guidance](references/challenge-guidance.md) as applicable.
- Available incident memory: follow [debugging memory](../debugging-memory/SKILL.md), check actual project scope, and load [incident learning](references/incident-learning.md) for lifecycle or recording questions. If unavailable, continue source investigation and disclose that limit.
- Optional source scan: run `python3 <skill-dir>/scripts/scan.py --help` for supported selection and output arguments. Hits are candidates; confirm them against source and callers. Record authorized outcomes using the existing outcome tool, not a new ledger.
- Explicit full audit, pre-build plan or repository campaign: [audit](../audit/SKILL.md), [plan](../plan/SKILL.md) or [improve](../improve/SKILL.md).

Resolve paths from this installed skill folder. A review alone remains read-only. Keep routine output short; do not require every report field or persistent workflow state for a small task.
