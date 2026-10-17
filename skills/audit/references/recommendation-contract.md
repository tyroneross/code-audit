# Report version 2: outcomes, decisions and verified-improvement claims

Version 2 adds exact top-level `objectives` and `recommendations` lists to the version-1 report fields. The thirty assessment rows and finding objects keep their existing shape. New CLI packets use version 2; `audit.template(manifest)` retains its legacy version-1 API default, and `audit.template(manifest, schema_version=2)` selects the new shape. Validators/renderers read both versions. `--require-outcomes` rejects v1 for workflows that require the new contract.

A partial template can have empty objectives/recommendations. A complete v2 report needs at least one of each, and every finding must be linked from a recommendation. A single recommendation may link several principle findings about the same root cause. Keep the distinction between rule coverage and distinct defects. Do not propose a change merely to populate the list; a justified keep or investigation decision is useful.

## Objective fields

| Field | Contract |
|---|---|
| `id` | Unique nonempty string |
| `dimension` | `scalability`, `speed`, `correctness`, `efficiency`, `maintainability`, or `other` |
| `operation` | Actual operation or consumer boundary to improve |
| `desired_outcome` | Concrete result the user needs |
| `direction` | `lower`, `higher`, or `contract`; scalability/speed/efficiency require a numeric lower/higher direction |
| `workload` | Relevant inputs/scale/conditions, or explicitly state what remains unknown |
| `constraints` | String list of required behavior and limits |
| `baseline` | Exactly `state: observed|unknown`, `description`, `evidence` (locator list); observed requires citations |
| `verification` | Exactly `method`, `expected_outcome`, `boundary` (nonempty text) |

Use `correctness` with `direction: contract` for behavioral repairs without a meaningful numerical objective. If accuracy is an error-rate claim, use a numeric direction and the appropriate oracle. A proposed investigation can have an explicitly unknown baseline; a verified improvement cannot.

## Recommendation fields

Exact fields: `id`, `decision`, `priority`, `principles`, `objective_refs`, `finding_refs`, `best_practice`, `preferred_approach`, `why_preferred`, `code_impact`, `user_impact`, `tradeoff`, `alternatives`, `revisit_when`, `evidence`, `verification`, `result`, `measurements`.

- `id`: unique nonempty string. `decision`: `change|keep|investigate`. `priority`: `now|next|later`.
- `principles`: nonempty unique P01–P30 list. `objective_refs`: nonempty unique list of actual objective IDs.
- `finding_refs`: list of exact `{rule_id, finding_index}` objects. References must exist and belong to the recommendation's principles. An unresolved violation cannot be disposed of as `keep`.
- `best_practice`: the relevant general rule in plain language. `preferred_approach`: the concrete choice. `why_preferred`: the contextual reason for preferring it. `tradeoff` and `revisit_when`: concrete nonempty text.
- `code_impact` and `user_impact`: each exactly `{claim, basis, evidence}`. Basis is `observed|expected|unknown`; observed requires evidence. A prediction stays expected even when it seems plausible. Unknown impact needs an explanation, not an invented benefit.
- `alternatives`: list of exact `{approach, prefer_when, benefit, cost}` objects with nonempty text. It may be empty when no additional viable option is established.
- `evidence`: locator list, required for change/keep; investigation may instead explicitly describe the missing evidence in its reasoning.
- `verification`: exactly `{plan, expected_outcome, boundary, checks_run}`; three nonempty text fields and actual check locators. Proposed checks are not receipts.
- `result`: exactly `{state, explanation, before_evidence, after_evidence}`. State is `proposed|implemented_unverified|verified|blocked|not_applicable`. Explain the actual state. Only a change may claim a verified improvement; it requires before/after locators, an executed check and observed linked baselines.
- `measurements`: list of the objects below. Leave empty for unmeasured proposals and nonnumeric contract repairs. Never invent a measurement to make a report pass.

## Measurement fields

Exact fields: `objective_id`, `unit`, `workload`, `method`, `boundary`, `before`, `after`, `uncertainty`, `evidence_before`, `evidence_after`.

An objective can appear once per recommendation's measurements. It must be linked by that recommendation. Unit, method, boundary and uncertainty are nonempty text. Workload must match the objective's declared workload. Before/after are finite numbers, not booleans, and both need exact evidence locators. Use a representative summary and describe repetitions/variation in method and uncertainty when timing noise matters.

For `result.state: verified`, every linked numeric objective needs a measurement. Its after value must improve the declared lower/higher direction. Before/after values describe the same unit, workload and boundary. The checker cannot discover a mislabeled workload, authenticate logs, infer causality or judge statistical significance; the host reviewer must establish those facts. Do not relabel an outcome as a nonnumeric contract merely to avoid measurements.

All references use the existing exact snapshot locator contract. Comparison evidence may include prior-version receipts, but the host must preserve their actual source identities and scope. An evidence-only snapshot may contain mirrored source plus local receipts, with original-source freshness checked separately; do not mistake composite-root freshness for proof of the original repository's state.
