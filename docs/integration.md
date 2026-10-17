# Integration

This repository is the combined product source. The original repositories, installations and skill symlinks remain intact.

Audit scripts/cards are imported under `skills/`; debugger source and compiled code under `runtime/debugger`. The private runtime package removes its automatic postinstall setup. The root launcher starts only local MCP, with existing tool schemas and compatible storage paths. No lifecycle hooks are included.

The public router and debug adapter connect the workflows. Legacy instructions now disclose absent memory and independent execution; KNOWN_FIX still requires current-context validation. Shared engineering references live under `skills/code-principles/references/`. The runtime's internal server name/version identify the imported debugger; the root plugin version identifies the combined product.

The legacy CLI is retained for source/build compatibility, not registered as a plugin command. Procedures work without Claude-only agent registration. Earlier synthetic prose/pseudocode comparisons found no reliable winner: pseudocode-first is a navigation choice, not a proven accuracy gain. Details load conditionally.

The memory entrypoint was rewritten to match actual MCP schemas: manual isolated JSON writes and assumed domain-agent registration were removed. Structured verification metadata remains conservative; check receipts belong in the incident narrative and linked report. Audit package tests now validate the combined plugin identity/version separately from the retained audit-tool version.

Independent Opus review exposed inherited runtime issues. The combined runtime now disables internal file logging by default, describes retrieved fixes as historical candidates, bounds project log reads, recovers from malformed stdio lines, answers ping and negotiates supported basic-tool protocol versions. Outcome records reject unknown incidents, omit unknown historical verdicts and declare their append side effect. Unused legacy memory references and incidental session state were removed. These changes apply only to this combined repo.
