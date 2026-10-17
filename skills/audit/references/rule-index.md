# Thirty conditional coding principles

Apply [audit interpretation](audit-interpretation.json) before selecting a rule or check. Technique prerequisites never exclude unsafe uses or unsupported claims. Validation probes adapt to the actual contract; options may combine or form stages.

Spectrum recommendations and grouping are analyst interpretation of the researched guide, not direct author prescriptions. Positions are qualitative alternatives, not scores or a universal ranking.

## Plan and deliver software

What must work?

- [P01 — Define what the software should do before coding](cards/P01.md): Before coding, clarify expected behavior with concrete examples whenever different interpretations could change the result.
- [P02 — Make builds, checks, and releases repeatable](cards/P02.md): When a build, check, or delivery step must be repeated or handed off, make it reproducible and add automation only when its recurring benefit justifies maintenance.
- [P03 — Use safe defaults and ask users when their judgment is needed](cards/P03.md): When a workflow requires a choice, use a safe default for implementation details and ask the user when their preferences, judgment, or authority are necessary.
- [P04 — Match design and testing effort to failure risk](cards/P04.md): Match engineering effort to the cost of failure and expected reuse, using the simplest approach that still meets the required correctness, recovery, and compatibility guarantees.
- [P05 — Estimate delivery dates from evidence and state the uncertainty](cards/P05.md): When planning delivery, investigate major unknowns and use comparable completed work where available, stating uncertainty instead of promising precision the evidence cannot support.

## Organize code and data

Where should complexity live?

- [P06 — Make each value's meaning clear and prevent incorrect use](cards/P06.md): Give values specific names that communicate their meaning, units, and purpose, and use types and validation checks where needed to prevent values with different meanings from being used interchangeably.
- [P07 — State the behavior and limitations callers must know](cards/P07.md): When wrapping a dependency, hide unnecessary machinery while explicitly preserving the timing, failure, consistency, and other guarantees that callers need to make correct decisions.
- [P08 — Keep code together when it changes for the same reason](cards/P08.md): Separate code when its parts change for different reasons or owners, and keep it together when splitting would scatter one coherent rule.
- [P09 — Add ways to extend code only for real alternatives](cards/P09.md): Add an extension point only when real or committed variations share a stable contract and separating them is simpler to maintain than repeatedly changing the existing code.
- [P10 — Preserve behavior that callers rely on when replacing code](cards/P10.md): Use an implementation as a substitute only if it accepts all permitted inputs and preserves the behavior and guarantees that existing callers rely on.
- [P11 — Give each component only the operations it needs](cards/P11.md): Expose only the coherent capabilities a consumer needs when doing so reduces unwanted dependencies or separates meaningful permissions, without fragmenting operations that belong together.
- [P12 — Separate business rules from databases, frameworks, and services](cards/P12.md): Separate durable business rules from frameworks and external services when that lets the rules change or be tested independently at a justified maintenance cost.
- [P13 — Split code only when the whole operation becomes easier to understand](cards/P13.md): Extract a function or module only when its name and interface reduce the total context needed to understand, use, and change the operation.

## Handle failures and partial changes

What happens when it fails?

- [P14 — Classify failures by the safe next action](cards/P14.md): When an operation fails, classify the failure by what the responsible component can safely do next, based on the actual operation and affected state.
- [P15 — Report failures in a form callers can handle correctly](cards/P15.md): When designing a failure contract, choose results, exceptions, or translation according to the caller's required actions and the runtime's actual propagation and cleanup guarantees.
- [P16 — Handle failures where enough context exists to respond safely](cards/P16.md): Handle a failure at the component that can take a useful, safe next action; otherwise preserve context and pass it to that component.
- [P17 — Stop work that could use corrupted data or invalid resources](cards/P17.md): When a failure makes state unsafe to use, stop the operation, worker, or process needed to contain the damage, and continue unrelated work only if its state remains trustworthy.
- [P18 — Define what happens when an operation succeeds only in part](cards/P18.md): If an operation can fail after changing visible or persistent state, define which effects commit together and how incomplete effects will be reported, rolled back, or reconciled.
- [P19 — Retry failed requests only when another attempt can help safely](cards/P19.md): Retry a failed request only if the next attempt has a reasonable chance of succeeding and can be made without excessive load or harmful duplicate effects.

## Manage background and parallel work

Who owns unfinished work?

- [P20 — Keep background work supervised until it finishes or stops](cards/P20.md): When background work can outlive its caller or become obsolete, keep its resources valid until it stops, assign an explicit owner, and prevent stale results from changing current state.
- [P21 — Decide what happens when one of several parallel tasks fails](cards/P21.md): When several tasks form one operation, define whether failure cancels the rest, results are gathered, or work continues under another owner, and report completion according to that contract.

## Test behavior and explain decisions

What evidence supports the claim?

- [P22 — Choose when to write tests and when to explore first](cards/P22.md): For lasting or consequential behavior, write meaningful tests before or alongside implementation when expected outcomes are known, and explore first when they are not.
- [P23 — Verify the actual outcome before claiming the change works](cards/P23.md): Before claiming a change works, run a check that observes the behavior at the claimed boundary, whether that is logic, integration, rendered UI, installation, or deployment.
- [P24 — Simulate difficult test conditions and verify assumptions against real systems](cards/P24.md): Use a fake or mock when controlled dependency behavior makes a meaningful test practical, and check its assumptions against the real dependency when integration behavior matters.
- [P25 — Explain why code exists when the reason is not obvious](cards/P25.md): Document a design's rationale when future changes depend on constraints or tradeoffs the code cannot explain, including what would invalidate the decision.

## Change and operate software

What should we preserve or change?

- [P26 — Choose gradual improvement or replacement without losing required behavior](cards/P26.md): Improve existing code incrementally when that preserves useful behavior at lower risk, and replace it when required benefits justify the migration and verification costs.
- [P27 — Plan transitions when existing users depend on old behavior](cards/P27.md): When changing a public contract or stored format, preserve behavior that supported consumers need unless correctness, safety, or a justified retirement requires an explicit break or migration.
- [P28 — Improve performance only where measurements show a real problem](cards/P28.md): Optimize only when representative measurements show a meaningful resource problem, and keep a change only if it improves the relevant result while preserving required behavior.
- [P29 — Separate processes or services only when isolation, scaling, or independent releases justify the cost](cards/P29.md): Give a component its own process or service only when the isolation, scaling, ownership, or deployment benefit justifies the new communication and operating costs.
- [P30 — Choose custom code, libraries, or services by required behavior and ongoing cost](cards/P30.md): Choose custom code, a library, or a service by whether it supplies the required guarantees at a lifecycle cost the team can maintain and justify.
