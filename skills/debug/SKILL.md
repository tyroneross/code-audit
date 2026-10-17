---
name: debug
description: Investigate and repair code failures by tracing causal mechanisms, consulting incident memory when available and verifying supported behavior.
user-invocable: false
---

# Debug with shared audit principles

```text
identify symptoms, expected behavior, revision and authorized scope
if memory available: search symptoms and inspect candidate context
reproduce when feasible; record original-environment gaps
trace plausible causes through shared state and failure boundaries
predict a check that distinguishes the strongest cause from alternatives
compare the symptom patch with the simplest adequate mechanism repair
repair in scope; run the prediction, reproducer and affected regressions
seek independent critique when available; disclose its actual status
report evidence and gaps; store evidence-supported repair history
```

For a review-only request, investigate and report proposed repairs without applying code changes, writing workflow state or storing incidents unless separately authorized.

Load [shared principles](../code-principles/SKILL.md) and relevant challenge references. For a recurrent, disputed or nontrivial cause follow [the deeper loop](../debug-loop/SKILL.md). For an obvious cause use a short investigate, fix, verify sequence. A past KNOWN_FIX still requires validation against current contracts and verification.

The bundled MCP server `code-audit-debugger` supplies search, detail, store, outcome, status, list, patterns and read_logs. Use actual host-exposed names. If unavailable, report that memory was not checked and continue with source/log/test evidence. Never invent matches or successful storage. Do not write another host's personal assistant memory.

The procedure is host-neutral. Investigate directly when a host lacks agent registration. Independent critique requires an actual independent execution; self-review cannot substitute for it. If unavailable, mark critique UNAVAILABLE and deliver bounded results with that gap disclosed.

Timeouts can leave completed writes behind. Preserve logical identity, reconcile uncertain effects, retry at one layer, choose limits from relevant observations or explicit reasonable assumptions, and propagate the total deadline. Increasing a timeout alone does not prevent duplicate effects.
