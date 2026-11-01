#!/usr/bin/env python3
"""Paired per-case comparison of arms on the fresh case set (pre-registered rule: README.md).

  stats.py --agg AGG.json [AGG.json ...] --compare A:B [A:B ...] [--holm A:B ...]

Each AGG.json is `grade.py aggregate` output. One repetition per case, so each arm has one 0/1 outcome per defect
case. The test is an exact two-sided McNemar (binomial on discordant cases). Cases missing or invalid in either arm
are dropped from that comparison and counted.
"""
import argparse
import json
from math import comb


def mcnemar(b, c):
    """Exact two-sided p for b cases won by A only and c won by B only."""
    n = b + c
    if n == 0: return 1.0
    tail = sum(comb(n, k) for k in range(min(b, c) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def outcomes(arm):
    return {case: runs[0] for case, runs in arm['per_case'].items() if runs}


def compare(arms, a, b, threshold=0.10):
    A, B = outcomes(arms[a]), outcomes(arms[b]); cases = sorted(set(A) & set(B))
    wins_a = sum(A[c] and not B[c] for c in cases); wins_b = sum(B[c] and not A[c] for c in cases)
    n = len(cases); delta = round((sum(A[c] for c in cases) - sum(B[c] for c in cases)) / n, 3) if n else None
    fp = arms[a]['control_false_positives'] - arms[b]['control_false_positives']
    p = mcnemar(wins_a, wins_b)
    cost = {k: round(arms[a][k] / arms[b][k], 2) if arms[b][k] else None for k in ('tokens', 'seconds')}
    return {'a': a, 'b': b, 'paired_cases': n, 'dropped': len(set(A) ^ set(B)), 'a_detected': sum(A[c] for c in cases),
            'b_detected': sum(B[c] for c in cases), 'a_only': wins_a, 'b_only': wins_b, 'delta': delta, 'p': round(p, 4),
            'delta_control_fp': fp, 'cost_ratio': cost}


def verdict(row, alpha=0.05, threshold=0.10):
    """helps: delta >= +0.10, p < alpha (Holm-adjusted when given) and control-FP delta <= +1;
    worse: delta <= -0.10 with p < alpha, or control-FP delta >= +2; otherwise parity (no detectable difference).
    'helps at cost' when helps and tokens or seconds exceed 2x the comparator."""
    p = row.get('p_holm', row['p'])
    if row['delta'] is None: return 'no data'
    if row['delta_control_fp'] >= 2 or (row['delta'] <= -threshold and p < alpha): return 'worse'
    if row['delta'] >= threshold and p < alpha and row['delta_control_fp'] <= 1:
        return 'helps at cost' if any((r or 0) > 2 for r in row['cost_ratio'].values()) else 'helps'
    return 'parity'


def holm(rows):
    order = sorted(range(len(rows)), key=lambda i: rows[i]['p']); m = len(rows); running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * rows[i]['p'])); rows[i]['p_holm'] = round(running, 4)
    return rows


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--agg', nargs='+', required=True); p.add_argument('--compare', nargs='*', default=[]); p.add_argument('--holm', nargs='*', default=[])
    a = p.parse_args(); arms = {}
    for path in a.agg:
        for name, arm in json.load(open(path))['arms'].items():
            if arm['review_trials'] or arm['control_trials']: arms[name] = arm
    pairs = lambda specs: [tuple(s.split(':', 1)) for s in specs]
    family = holm([compare(arms, x, y) for x, y in pairs(a.holm)])
    rows = family + [compare(arms, x, y) for x, y in pairs(a.compare)]
    for row in rows: row['verdict'] = verdict(row)
    summary = {n: {k: arm[k] for k in ('review_trials', 'detected', 'detection_rate', 'located', 'control_trials', 'control_false_positives',
                                       'review_invalid', 'findings', 'tokens', 'seconds')} for n, arm in arms.items()}
    print(json.dumps({'arms': summary, 'comparisons': rows}, indent=1))


if __name__ == '__main__':
    main()
