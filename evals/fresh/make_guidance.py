#!/usr/bin/env python3
"""Write the frozen round-2 guidance files from git, so each arm's text is reproducible from a commit.

  make_guidance.py --methods-rev REV

bundle+tools = the four code-audit SKILL.md files at PRE (pre-methods main), joined like earlier bundles.
adaptive     = the same four files at REV plus skills/code-audit/references/audit-methods.md.
fixed-plan   = adaptive with the adaptation section, recipe R6 and the "adapt" instruction removed.
principles+tools = the existing source bundle evals/matched/guidance/code-principles-audit.txt.
"""
import argparse
import hashlib
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
PRE = '6168d75'
SKILLS = ['skills/code-audit/SKILL.md', 'skills/code-principles/SKILL.md', 'skills/debug/SKILL.md', 'skills/debug-loop/SKILL.md']
METHODS = 'skills/code-audit/references/audit-methods.md'


def show(rev, path):
    return subprocess.run(['git', '-C', str(REPO), 'show', f'{rev}:{path}'], capture_output=True, text=True, check=True, timeout=30).stdout


def bundle(name, rev, paths, texts=None):
    full = subprocess.run(['git', '-C', str(REPO), 'rev-parse', rev], capture_output=True, text=True, check=True, timeout=30).stdout.strip()
    parts = [f'# Frozen {name} guidance bundle: {full}; files load in this order. Relative links do not resolve in this packet.']
    for path in paths:
        text = (texts or {}).get(path) or show(rev, path)
        parts.append(f'===== {path} (sha256 {hashlib.sha256(text.encode()).hexdigest()[:16]}) =====\n{text}')
    return '\n'.join(parts)


def without_adaptation(methods, router):
    """Remove section 4, the R6 recipe and every R6 mention; the starting route stays."""
    cuts = [(r'\n## 4\. Adapt during the audit\n.*?(?=\n## 5\.)', '\n'),
            (r'\n\*\*R6:<slug> — class sweep\.\*\*[^\n]*\n', '\n'),
            (r', `R6:<slug>`', ''), (r', recipe id `R6:<slug>`', ''), (r'`R1`…`R5b`, `R6:<slug>`', '`R1`…`R5b`'),
            (r'Log every recipe, sweep and convention grep', 'Log every recipe'),
            (r'; stop and report the dimension as low precision', ''),
            (r'- Append `low precision n/N` when the noise rule in section 4 stopped the method\.\n', ''),
            (r'The starting route is a plan\.[^\n]*\n', '')]
    for pattern, repl in cuts:
        methods = re.sub(pattern, repl, methods, flags=re.S)
    router_new = router.replace('follow the starting route in references/audit-methods.md, adapt per its rules and end with its coverage matrix',
                                'follow the starting route in references/audit-methods.md without changing it and end with its coverage matrix')
    if router_new == router: raise SystemExit('router adapt line not found')
    for word in ['Adapt during', 'R6', 'class sweep', 'adapt per']:
        if word in methods or word in router_new: raise SystemExit(f'fixed-plan still mentions {word!r}')
    return methods, router_new


def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--methods-rev', required=True); a = p.parse_args()
    out = HERE / 'guidance'; out.mkdir(exist_ok=True)
    files = {
        'bundle+tools': bundle('code-audit (pre-methods)', PRE, SKILLS),
        'adaptive': bundle('code-audit adaptive', a.methods_rev, SKILLS + [METHODS]),
        'principles+tools': (REPO / 'evals/matched/guidance/code-principles-audit.txt').read_text(),
    }
    methods, router = without_adaptation(show(a.methods_rev, METHODS), show(a.methods_rev, SKILLS[0]))
    files['fixed-plan'] = bundle('code-audit fixed-plan', a.methods_rev, SKILLS + [METHODS], {METHODS: methods, SKILLS[0]: router})
    for name, text in files.items():
        (out / f'{name}.txt').write_text(text)
        print(name, len(text), hashlib.sha256(text.encode()).hexdigest())


if __name__ == '__main__':
    main()
