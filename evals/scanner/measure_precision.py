"""Write the scanner precision record: public tuning repos at fixed commits, every sampled hit with its hand label."""
import json, os, random, subprocess, sys
from pathlib import Path
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'skills/code-principles/scripts'))
import scan, frozen
G = os.environ.get('SCANNER_REPOS_ROOT', str(REPO.parent)) + '/'
REPOS = ['build-loop', 'NavGator', 'interface-built-right', 'agent-rally-point', 'spectra', 'local-smartz', 'decision-doctor-cc', 'code-audit']
# Hand labels for the sample drawn with seed 20261029 (15 per rule), keyed "repo/file:line": (label, reason).
LABELS = {
 'F1': {'spectra/src/cli/index.ts:162': ('fp', 'CLI help text showing an example pattern')},
 'F2': {'spectra/macos/Spectra/DaemonCore/verify-g2-suite.ts:387': ('fp', 'verification-suite fixture target'),
        'spectra/macos/Spectra/DaemonCore/SessionStore.swift:423': ('fp', 'conformance fixture URL'),
        'local-smartz/app/LocalSmartz/Views/SettingsTabs.swift:177': ('fp', 'UI text that displays the host'),
        'local-smartz/src/localsmartz/doctor.py:45': ('fp', 'status message string'),
        'spectra/src/cli/index.ts:158': ('fp', 'CLI help example')},
 'F7': {'build-loop/scripts/install_memory.py:62': ('fp', 'same file name, different manifest (a seed manifest, not the architecture manifest)')},
}
REASON_TP = {'F1': 'machine-specific path in shipped code or default', 'F2': 'local host/port frozen in code or as a default',
             'F3': 'version literal copies or contradicts the owning manifest', 'F6': 'module-level toggle fixed in code',
             'F7': 'same identifier defined in two files that must agree'}
rows = {}; files_total = 0; shas = {}
for repo in REPOS:
    root = G + repo
    shas[repo] = subprocess.check_output(['git', '-c', 'credential.helper=', '-C', root, 'rev-parse', 'HEAD'], text=True).strip()
    tracked = subprocess.check_output(['git', '-c', 'credential.helper=', '-C', root, 'ls-files'], text=True).split('\n')
    store = frozen.new_store(); hits = []; skipped = []
    for rel in tracked:
        if not rel or os.path.splitext(rel)[1] not in scan.CODE_EXT or scan.TEST_PATH.search(rel): continue
        if any(part in scan.SKIP_DIRS for part in rel.split('/')): continue
        full = os.path.join(root, rel)
        if not os.path.isfile(full) or os.path.islink(full): continue
        found = scan.scan_file(full, rel, skipped, store)
        if found is not None: files_total += 1; hits.extend(found)
    hits.extend(frozen.cross_file_hits(store, [root]))
    for item, label, f, n, t in hits:
        if item[0] == 'F': rows.setdefault(item, []).append((repo, f, n, label))
rng = random.Random(20261029); record = {}
for item in sorted(rows):
    sample = rng.sample(rows[item], min(15, len(rows[item])))
    graded = []
    for repo, f, n, label in sample:
        key = f'{repo}/{f}:{n}'; lab = LABELS.get(item, {}).get(key, ('tp', REASON_TP[item]))
        graded.append({'repo': repo, 'file': f, 'line': n, 'signal': label, 'label': lab[0], 'reason': lab[1]})
    tp = sum(g['label'] == 'tp' for g in graded)
    record[item] = {'hits': len(rows[item]), 'sampled': len(graded), 'true_positive': tp, 'precision': round(tp / len(graded), 2), 'sample': graded}
out = {'date': '2026-10-29', 'method': 'git-tracked non-test source files; scanner as committed with this record; one rater (the author) labelled each sampled hit tp/fp: tp means the value has a source of truth or varies by context and is frozen in code. Informal: single rater, no second label, samples of at most 15.',
       'files_scanned': files_total, 'repos': shas, 'seed': 20261029, 'rules': record,
       'held_out_informal': {'repos': 6, 'note': 'private local repositories; labels kept outside this repository. Measured on 2026-10-28 with an earlier version of the rules: F1 9/11, F2 9/15, F7 15/15.'},
       'cut_rules_informal': {'model ids': '~25% (3 of 12 sampled)', 'pass-through functions': '~20% (2-3 of 12)', 'generic account/tenant ids': 'mostly test data and wire-name mappings', 'unrestricted boolean toggles': 'mostly UI properties and state assignments', 'single-implementation interfaces': 'second implementation is usually a test fake the scanner skips'}}
dest = REPO / 'skills/code-principles/references/frozen-values-precision.json'
open(dest, 'w').write(json.dumps(out, indent=1) + '\n')
print({k: (v['true_positive'], v['sampled'], v['hits']) for k, v in record.items()})
