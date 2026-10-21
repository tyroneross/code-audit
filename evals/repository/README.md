# Evaluate repository review and memory retrieval

Use this opt-in harness to compare added guidance against the same model without it on full repository modules. Keep retrieval evaluation separate from model review. These experiments do not establish production accuracy, safe advice or human-effort savings.

The two source manifests pin four complete modules at a defective revision and a repaired revision. Each packet contains about 2,900 numbered source lines. Each review receives one revision only, preventing paired repair leakage. These are two states of one codebase, not independent repository tasks; the repaired state controls for the named historical defect classes and may contain other defects. Source bytes must match their recorded hashes. The pinned Git objects must be available locally; shallow history may be insufficient, and the harness does not fetch automatically.

## Run explicitly

Use an existing file-based Codex session and a macOS host with `sandbox-exec`. The runner references the existing auth file through a temporary symlink, refuses missing authentication, ignores user configuration, and prohibits tools through the prompt and recorded-event validator. The OS policy denies repository, output and foreign temporary reads, Keychain file reads and the security helper. It is a bounded experiment boundary, not general security certification. No login, credential migration, automatic mining, global memory setup or installation occurs. The file-storage option follows the [official credential-storage contract](https://developers.openai.com/codex/auth#credential-storage).

```sh
python3 evals/repository/experiment.py review --repo . --out /absolute/private/new-review-run
python3 evals/repository/experiment.py adjudicate --repo . --out /absolute/private/new-review-run
python3 evals/repository/experiment.py score --out /absolute/private/new-review-run
python3 evals/repository/experiment.py revise --repo . --out /absolute/private/new-review-run
python3 evals/repository/experiment.py revision-score --out /absolute/private/new-review-run
python3 evals/repository/memory.py --repo . --out /absolute/private/new-memory-run.json
python3 -m unittest discover -s evals/repository -p 'test_*.py'
```

The example requests `gpt-6.1-sol` at medium effort; this is an experiment configuration, not a current model recommendation. Existing outputs are never overwritten. Initial review runs two repetitions across no-guidance/current/trimmed bundles from the existing matched experiment. Calls consume model usage. Keep raw captures, prompts, mappings, per-run ledgers and internal reports outside tracked product files. Only the reusable method, source manifests, test labels and tests belong in this directory. The harness has a Codex adapter; unsupported providers remain unavailable rather than using a credential fallback.

## Judge before interpreting

Adjudication runs in a fresh context with arm names replaced by blind labels. Every actual finding must receive source-based validity, correction-harm and duplicate judgments before the existing scorer accepts it. New valid defects outside named classes remain valid findings and create explicit oracle challenges. Do not force a historical repaired control to be globally clean. A source-adjudicated compound finding can cover multiple named causes; explicit secondary IDs and rationales form a coverage union while the original single-primary scorer output stays unchanged. Inspect challenges before comparing arms; the scorer validates accounting, not semantic truth. Reviewer and judge use the same model family in this adapter, so shared blind spots remain possible.

One optional assisted revision receives its own review plus source-adjudicated feedback, including disclosed missed classes. The revision uses a common correction instruction across all arms. Its score measures downstream revision work after feedback, never another blind detection result. Keep two-round failures and unavailable judgments censored. Token usage, wall time, finding workload and assisted revision rounds measure model effort; human correction time is unmeasured.

The memory experiment creates temporary synthetic records backed by actual source provenance, irrelevant controls and an explicitly misleading unverified record. It freezes exact-wording, paraphrased and negative queries before running both bundled retrieval paths. Record relevant rank, misleading rank, verification labels, returned IDs and inspected-corpus coverage. Missing a paraphrase measures this fixture's retrieval behavior; it does not by itself prove a contract defect. Retrieval matches do not establish that a model would choose a correct repair.
