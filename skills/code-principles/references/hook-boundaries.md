# Review hooks at the boundary they claim to control

Use this guidance when a system claims that hooks enforce readiness, scope, completion or approval. Trace one real operation from the host event through the decision to its observable effects. A configured hook is a candidate control; enforcement requires evidence that the host invoked it and honored its result.

## Specific checks

| Applies when | Action | Expected result and failure condition | Evidence to retain |
|---|---|---|---|
| A hook is claimed to be active | Inspect enabled configuration, trust, matcher and host/tool coverage; exercise a harmless native call | The intended handler runs. Missing trust, a skipped matcher or an uncovered tool path is a coverage gap | Host/version, effective source, handler identity and event/tool correlation |
| A pre-action hook claims to prevent an effect | In an isolated fixture, attempt a valid action and a prohibited action through the real host | Valid work succeeds; prohibited effects do not occur. A warning or refusal string with the effect still present fails | Exact fixture input, decision, observed side effects and output |
| Readiness depends on another task or artifact | Exercise a ready input and a missing, stale or mismatched dependency | Work follows the existing dependency policy. An unrelated receipt must not satisfy readiness | Run/task identity, dependency identity and actual receipt validation |
| Completion depends on worker evidence | Trace the result to the requested scope, input, revision, executed checks and reviewer | Required current evidence supports each completion claim. An exit code or self-reported “done” alone is insufficient | Artifact/receipt references, command results, reviewed revision and remaining gaps |
| Human approval is required by the host/project | Check that the recorded response refers to the intended action/output and relevant evidence | Approval satisfies the governing policy. A hook, model verdict or ambiguous response cannot fill the required human slot | Original response, context, target, evidence reference and decision time |
| A hook fails, retries or resumes | Exercise applicable malformed input, timeout, missing executable, duplicate delivery and restart cases | Failure behavior follows explicit policy; uncertain execution stays uncertain and retries avoid duplicate effects | Error path, elapsed time, resulting state and retry identity |

Check alternate paths that can reach the same effect: shell writes, native edit tools, MCP calls, background work and direct API access where applicable. State untested paths. Scope checks are only as strong as their interception and execution boundaries; local hooks do not establish machine-wide containment.

Post-action hooks can correlate results and detect failures; prevention requires a control before the effect or at the receiving system. A Stop event marks a host lifecycle boundary; establish task completion separately. Keep advisory reminders non-blocking unless the governing policy explicitly requires a safety or integrity block.

Prefer an existing validator and receipt format over a parallel framework. Retain valid artifacts and decisions, repair unmet criteria, and recheck evidence affected by changed inputs. Measure hook overhead on the same workload when making latency claims. Do not infer broader quality improvement from one accepted worker or one refused action.

## Apply the checks without adding another framework

Choose the existing owner before proposing a new hook: instructions/skills for judgment, a hook for a bounded event reaction, an existing CLI/API for external operations, and a receiving-system or execution-boundary control when every writer must obey. Model-based hooks retain judgment uncertainty. Keep expensive integration work in a targeted acceptance or CI lane rather than every tool call.

Trace package root separately from consumer workspace, and inspect all effective host configuration layers. A handler can run while a missing helper silently yields a no-op. Measure the total deadline from startup through child cleanup. If independent sibling handlers need ordering, give that ordering to an existing dispatcher; do not assume host scheduling serializes them. Check logical operation identity on duplicate delivery and restart.

Distinguish executable syntax from quoted payloads. During this ingestion, a transcript-writing command was refused by a raw-text wait heuristic even though it contained no executable polling loop. Use literal-text negative controls as well as real prohibited operations when reviewing command classifiers. Source capture used a direct file-write tool; the runtime gate was not repaired in this documentation change.

Keep absent evidence, a failed check, a skipped check and a confirmed violation distinct. An advisory observer can continue with a useful gap note. A required safety control must hold/refuse the governed effect through a mechanism the installed host supports. Review original approval context without inventing additional human gates. Avoid storing raw prompts, secrets or credential values in hook telemetry.

Verify installed contracts rather than copying old examples. The current Claude reference documents `TaskCompleted`, superseding the May 9 local research claim that it did not exist. The current Codex reference says PreToolUse `permissionDecision: "ask"` is unsupported and the tool call continues after reporting failure; a Claude response shape therefore cannot establish Codex approval enforcement. Use the host's supported permission path and a native fixture to prove the effect.

For performance claims, compare the same host, inputs, repository state and handler set; separate cold startup, repeated calls, timeouts, output volume and duplicate effects as relevant. Existing timing estimates or one successful worker cannot establish an improvement. Advisory rollout can expose false positives before a justified new block; existing mandatory safety checks retain their required behavior.

## Report the actual evidence level

Separate configured, trusted/enabled, invoked, decision-honored, output-verified and human-accepted observations. Claim each only when its evidence exists. Digests support integrity and correlation; they do not authenticate the person who approved work or establish that an artifact is correct.

Record missing hook coverage as a gap. Confirm a defect only when the required contract, triggering input and consequence are established. Use the existing [review feedback](review-feedback.md) and [whole-system repair](whole-system-repair.md) guidance for findings and authorized repairs. These checks do not authorize hook installation, global setup, approval changes or expansion of the user's scope.

## Provenance and limits

Shared from Build Loop on October 18, 2026 at the user's request. Source: user-supplied image **Why hooks govern agent work**, labelled “Evidence 18 Oct 2026,” plus inspection of Build Loop at `21b77e8d3f8c8c29430635120c2cc62ed39c861a`. The image distinguishes readiness, bounded execution, completion and evidence-bound approval, and explicitly reports unfinished delivery. Its underlying run records were unavailable; its reported native execution and refusals were not independently reproduced here.

Checked the official [Claude Code hook reference](https://code.claude.com/docs/en/hooks) and [Codex hook reference](https://developers.openai.com/codex/hooks/) on October 18, 2026 for event, decision, trust and tool-coverage semantics. Confirm the installed host's behavior before relying on those capabilities. This is review guidance; code-audit's packaged behavior remains unchanged and this document establishes no measured improvement in audit quality.

The follow-up synthesis is **Engineering effective agent hooks**, maintained in Build Loop at `docs/hooks-guide.md` and indexed in the local research library under `agents.hooks-engineering-guide-2026-10-18`, associated with both build-loop and code-audit. This reference keeps the portable audit checks; the guide owns the broader operating explanation.

The requested [Oct. 13 Claude Code: Advanced webinar](https://anthropic.ondemand.goldcast.io/on-demand/26b3d349-9fd9-4fa3-b122-f5b2f07c17a5) exposed its title and speaker metadata, but no usable recording/transcript here. Its teaching content remains un-ingested. Separate Anthropic [Advanced Patterns](https://anthropic.ondemand.goldcast.io/on-demand/f52c4cc3-7b23-4ab8-93f3-d202706dd62b?t=5.28) and [What We Shipped](https://anthropic.ondemand.goldcast.io/on-demand/9e373c2d-26b9-4a37-917d-c355df38c6a1) indexed discussions support the formatting/notification examples and caution about obsolete hooks or excessive context; they are supplemental sources, not substitutes attributed to the requested recording.
