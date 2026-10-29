#!/usr/bin/env python3
"""Blind F1 judge packets, then score all families and apply the pre-registered verdict rule."""
import argparse
import json
import random
from pathlib import Path
from common import ARMS,EVALS,load

experiment=load('score_experiment',EVALS/'repository/experiment.py')
SEED=20261028


def blind(review_dir,judge_dir,repo):
    manifest=json.loads((EVALS/'repository/cases.json').read_text());oracles=json.loads((EVALS/'repository/private/oracles.json').read_text())['oracles']
    judge_dir.mkdir(parents=True,exist_ok=False);rng=random.Random(SEED)
    for case in manifest['cases']:
        folders=sorted(p for p in review_dir.glob(case['id']+'-*') if json.loads((p/'meta.json').read_text()).get('status')=='completed')
        labels=[f'L{n:02d}' for n in range(1,len(folders)+1)];rng.shuffle(labels)
        mapping=dict(zip(labels,[p.name for p in folders]))
        reviews={label:json.loads((review_dir/name/'answer.json').read_text()) for label,name in sorted(mapping.items())}
        source=experiment.packet(case,manifest,repo)
        (judge_dir/f'{case["id"]}-prompt.txt').write_text(experiment.judge_prompt(source,{case['id']:oracles[case['id']]},reviews))
        mapping_dir=judge_dir.parent/'judge-mapping';mapping_dir.mkdir(exist_ok=True)
        # Kept apart so a judge with file tools cannot un-blind itself.
        (mapping_dir/f'{case["id"]}-mapping.json').write_text(json.dumps(mapping,indent=2))


def f1(review_dir,judge_dir):
    trials={}
    for p in sorted(review_dir.iterdir()):
        if p.is_dir():
            m=json.loads((p/'meta.json').read_text());trials[p.name]={'arm':m['arm'],'case':m['case_id'],'repeat':m['repeat'],'status':m['status'],'seconds':m.get('elapsed_seconds'),'usage':m.get('usage')}
    for case in ['P01','P02']:
        mapping=json.loads((judge_dir.parent/'judge-mapping'/f'{case}-mapping.json').read_text());answer=json.loads((judge_dir/f'{case}-answer.json').read_text())
        for label,name in mapping.items():
            j=answer['reviews'][label]['judgments'];t=trials[name]
            covered={x['oracle_id'] for x in j if x['valid'] and x.get('oracle_id')}|{c['oracle_id'] for x in j if x['valid'] for c in x.get('also_covers',[])}
            t.update({'findings':len(j),'valid':sum(x['valid'] for x in j),'harmful':sum(bool(x.get('harmful')) for x in j),'duplicates':sum(bool(x.get('duplicate')) for x in j),'covered':sorted(covered)})
    arms={}
    for arm in ARMS:
        rows=[t for t in trials.values() if t['arm']==arm]
        p01=[t for t in rows if t['case']=='P01']
        recalls=[len(t.get('covered',[]))/4 if t['status']=='completed' else 0.0 for t in p01]
        precisions=[]
        for rep in sorted({t['repeat'] for t in rows}):
            rr=[t for t in rows if t['repeat']==rep and t['status']=='completed'];f=sum(t['findings'] for t in rr);v=sum(t['valid'] for t in rr)
            precisions.append(v/f if f else 1.0)
        arms[arm]={'recall_per_trial':recalls,'mean_recall':round(sum(recalls)/len(recalls),3) if recalls else None,'precision_per_repeat':[round(x,3) for x in precisions],'mean_precision':round(sum(precisions)/len(precisions),3) if precisions else None,
                   'harmful':sum(t.get('harmful',0) for t in rows),'failed_trials':sum(t['status']!='completed' for t in rows),'seconds':[t['seconds'] for t in rows],'tokens':[(t['usage'] or {}).get('input_tokens',0)+(t['usage'] or {}).get('output_tokens',0) for t in rows]}
    return {'trials':trials,'arms':arms}


def f2(repair_dir):
    rows=[]
    for p in sorted(repair_dir.iterdir()):
        if p.is_dir() and (p/'meta.json').exists():
            m=json.loads((p/'meta.json').read_text());case='R1' if p.name.startswith('repair-') else 'R2'
            checks=(m.get('verification') or {}).get('summary') if case=='R2' else None
            rows.append({'trial':p.name,'case':case,'arm':m['arm'],'repeat':m['repeat'],'status':m.get('status'),'passed':bool(m.get('passed')),'protected_changes':m.get('protected_changes'),'seconds':m.get('elapsed_seconds'),'usage':m.get('usage'),'checks':checks,
                         'r1_verification':{k:m.get('verification',{}).get(k) for k in ['passed','tests']} if case=='R1' and isinstance(m.get('verification'),dict) else None})
    arms={arm:{case:sum(r['passed'] for r in rows if r['arm']==arm and r['case']==case) for case in ['R1','R2']} for arm in ARMS}
    for arm in arms:arms[arm]['pooled']=arms[arm]['R1']+arms[arm]['R2'];arms[arm]['trials']=sum(1 for r in rows if r['arm']==arm)
    return {'trials':rows,'arms':arms}


def verdicts(f1v,f2v,f3v):
    out={}
    for source in ['coding-debugger','code-principles-audit','none']:
        a=f1v['arms']['code-audit'];b=f1v['arms'][source];dr=round(a['mean_recall']-b['mean_recall'],3);dp=round(a['mean_precision']-b['mean_precision'],3)
        v1='outperforms' if dr>=0.25 and dp>=-0.10 else 'worse' if dr<=-0.25 or dp<=-0.15 else 'parity'
        a2=f2v['arms']['code-audit'];b2=f2v['arms'][source];dpool=a2['pooled']-b2['pooled'];dcase=[a2[c]-b2[c] for c in ['R1','R2']]
        v2='outperforms' if dpool>=2 and min(dcase)>-1 else 'worse' if dpool<=-2 or min(dcase)<=-2 else 'parity'
        ca=f3v['code-audit']['standard']
        if source=='coding-debugger':sb=f3v['coding-debugger']['standard']
        elif source=='none':sb=f3v['none']['keyword']
        else:sb={'recall_at_5':0.0,'negative_false_return_rate':0.0}
        d3=round(ca['recall_at_5']-sb['recall_at_5'],3);dn=round(ca['negative_false_return_rate']-sb['negative_false_return_rate'],3)
        v3='outperforms' if d3>=0.10 and dn<=0.10 else 'worse' if d3<=-0.10 or dn>=0.20 else 'parity'
        if source=='code-principles-audit':v3='not applicable (source has no incident memory); code-audit adds the capability'
        out[source]={'F1':{'delta_recall':dr,'delta_precision':dp,'verdict':v1},'F2':{'delta_pooled':dpool,'delta_per_case':dict(zip(['R1','R2'],dcase)),'verdict':v2},'F3':{'delta_recall_at_5':d3,'delta_negative_false_return':dn,'verdict':v3}}
    return out


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('phase',choices=['blind','score']);p.add_argument('--private',type=Path,required=True);p.add_argument('--repo',type=Path,default=EVALS.parent);p.add_argument('--out',type=Path)
    a=p.parse_args()
    if a.phase=='blind':blind(a.private/'review',a.private/'judge',a.repo);return
    f1v=f1(a.private/'review',a.private/'judge');f2v=f2(a.private/'repair')
    f3v=json.loads((EVALS/'comparison/results/2026-10-28/memory-run3-after-legacy-id-fix.json').read_text())['results']
    value={'f1':f1v,'f2':f2v,'f3':f3v,'verdicts':verdicts(f1v,f2v,f3v)}
    a.out.write_text(json.dumps(value,indent=2)+'\n');print(json.dumps(value['verdicts'],indent=1))

if __name__=='__main__':main()
