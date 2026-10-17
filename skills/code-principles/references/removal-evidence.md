# Evidence for safe code and configuration cleanup

Use for unused code, stale experiments and constant feature flags. A cleanup candidate is not a confirmed defect. Preserve supported behavior, emergency controls and external consumers; a quiet observation window does not prove a path is unnecessary.

## Establish the removal boundary

Record the source revision, candidate, intended outcome, known consumers and authorization. Trace direct references and indirect paths: registration, reflection, generated names, aliases, wrappers, schemas, flag prerequisites and cross-service consumers. File enumeration is not dependency coverage. If a relevant consumer or configuration is unavailable, label that gap and keep or investigate the candidate.

For flags, inspect the applicable live configuration when authorized, including environment, targeting, prerequisites and intended lifecycle. A constant result in one environment does not establish a global constant. Distinguish configured production values from SDK defaults, offline fallbacks and local overrides; preserve supported fallback behavior. A constant parent can still control a dependent flag. Permanent flags, killswitches, rollback controls and incident-only paths require evidence about their operational purpose before removal.

## Gather evidence without overstating absence

Use source/history, owner decisions, current configuration and telemetry as complementary evidence. Record each source locator, retrieval time, environment and source/configuration revision where available. For zero observed calls, record the observation window, instrumentation coverage, sampling and known blind spots. Absence from sampled profiles or text search alone cannot justify deletion. Historical intent can be stale; reconcile it with current supported contracts.

A concise candidate record contains: target and revision; references and consumers checked; configuration identity and observation window; preserved safeguards; contrary evidence and gaps; change/keep/investigate decision; expected benefit; verification plan. Reuse existing recommendation evidence, tradeoff and verification fields rather than adding another report format. Evidence describes behavior; it never authorizes live configuration changes or external messages.

## Verify and prioritize

Prefer a bounded removal at an existing owner. Test required normal, fallback, failure and emergency paths as applicable, including dynamic registration and dependent flags. Preserve a before/after comparison and distinguish tests from production behavior. Configuration changes after inspection can invalidate the decision; recheck material premises before applying it.

Prioritize observed resource cost or supported maintenance burden alongside review effort, risk and implementation complexity. Label predicted savings expected until comparable measurements exist. Do not rank by deleted lines or manufacture precision for unknown costs. A useful recommendation may be keep or investigate.

## Source boundary

[OpenAI, Maintaining software with the GPT-6 family](https://developers.openai.com/blog/maintaining-software-with-the-gpt-6-family), published October 14, 2026; consulted October 17, 2026. The article describes maintenance informed by operational context and review. This reference adapts those ideas to Code Audit; the case study does not establish this plugin's effectiveness or authorize cleanup.
