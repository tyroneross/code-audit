#!/usr/bin/env python3
"""Reproduce or rebuild the section F scanner precision record from fixed commits.

  measure_precision.py --check            re-scan every repository at its recorded commit and confirm the sample
  measure_precision.py --record LABELS    rebuild the record from explicit labels (at the recorded commits, else HEAD)

Files are read from `git archive <commit>`, never from a working tree, so a moved or dirty checkout cannot change
the result. Every sampled hit needs an explicit tp/fp label; an unlabelled hit is an error, never a default.
SCANNER_REPOS_ROOT names the folder that holds the repositories (default: the folder above this repository).
"""
import argparse
import io
import json
import os
import random
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'skills/code-principles/scripts'))
import scan  # noqa: E402
import frozen  # noqa: E402

ROOT = Path(os.environ.get('SCANNER_REPOS_ROOT', str(REPO.parent)))
RECORD = REPO / 'skills/code-principles/references/frozen-values-precision.json'
REPOS = ['build-loop', 'NavGator', 'interface-built-right', 'agent-rally-point', 'spectra', 'local-smartz', 'decision-doctor-cc', 'code-audit']
SEED, PER_RULE = 20261029, 15


def git(repo, *args):
    return subprocess.check_output(['git', '-c', 'credential.helper=', '-C', str(ROOT / repo), *args])


def hits_at(repo, sha):
    """Section F hits for git-tracked, non-test source files at one commit, read from `git archive` (regular files only)."""
    archive = git(repo, 'archive', '--format=tar', sha)
    rows = []; files = 0; rels = []
    with tempfile.TemporaryDirectory(prefix='code-audit-precision-') as folder:
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            for member in tar:
                rel = member.name
                if not member.isreg() or rel.startswith('/') or '..' in rel.split('/'): continue
                manifest = any(rel == m or rel.endswith('/' + m) for m in frozen.MANIFESTS)  # F3 reads the owning manifest
                source = os.path.splitext(rel)[1] in scan.CODE_EXT and not scan.TEST_PATH.search(rel) and not any(part in scan.SKIP_DIRS for part in rel.split('/'))
                if not (manifest or source): continue
                target = Path(folder, rel); target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(tar.extractfile(member).read())
                if source: rels.append(rel)
        store = frozen.new_store(); skipped = []
        for rel in sorted(rels):
            found = scan.scan_file(os.path.join(folder, rel), rel, skipped, store)
            if found is not None:
                files += 1; rows.extend(h for h in found if h[0][0] == 'F')
        rows.extend(h for h in frozen.cross_file_hits(store, [folder]) if h[0][0] == 'F')
    return files, [(item, f'{repo}/{f}:{n}', label) for item, label, f, n, _ in rows]


def sample(shas):
    by_rule = {}; files = 0
    for repo in REPOS:
        n, rows = hits_at(repo, shas[repo]); files += n
        for item, key, label in rows: by_rule.setdefault(item, []).append((key, label))
    out = {}
    for item in sorted(by_rule):
        rng = random.Random(f'{SEED}-{item}')  # one stream per rule: a change in one rule cannot reshuffle another
        out[item] = (len(by_rule[item]), rng.sample(by_rule[item], min(PER_RULE, len(by_rule[item]))))
    return files, out


def main():
    p = argparse.ArgumentParser(description=__doc__)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument('--check', action='store_true'); g.add_argument('--record', type=Path, metavar='LABELS')
    a = p.parse_args()
    if a.check:
        record = json.loads(RECORD.read_text())
        files, drawn = sample(record['repos']); errors = []
        for item, (total, rows) in drawn.items():
            want = record['rules'].get(item, {})
            keys = [k for k, _ in rows]; recorded = [s['key'] for s in want.get('sample', [])]
            if keys != recorded or total != want.get('hits'): errors.append(f'{item}: sample differs from the record')
            if any(s.get('label') not in ('tp', 'fp') for s in want.get('sample', [])): errors.append(f'{item}: unlabelled hit')
        if set(drawn) != set(record['rules']): errors.append('rule set differs from the record')
        print(json.dumps({'files_scanned': files, 'errors': errors, 'precision': {k: f"{v['true_positive']}/{v['sampled']}" for k, v in record['rules'].items()}}))
        return 1 if errors else 0
    labels = json.loads(a.record.read_text())
    # Keep the recorded commits when a record exists, so a rebuild relabels the same code; otherwise pin HEAD.
    shas = json.loads(RECORD.read_text())['repos'] if RECORD.exists() else {r: git(r, 'rev-parse', 'HEAD').decode().strip() for r in REPOS}
    files, drawn = sample(shas); rules = {}; missing = []
    for item, (total, rows) in drawn.items():
        graded = []
        for key, signal in rows:
            lab = labels.get(item, {}).get(key)
            if not lab: missing.append(f'{item} {key}'); continue
            graded.append({'key': key, 'signal': signal, 'label': lab[0], 'reason': lab[1]})
        tp = sum(x['label'] == 'tp' for x in graded)
        rules[item] = {'hits': total, 'sampled': len(graded), 'true_positive': tp, 'precision': round(tp / len(graded), 2) if graded else None, 'sample': graded}
    if missing:
        print('unlabelled sampled hits:\n  ' + '\n  '.join(missing)); return 1
    record = {'date': '2026-10-29', 'method': 'git-tracked non-test source read from git archive at the recorded commits; one sample per rule (seed 20261029-<rule>, at most 15); one rater (the author) labelled every sampled hit explicitly, tp meaning the value has a source of truth or varies by context and is frozen in code. Informal: single rater, small samples.',
              'files_scanned': files, 'repos': shas, 'rules': rules,
              'held_out_informal': {'repos': 6, 'note': 'private local repositories; labels kept outside this repository. Measured on 2026-10-28 with an earlier version of the rules: F1 9/11, F2 9/15, F7 15/15.'},
              'cut_rules_informal': {'model ids': '~25% (3 of 12 sampled)', 'pass-through functions': '~20% (2-3 of 12)', 'generic account/tenant ids': 'mostly test data and wire-name mappings', 'unrestricted boolean toggles': 'mostly UI properties and state assignments', 'single-implementation interfaces': 'second implementation is usually a test fake the scanner skips'}}
    RECORD.write_text(json.dumps(record, indent=1) + '\n')
    print({k: f"{v['true_positive']}/{v['sampled']} of {v['hits']}" for k, v in rules.items()})
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
