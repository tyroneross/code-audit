# Frozen values and path length

Two review procedures for problems that pass tests on the author's machine and break somewhere else: values that should be dynamic but are frozen in code, and paths with more layers than the job needs. Use them during focused review when the change touches configuration, versions, identifiers, environment-facing code, or structure (new layers, wrappers, services, state owners). Pair the second with cards [P09](../../audit/references/cards/P09.md) (extension points), [P13](../../audit/references/cards/P13.md) (splitting) and [P29](../../audit/references/cards/P29.md) (separate services); this file supplies the procedure, the cards supply the tradeoffs.

## 1. Frozen values that should be dynamic

**The test is not "is this a literal".** A value is a finding when it has a live source of truth, or varies by context, and the code freezes a copy anyway. Literals that *are* the source of truth, protocol constants and real policy are correct.

### Where frozen values come from

| Kind | Typical shape | Source of truth or varying context |
|---|---|---|
| Duplicated value | the same file name, schema id, env-var name, URL or key defined in two modules or two languages | each other: one change must reach every copy |
| Copied source | a version string, model id, price, limit or list copied from a manifest, config, DB, API or sibling constant | the manifest, config, DB, API or sibling |
| Environment-specific literal | `localhost`/ports, preview-deploy hosts, absolute or home paths, account/project/tenant ids, regions | the deployment, machine or tenant |
| Deployment-varying limit | timeouts, rate limits, batch sizes and thresholds tuned on one environment | the environment's measured behavior or config |
| Stuck toggle | `FEATURE_X_ENABLED = False`, `if (true)` | the flag service or config the toggle should read |
| Frozen time | a year, date or "latest" list compared in logic | the clock, the data or the catalog |
| User- or tenant-specific value | one customer's id, email, path or quota in shared code | per-user data |

### Procedure

1. **Name the source.** For each candidate, say where the value really comes from (file, config key, table, API, manifest, the constant it mirrors) or what it varies by (machine, deployment, tenant, date). If you cannot name one, it is probably not a finding.
2. **Check whether the code reads it.** A literal used only as a fallback after reading the source (`os.environ.get("X", default)`) is lower risk: check that the default is safe for the environments that will hit it.
3. **Find every copy.** Search for the literal value, not just the name; duplicates often have different names (`LOCK_NAME` vs `REGISTRY_LOCK_FILENAME`) or live in another language. Compare the copies: differing values are drift that has already happened.
4. **Trace the break.** State the context in which the frozen value goes wrong (another machine, a release bump, a second tenant, next year, a model retirement) and what the user sees then.
5. **Keep real constants.** Protocol values, units, standard ports in the protocol's own client, enum wire names that the wire format defines, and test fixtures stay. A value that looks wrong may encode a fact newer than your knowledge (a model id, a price, an API version): check the live source before calling it wrong.
6. **Repair at the source.** Read the value from its owner, generate the copies from it, or add a check that fails when copies disagree. Do not replace one literal with another.

### Order by harm

1. Absolute/home paths and environment-specific hosts: break on the next machine or deployment.
2. Values copied from a manifest or sibling that has already drifted.
3. Duplicated identifiers that must match (file names, schema ids, env-var names, wire names).
4. Deployment-varying limits, stuck toggles, model ids, frozen dates.

### Scanner support

`scripts/scan.py` reports section F candidates under the checklist's item numbers. It also flags cloud account ARNs and years compared in logic (F5), which had no hits to measure. Each hit still needs steps 1–5.

| Item | Signal | Precision measured 2026-10-28 |
|---|---|---|
| F1 | home or machine-specific absolute path in code | 91% on 8 tuning repos (10/11); 82% on 6 held-out repos (9/11), measured before two filters the held-out misses suggested |
| F2 | localhost/private-IP/preview-deploy host in code, unless read from env/config, a server this code started, or a URL parse base | 67% tuning (10/15 sampled); 60% held-out (9/15 sampled) before the parse-base and placeholder filters; weakest kept rule |
| F3 | a literal that copies this package's manifest version (`__version__`, client/server info) | 3/3 tuning; no held-out hits |
| F6 | an upper-case feature toggle fixed to true/false at module level | 1/1 tuning; no held-out hits |
| F7 | the same file name, path, URL, schema id or env-var name defined as a constant in several files (the constants/config file itself is not flagged) | 87% tuning (13/15 sampled); 100% held-out (15/15 sampled) |

Rules measured and **cut** because they were noisier than useful: model ids in code (~25%: most are catalogs, pricing tables or docs), generic account/tenant id assignments (mostly test data and wire-name mappings), date constructors (fixtures and "last updated" stamps), and unrestricted boolean toggles (UI properties and state assignments). Review those kinds by hand with the table above.

## 2. Shortest path and brittle structure

### Procedure

1. **Trace the operation** from the user's request or trigger to its outcome. Count hops: function or service boundaries, layers, indirections, handoffs between owners, serialization steps, and the configuration surfaces that must agree.
2. **Name the shortest correct path** that meets the same requirements: correctness, isolation, scale, compatibility and required observability. Say what each requirement forces, not what might be needed someday.
3. **Mark each extra layer with the capability it adds.** A layer earns its place with a named capability: isolation, independent deploy or scale (P29), a real alternative implementation (P09), a test seam at a real boundary, a stable public contract, or a meaningful simplification of the whole operation (P13). Flag layers that add none:
   - a pass-through wrapper that forwards its arguments unchanged;
   - an interface or factory with one implementation and no committed second one (count test fakes at a real boundary as a use);
   - a speculative plugin, registry or strategy system;
   - two owners of the same state, or a cache or mirror with no invalidation owner;
   - a service split with no isolation or scale need, so every call pays a network hop and a version skew.
4. **Judge brittleness by failure points and coupling, not taste.** For each extra hop, list what can now fail or disagree: serialization that drops fields, two tie-break rules for one record set, partial updates between owners, version skew, retries at two layers. A layer that adds a failure point and no capability is a finding; a layer that is merely unfamiliar is not.
5. **Recommend the smaller path** with a migration that preserves callers (P10, E6), or state why the current path is the shortest correct one.

### Scanner support

None. Pass-through functions (about 20% precise on the same repos: most are named aliases, adapters or callbacks) and single-implementation interfaces (the second implementation is usually a test fake, which the scanner skips) were measured and cut. Use the procedure.
