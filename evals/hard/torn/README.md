# Torn and lost appends: does a checklist item help on unseen cases? (pre-registered 2026-11-01)

Every arm in every run so far missed H07, a torn append: one logical record written with two write calls. Neither the focused checklist nor the cards cover this class. This run tests whether a new checklist item, C7, helps a reviewer find it. The test uses **fresh cases**, not H07.

This file and `cases-public.json` were committed before C7 was written and before any trial of this run.

## Cases (fresh, mined 2026-11-01)

There are six real defects, each confirmed by a later fix commit. None of them is H07 or comes from the same function as an earlier case. The class is a record lost or corrupted by how a log or state file is appended or rewritten:
- writing a record and its newline separately;
- `seek`-to-end followed by a write, without O_APPEND;
- an unlocked read-modify-write of a shared file;
- an atomic rename used where a lock is needed, so updates are still lost.

| ID | Repository | Visibility | Class |
|---|---|---|---|
| T01 | private-desktop-app | private | torn-tail handling erases a complete record |
| T02 | private-assistant-app | private | unlocked rewrite of an append log |
| T03 | build-loop @ 8afb55f (fix bdf7cdf) | public | unlocked read-modify-write; mid-write read wipes state |
| T04 | private-desktop-app | private | lost update through a snapshot rewrite |
| T05 | build-loop @ 560acf3 (fix adde4a3) | public | missing lock that other writers hold |
| T06 | private-desktop-app | private | seek-to-end write without O_APPEND across processes |
| TC3 | build-loop @ bdf7cdf | public | control: T03 after its fix |
| TC6 | private-desktop-app | private | control: T06 after its fix |

The private cases come from the owner's private repositories. Their manifest and answer key stay outside this public repository, at `.build-loop/evals/torn/`. These hashes fix them before any trial:
- `cases-all.json` sha256 `ddc4e8ff66a635abc935b9e9202a3c710f110489cb1f9079f8f7ae04941bec32`
- `oracles-all.json` sha256 `b7307427c88595e9677bd7041ca29d26790dd45edddd99dd9d8c9330f84d5582`

Trials send private code to the same Codex lane the owner already uses for those repositories. No private code or answer text is committed here.

## Arms

| Arm | Guidance |
|---|---|
| `code-audit-full` | The full bundle at 405a6b0: SKILL.md files, the focused checklist and all 30 cards. |
| `code-audit-full-c7` (subject) | The same bundle built at the next commit, which adds only checklist item C7. |
| `none` | No guidance. |

The model, effort, isolation, schema-constrained output and blinded Opus-tier judging are those of the hard benchmark. Each case runs twice per arm. There is no pilot: every case is fresh, and all are scored.

## Verdict

Let Δ = `code-audit-full-c7` − `code-audit-full`, computed over T01–T06 with controls TC3 and TC6.
- **C7 helps** if detection Δ ≥ +0.15 and control false-positive Δ ≤ +1.
- **C7 hurts** if detection Δ ≤ −0.15 or control false-positive Δ ≥ +2.
- Otherwise the result is **no measurable effect**.

The result against `none` is reported too. Six cases with two repetitions each is a small sample: one trial is 0.083.
