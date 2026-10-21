"""Deterministic historical-lead retrieval experiment; no model calls, mining or shared memory."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[2]
REVISION='082621dbfffe18a8cf8f2bf3a656a2ff0facabaf'
LEADS=[
 {'id':'INC_RECENCY','symptom':'old future incident records outrank recent incident records','cause':'Age duration was compared against an epoch cutoff in both retrieval paths.','fix':'Compare timestamps with cutoff and current time; preserve explicit zero days.','path':'runtime/debugger/src/retrieval.ts'},
 {'id':'INC_COVERAGE','symptom':'malformed incident JSON disappears no match appears complete','cause':'Read and JSON failures silently skipped every invalid corpus file.','fix':'Retain usable records and count bounded skip reasons; qualify incomplete absence.','path':'runtime/debugger/src/storage.ts'},
 {'id':'INC_SCOPE','symptom':'memory stored installed plugin directory instead selected project','cause':'Server starts in the installed package and storage inherits its working directory.','fix':'Select project_root on each call and reject unsafe implicit scope.','path':'runtime/debugger/src/mcp/tools.ts'}]
QUERIES=[
 {'id':'Q1','text':LEADS[0]['symptom'],'relevant':['INC_RECENCY']},
 {'id':'Q2','text':'Old entries rank above recent entries when timestamps are future dated','relevant':['INC_RECENCY']},
 {'id':'Q3','text':LEADS[1]['symptom'],'relevant':['INC_COVERAGE']},
 {'id':'Q4','text':'Corrupt JSON files look like an empty incident corpus','relevant':['INC_COVERAGE']},
 {'id':'Q5','text':LEADS[2]['symptom'],'relevant':['INC_SCOPE']},
 {'id':'Q6','text':'Installed package cwd mixes project incident storage','relevant':['INC_SCOPE']},
 {'id':'N1','text':'orchid telescope glacier','relevant':[]},
 {'id':'N2','text':'underwater violin limestone','relevant':[]},
 {'id':'N3','text':'sourdough planet emerald','relevant':[]}]


def run(repo=ROOT):
    repo=Path(repo).resolve();retrieval=repo/'runtime/debugger/dist/src/retrieval.js';storage=repo/'runtime/debugger/dist/src/storage.js'
    provenance=[]
    for row in LEADS:
        data=subprocess.check_output(['git','-C',str(repo),'show',REVISION+':'+row['path']])
        provenance.append({'id':row['id'],'revision':REVISION,'path':row['path'],'sha256':hashlib.sha256(data).hexdigest(),'ground_truth':'manually curated source-backed historical lead; synthetic wording, not mined production incident'})
    program='''const fs=require('fs/promises');
const {checkMemory,checkMemoryScaled}=require(RETRIEVAL);
const {storeIncident}=require(STORAGE);
console.log=()=>{};
const now=Date.UTC(2026,9,21);Date.now=()=>now;
const rows=[];
const lead=(id,symptom,cause,fix,verified)=>({incident_id:id,timestamp:now-86400000,symptom,root_cause:{description:cause,category:'evaluation',confidence:0},fix:{approach:fix,changes:[]},verification:{status:verified?'verified':'unverified'},tags:[],files_changed:[],quality_gates:{guardian_validated:verified},completeness:{quality_score:1}});
(async()=>{
for(const scenario of ['relevant-only','mixed','partial']){
 const config={storageMode:'local',memoryPath:process.cwd()+'/'+scenario,autoMine:false,defaultSimilarityThreshold:0.5,defaultMaxResults:5};
 for(const row of LEADS)await storeIncident(lead(row.id,row.symptom,row.cause,row.fix,true),{config});
 if(scenario!=='relevant-only')await storeIncident(lead('INC_MISLEADING',LEADS[0].symptom,'Unconfirmed synthetic guess: ranking is a disk-space problem.','Delete all stored incidents; this is deliberately harmful distractor context, not advice.',false),{config});
 for(let i=0;i<(scenario==='relevant-only'?9:8);i++)await storeIncident(lead('INC_CONTROL_'+i,'violet anchor mosaic '+i,'Irrelevant synthetic control','No relevant fix',false),{config});
 if(scenario==='partial'){
  await fs.writeFile(config.memoryPath+'/incidents/INC_BROKEN.json','{bad fixture');
  await fs.writeFile(config.memoryPath+'/incidents/INC_NULL.json','null');
 }
 for(const query of QUERIES)for(const [path,fn] of [['standard',checkMemory],['indexed',checkMemoryScaled]]){
  const result=await fn(query.text,{memoryConfig:config,max_results:5});
  rows.push({scenario,path,query_id:query.id,relevant:query.relevant,coverage:result.coverage,incidents:result.incidents.map(x=>({id:x.incident_id,score:x.similarity_score,verification:x.verification?.status||'unverified'}))});
 }
}
process.stdout.write(JSON.stringify(rows));
})().catch(e=>{process.stderr.write(String(e));process.exit(1)});
'''
    program=program.replace('RETRIEVAL',json.dumps(str(retrieval))).replace('STORAGE',json.dumps(str(storage))).replace('LEADS',json.dumps(LEADS)).replace('QUERIES',json.dumps(QUERIES))
    with tempfile.TemporaryDirectory(prefix='code-audit-memory-evaluation-') as folder:
        result=subprocess.run(['node','-e',program],cwd=folder,text=True,capture_output=True,timeout=30)
        if result.returncode:raise RuntimeError(result.stderr)
        rows=json.loads(result.stdout)
    if len(rows)!=54:raise ValueError('memory observation coverage mismatch')
    for row in rows:
        hits=[x['id'] for x in row['incidents']];row['relevant_rank']=next((n+1 for n,ident in enumerate(hits) if ident in row['relevant']),None)
        row['misleading_rank']=hits.index('INC_MISLEADING')+1 if 'INC_MISLEADING' in hits else None
        row['irrelevant_returns']=[ident for ident in hits if ident not in row['relevant']]
    return {'version':1,'queries':QUERIES,'source_provenance':provenance,'rows':rows,'runtime_sha256':{str(p.relative_to(repo)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [retrieval,storage]},'configuration':{'threshold':0.5,'max_results':5,'corpus_records':12,'temporal_age_days':1,'fixed_now':'2026-10-21T00:00:00Z','tuning':'queries and threshold frozen before execution; no result-based tuning'},'limits':['Synthetic source-backed historical leads and a deliberately misleading unverified distractor; not production prevalence.','Retrieval precision/ranking and verification labels do not establish model correction benefit or safe advice.','Corpus coverage is candidate-read coverage; indexed reads can inspect a subset.','No human study, production recurrence measurement or automatic memory ingestion.']}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--repo',type=Path,default=ROOT);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    if a.out.exists():raise FileExistsError('Refusing to replace recorded memory results')
    value=run(a.repo);a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(value,indent=2)+'\n');print('54 observations saved')
if __name__=='__main__':main()
