# Matched Code Audit comparisons

Compare added guidance against the same host without that guidance. This is an explicit experiment, not automatic session mining or an accuracy certification.

The review set combines nine existing review cases, three cleanup cases, and four bounded adaptations of two confirmed repository failures and their repaired controls. There are 16 cases, 13 seeded causal classes and five clean cases. The adaptations preserve a source revision/path and state their translation; they are not full-repository discovery tasks or independently labeled human incidents.

`guidance/none.txt`, `current.txt` and `trimmed.txt` freeze the compared instruction bundles. Current includes references the previous entry workflow directed reviewers to read; trimmed keeps the compact judgment rules. The comparison changes the whole guidance bundle, not one isolated sentence, language model capability, memory backend or installed plugin. Both review and repair trials inject the same frozen bundles; the separate host-loading check establishes actual plugin/MCP integration.

## Run explicitly

Use authenticated local Claude and Codex CLIs. Choose and record the actual model configuration; example identities below are the recorded trial requests, not a current model recommendation.

```sh
python3 evals/matched/run.py --host claude --model claude-opus-5-5 --out /tmp/new-claude-review-trials
python3 evals/matched/run.py --host codex --model gpt-6.1-sol --out /tmp/new-codex-review-trials
python3 evals/matched/repair.py --host claude --model claude-opus-5-5 --out /tmp/new-claude-repair-trials
python3 evals/matched/repair.py --host codex --model gpt-6.1-sol --out /tmp/new-codex-repair-trials
```

Each command defaults to two repetitions of three arms in fresh temporary contexts, with order reversed for repetition two and a conservative 300-second per-call cap. These are cloud model calls and can incur usage charges. Existing result directories are never overwritten. No plugin, dependencies or credentials are installed globally; temporary Codex homes reference existing local authentication without copying its contents.

Review cases and guidance are supplied directly; reviewers receive neither `private/oracles.json` nor prior outputs. Review trials prohibit tools and reject recorded tool use, host errors or missing case coverage. Claude tools are disabled; Codex receives a no-tools instruction and its event receipt is inspected. This enforcement differs by host and limits cross-host comparisons. Codex receipts retain requested identity and usage; unavailable served identity and dollar cost stay null.

Before scoring, independently adjudicate every actual finding against source/contracts using the existing [review procedure](../review/README.md). Blind arm labels, allow oracle challenges and assess correction harm. Save the raw judgments, mapping and source reasoning. Use the existing scorer with `--cases evals/matched/cases.json --oracles evals/matched/private/oracles.json`; a passing parser does not establish semantic validity. Do not infer oracle matches from keywords.

Repair trials copy only the public [timeout/retry baseline](../timeout-retry/baseline/case/README.md) into a temporary workspace, allow actual local code tools, and then independently run all 18 withheld behavioral checks. On macOS, `sandbox-exec` must be available; the runner fails closed otherwise. Kernel canaries check repository/oracle and foreign temporary reads plus outside writes. The parent freezes baseline/verifier bytes before model execution, kills its owned process group before artifact inspection, and rejects links, special files and oversized outputs before reading candidate bytes. The parent verifies protected contract, simulator, profile and public-test bytes against that frozen baseline. Candidate Python executes only in a separate sandboxed JSON worker; the parent runs the unchanged withheld assertions with a pristine simulator and writes the result receipt. A model-created receipt cannot establish a pass. Candidate outputs and raw host receipts are retained. A fixture repair is not production behavior, and a model reporting passing tests is not the parent's verification.

## Interpret results

Compare within each host and effort configuration. Keep false positives, harmful advice, unavailable coverage, failed repairs, protected-file changes, usage, elapsed time and individual repetitions visible. Two repetitions describe observed spread, not a reliable population estimate. Cached-token accounting and CLI scaffolding differ; instruction word count does not establish actual token savings or faster execution. Human review effort and production recurrence were not measured.

The recorded run includes an oracle caveat: R07 has no before snapshot, so `unknown` origin can be a defensible conservative answer. Original origin-error counts remain descriptive and must not rank the arms. R01 does not mandate equal-revision policy; both contract-preserving corrections are admissible. No oracle or reviewer output was rewritten to manufacture a winner.

The compact production entry uses the tested trimmed core plus conditional navigation and host-scope instructions. Those packaging/navigation changes receive source and integration checks; the frozen packets identify exactly what the model comparison measured. Detailed checks remain available in [focused checklist](../../skills/code-principles/references/focused-checklist.md).

See the [recorded comparison](results/2026-10-20/comparison.md) for primary results, exploratory exclusions and limitations.
