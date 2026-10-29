#!/usr/bin/env python3
"""F3: deterministic incident retrieval on a real private corpus. No model calls. Commits IDs, hashes and scores only."""
import argparse
import hashlib
import json
import random
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
RUNTIMES={'code-audit':ROOT/'runtime/debugger/dist/src','coding-debugger':Path('/Users/tyroneross/dev/git-folder/claude-code-debugger/dist/src')}
SEED=20261028
STOP=set('a an the of to in on for and or is are was were be been with without from by at as it its this that when after before not no into than then but if via vs'.split())
NEGATIVES=['SwiftUI widget timeline reload budget exhausted on lock screen','Bluetooth peripheral pairing drops after watchOS sleep','Kubernetes pod evicted for ephemeral storage pressure','Unity shader compile stalls on Vulkan pipeline cache','Rust borrow checker lifetime error in async trait impl','Gradle daemon heap exhausted during Android lint','Terraform state lock stuck in DynamoDB table','Bluetooth LE advertisement interval ignored on Raspberry Pi','Excel macro security prompt blocks VBA add-in load','FPGA bitstream timing closure fails on clock domain crossing']


def words(text):
    return [w for w in re.findall(r'[a-z0-9]+',(text or '').lower()) if w not in STOP and len(w)>1]


def norm(text):
    return ' '.join(re.findall(r'[a-z0-9]+',(text or '').lower()))


def first_sentence(text):
    return re.split(r'(?<=[.!?])\s+',(text or '').strip())[0]


def load_corpus(path):
    rows={}
    for p in sorted(Path(path).glob('*.json')):
        try:row=json.loads(p.read_text())
        except (OSError,ValueError):continue
        if isinstance(row,dict) and isinstance(row.get('incident_id'),str) and isinstance(row.get('symptom'),str):rows[row['incident_id']]=row
    return rows


def freeze_queries(corpus):
    """Fixed seed and rules, executed before any arm; no result-based tuning."""
    eligible=sorted(i for i,r in corpus.items() if len(words(r['symptom']))>=6 and isinstance(r.get('root_cause'),dict) and len(words(r['root_cause'].get('description')))>=4)
    targets=random.Random(SEED).sample(eligible,20)
    by_symptom={}
    for i,r in corpus.items():by_symptom.setdefault(norm(r['symptom']),set()).add(i)
    queries=[]
    for n,ident in enumerate(targets,1):
        r=corpus[ident];relevant=sorted(by_symptom[norm(r['symptom'])])
        queries.append({'id':f'T{n:02d}-exact','text':r['symptom'],'relevant':relevant})
        queries.append({'id':f'T{n:02d}-partial','text':' '.join(words(r['symptom'])[:6]),'relevant':relevant})
        queries.append({'id':f'T{n:02d}-cause','text':first_sentence(r['root_cause']['description']),'relevant':relevant})
    for n,text in enumerate(NEGATIVES,1):queries.append({'id':f'N{n:02d}','text':text,'relevant':[]})
    return queries


def keyword_baseline(corpus,query,k=5,minimum=2):
    q=set(words(query))
    scored=[]
    for i,r in corpus.items():
        doc=set(words(r['symptom']))|set(words((r.get('root_cause') or {}).get('description') if isinstance(r.get('root_cause'),dict) else ''))
        overlap=len(q&doc)
        if overlap>=minimum:scored.append((-overlap,i))
    return [i for _,i in sorted(scored)[:k]]


def runtime_results(dist,memory,queries):
    program='''const {checkMemory,checkMemoryScaled}=require(RETRIEVAL);console.log=()=>{};console.warn=()=>{};
const config={storageMode:'local',memoryPath:MEMORY,autoMine:false,defaultSimilarityThreshold:0.5,defaultMaxResults:5};
(async()=>{const rows=[];for(const q of QUERIES)for(const [path,fn] of [['standard',checkMemory],['indexed',checkMemoryScaled]]){
 let ids=null,error=null;try{const r=await fn(q.text,{memoryConfig:config,max_results:5});ids=(r.incidents||[]).map(x=>x.incident_id)}catch(e){error=String(e&&e.message||e)}
 rows.push({query_id:q.id,path,ids,error})}
process.stdout.write(JSON.stringify(rows))})().catch(e=>{process.stderr.write(String(e));process.exit(1)});'''
    program=program.replace('RETRIEVAL',json.dumps(str(dist/'retrieval.js'))).replace('MEMORY',json.dumps(str(memory))).replace('QUERIES',json.dumps(queries))
    result=subprocess.run(['node','-e',program],cwd=memory.parent,text=True,capture_output=True,timeout=120)
    if result.returncode:raise RuntimeError(result.stderr[-2000:])
    return json.loads(result.stdout)


def metrics(rows,queries):
    rel={q['id']:set(q['relevant']) for q in queries};pos=[q['id'] for q in queries if q['relevant']];neg=[q['id'] for q in queries if not q['relevant']]
    by={r['query_id']:r for r in rows}
    def rank(qid):
        ids=by[qid]['ids'] or []
        return next((n+1 for n,i in enumerate(ids) if i in rel[qid]),None)
    ranks=[rank(q) for q in pos]
    out={'positive_queries':len(pos),'negative_queries':len(neg),'recall_at_5':round(sum(r is not None for r in ranks)/len(pos),3),'mrr':round(sum(1/r for r in ranks if r)/len(pos),3),
         'negative_false_return_rate':round(sum(bool(by[q]['ids']) for q in neg)/len(neg),3),'errors':sum(1 for r in rows if r.get('error'))}
    for kind in ['exact','partial','cause']:
        ks=[q for q in pos if q.endswith(kind)];out[f'recall_at_5_{kind}']=round(sum(rank(q) is not None for q in ks)/len(ks),3)
    return out


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--corpus',type=Path,default=Path('/Users/tyroneross/dev/git-folder/atomize-ai/.claude/memory'))
    p.add_argument('--private',type=Path,required=True,help='directory outside the repository for query text and raw rows');p.add_argument('--out',type=Path,required=True)
    a=p.parse_args()
    if a.out.exists():raise FileExistsError('refusing to replace recorded results')
    if a.private.resolve().is_relative_to(ROOT) and '.build-loop' not in a.private.resolve().parts:raise ValueError('private output must stay out of tracked files')
    with tempfile.TemporaryDirectory(prefix='code-audit-memory-arms-') as folder:
        memory=Path(folder)/'memory';shutil.copytree(a.corpus,memory,ignore=shutil.ignore_patterns('sessions','traces'))
        corpus=load_corpus(memory/'incidents');queries=freeze_queries(corpus)
        a.private.mkdir(parents=True,exist_ok=True);(a.private/'queries.json').write_text(json.dumps(queries,indent=1))
        raw={};results={}
        for arm,dist in RUNTIMES.items():
            rows=runtime_results(dist,memory,queries);raw[arm]=rows
            results[arm]={path:metrics([r for r in rows if r['path']==path],queries) for path in ['standard','indexed']}
            results[arm]['runtime_sha256']=hashlib.sha256((dist/'retrieval.js').read_bytes()).hexdigest()
        rows=[{'query_id':q['id'],'path':'keyword','ids':keyword_baseline(corpus,q['text']),'error':None} for q in queries];raw['none']=rows
        results['none']={'keyword':metrics(rows,queries)}
        results['code-principles-audit']={'capability':'absent','recall_at_5':0.0,'mrr':0.0,'negative_false_return_rate':0.0,'note':'no incident memory in this source'}
        (a.private/'raw-rows.json').write_text(json.dumps(raw,indent=1))
        value={'version':1,'corpus':{'project':'atomize-ai (private; text withheld)','incidents_loaded':len(corpus),'incident_files':len(list((memory/'incidents').glob('*.json'))),'sha256_of_sorted_ids':hashlib.sha256('\n'.join(sorted(corpus)).encode()).hexdigest()},
               'queries':{'seed':SEED,'count':len(queries),'positive':sum(1 for q in queries if q['relevant']),'negative':sum(1 for q in queries if not q['relevant']),'sha256':hashlib.sha256(json.dumps(queries,sort_keys=True).encode()).hexdigest(),'targets':[q['id'] for q in queries if q['id'].endswith('exact')],'relevant_ids':{q['id']:q['relevant'] for q in queries if q['id'].endswith('exact')}},
               'configuration':{'threshold':0.5,'max_results':5,'baseline':'content-token overlap over symptom+root cause, >=2 overlaps, top 5'},'results':results,
               'limits':['One project corpus; incident wording was written by agents during real sessions.','Partial and cause queries are rule-derived, not human paraphrases.','Relevance is the target plus exact-duplicate symptoms; other genuinely related incidents count as non-relevant.','Retrieval does not establish that a model applies a correct repair.']}
    a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(value,indent=2)+'\n');print(json.dumps(results,indent=1))

if __name__=='__main__':main()
