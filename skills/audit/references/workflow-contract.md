# Discovery, planning and repair have different evidence boundaries

`campaign.py inventory` reads eligible regular UTF-8 source through the same no-follow reader as the audit collector. It does not import or execute source. Defaults: 100 primary files / 1,000,000 bytes per batch, 200,000 bytes per file, 100,000 enumerated entries, 50 optional Python observations per file. Budgets are adjustable up to existing snapshot ceilings; observation ceiling is 5,000. Inventory JSON is bounded to 8 MiB. If the metadata would exceed that ceiling, the command rejects the output and asks for explicit subtree inventories. Resource ceilings are not principle thresholds or a promise of unlimited scanning.

An inventory records each eligible file's path, hash, bytes and physical lines; omissions; deterministic path-ordered batches; optional syntactic observations; and its content-derived identity. Discovery can be partial due to enumeration, unreadable/unsafe sources or per-file byte budgets. Excluded dependency/generated/likely-secret/binary material stays outside the eligible inventory. Excluded directories are unenumerated subtrees, not counted skipped files. No `.gitignore` completeness or secret-detection guarantee is claimed.

`batch` validates inventory structure/digest, rejects missing or changed selected source, and uses the existing collector. Context paths must also be inventoried; they can expand a primary batch up to the existing snapshot file/byte ceilings. Inspect that expansion cost before loading it. Failure to collect the exact selection leaves an explicit failed snapshot rather than a valid-looking partial batch.

A review ledger has this shape:

```json
{
  "inventory_id": "the exact inventory digest",
  "reviews": [
    {"snapshot": "batch-001", "report": "report-001.json", "reviewed_files": ["src/example.py"]}
  ]
}
```

Artifact paths are relative to the ledger's folder and cannot escape it. Each report must pass the existing thirty-rule complete-report/evidence validator. Every attested nonempty file must match the inventoried hash and appear in a source locator; an empty file can be attested by its verified empty hash. A file merely copied as context does not count unless explicitly attested. Attestation is the reviewer's claim, not independently proven comprehension.

`progress --check-current-root` scans the eligible inventory again with the same budgets and compares additions, deletions, hashes, omissions and discovery state. Without this flag, freshness is explicitly unchecked and complete selected-inventory review is false. Even complete selected-inventory review is not compliance, defect absence, repair completion or coverage of excluded material. Findings retain their report/rule/index references; the agent groups semantic duplicates. Source changes begin a new inventory generation.

`planning.py prepare` takes a snapshot, current root, goal file and new outside-root folder. It emits a rationale index and unfinished thirty-decision template. A completed plan has exact fields: schema/catalog/snapshot identity, goal, scope, acceptance, context, steps, decisions and limitations. Context entries contain fact/basis/evidence; `source` and `inference` require exact locators, while user statements, assumptions and unknowns stay labeled.

Each decision contains ID, disposition, reason, context references, premises, approach, tradeoff, revisit trigger and planned verification (plan/expected outcome/boundary). Dispositions are apply, exclude, needs_context or unreviewed. Applying/excluding requires explicit non-unknown context; applying additionally requires all decision and verification fields and at least one corresponding step. Every step names its action, proposed paths and applied principles. Step paths must stay inside proposed scope. Unknown or duplicate IDs, fabricated citations, mismatched catalogs and incomplete decisions are rejected. `check --require-ready` also rejects unresolved decisions and missing acceptance/steps.

Readiness is structural. It neither verifies an assumption nor grants permission. Source freshness checks included files only, so broader dependency or addition coverage uses the campaign comparator. The specialist reviewer evaluates whether the reasons are specific, the exclusions justified, and the alternatives/tradeoffs proportionate. Arbitrary keyword presence cannot establish that judgment.

Planning preparation requires a new output directory outside the repository and source snapshot. Rendering defaults to stdout; `--out` creates a new file at the caller-selected destination, including inside a repository if explicitly chosen, and never overwrites an existing file. Neither operation runs check commands or repairs. Skills guide a host agent to perform authorized changes using its actual tools, ownership process and verification. The repair record is a transparent working artifact; there is no automatic fix-certification or command-execution engine. Verified repair requires actual before/after observations and reviewer judgment at the claimed boundary.

Generated JSON is checked against the shared 8 MiB reader budget before writing. Audit preparation preflights manifest and report-template metadata before publishing them. A metadata rejection can leave collected files in a failed output folder, but exits with an error and publishes no usable-success claim; choose a new, narrower selection for recovery. A successfully written generated JSON artifact fits its reader budget.

New report packets use the [v2 outcome/decision contract](recommendation-contract.md). Complete v2 reviews connect findings to recommendations and define an objective even when the next action is investigation. `--require-outcomes` rejects legacy v1 when these guarantees are required. It checks fields, references, evidence consistency and numeric direction, not semantic quality or genuine speed/accuracy gains. Follow [outcome guidance](outcome-guidance.md) for the actual workload and verification decision.

All script commands use explicit new output paths; existing outputs are preserved. Exit 0 means a command completed, not that a codebase is correct. Planning check exits 1 for a rejected plan; malformed inputs and I/O failures exit 2. Campaign CLI errors exit 2. A successfully calculated incomplete progress report returns 0 while explicitly retaining pending/unknown state.
