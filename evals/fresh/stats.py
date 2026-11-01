#!/usr/bin/env python3
"""Paired per-case comparison of arms on the fresh case set (pre-registered rule: README.md).

  stats.py --agg AGG.json [AGG.json ...] [--union NEW=A+B ...] --compare A:B [A:B ...] [--holm A:B ...]

Each AGG.json is `grade.py aggregate` output; an arm name may appear in only one of them. One repetition per case, so
each arm has one 0/1 outcome per defect case and per control. Detection uses an exact two-sided McNemar test on the
defect cases valid in both arms; control false positives are compared on the controls valid in both arms. Cost is
the mean tokens and seconds per attempt, invalid attempts included. `--union NEW=A+B` builds an arm whose outcome per
case is A or B over cases valid in both, costed as A's plus B's cost on those cases (the two-pass arm: first pass A,
second-pass new findings B); unions compose. A union's cost covers only the cases valid in both parts.
"""
import argparse
import json
import os
from math import comb
from pathlib import Path

CASES = Path(os.environ.get('HARD_CASES', Path(__file__).resolve().parent / 'cases.json'))


def mcnemar(b, c):
    """Exact two-sided p for b cases won by A only and c won by B only."""
    n = b + c
    if n == 0: return 1.0
    tail = sum(comb(n, k) for k in range(min(b, c) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def outcomes(arm, key='per_case'):
    return {case: runs[0] for case, runs in (arm.get(key) or {}).items() if runs}


def per_trial(arm, field):
    """Mean cost per attempt: the totals include invalid attempts, so the denominator does too."""
    n = arm.get('attempts') or arm['review_trials'] + arm['control_trials'] + arm.get('review_invalid', 0)
    return arm[field] / n if n else None


def union(a, b):
    """Arm whose per-case outcome is a OR b, over cases valid in both, with summed per-trial cost."""
    out = {'per_case': {}, 'per_control': {}, 'review_trials': 0, 'control_trials': 0, 'detected': 0, 'control_false_positives': 0,
           'review_invalid': a['review_invalid'] + b['review_invalid'], 'findings': a['findings'] + b['findings'], 'located': None}
    for key, count, hits in (('per_case', 'review_trials', 'detected'), ('per_control', 'control_trials', 'control_false_positives')):
        A, B = outcomes(a, key), outcomes(b, key)
        for case in set(A) & set(B):
            v = int(A[case] or B[case]); out[key][case] = [v]; out[count] += 1; out[hits] += v
    kept = set(out['per_case']) | set(out['per_control']); ca, cb = a.get('cost_by_case') or {}, b.get('cost_by_case') or {}
    if not kept <= set(ca) & set(cb): raise SystemExit('union needs cost_by_case for every retained case; re-run grade.py aggregate')
    out['cost_by_case'] = {c: [ca[c][0] + cb[c][0], ca[c][1] + cb[c][1]] for c in kept}
    out['tokens'] = sum(v[0] for v in out['cost_by_case'].values()); out['seconds'] = round(sum(v[1] for v in out['cost_by_case'].values()), 1)
    out['attempts'] = len(kept)  # a union is defined only on cases valid in both parts, so its attempts are those cases
    out['detection_rate'] = round(out['detected'] / out['review_trials'], 3) if out['review_trials'] else None
    return out


def compare(arms, a, b, universe=None):
    if a not in arms or b not in arms:
        return {'a': a, 'b': b, 'delta': None, 'p': 1.0, 'delta_control_fp': 0, 'cost_ratio': {}, 'note': 'arm missing'}
    A, B = outcomes(arms[a]), outcomes(arms[b]); cases = sorted(set(A) & set(B))
    wins_a = sum(A[c] and not B[c] for c in cases); wins_b = sum(B[c] and not A[c] for c in cases)
    n = len(cases); delta = round((sum(A[c] for c in cases) - sum(B[c] for c in cases)) / n, 3) if n else None
    CA, CB = outcomes(arms[a], 'per_control'), outcomes(arms[b], 'per_control'); controls = sorted(set(CA) & set(CB))
    fp = sum(CA[c] for c in controls) - sum(CB[c] for c in controls)
    cost = {}
    for field in ('tokens', 'seconds'):
        x, y = per_trial(arms[a], field), per_trial(arms[b], field)
        cost[field] = x / y if x is not None and y else None  # unrounded: verdict() compares against 2
    universe = universe or set(A) | set(B)
    return {'a': a, 'b': b, 'paired_cases': n, 'dropped': len(universe) - n, 'a_detected': sum(A[c] for c in cases),
            'b_detected': sum(B[c] for c in cases), 'a_only': wins_a, 'b_only': wins_b, 'delta': delta, 'p': mcnemar(wins_a, wins_b),
            'paired_controls': len(controls), 'delta_control_fp': fp, 'cost_ratio': cost}


def verdict(row, alpha=0.05, threshold=0.10):
    """helps: delta >= +0.10, p < alpha (Holm-adjusted when given) and control-FP delta <= +1;
    worse: delta <= -0.10 with p < alpha, or control-FP delta >= +2; otherwise parity (no detectable difference).
    'helps at cost' when helps and mean tokens or seconds per trial exceed 2x the comparator."""
    p = row.get('p_holm', row['p'])
    if row['delta'] is None: return 'no data'
    if row['delta_control_fp'] >= 2 or (row['delta'] <= -threshold and p < alpha): return 'worse'
    if row['delta'] >= threshold and p < alpha and row['delta_control_fp'] <= 1:
        return 'helps at cost' if any((r or 0) > 2 for r in row['cost_ratio'].values()) else 'helps'
    return 'parity'


def holm(rows):
    order = sorted(range(len(rows)), key=lambda i: rows[i]['p']); m = len(rows); running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * rows[i]['p'])); rows[i]['p_holm'] = running
    return rows


def load(paths):
    arms = {}
    for path in paths:
        for name, arm in json.load(open(path))['arms'].items():
            if not (arm['review_trials'] or arm['control_trials'] or arm['review_invalid']): continue
            if name in arms: raise SystemExit(f'arm {name!r} appears in more than one --agg file; merge them first')
            if arm['control_trials'] and 'per_control' not in arm: raise SystemExit(f'{path}: arm {name!r} lacks per_control; re-run grade.py aggregate')
            arms[name] = arm
    return arms


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--agg', nargs='+', required=True); p.add_argument('--union', nargs='*', default=[])
    p.add_argument('--compare', nargs='*', default=[]); p.add_argument('--holm', nargs='*', default=[])
    a = p.parse_args(); arms = load(a.agg)
    for spec in a.union:
        new, parts = spec.split('=', 1); x, y = parts.split('+', 1); arms[new] = union(arms[x], arms[y])
    universe = {c['id'] for c in json.loads(CASES.read_text())['review'] if c['role'] == 'defect'} if CASES.exists() else None
    pairs = lambda specs: [tuple(s.split(':', 1)) for s in specs]
    family = holm([compare(arms, x, y, universe) for x, y in pairs(a.holm)])
    rows = family + [compare(arms, x, y, universe) for x, y in pairs(a.compare)]
    for row in rows:
        row['verdict'] = verdict(row); row['cost_ratio'] = {k: (round(v, 3) if v is not None else None) for k, v in row['cost_ratio'].items()}
    keep = ('review_trials', 'detected', 'detection_rate', 'located', 'control_trials', 'control_false_positives', 'review_invalid', 'findings', 'tokens', 'seconds')
    summary = {n: {k: arm.get(k) for k in keep} for n, arm in arms.items()}
    print(json.dumps({'arms': summary, 'comparisons': rows}, indent=1))


if __name__ == '__main__':
    main()
