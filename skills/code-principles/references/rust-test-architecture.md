# Rust test architecture review

Load for Rust test relocation, crate splits, test duplication or shared harness proposals. These are review prompts, not mandatory layout rules or evidence of a defect.

Read manifests, workspace membership, custom lib/bin paths, autotests, explicit targets, required-features and build scripts. A package may expose several crates/binaries; a crate is not a running daemon. Separate production modules, cfg(test) code, integration targets, examples, benches, doctests, generated and vendored code. Physical lines and lexical test markers are not semantic production/test counts. Never subtract everything after the first cfg(test).

Unit tests may use private parent-module items. Moving them to a file under the same cfg(test) module preserves that access; moving them to tests/ makes them external consumers. Do not widen production visibility just to move tests. Integration dependencies do not inherit the library's cfg(test). Prefer package-local helpers; introduce a dev-only support crate only for demonstrated cross-package duplication. Inspect dependency kinds and features for shipping leakage. Features are additive; all-features does not prove default/minimal or incompatible configurations work.

For each reviewed test/suite record owner, behavior/risk, trigger, observable oracle, target/features/platform, fixture identity, measured cost and disposition: keep, move, consolidate, replace or remove. Follow assertions and failure paths. Similar names do not establish redundancy. A support-named top-level file may contain real tests; inspect it before calling it an accidental Cargo target.

For process tests check unique state/socket/port, exact binary identity, concurrent runs, deadlines, partial outcomes, normal shutdown and cleanup ownership. Preserve logs/state on uncertain cleanup. Distinguish write completion, delivery, acknowledgement and business completion. A sleep alone does not prove flakiness; an equivalent readiness/event signal must preserve the intended oracle. Do not manipulate live user credentials, apps or sessions by default.

Use RossLabs LSP definitions/references for visibility and cross-file impact. Record revision, target, features, platform, readiness and errors. Empty references cannot prove absence across cfg states, macros, dynamic registration or downstream consumers. Transport failure means unavailable. Do not restart shared servers implicitly. Rust indexing can execute build scripts/proc macros; strictly static reviews use Architect static scans and source reads instead. LSP diagnostics are not behavioral acceptance.

Architect maps relationships, Code Audit validates mechanisms/oracles, Build Loop executes authorized migrations. Prefer crate-owned tests and on-demand orchestration. A permanent test service needs a concrete capability justifying lifecycle, state and version-skew overhead. Do not centralize production authority in test support.

Retain regressions pending equivalent replacement evidence. Compare discovered test identities, not counts alone. Report sampled, reviewed, executed and unreviewed coverage separately. Moving cfg(test) code improves navigation; normal builds already exclude it, so release memory/speed gains require measurement.

Primary sources: [Rust test organization](https://doc.rust-lang.org/book/ch11-03-test-organization.html), [Cargo targets](https://doc.rust-lang.org/cargo/reference/cargo-targets.html), [Cargo features](https://doc.rust-lang.org/cargo/reference/features.html), [rust-analyzer security](https://rust-analyzer.github.io/book/security.html).
