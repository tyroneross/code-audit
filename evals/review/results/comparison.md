# Recorded review comparison — October 17, 2026

Both baseline and candidate detected all eight seeded defect classes, left all three clean controls without findings, correctly classified the pre-existing defect, and reopened the changed async contract without an unnecessary duplicate. The trial found no correctness advantage for the updated guidance. It establishes a reproducible regression baseline for these explicit cases, not general recall or task-effort savings.

| Observation | Baseline | Candidate |
|---|---:|---:|
| Reviewed cases | 9 | 9 |
| Seeded defect classes detected | 8 / 8 | 8 / 8 |
| Clean controls without false or harmful findings | 3 / 3 | 3 / 3 |
| Adjudicated false positives | 0 | 0 |
| Adjudicated harmful recommendations | 0 | 0 |
| Unnecessary repeated findings | 0 | 0 |
| Origin errors | 0 | 0 |
| Unavailable cases | 0 | 0 |

## Matched inputs and adjudication

Both arms ran in fresh tool-less safe-mode Claude CLI contexts with no session persistence, requested and served `claude-opus-5-5` through firstParty at medium effort. The same public cases, JSON response contract and conservative 300-second cap applied. The baseline took 37.5 seconds and candidate 31.6 seconds in this run; single observations do not establish a latency difference. The cap was a conservative allowance informed by earlier bounded runs, not a service latency target.

The baseline packet contains the original entry, focused-review and memory instructions. The candidate contains updated equivalents and the two routed references. This is a bundled guidance comparison, not an isolated format, placement or single-rule experiment. Exact packet components and hashes are retained in [provenance](provenance.json), [baseline guidance](baseline-guidance.txt), [candidate guidance](candidate-guidance.txt) and the [common prompt](review-prompt.txt). The final selected guidance was rerun after the main source corrections. Post-freeze deltas are listed below; the frozen candidate text identifies the behavior-tested wording.

Oracles and other outputs were withheld from both reviewers. A fresh Opus execution adjudicated source/contract fit and repair harm with the outputs labeled alpha/beta and without the guidance mapping. The host also inspected causal fit. This is context-independent adjudication within the same model family, not an independent empirical replication or authenticated human ground truth.

Initial oracle review identified an ambiguous deadline representation and an overly strict notion of ID reuse. The duration contract was clarified, ID spelling was removed as a mechanical correctness criterion, and both arms were rerun on version 2 with a fresh blinded adjudication. A reopening can reuse an ID or explicitly reference the old identity. [Oracle review](oracle-review.json) preserves the correction; first-run packets remain in the private local build record and are not counted as additional independent trials.

An earlier adjudication returned a null-finding commentary row for a clean case. The strict scorer rejected it. The final adjudication prompt explicitly excludes such rows and the fresh result needed no normalization; [normalization notes](adjudication-normalization.json) is empty and the [raw result](adjudicator-raw.json) is preserved. Prior records remain in the local build archive. The scorer consumes explicit judgments; it does not infer validity from keywords.

## Final-source deltas and scope

After the last selected-guidance model run, source review made three routing clarifications: the entry router now routes every authorized recording through debugging-memory storage checks; focused review explicitly loads that adapter for memory lookup; and the adapter's opening pseudocode explicitly searches candidate IDs for linked invalidation and uses the `modified` outcome spelling. Those three wording changes were source-reviewed, not measured in a new model trial. The separate live temporary-project MCP check confirms a linked invalidation record can be stored and retrieved by the original incident ID; it does not establish reliable retrieval on real corpora.

The deep-debug routing/storage instructions, scorer accounting, case-only isolation procedure and package metadata are also outside this selected-guidance behavioral comparison. They receive source review, mechanical checks and appropriate integration tests. Case/oracle versions and canonical parsed-JSON hashes are included in every new score; exact input file hashes are in provenance.json. A valid harmless unseeded finding is neutral in the clean-control outcome metric, while raw finding presence remains descriptive.

## Replay

From the repository root:

```sh
python3 evals/review/score.py evals/review/results/baseline-review.json evals/review/results/baseline-adjudication.json --output /tmp/code-audit-baseline-score.json
python3 evals/review/score.py evals/review/results/candidate-review.json evals/review/results/candidate-adjudication.json --output /tmp/code-audit-candidate-score.json
```

Compare with the saved [baseline score](baseline-score.json) and [candidate score](candidate-score.json). Replay verifies arithmetic and receipt consistency; it does not rerun a model, adjudicate the prose anew or execute proposed repairs. The [scorer checks](../test_score.py) also exercise harmful advice, invalid/missing judgments, class deduplication and unavailable coverage, because both actual model runs reached a ceiling on the current cases.

Remaining gaps: real-repository discovery, repeated live review/fix rounds, hostile instructions, risk-tier calibration, semantic memory relevance, model portability, retained team understanding, production/runtime behavior and measured downstream human effort. Add independently labeled cases and actual outcomes before claiming improvements in those areas.
