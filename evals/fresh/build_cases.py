#!/usr/bin/env python3
"""Assemble mined lane outputs into cases.json + private/oracles.json, validating every case against git.

  build_cases.py LANE.json [LANE.json ...] [--check]

Checks per case: parent is the fix's first parent; every packet file exists at the parent; ranges are in bounds;
files over 700 lines have ranges; oracle windows are in bounds and inside the packet; the fix commit changes the
oracle file. A failing case is reported and left out, never repaired. Controls: a seeded draw of 8 defect cases,
reviewed again at the fix revision.
"""
import argparse
import json
from pathlib import Path
import random
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = Path('/Users/tyroneross/dev/git-folder')
SEED, CONTROLS = 20261101, 8


def git(repo, *args):
    return subprocess.run(['git', '-c', 'credential.helper=', '-C', str(ROOT / repo), *args], capture_output=True, text=True, timeout=60)


def lines_at(repo, rev, path):
    r = git(repo, 'show', f'{rev}:{path}')
    return None if r.returncode else len(r.stdout.splitlines())


def problems(c):
    out = []
    first_parent = git(c['repo'], 'rev-parse', c['fix'] + '^').stdout.strip()
    if first_parent != c['parent']: out.append('parent is not fix^')
    sizes = {}
    for f in c['files']:
        n = lines_at(c['repo'], c['parent'], f['path']); sizes[f['path']] = n
        if n is None: out.append(f'missing {f["path"]}'); continue
        if n > 700 and not f.get('ranges'): out.append(f'{f["path"]} has {n} lines and no ranges')
        for a, b in f.get('ranges') or []:
            if not 1 <= a <= b <= n: out.append(f'range {a}-{b} outside {f["path"]}')
    o = c['oracle']
    for w in [{'file': o['file'], 'lines': o['lines']}] + o.get('also', []):
        n = sizes.get(w['file']) or lines_at(c['repo'], c['parent'], w['file'])
        if w['file'] not in sizes: out.append(f'oracle file {w["file"]} not in packet')
        for a, b in w['lines']:
            if n is None or not 1 <= a <= b <= n: out.append(f'window {a}-{b} outside {w["file"]}')
            ranges = next((f.get('ranges') for f in c['files'] if f['path'] == w['file']), None)
            if ranges and not any(ra <= a and b <= rb for ra, rb in ranges): out.append(f'window {a}-{b} not inside packet ranges')
    changed = git(c['repo'], 'diff', '--name-only', c['parent'], c['fix']).stdout.split()
    if o['file'] not in changed: out.append('fix does not change the oracle file')
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('lanes', nargs='+', type=Path); p.add_argument('--check', action='store_true')
    a = p.parse_args()
    mined = [c for lane in a.lanes for c in json.loads(lane.read_text())]
    keys = [c['key'] for c in mined]
    if len(keys) != len(set(keys)): sys.exit('duplicate keys')
    good, bad = [], {}
    for c in mined:
        issues = problems(c)
        (bad.__setitem__(c['key'], issues) if issues else good.append(c))
    review, oracles = [], {}
    for n, c in enumerate(good, 1):
        review.append({'id': f'F{n:02d}', 'key': c['key'], 'repo': c['repo'], 'revision': c['parent'], 'role': 'defect', 'language': c.get('language'), 'files': c['files']})
        oracles[c['key']] = dict(c['oracle'], fix=c['fix'])
    for m, case in enumerate(sorted(random.Random(SEED).sample(review, min(CONTROLS, len(review))), key=lambda r: r['id']), 1):
        fix = oracles[case['key']]['fix']
        files = [{'path': f['path'], **({'ranges': [[r[0], min(r[1], lines_at(case['repo'], fix, f['path']) or r[1])] for r in f['ranges']]} if f.get('ranges') else {})}
                 for f in case['files'] if lines_at(case['repo'], fix, f['path'])]
        review.append({'id': f'FC{m:02d}', 'key': case['key'], 'repo': case['repo'], 'revision': fix, 'role': 'control', 'control_of': case['id'], 'files': files})
    cases = {'version': 1, 'repos_root': str(ROOT), 'oracles': '../fresh/private/oracles.json', 'review': review, 'repair': [],
             'arms': ['none', 'hint', 'none-2pass', 'none+tools', 'bundle+tools', 'adaptive', 'fixed-plan', 'principles+tools'],
             'subject': 'adaptive', 'comparators': ['none+tools', 'bundle+tools', 'fixed-plan', 'principles+tools']}
    print(json.dumps({'mined': len(mined), 'valid': len(good), 'rejected': bad, 'controls': [r['id'] + '<-' + r['control_of'] for r in review if r['role'] == 'control']}, indent=1))
    if a.check: return
    (HERE / 'private').mkdir(exist_ok=True)
    (HERE / 'cases.json').write_text(json.dumps(cases, indent=1) + '\n')
    (HERE / 'private/oracles.json').write_text(json.dumps(oracles, indent=1) + '\n')


if __name__ == '__main__':
    main()
