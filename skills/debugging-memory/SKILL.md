---
name: debugging-memory
description: Consult stored debugging incidents before fresh investigation when the bundled memory MCP is available; validate past causes against current code and record evidence-supported outcomes.
user-invocable: false
---

# Debugging memory

```text
if memory unavailable: disclose the gap and continue source investigation
search the current symptom
load details only for plausible matches
before reuse: search candidate ID for linked invalidation/supersession records (best-effort)
validate lifecycle, cause, applicability, failed approaches and fix against current code
if a known fix fits: adapt it and verify current behavior
else: use ../debug/SKILL.md and investigate fresh
store trigger, cause, tried/rejected approaches, repair, evidence and limits when authorized
record whether an actually attempted retrieved fix worked, failed or modified
```

Resolve references from this skill's installed location. Use the actual host-exposed names for tools on `code-audit-debugger`.

Read [incident learning](../code-principles/references/incident-learning.md) when using or recording a lesson. Use existing MCP fields and narrative; do not invent lifecycle/verification update arguments.

## Retrieval is evidence

`search(symptom)` returns KNOWN_FIX, LIKELY_MATCH or NO_MATCH on the default MCP path. WEAK_SIGNAL remains available to programmatic low-confidence callers; it is not produced by the fixed-tier default search. Results include historical verification and checked/loaded/skipped corpus counts. A partial-coverage warning makes absence of matches inconclusive. These describe retrieval relevance, not calibrated correctness or proof of current causality. Use `detail(id)` to inspect the stored cause, fix, environment and verification limits. A KNOWN_FIX can be stale, inapplicable or insufficient for wider current symptoms. Validate source fit before applying it and rerun the relevant checks afterward. NO_MATCH means no usable match was found, not that the code is correct.

Use `status`, `list` and `patterns` to inspect the existing corpus as needed. Use `read_logs` only for the authorized project's relevant logs; inspect sensitive contents before external sharing. An inaccessible log is a coverage gap, not evidence that no errors occurred.

## Storage and outcomes

Some installed hosts start MCP in the plugin directory. If `status` reports unavailable project scope, pass the authorized absolute `project_root` to `status` and every memory operation. This explicitly selects `<project_root>/.claude/memory` for that call; it does not change process cwd, global settings or later calls. Keep the same root throughout a roundtrip and verify the returned path before writing. Without an explicit project, a package-root host refuses memory access. `read_logs` remains scoped to the actual server working directory; `project_root` does not redirect logs. Existing explicit `CLAUDE_MEMORY_*` configuration remains supported when no per-call root is selected.

Before any `store` or `outcome` write, check `status` for the actual server working directory and configured memory path. They must match the authorized project or an explicitly selected shared corpus. If the host starts in an unintended directory, disclose the storage gap and correct host configuration within authorization; do not write incidents into an assumed project.

`store` accepts required strings `symptom`, `root_cause`, `fix`; optional `category`, `tags`, `files_changed`, `file`. Describe the triggering conditions, causal evidence, actual changes and checks in these fields. Distinguish hypotheses and recommendations from verified repairs. Do not invent findings merely to populate memory.

The current tool stores conservative structured verification fields as unverified; it does not accept a verification object or authenticate test receipts. Include observed check commands/results and boundaries in the fix narrative, and retain the linked evidence report. Do not claim the structured metadata became verified simply because the narrative reports passing checks.

Use `outcome(incident_id, result, notes)` for a retrieved repair actually tried, with result `worked`, `failed` or `modified`. Explain the tested environment and limitations in notes. An outcome record is not production acceptance or independent verification.

Do not manually write an isolated incident JSON file: storage also maintains retrieval indexes and append logs. Use the bundled API/MCP to preserve those structures. If unavailable, keep a local task report and disclose that incident persistence was not performed. Preserve explicit `CLAUDE_MEMORY_*` overrides; do not migrate, merge or enable shared memory without authorization.

## Independent work

The plugin provides procedures, not pre-registered domain assessors on every host. If authorized agents are available, pass the relevant current evidence and candidate incidents, clearly labeling historical hypotheses. Never invent dispatch, access or independent approval. Continue directly when independent execution is unavailable, and disclose the review gap. See [the debug workflow](../debug/SKILL.md) and [deep loop](../debug-loop/SKILL.md).


## Programmatic retrieval

All retrieval wrappers carry inspected-corpus coverage. Quick checks include pattern matches and expose `inconclusive` when records were skipped. Full-tier results use additive `full_incidents` and `full_patterns`; compact-tier fields retain their existing shapes. Progressive matches separate `retrieval_score` from explicitly historical diagnosis/success metadata. See [retrieval contracts](../../docs/retrieval-contracts.md) for flags, budgets and storage boundaries.
