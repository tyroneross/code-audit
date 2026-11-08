# UB measurement and repair practices

Reviewed November 8, 2026 from pinned source: Uncle Bob's MIT-licensed [ub-mode](https://github.com/unclebob/ub-mode/blob/3da62bf3fcfd2034de41f30d920d2739e566171f/SKILL.md), revision `3da62bf3fcfd2034de41f30d920d2739e566171f`.

Selected contributions are explicit complexity/coverage scoring, structural duplicate candidates, mutation checks, observed failing regressions, behavior-preserving refactoring and testing the shared premise of repeated failed repairs. Code Audit applies these through [measurement guidance](../skills/code-principles/references/measurement.md), preserving causal evidence, contextual thresholds and task authorization.

Companion implementation contracts checked at these revisions:

- [Crapper CLI](https://github.com/unclebob/crapper/blob/6fd92c4c9bcc56efb64a2f8743d5a2993bcfd42d/src/crapper/cli.py), `6fd92c4c9bcc56efb64a2f8743d5a2993bcfd42d`: threshold and empty-scope handling require interpretation; missing compatible coverage is not zero.
- [Dryer CLI](https://github.com/unclebob/dryer/blob/66ff6d21a42c04afcad89c78a80066176d1294b0/src/dryer/cli.py), `66ff6d21a42c04afcad89c78a80066176d1294b0`: similarity reports are candidates; default 0.82 differs from UB's 0.8 recommendation.
- [Mutator](https://github.com/unclebob/mutator/tree/a5a0cb803b66e0cdb8bf471b3b08af701d424a41), `a5a0cb803b66e0cdb8bf471b3b08af701d424a41`: failure classification, cache freshness and worker import provenance limit claims about test strength.

A bounded paired trial on Code Audit and private-desktop-app found a shared index lost-update defect. Measurements supplied separate structural leads. The trial did not establish reviewer superiority, whole-repository recall or runtime speed gains. Recheck installed contracts when tool versions change. Companions are not installed or executed automatically, and source lifecycle guidance grants no push, cleanup or credential authority.
