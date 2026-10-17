# Reproducible evaluation case

The timeout/retry case starts from duplicate receipts after a lost response, cold-start failures and deadline overruns. It uses an injected simulated clock/provider and an explicit contract. No network or real waiting occurs.

Copy `timeout-retry/baseline` to an isolated candidate directory. Give the coding model only the public case and plugin guidance; withhold `verify.py`, repaired-example and prior results until completion. Then run:

```sh
python3 evals/timeout-retry/verify.py /absolute/path/to/candidate /tmp/timeout-results.json
```

The original baseline passes 4 of 18 checks. The [recorded Opus 5.5 result](timeout-retry/observed-result.json) passes 18 of 18, preserving the contract, simulator and public test. The saved repaired example allows replay without calling a model:

```sh
python3 evals/timeout-retry/verify.py evals/timeout-retry/repaired-example /tmp/replay-results.json
```

This single synthetic case exposes mechanism and instruction failures; it cannot establish overall defect recall, production latency or superiority over another prompt format. The model's reported private checks are independently rerun by the host. Other earlier comparisons remain in the original workspace and are not represented as new combined-plugin trials.

## Review judgment and feedback

The [focused-review evaluation](review/README.md) adds seeded defects and clean controls, changed dependency contracts, repeated/reopened findings, repair-harm adjudication and origin classification. It evaluates saved review outputs separately from executable repair correctness.

## Cleanup and matched comparisons

The [cleanup dataset](cleanup/README.md) pairs three safe-removal opportunities with dynamic, dependency and emergency-path controls. It reuses the review scorer with explicit dataset paths and does not alter recorded review results. No cleanup model performance is claimed from fixture checks.

For a model/effort comparison, freeze source, guidance, tool access, prompt and budget; vary only the named model/effort configuration. Record requested and served identity, effort, input hashes, outputs, actual usage/cost, runtime, review effort and independent adjudication. Keep separate result directories; never overwrite a historical comparison. Treat one run as exploratory and repeat when variance matters.

For instruction A/B replay, use the same model and snapshot and change only one instruction. Give each arm a fresh isolated context and the same tools/budget, withholding oracles. Compare accepted findings, missed opportunities, harmful recommendations, required behavior, tool calls, runtime and actual cost. Retain adverse results. Use an existing case or confirmed incident when authorized; do not mine sessions automatically. A second model row or instruction comparison is a future experiment until it has actual receipts.
