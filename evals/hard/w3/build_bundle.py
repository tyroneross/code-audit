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


def bundle(arm, commit):
    full = subprocess.check_output(['git', '-c', 'credential.helper=', '-C', str(REPO), 'rev-parse', commit], text=True).strip()
    header = f'# Frozen {arm} guidance bundle: {full}; files load in this order. Relative links do not resolve in this packet.\n'
    parts = []
    for path in FILES:
        data = subprocess.check_output(['git', '-c', 'credential.helper=', '-C', str(REPO), 'show', f'{full}:{path}'])
        parts.append(f'===== {path} (sha256 {hashlib.sha256(data).hexdigest()[:16]}) =====\n' + data.decode())
    return header + '\n'.join(parts)


def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('arm'); p.add_argument('commit'); p.add_argument('--check', type=Path)
    a = p.parse_args(); text = bundle(a.arm, a.commit)
    if a.check:
        ok = a.check.read_text() == text; print('match' if ok else 'differs'); return 0 if ok else 1
    sys.stdout.write(text); return 0


if __name__ == '__main__':
    raise SystemExit(main())
