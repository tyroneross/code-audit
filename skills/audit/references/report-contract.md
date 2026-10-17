# Structured audit report contract (versions 1 and 2)

New CLI packets use version 2, adding `objectives` and `recommendations` as defined in the [decision contract](recommendation-contract.md). The thirty assessment/finding fields below remain unchanged. Existing version-1 reports still validate and render, with an explicit legacy limitation. Use `--require-outcomes` to require version 2 in a new improvement workflow; legacy compatibility does not supply the new checks.

Start from the prepared `report-template.json`. Strict field names prevent unnoticed typos. JSON objects cannot have duplicate keys or non-finite numbers. Reports always contain exactly P01 through P30 once each.

Base top-level fields: `schema_version: 1|2`, `snapshot_id`, `review_state: partial|complete`, nonempty `reviewer` and `summary`, `context`, `assessments`, and a nonempty `limitations` list. Version 2 also requires `objectives` and `recommendations`. `complete` means every rule received a disposition, not that unknowns were resolved or all code works. A template is partial and contains thirty `not_reviewed` rows. `--require-complete` rejects it.

`context` is a list of objects: `fact` (nonempty text), `basis` (`user_statement|source|inference|unknown`) and `evidence` (locator list). Source facts and inferences need at least one supporting locator. Record a meaningful fact's origin; do not invent a user statement or uncited inference to justify inapplicability.

Each assessment has these exact fields:

| Field | Meaning |
|---|---|
| `id` | Stable P01–P30 ID |
| `status` | `violation|observed_alignment|not_applicable|insufficient_evidence|not_reviewed` |
| `subject` | `code_behavior|reporting_claim|context` |
| `boundary` | Concrete reviewed scope and observation boundary |
| `evidence_basis` | `source_observation|behavioral_receipt|unknown` |
| `runtime_state` | `not_checked|observed_within_stated_boundary|not_applicable` |
| `applicability` | Actual triggering context or justified exclusion |
| `premises` | List of established assumptions; nonempty for violation, alignment and inapplicability |
| `explanation` | Engineering reasoning, with facts and inference distinguished |
| `evidence` | Source locators; required for violation, alignment and behavioral receipts |
| `context_refs` | Zero-based indices into the report's context list |
| `counterevidence` | What was checked that could weaken the judgment; state remaining search limits |
| `uncertainty` | Concrete remaining unknowns or explicitly scoped lack of known uncertainty |
| `assumption_change` | What would alter the advice |
| `findings` | Nonempty only for violation; empty for other dispositions |

Inapplicability requires source evidence or a referenced context fact whose basis is not `unknown`. Absent context is insufficient evidence, not inapplicability. Runtime observation requires `behavioral_receipt` and a locator, but the agent still must judge receipt authenticity, sufficiency and scope.

A locator has exactly `path`, `start_line`, `end_line`, `file_sha256`, `content_sha256`, `excerpt`. Lines are one-based and inclusive, separated by CRLF, LF or CR; form-feed, vertical-tab and Unicode separators inside a line remain data. Hash and excerpt match the exact snapshot bytes (including original line endings). Use the `evidence` command. Relative POSIX paths cannot contain dot/traversal components, backslashes or control characters. Focused locators are limited to 200 lines and 24,000 UTF-8 bytes; these are evidence-packet bounds, not code-quality thresholds. Human-readable rendering escapes terminal and directional controls and normalizes displayed line endings; the structured excerpt and its hash preserve the original bytes.

A finding has exactly `title`, `severity` (`critical|high|medium|low`), `confidence` (`high|medium|low`), `applicability`, `premises` (nonempty list), `evidence` (nonempty locator list), `consequence`, `action`, `tradeoff`, `counterevidence`, `assumption_change`, and `verification`.

`verification` has exactly `plan`, `expected_outcome`, `boundary` (all concrete nonempty text), and `checks_run` (locator list; empty when no checks actually ran). A plan states how to establish the correction works and what should be observed; it is not an execution receipt. Confidence is the reviewer's qualitative judgment, not a calibrated probability.

Example verification object:

```json
{
  "plan": "At the parser boundary, supply a nonnumeric amount and verify it returns a validation error before storage is called.",
  "expected_outcome": "The caller gets an explicit rejection and no storage write occurs.",
  "boundary": "Parser plus storage-call observation; a proposed check, not a deployment claim.",
  "checks_run": []
}
```

Severity follows established consequence and reach: critical for demonstrated severe broad harm, high for a consequential reachable failure, medium for a bounded meaningful defect, low for a minor established defect. Speculative preferences and unrelated tests do not become findings. Group overlapping evidence and explain combined/staged remedies rather than counting one defect repeatedly.

Validation returns `valid`, `snapshot_integrity`, `source_freshness`, `semantic_correctness: unverified`, `review_state`, coverage counts, errors and limits. A valid partial report is explicitly partial. `included_files_match` freshness excludes additions and omitted sources. Hashes detect internal inconsistency; they are not signatures, provenance authentication, or protection against an attacker rewriting both manifest and snapshot.
