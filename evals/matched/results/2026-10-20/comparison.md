# Matched comparison: October 20, 2026

The added guidance did not improve observed correctness in this bounded comparison. All three arms tied in both hosts. The compact default preserves that observed result while moving detailed checks behind conditional references; this does not establish token, latency, production-quality or memory-retrieval benefit.

| Host | Guidance | Review defect classes, each repetition | False positives / harmful advice | Repair checks, each repetition | Review seconds, range | Repair seconds, range |
|---|---|---|---|---|---|---|
| claude | none | 13/13, 13/13 | 0 / 0 | 18/18, 18/18 | 44.3–50.2 | 78.2–84.6 |
| claude | current | 13/13, 13/13 | 0 / 0 | 18/18, 18/18 | 54.8–60.2 | 75.5–80.4 |
| claude | trimmed | 13/13, 13/13 | 0 / 0 | 18/18, 18/18 | 47.9–48.7 | 63.9–80.2 |
| codex | none | 13/13, 13/13 | 0 / 0 | 18/18, 18/18 | 29.7–52.1 | 107.6–122.6 |
| codex | current | 13/13, 13/13 | 0 / 0 | 18/18, 18/18 | 47.8–51.2 | 92.0–139.4 |
| codex | trimmed | 13/13, 13/13 | 0 / 0 | 18/18, 18/18 | 49.6–67.0 | 108.6–152.4 |

Two repetitions per arm per host are insufficient to estimate stable differences. Review has 16 short cases, including five clean controls. Repair has one synthetic checkout task. Different cache states and CLI scaffolding confound cost/time comparisons. Human review effort and production recurrence were not measured.

Claude requests and served receipts identify claude-opus-5-5. Codex requested gpt-6.1-sol at medium effort; served identity and dollar cost are unavailable and remain null. [Review summary](review-summary.json) and [repair summary](repair-summary.json) retain individual usage, cost, time and identity fields. Raw host output, frozen prompts, independent blinded adjudications and scores accompany each trial.

The independent adjudicator raised an origin-label ambiguity for R07, which has no before snapshot, and an equal-revision policy caveat for R01. These are retained in [oracle review](adjudication-codex-2/oracle-review.json). Origin errors are descriptive and are excluded from arm ranking. The supplied packets compare whole guidance bundles, not installed plugin behavior or the memory backend.

The primary repairs were generated behind OS read/write isolation. After Claude identified a verifier boundary defect, all 12 saved candidate sets were replayed without model regeneration through a separate sandboxed worker. The parent owns the original 18 assertions, pristine simulator, clock/provider effects and result file. Each trial includes parent-owned boundary-verification and metadata. Baseline reproduces 4/18 and the previous saved repair 18/18. Actual OS and malicious-candidate regression checks support this bounded boundary; they are not general arbitrary-code security certification.

Earlier prompt-only repairs passed but lacked OS isolation and are excluded. Initial infrastructure attempts failed CLI startup or nested sandbox/PTY access; these are retained separately in local build receipts and are not guidance failures. A duplicate Claude batch was canceled and excluded before completion. Later artifact-link, process-quiescence and receipt-forgery defenses were mechanically tested and applied during replay; original generation traces were not rewritten.

Next evaluation should use harder source-backed repository tasks with independently adjudicated controls, measure human correction effort and recurrence, and compare memory retrieval separately. This run supports a smaller default and confirmed runtime repairs; it does not support an efficacy marketing claim.
