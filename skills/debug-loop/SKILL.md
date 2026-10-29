---
name: debug-loop
description: Use for nontrivial, uncertain, recurrent or disputed root causes, a repair that did not hold, or an explicit deep investigation. Memory labels inform investigation but do not determine depth.
user-invocable: false
---

# Debug Loop — Iterative Root Cause Debugging

A 7-phase debugging loop: investigate via causal tree analysis, hypothesize root cause, implement targeted fix, verify with evidence, score against criteria, pressure-test via critique agent, and report with transparency markers. Iterates up to 5x on failures.

Read [shared principles](../code-principles/SKILL.md) and relevant challenge details before choosing a repair.

## Scope Check

Before entering the loop, assess whether it's warranted. Choose depth from the actual causal uncertainty, recurrence and scope. Retrieval similarity is not calibrated confidence in a fix.

- **Skip the deep loop** for `KNOWN_FIX` only after validating causal fit and current contracts; adapt and verify
- **Skip the loop** for trivial issues: typos, missing imports, obvious config errors where the cause is immediately clear
- **Enter the loop** for a nontrivial or disputed cause, a previous repair that did not hold, an unexplained cross-component failure, or an explicit deep-investigation request. A weak or absent memory match is one input, not an automatic trigger.

## Efficiency

- Terminal output: current phase, key findings (one line each), status changes, failures. No verbose reasoning
- Agent context: minimum needed per job. Pass symptom + relevant findings, not full conversation history
- Load convergence rules reference on demand only when entering iteration

For a repair or restart crossing component boundaries, read [change and failure isolation](references/change-isolation.md). Verify the shared cause and affected callers; a past incident or a small diff does not establish that the current boundary is adequate.

## Phase 1: INVESTIGATE — Gather Evidence and Trace Root Cause

**Goal**: Understand what's actually failing and why, not just what it looks like.

1. **Search memory when available** — use the bundled debugger search tool; inspect candidate context. If unavailable, disclose the gap and continue source investigation.
2. **Reproduce the issue when feasible** — identify exact steps, commands, or conditions that trigger the bug. If the original environment is unavailable, record the causal evidence and limits; distinguish a controlled regression case from reproduction of the original incident.
3. **Trace plausible causes** — inspect callers, state and failure boundaries, rank by evidence and prune with counterevidence. Use an independent investigator only when authorized and available (on Claude Code, the bundled `root-cause-investigator` agent; for an unclear multi-domain symptom, `assessment-orchestrator` and its domain assessors); agent registration is not required for investigation.
4. **Research gate** — if the investigator flags unfamiliar error codes, library behavior, or version-specific issues:
   - Search official sources using a minimal non-sensitive query; never send private code, credentials or logs without authorization
   - Document what was searched and what was found
   - If search is unavailable, document what SHOULD be searched
5. **Assess completeness** — does the investigation explain ALL reported symptoms? Check for multi-causal bugs (2+ independent root causes)

**Output**: Causal tree (with confirmed and pruned branches), reproduction steps, evidence gathered, research performed

## Phase 2: HYPOTHESIZE — State the Root Cause

**Goal**: Commit to a specific, testable hypothesis before writing any fix.

1. **State the root cause hypothesis** with evidence level:
   - **Strong**: Multiple evidence types (code, logs, reproduction) all point to this cause
   - **Moderate**: Some direct evidence plus reasonable inference
   - **Weak**: Mostly inference, limited direct evidence — consider investigating other branches first
2. **Predict verification test**: If this hypothesis is correct, what specific test would prove it?
3. **Predict related symptoms**: What else should be affected if this root cause is real?
4. **If multiple hypotheses exist**, rank by evidence strength. Pursue the strongest first

**Output**: Hypothesis statement, evidence level, prediction test, related symptom predictions

## Phase 3: FIX — Implement Targeted Change

Apply code changes only when the task authorizes repair. For review-only requests, report the supported cause, proposed correction and verification plan; do not apply fixes or write incident/workflow state.

**Goal**: Make the simplest adequate change that addresses the causal mechanism across affected supported paths.

1. **Compare a symptom patch with a causal repair** — trace the existing state owner and affected callers before adding a case-specific exception. A null guard can be correct at a boundary that permits missing data; establish the contract rather than treating every guard as a symptom patch.
2. **Keep changes proportional** — repair the shared mechanism where needed, preserving supported callers and valid counterexamples. Avoid unrelated cleanup or speculative frameworks; minimum adequate means causal coverage, not the fewest changed lines.
3. **Note exactly what was changed and why** — this becomes the evidence trail

**Output**: List of changes with rationale

## Phase 4: VERIFY — Test the Fix with Evidence

**Goal**: Collect concrete evidence that the fix works.

1. **Run the prediction test** from Phase 2 — does it confirm the hypothesis?
2. **Run the original reproduction steps** — is the symptom gone?
3. **Run related test suite** — do existing tests still pass?
4. **Check for regressions** — run broader test suite if available
5. **Verify related symptom predictions** — are the predicted effects present?

Each applicable verification step needs evidence: command output, test results, or observable behavior. Mark a genuinely inapplicable check N/A with its scope reason, or a missing required environment/check UNAVAILABLE with the gap. Neither is PASS. "It should work" is not evidence.

**Output**: Evidence for each verification step

## Phase 5: SCORE — Evaluate Against Criteria

**Goal**: Evidence-based status for each criterion.

Score against these criteria:

| # | Criterion | Method | Pass Condition | Evidence Required |
|---|-----------|--------|----------------|-------------------|
| 1 | Symptom resolved | Reproduction steps | Symptom no longer occurs | Command output or test result |
| 2 | Tests pass | Test suite | All relevant tests pass | Test runner output |
| 3 | No regressions | Broader test suite | No new failures introduced | Test runner output |
| 4 | Root cause addressed | Code review | Fix targets root cause, not symptom | Diff + reasoning |
| 5 | Hypothesis confirmed | Prediction test | Prediction test passes | Test output |

**Every criterion needs an evidence status.** Use PASS with observed evidence, FAIL for an observed unmet criterion, N/A only when genuinely inapplicable to the approved scope, and UNAVAILABLE when required verification cannot be performed. No criterion is PASS without proof, and N/A cannot waive a required check.

**If a criterion fails and repair is feasible** → enter iteration (Phase 6 rules apply).
**If all applicable criteria pass, with justified N/A where appropriate** → proceed to critique (Phase 6).
**If required verification is unavailable** → finish independent authorized work, then report bounded results and remaining gaps; do not repeat code changes to satisfy a missing environment or claim full verification.

**Output**: Scorecard with status per criterion, evidence or the specific limitation

## Phase 6: CRITIQUE — Pressure-Test Before Declaring Done

**Goal**: Challenge the fix before the user relies on it.

1. **Seek independent critique when available** (on Claude Code, the bundled `fix-critique` agent) with:
   - The symptom
   - The causal tree from investigation (confirmed branch path + pruned branches)
   - The fix (what was changed)
   - The verification evidence
If independent execution is unavailable, mark critique UNAVAILABLE and disclose the gap; self-review is not independent approval.

2. **Evaluate the actual verdict**:
   - **APPROVED** → proceed to REPORT
   - **CHALLENGED** → the concerns become input for the next iteration. Route back to INVESTIGATE with the specific challenges as new investigation targets

The critique agent checks 5 things:
- Root cause vs symptom fix
- Symptom coverage (similar bugs elsewhere)
- Regression risk
- Evidence verification
- Causal tree consistency

## Phase 7: REPORT — Transparent Status

**Goal**: Clear, honest summary. No overclaiming.

### Transparency Markers

Every item in the report gets one marker:

- **✅ Verified**: Checked with evidence (test output, reproduction, command results)
- **⚠️ Assumed**: Believed to be true based on reasoning, but not verified with a test
- **❓ Unknown**: Not checked at all — explicitly acknowledged gaps

### Report Contents

1. **Verdict**: Fixed within scope when all applicable criteria pass, any N/A is justified, and actual independent critique approves. If critique is unavailable, report the verified behavioral scope and review gap. Report partial verification when required evidence is unavailable; report unresolved when failures remain or the iteration limit is reached. Neither partial nor unresolved means fully verified.
2. **Root Cause**: The identified cause with evidence level
3. **Causal Tree**: The investigation path — confirmed branches, pruned branches with rejection evidence, any multi-causal findings
4. **Fix Applied**: What was changed, with rationale
5. **Scorecard**: Final status per criterion with evidence or a justified N/A/UNAVAILABLE reason
6. **Research Used**: What was searched externally, what was found, what sources
7. **Iteration History** (if >1 iteration): What was tried, what failed, what changed between iterations
8. **Remaining Gaps**: Anything marked ⚠️ or ❓

### After Reporting

- **Before any memory write**, follow [debugging-memory storage preconditions](../debugging-memory/SKILL.md): confirm task authorization and inspect `status` for the actual server working directory and configured memory path. They must match the authorized project or an explicitly selected shared corpus; otherwise keep a task report and disclose the storage gap.
- **Store the incident only after those checks pass** via the existing debugger `store` fields and narrative for future retrieval
- **Record an outcome only after those checks pass and a retrieved repair was actually attempted**, using `worked`, `failed` or `modified`. Keep uncertain results in the incident narrative or task report; do not invent an outcome enum.
- **Write state only when task-authorized** to `.claude-code-debugger/debug-loop/scorecard.md`

## Iteration Rules

When any criterion fails or the critique is CHALLENGED, iterate:

1. **Diagnose why the criterion failed** — don't blind retry
2. **Revise the hypothesis** if verification disproved it
3. **Create a targeted fix plan** for the failed mechanism and affected criteria
4. **Execute fix**
5. **Re-verify failed and affected checks** — rerun previously passing checks whose evidence the new change can invalidate. Retain unrelated passing evidence only when its source and assumptions remain applicable.
6. **Re-score and re-critique**

Use [review feedback](../code-principles/references/review-feedback.md) to reconcile repeated critique findings, changed closure premises and affected caller contracts. One justified budget covers nested review and repair; the five-iteration maximum below still applies. Record failed hypotheses and evidence in [incident lessons](../code-principles/references/incident-learning.md) when authorized.

### Convergence Detection

Load `references/convergence-rules.md` for detailed rules and escalation templates.

Summary:
- **Same hypothesis fails 2x** → reject or revise it and seek discriminating evidence; ask only for genuinely missing context or a consequential user decision
- **Fix A breaks criterion B (oscillation)** → inspect shared ownership or conflicting requirements; continue an authorized adequate repair, asking only if requirements cannot be resolved
- **3+ criteria fail after a fix** → systemic issue, stop loop and reassess the approach entirely
- **New regression detected** → fix is causing side effects, reconsider the approach
- **Hard stop at 5 iterations** → report what's known and what isn't. Never silently loop beyond 5

### State Tracking

Only when workflow-state writing is authorized, write iteration state to `.claude-code-debugger/debug-loop/state.json`:

```json
{
  "symptom": "original symptom",
  "iteration": 1,
  "phase": "VERIFY",
  "hypotheses": [
    {
      "iteration": 1,
      "hypothesis": "description",
      "evidence_level": "strong | moderate | weak",
      "result": "confirmed | disproved | partial",
      "evidence": "what was found"
    }
  ],
  "scorecard": [
    {
      "criterion": "symptom_resolved",
      "result": "PASS | FAIL | N/A | UNAVAILABLE",
      "evidence": "summary"
    }
  ],
  "critique_verdict": "APPROVED | CHALLENGED | pending",
  "changes_made": ["file:change summary"]
}
```

When workflow-state writing is authorized, create `.claude-code-debugger/debug-loop/` before writing.

## Anti-Patterns to Avoid

| Anti-Pattern | What to Do Instead |
|-------------|-------------------|
| Accepting the first explanation | Branch first — identify 2+ plausible causes before pursuing any |
| Fixing the symptom | Trace to root cause, fix there |
| "This should fix it" | Run the tests, show the output |
| Retrying the same approach | If it failed once with the same evidence, it'll fail again. Change the hypothesis |
| Declaring victory without evidence | Every claim needs a ✅/⚠️/❓ marker |
| Skipping research when stuck | If you don't know why something behaves this way, search for it |
| Hiding uncertainty | ⚠️ and ❓ are not failures — they're honest. Hiding them is the failure |
