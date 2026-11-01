#!/usr/bin/env python3
"""Freeze an arm's guidance bundle from committed skill files, in the same format as evals/matched/guidance/code-audit.txt.

  build_bundle.py ARM COMMIT [--check FILE]   print the bundle, or verify FILE equals it
"""
import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
FILES = ['skills/code-audit/SKILL.md', 'skills/code-principles/SKILL.md', 'skills/debug/SKILL.md', 'skills/debug-loop/SKILL.md']
# --full adds the reference text an installed plugin can load: the focused checklist and all 30 principle cards, in
# order, chosen without regard to any case (adding cards per case would leak the answer key).
REFERENCES = ['skills/code-principles/references/focused-checklist.md'] + [f'skills/audit/references/cards/P{n:02d}.md' for n in range(1, 31)]


def bundle(arm, commit, full=False):
    sha = subprocess.check_output(['git', '-c', 'credential.helper=', '-C', str(REPO), 'rev-parse', commit], text=True).strip()
    header = f'# Frozen {arm} guidance bundle: {sha}; files load in this order. Relative links do not resolve in this packet.\n'
    parts = []
    for path in FILES + (REFERENCES if full else []):
        data = subprocess.check_output(['git', '-c', 'credential.helper=', '-C', str(REPO), 'show', f'{sha}:{path}'])
        parts.append(f'===== {path} (sha256 {hashlib.sha256(data).hexdigest()[:16]}) =====\n' + data.decode())
    return header + '\n'.join(parts)


def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('arm'); p.add_argument('commit'); p.add_argument('--check', type=Path)
    p.add_argument('--full', action='store_true', help='also include the focused checklist and all 30 principle cards')
    a = p.parse_args(); text = bundle(a.arm, a.commit, a.full)
    if a.check:
        ok = a.check.read_text() == text; print('match' if ok else 'differs'); return 0 if ok else 1
    sys.stdout.write(text); return 0


if __name__ == '__main__':
    raise SystemExit(main())
