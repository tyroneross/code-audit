# Focused-review evaluation

These nine synthetic cases test review judgment, not application execution: cross-path stale state, valid retry resets, first-duplicate semantics, an unchanged caller broken by changed units, an already resolved finding, a legitimately reopened finding, checkout identity/retry/deadline failures, an unwired handler and a severe pre-existing defect. There are three clean controls and eight seeded causal defect classes. Cases are intentionally small and explicit; they cannot establish production recall or the best review budget.

## Run a matched comparison

1. Freeze the selected guidance, `cases.json`, model/effort, tool access and output format. Record hashes. Run the current guidance as a baseline before revising it.
2. Give a fresh reviewer only the public cases and selected guidance. Withhold `private/oracles.json`, other reviewer outputs, adjudication and recorded results. Disable extra file/tool access or use an isolated copy containing only `cases.json` and the selected guidance, explicitly excluding `private/` and `results/`. "Private" means withheld during evaluation; labels are published for replay, not secret.
3. Run the candidate with the same cases, model, effort, isolation and format. Report every intentional input difference. Fresh trials need new contexts; replaying saved JSON is not a new model trial.
4. Have an independent adjudicator read the actual source/contract and each finding/repair. Match causes and required behavior, not wording or finding count. Check advice on clean cases, affected locations, origin, repeated findings and justified reopening. An unseeded finding needs its own source evidence; do not count it wrong merely because it is absent from the oracle. Preserve disputed judgments.
5. Score the supplied judgments, then run affected package tests and the existing repair fixture. Do not treat a schema pass as a semantic judgment or a passing score as execution of a proposed repair.

Review JSON:

```json
{"cases":[{"case_id":"R01","coverage":"complete","findings":[{"id":"F1","cause":"specific mechanism","locations":["store.py:2"],"severity":"high","origin":"introduced","disposition":"open","suggested_change":"adequate correction","verification":"proposed discriminating check"}]}]}
```

Include every case once. Clean cases have an empty findings array. Coverage is `complete` or `unavailable`; unavailable cases need a `reason` and remain visible in scoring. `origin` is `introduced`, `pre_existing` or `unknown`; severity is independent. A reopened issue should reuse its prior ID or explicitly link the old identity; the adjudicator checks that relationship, rather than scoring ID spelling. Proposed checks are not executed receipts.

Adjudication JSON:

```json
{"judgments":[{"case_id":"R01","finding_id":"F1","oracle_id":"stale-poll","valid":true,"harmful":false,"duplicate":false,"rationale":"The poll path bypasses admission; the proposed shared guard preserves valid newer events."}]}
```

Every returned finding needs one judgment. Use `oracle_id: null` for a false positive or independently justified unseeded finding. `valid` concerns the defect; `harmful` concerns the recommendation, so both may be true. A legitimate reopening is not an unnecessary duplicate. The scorer does not authenticate judgment rationales or infer causes from prose.

```sh
python3 evals/review/score.py /path/to/review.json /path/to/adjudication.json --output /tmp/review-score.json
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s evals/review -p 'test_*.py'
```

The result separates seeded-class recall, finding precision, false positives, harmful advice, repeated findings, origin errors, clean controls and unavailable coverage. It records case/oracle versions and canonical parsed-JSON hashes; provenance.json additionally hashes the exact files. Raw clean-case finding presence is descriptive, not a failure score: use `clean_cases_without_false_or_harmful_findings` to avoid penalizing independently valid, harmless unseeded findings. Classes found multiple times count once. Precision is unavailable when no findings exist; an all-empty report still misses every seeded defect. Unavailable cases are not clean successes. Operational rounds-to-pass, human effort, real latency, cost and later incidents require actual workflow observations and are not inferred from these static cases.

## Evidence and updates

[Recorded comparison](results/comparison.md) and its source packets identify what was actually tested. Re-score meaningful prompt/reference/model/tool changes on the applicable set; also collect real confirmed incidents when authorized, without publishing private code. Preserve an independent held-out set when tuning. Do not tune against these published cases and then present them as unseen validation.

These fixtures can expose guidance failures but do not isolate the effect of individual instructions, predict model rankings or establish that more context is better. Use the [review contract](../../skills/code-principles/references/review-feedback.md), [research limits](../../research/learning-evidence.md) and [existing behavioral repair evaluation](../README.md) together.
