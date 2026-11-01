# Review GPUI behavior against the application's pinned source

Apply these checks to the changed flow and its affected consumers. An upstream
example, scanner signal, architecture map or historical incident is a lead.
Confirm the trigger, cause and user consequence before reporting a defect.
This reference does not require a complete application audit for a small change.

## Establish compatibility and ownership

Read Cargo manifests, the lockfile, enabled features and vendored integration
notes. Identify the resolved GPUI/platform/macro family and local patches.
Shared ancestry does not make community GPUI, retained-rendering forks,
alternate backends or component-library entity/window/action types compatible.
Compare any copied API against the pinned source, not just current main docs.
Preserve attribution and intentional local adaptations when porting a fix.

Use an existing source-backed architecture map to find the relevant state owner
and boundaries. Keep revision, scanner version and scan scope with comparisons;
different scope can explain different node counts. Use semantic navigation for
Rust definitions and references when available. Record unavailable coverage;
successful navigation is not runtime verification.

## Trace the affected contract

| Change | Questions that distinguish a defect from intentional behavior |
|---|---|
| Text input | Are UTF-8/UTF-16 offsets converted at the right boundary? Do marked text, composition cancellation, reversed selection, replacement, clipboard and undo/redo preserve the existing contract? Does action routing respect key context and focus? |
| Settings/parser | Can an incomplete write become a valid prefix and replace last good state? Are comments inside strings preserved? Are invalid values, unknown fields, precedence and fallback reported at the owner that can recover? |
| Theme | Which foreground/background pairs do real consumers draw? Include secondary, warning, destructive and input-boundary roles when used. Verify inherited values under partial overrides and both supported appearances against the project's existing contrast policy. |
| Rendering/list | Which damage or invalidation changes require rebuilding? Do existing caches include all relevant font, width, theme and selection inputs? Preserve stable identity, scroll anchor, follow-live intent and bounded retained history. |
| Native lifetime | Can a deferred callback query a released view? Which lock/thread owns closure, callback removal and native release? Trace resize, visibility, responder-chain and teardown ordering across host and embedded view. |
| Accessibility/layout | Are roles, names, values and actions usable? Does keyboard navigation reach the changed control? Check the real parent size, long content and large-text constraints through pixels or AX bounds. |
| Background stream | Are tasks owned and failures observable? Are queues and replay bounded? Does sequential admission preserve ordering or backpressure that parallel execution would break? |

For a settings repair, exercise the actual persisted-file load/reload path as
well as parser helpers. Include unfinished comments and strings, escaped quotes,
Unicode, comment markers in strings, partial overrides and inherited defaults.
Preserve recovery behavior and existing thresholds rather than weakening policy
to make a fixture pass.

For a lifetime repair, trace enqueue, execution, teardown and cancellation.
Verify a queued task after closure and callback removal where the architecture
allows a deterministic test. Native create/close observations complement that
test; absence of a crash without baseline reproduction does not prove its cause.

## Reject misleading optimization leads

An await inside a loop can preserve ordered stream output, capacity admission
or intentional pacing. Confirm independence before proposing fan-out. Rust's
iterator `unzip()` separates tuples; a text scanner may mistake its spelling
for decompression. Record the rejected lead instead of repairing unrelated code.

Inspect existing row/glyph caches before adding another cache. Compare the same
representative workload and build configuration before claiming a speed gain.
Upstream benchmark numbers are not measurements of this application's platform,
embedding layer or workload. Review cold start, invalidation, bounds and cleanup
when a cache is justified.

## Close findings with proportionate evidence

Record the candidate revision and affected paths. A confirmed finding needs its
trigger, cause, consequence, counterevidence, smallest adequate correction and a
check that would distinguish working from broken behavior. In authorized repair
work, reproduce against baseline when feasible, rerun after repair and verify
affected supported behavior. In review-only work, recommend without editing.

Distinguish model/unit tests, application compilation, standalone native runtime,
embedded host runtime and installed-app acceptance. An empty or unavailable AX
scan leaves native acceptance unverified. Settings logs alone do not establish
visible text contrast, IME behavior or accessibility. State the missing coverage
and continue independent authorized checks.

Use the existing incident/outcome tools when recording is authorized. Reuse
finding identities and check earlier closure premises before reopening a defect.
Keep private source, session data and project-specific evidence in the project's
private lane. A reusable reference should contain portable guidance and public
source links.

## Source basis and freshness

Research baseline: 2026-11-01. Refresh revision-sensitive API and dependency
claims before applying them. Project-specific source and tests remain the
authority for that application's behavior.

- [Official GPUI README](https://github.com/zed-industries/zed/blob/main/crates/gpui/README.md)
- [GPUI examples and desktop patterns](https://gpui.rs/examples/)
- [Longbridge GPUI Kit](https://github.com/longbridge/gpui-kit)
- [Community GPUI](https://github.com/gpui-ce/gpui-ce)
- [GPUI starter](https://github.com/lassejlv/gpui-starter)

Starter files and demos require inspection: an included configuration file does
not prove the application loads it. Framework or mobile migration needs a named
requirement, compatibility assessment and candidate-specific acceptance work.
