# Code Audit

One plugin for reviewing code, tracing bugs and verifying proportionate improvements. It combines Code Principles Audit tools and Coding Debugger memory with shared engineering guidance and research.

## Use

Ask your agent to use **Code Audit**:

- Review this change for correctness, unnecessary work and recovery risks.
- Fix this recurring failure; check the shared cause and affected callers.
- Audit the repo against the thirty contextual principles.
- Check this implementation plan before building.

The [entry skill](skills/code-audit/SKILL.md) starts with pseudocode, selects the workflow and loads details relevant to the challenge. A review-only request remains read-only.

## Included

| Component | Purpose |
|---|---|
| `skills/code-audit` | One entry for review, debugging, planning and improvement. |
| `skills/code-principles` | Focused checklist, source scanner and contextual engineering definitions. |
| `skills/audit`, `plan`, `improve` | Thirty-rule evidence reports, pre-build checks and improvement campaigns. |
| `skills/debug`, `debug-loop`, `debugging-memory`, `logging-tracer` | Causal investigation, verification and incident retrieval. |
| `runtime/debugger` | Bundled local incident-memory MCP implementation. |
| [Research](research/README.md) | Source links, applicability and limitations. |

Shared guidance covers simplicity, systems engineering, usability, human factors, data structures, failure isolation, whole-system repair and intentional timeouts. Choose the simplest adequate causal correction across supported paths.

Reviews track finding identity and disposition, inspect changed code and affected contracts, and separate severity from introduced/pre-existing origin. Incident lessons retain applicability, failed approaches and evidence limits. Start with the [review workflow](skills/code-principles/references/review-feedback.md), [incident learning](skills/code-principles/references/incident-learning.md) and [evaluation evidence](evals/review/README.md) when those challenges apply.

## Load locally

Python 3.10+ runs audit tools; Node.js 18+ runs memory. Compiled debugger code is included, so ordinary MCP use needs no dependency installation. No automatic mining hook is enabled.

Clone the repository once:

```sh
git clone https://github.com/tyroneross/code-audit.git
```

Claude Code, from the project being inspected:

```sh
claude --plugin-dir /absolute/path/to/code-audit
```

Invoke `/code-audit:code-audit` or ask to use Code Audit.

Codex: this repo includes a local marketplace. Register its folder:

```sh
codex plugin marketplace add /absolute/path/to/code-audit
```

Install into your selected Codex configuration and test in a new chat:

```sh
codex plugin add code-audit@code-audit-local
```

The local CLI checks exercised automatic skill and MCP discovery in isolated configurations. Desktop Plugins Directory installation remains a separate UI boundary. See the [official local marketplace instructions](https://developers.openai.com/plugins/build/plugins). Portable manifests and the `.codex-plugin` compatibility manifest are included. See [observed host checks](docs/verification.md) for the tested CLI boundaries and limits.

For manual use, read `skills/code-audit/SKILL.md` explicitly. Paths resolve relative to the installed skill. Without MCP registration, continue source review/debugging and disclose the memory gap.

## Memory and effects

Memory uses the compatible per-project `.claude/memory` path and explicit `CLAUDE_MEMORY_*` overrides; shared mode is opt-in. Installed hosts that start MCP inside the package must supply the authorized absolute `project_root` on `status` and every memory call. This selects a local corpus per request; package-root access otherwise fails visibly. Incident tool calls write data, but this package enables no global setup, mining or background daemon. Personal assistant memories remain separate. Audit/scanner tools read source and write outputs to specified locations; repairs require task authorization. Inspect private code/logs before external sharing. The plugin itself requires no cloud service or API key.

## Verify

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s skills/audit/scripts -p 'test_*.py'
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s skills/code-principles/scripts -p 'test_*.py'
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_*.py'
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s evals/review -p 'test_*.py'
```

For runtime development use the bundled package lockfile, disable install scripts, build TypeScript and rerun the supplied runtime suites. Compiled outputs are tracked for dependency-free startup. See [integration](docs/integration.md), [source provenance](docs/source-provenance.json) and [verification](docs/verification.md). Source checks, host loading, model repairs, live application behavior and deployment remain separate evidence.

Search results report historical verification and checked/loaded/skipped corpus counts. Partial coverage remains visible even when no matches are returned. Detailed checklists load only for relevant challenges; the [matched comparisons](evals/matched/README.md) retain the no-guidance control and adverse evidence.

Internal file logging is off by default. Explicit `DEBUGGER_LOG_ENABLED=1` enables diagnostic writes and marks MCP tools as having side effects; logs can contain sensitive operation details. `read_logs` stays within the server working directory and refuses home, its ancestors and filesystem-root scopes, reads at most 16 files of 1 MiB each and returns at most 500 entries; rejected or skipped files are reported. Log tool responses stop at 32 KiB with an explicit truncation notice; narrow filters or use project tools for full logs. These are conservative interactive inspection budgets, not exhaustive log analysis.

For distribution, use `git archive` from the validated commit; it excludes ignored local state and development dependencies. A direct `--plugin-dir` launch is local development use and does not filter ignored files. Confirm the server working directory in the host before relying on per-project memory or log scope.

## License

[Apache License 2.0](LICENSE). Source origins and adaptations are recorded in [source provenance](docs/source-provenance.json).

Programmatic debugger APIs and storage boundaries are described in [retrieval contracts](docs/retrieval-contracts.md). Larger source-backed instruction and temporary-corpus comparisons can be run explicitly with the [repository evaluation harness](evals/repository/README.md).
