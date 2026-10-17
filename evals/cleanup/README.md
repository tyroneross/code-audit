# Cleanup judgment cases

Three synthetic cases pair a removable target with a preservation requirement: dynamic registration, a flag prerequisite, and an emergency safeguard. The supplied inventories are explicitly complete within each fixture; real repositories must establish that scope rather than assume it. These are review cases, not executable repair trials or production evidence. No model run has been recorded for this dataset.

Give the model only cases.json and the selected installed guidance, requesting the review JSON format from [review evaluation](../review/README.md). Copy those inputs into an isolated directory; withhold private/oracles.json, fixture tests and prior outputs until completion. The private folder name itself is not access control. These published cases are development fixtures, not an unseen holdout set.

A separate adjudicator compares every finding and suggested change with the contracts and private oracles. Map each supported removable target to its oracle; mark advice that breaks a protected path harmful even when it also identifies a real cleanup. Accept equivalent supported simplifications; do not demand one patch shape. Unseeded useful findings need their own evidence. An all-keep output misses all three opportunities. The existing scorer calls these seeded_defect_classes for compatibility; here they are cleanup opportunities, not correctness defects. Recall alone is not a pass: assess harmful advice, precision, unavailable coverage and adjudicator rationale separately.

Use the existing scorer, without changing its default dataset or historical results:

```sh
python3 evals/review/score.py /path/to/review.json /path/to/adjudication.json --cases evals/cleanup/cases.json --oracles evals/cleanup/private/oracles.json --output /tmp/cleanup-score.json
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s evals/cleanup -p 'test_*.py'
```

Fixture tests validate representative preserved behavior and scoring accounting, not model judgment or arbitrary patches. Actual model comparisons require saved outputs and independent adjudication.
