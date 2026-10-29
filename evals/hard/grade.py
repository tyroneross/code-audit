#!/usr/bin/env python3
"""Score the hard benchmark: deterministic location matching, blinded judge packets, per-arm aggregates and verdicts.

  grade.py judge-packets --out RAW --judges DIR --labels FILE   write one blinded packet per review case
  grade.py aggregate --out RAW --judgments DIR --labels FILE [--cases ...]   per-arm scores + verdicts as JSON

Judges see the oracle mechanism, the defect lines and findings under random labels. Arm names, repetitions and the
label map never enter the judge folder. A review case counts as detected in a trial only when one finding both
cites the defect file within the oracle window (deterministic, +/-10 lines) and is judged to describe the oracle
mechanism.
"""
import argparse
import json
from pathlib import Path
import random
import re
import secrets
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import os
CASES_FILE = Path(os.environ.get('HARD_CASES', HERE / 'cases.json')).resolve()
CASES = json.loads(CASES_FILE.read_text())
ORACLES = json.loads((HERE / CASES.get('oracles', 'private/oracles.json')).read_text())
TOLERANCE = 10
ARMS = CASES.get('arms', ['code-audit', 'coding-debugger', 'code-principles-audit', 'none'])
SUBJECT = CASES.get('subject', 'code-audit')
SOURCES = CASES.get('comparators', ['coding-debugger', 'code-principles-audit'])

JUDGE_PROMPT = '''You are grading code-review findings against one known historical defect. Decide for each finding whether it identifies THIS defect: the same trigger and mechanism, at or calling into the defective code. A finding about a different problem, or one that names the location but a different mechanism, does not match. Severity, wording and fix quality do not matter. For a CONTROL packet the defect was already fixed in the reviewed code: mark a finding as matching only if it claims this same defect is still present.
Return only JSON {"judgments":[{"label":"...","finding_id":"...","matches":true|false,"reason":"one sentence"}]} with one row per finding supplied.
'''


def parse_location(text):
    match = re.match(r'\s*`?([^`:\s]+):(\d+)(?:\s*[-–]\s*(\d+))?', text or '')
    if not match: return None
    start = int(match.group(2)); end = int(match.group(3) or start)
    return match.group(1), min(start, end), max(start, end)


def same_file(cited, oracle_file):
    cited = cited.lstrip('./')
    return cited == oracle_file or oracle_file.endswith('/' + cited) or cited.endswith('/' + oracle_file)


def windows(oracle):
    """(file, lines) pairs: the primary defect file plus any other file whose copy is part of the defect."""
    return [(oracle['file'], oracle['lines'])] + [(w['file'], w['lines']) for w in oracle.get('also', [])]


def location_hit(finding, oracle, tolerance=TOLERANCE):
    for text in finding.get('locations') or []:
        loc = parse_location(text)
        if not loc: continue
        for path, lines in windows(oracle):
            if not same_file(loc[0], path): continue
            for a, b in lines:
                if loc[1] <= b + tolerance and loc[2] >= a - tolerance: return True
    return False


def cites_file(finding, oracle):
    return any((loc := parse_location(t)) and any(same_file(loc[0], path) for path, _ in windows(oracle)) for t in finding.get('locations') or [])


def trials(out, family=None):
    rows = []
    for meta_path in sorted(Path(out).glob('*/meta.json')):
        meta = json.loads(meta_path.read_text())
        if family and meta.get('family') != family: continue
        answer = meta_path.parent / 'answer.json'
        meta['answer'] = json.loads(answer.read_text()) if answer.exists() else None
        meta['folder'] = meta_path.parent.name
        rows.append(meta)
    return rows


def case_info(case_id):
    case = next(c for c in CASES['review'] if c['id'] == case_id)
    return case, ORACLES[case['key']]


def judge_packets(out, judges, labels_file, rng=None):
    """One packet per review case holding every file-citing finding under a random trial label."""
    from harness import git_show
    rng = rng or random.SystemRandom(); judges.mkdir(parents=True, exist_ok=True); labels = {}
    by_case = {}
    for t in trials(out, 'review'):
        if t['status'] == 'completed': by_case.setdefault(t['case_id'], []).append(t)
    for case_id, rows in sorted(by_case.items()):
        case, oracle = case_info(case_id)
        rng.shuffle(rows); findings = []
        for t in rows:
            label = 'T' + secrets.token_hex(3); labels[label] = t['folder']
            for n, f in enumerate(t['answer']['findings']):
                if cites_file(f, oracle):
                    findings.append({'label': label, 'finding_id': finding_key(n, f), 'cause': f['cause'], 'locations': f['locations'], 'suggested_change': f['suggested_change']})
        rng.shuffle(findings)
        source = git_show(case['repo'], case['revision'], oracle['file']).decode().splitlines()
        a = max(1, min(x for x, _ in oracle['lines']) - 15); b = min(len(source), max(y for _, y in oracle['lines']) + 15)
        packet = {'packet': 'J-' + secrets.token_hex(3), 'kind': 'CONTROL (defect already fixed in reviewed code)' if case['role'] == 'control' else 'DEFECT',
                  'defect': {'file': oracle['file'], 'class': oracle['cls'], 'mechanism': oracle['mechanism'],
                             'pre_fix_lines': oracle['lines'] if case['role'] == 'defect' else 'n/a (fixed revision)'},
                  'reviewed_source_excerpt': '\n'.join(f'{n}: {source[n - 1]}' for n in range(a, b + 1)), 'findings': findings}
        (judges / f'{packet["packet"]}.json').write_text(JUDGE_PROMPT + '\nPACKET\n' + json.dumps(packet, indent=1))
        labels[packet['packet']] = case_id
    Path(labels_file).write_text(json.dumps(labels, indent=1) + '\n')
    return labels


def load_judgments(judgments_dir, labels):
    """Map (trial folder, finding id) -> matches, from judge outputs named <packet>.json."""
    matches = {}
    for path in sorted(Path(judgments_dir).glob('J-*.json')):
        rows = json.loads(path.read_text())['judgments']
        for row in rows: matches[(labels[row['label']], row['finding_id'])] = bool(row['matches'])
    return matches


def finding_key(index, finding):
    """Position-qualified key: the schema does not force unique finding ids, so one judgment must never cover two findings."""
    return f'{index}:{finding.get("id")}'


def usage_tokens(meta):
    u = meta.get('usage') or {}
    return (u.get('input_tokens') or 0) + (u.get('output_tokens') or 0)


def aggregate(out, matches, case_ids=None):
    arms = {arm: {'review_trials': 0, 'detected': 0, 'located': 0, 'control_trials': 0, 'control_false_positives': 0, 'review_invalid': 0,
                  'findings': 0, 'repair_trials': 0, 'repair_passed': 0, 'repair_invalid': 0, 'seconds': 0.0, 'tokens': 0, 'per_case': {}} for arm in ARMS}
    for t in trials(out):
        # Selecting a primary set never drops the controls: their false positives are part of every review verdict.
        if case_ids and t['case_id'] not in case_ids and not t['case_id'].startswith('C'): continue
        a = arms[t['arm']]; a['seconds'] += t.get('elapsed_seconds') or 0; a['tokens'] += usage_tokens(t)
        if t['family'] == 'repair':
            # Invalid trials (host failure, timeout, network or other tool use) are excluded from the denominator and counted.
            if 'valid' not in t or 'passed_final' not in t:
                raise ValueError(f"{t['folder']}: repair trial has no audit; run `harness.py reverify --out ...` before grading")
            if not t['valid']: a['repair_invalid'] += 1; continue
            passed = bool(t['passed_final'])
            a['repair_trials'] += 1; a['repair_passed'] += passed
            a['per_case'].setdefault(t['case_id'], []).append(int(passed)); continue
        case, oracle = case_info(t['case_id'])
        if t['status'] != 'completed': a['review_invalid'] += 1; continue
        found = (t.get('answer') or {}).get('findings') or []
        a['findings'] += len(found)
        judged = [f for n, f in enumerate(found) if matches.get((t['folder'], finding_key(n, f)))]
        if case['role'] == 'control':
            a['control_trials'] += 1; a['control_false_positives'] += bool(judged); continue
        a['review_trials'] += 1
        hit = any(location_hit(f, oracle) for f in judged)
        a['detected'] += hit; a['located'] += any(location_hit(f, oracle) for f in found)
        a['per_case'].setdefault(t['case_id'], []).append(int(hit))
    for a in arms.values():
        a['detection_rate'] = round(a['detected'] / a['review_trials'], 3) if a['review_trials'] else None
        a['seconds'] = round(a['seconds'], 1)
    return arms


def verdicts(arms):
    """Pre-registered rule (README): Delta = code-audit - source."""
    ca = arms[SUBJECT]; out = {'subject': SUBJECT}
    for source in SOURCES:
        s = arms[source]; row = {}
        if ca['detection_rate'] is not None and s['detection_rate'] is not None:
            d = round(ca['detection_rate'] - s['detection_rate'], 3); fp = ca['control_false_positives'] - s['control_false_positives']
            row['review'] = {'delta_detection': d, 'delta_control_fp': fp,
                             'verdict': 'outperforms' if d >= 0.15 and fp <= 1 else 'worse' if d <= -0.15 or fp >= 2 else 'parity'}
        if ca['repair_trials'] and s['repair_trials']:
            d = ca['repair_passed'] - s['repair_passed']
            cases = set(ca['per_case']) | set(s['per_case'])
            worst = min((sum(ca['per_case'].get(c, [])) - sum(s['per_case'].get(c, [])) for c in cases if c.startswith('X')), default=0)
            row['repair'] = {'delta_passes': d, 'worst_case_delta': worst,
                             'verdict': 'outperforms' if d >= 3 and worst > -2 else 'worse' if d <= -3 or worst <= -2 else 'parity'}
        out[source] = row
    none = arms['none']
    out['discrimination'] = {'review_control_below_ceiling': none['detection_rate'] is not None and none['detection_rate'] <= 0.75,
                             'repair_control_below_ceiling': bool(none['repair_trials']) and none['repair_passed'] / none['repair_trials'] <= 0.75}
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['judge-packets', 'aggregate'])
    p.add_argument('--out', type=Path, required=True); p.add_argument('--judges', type=Path); p.add_argument('--judgments', type=Path)
    p.add_argument('--labels', type=Path, required=True); p.add_argument('--cases', nargs='*')
    a = p.parse_args()
    if a.command == 'judge-packets':
        labels = judge_packets(a.out, a.judges, a.labels); print(len([k for k in labels if k.startswith('J-')]), 'packets'); return
    labels = json.loads(a.labels.read_text())
    arms = aggregate(a.out, load_judgments(a.judgments, labels), a.cases)
    print(json.dumps({'arms': arms, 'verdicts': verdicts(arms)}, indent=1))


if __name__ == '__main__':
    main()
