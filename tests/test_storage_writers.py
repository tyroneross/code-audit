"""Same-corpus persistence invariants through the bundled runtime API."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / 'runtime/debugger/dist/src'

class StorageWriters(unittest.TestCase):
    def probe(self, body):
        with tempfile.TemporaryDirectory() as folder:
            prelude = f"""
const fs = require('fs/promises'), path = require('path');
const {{ promisify }} = require('util');
const execFile = promisify(require('child_process').execFile);
const locks = require({json.dumps(str(DIST / 'corpus-write.js'))});
const s = require({json.dumps(str(DIST / 'storage.js'))});
const memoryPath = {json.dumps(folder)};
const config = {{storageMode:'local',memoryPath,autoMine:false,defaultSimilarityThreshold:.5,defaultMaxResults:5}};
const row = id => ({{incident_id:id,timestamp:1000,symptom:'shared alpha keyword',tags:['shared'],files_changed:['same.ts'],root_cause:{{category:'fixture',description:'shared cause'}},fix:{{approach:'fixture',changes:[]}},completeness:{{quality_score:.5}}}});
const store = id => s.storeIncident(row(id),{{config}});
console.log = () => {{}};
(async()=>{{
"""
            p = subprocess.run(['node', '-e', prelude + body + '\n})().catch(e=>{console.error(e);process.exit(1)});'], capture_output=True, text=True, timeout=30)
            self.assertEqual(p.returncode, 0, p.stderr)
            return json.loads(p.stdout)

    def test_overlapping_stores_preserve_all_indexes(self):
        result = self.probe("""
await store('INC_SEED');
const read = fs.readFile;
fs.readFile = async function(file,...args){const value=await read.call(this,file,...args);if(String(file).endsWith('index.json'))await new Promise(r=>setTimeout(r,15));return value;};
await Promise.all(Array.from({length:12},(_,i)=>store('INC_PARALLEL_'+i)));
fs.readFile=read;
const index=await s.loadIndex(config), keywords=await s.loadKeywordIndex(config);
process.stdout.write(JSON.stringify({total:index.stats.total_incidents,ids:index.by_category.fixture,keywords:keywords.keywords.shared,keywordTotal:keywords.total_incidents}));
""")
        expected = {'INC_SEED'} | {f'INC_PARALLEL_{i}' for i in range(12)}
        self.assertEqual(result['total'], 13)
        self.assertEqual(set(result['ids']), expected)
        self.assertEqual(set(result['keywords']), expected)
        self.assertEqual(result['keywordTotal'], 13)

    def test_multiple_processes_rebuild_and_replace_preserve_records(self):
        result = self.probe(f"""
await store('INC_SEED');
const worker = `const s=require({json.dumps(str(DIST / 'storage.js'))});const config=${{JSON.stringify(config)}};const row=${{row.toString()}};console.log=()=>{{}};(async()=>{{for(let i=0;i<5;i++)await s.storeIncident(row(process.argv[1]+'_'+i),{{config}})}})().catch(e=>{{console.error(e);process.exit(1)}});`;
await Promise.all(['INC_A','INC_B','INC_C'].map(id=>execFile(process.execPath,['-e',worker,id])));
await Promise.all([s.rebuildIndex(config),s.rebuildKeywordIndex(config),store('INC_SEED'),store('INC_LAST')]);
const index=await s.loadIndex(config),keywords=await s.loadKeywordIndex(config);
process.stdout.write(JSON.stringify({{total:index.stats.total_incidents,ids:index.by_category.fixture,keywordTotal:keywords.total_incidents,postings:keywords.keywords.shared}}));
""")
        self.assertEqual(result['total'],17)
        self.assertEqual(result['keywordTotal'],17)
        self.assertEqual(len(set(result['ids'])),17)
        self.assertEqual(len(set(result['postings'])),17)

    def test_aliases_serialize_while_other_corpora_continue(self):
        result = self.probe("""
const alias=memoryPath+'-alias'; await fs.symlink(memoryPath,alias);
let release,entered;const ready=new Promise(r=>entered=r);
const held=locks.withCorpusWrite(config,async()=>{entered();await new Promise(r=>release=r)});
await ready;
const same=s.storeIncident(row('INC_ALIAS'),{config:{...config,memoryPath:alias}});
const independent={...config,memoryPath:path.join(memoryPath,'independent')};
await s.storeIncident(row('INC_OTHER'),{config:independent});
release();await Promise.all([held,same]);await fs.unlink(alias);
process.stdout.write(JSON.stringify([(await s.loadIndex(config)).stats.total_incidents,(await s.loadIndex(independent)).stats.total_incidents]));
""")
        self.assertEqual(result,[1,1])

    def test_failed_publication_keeps_old_json_and_releases_writer(self):
        result = self.probe("""
await store('INC_SEED');const before=await fs.readFile(path.join(memoryPath,'index.json'),'utf8');
const rename=fs.rename;let failed=false;
fs.rename=async function(src,dst){if(!failed&&dst===path.join(memoryPath,'index.json')){failed=true;throw Object.assign(new Error('injected write failure'),{code:'EIO'})}return rename.call(this,src,dst)};
let message;try{await store('INC_RETRY')}catch(e){message=e.message}finally{fs.rename=rename}
const unchanged=before===await fs.readFile(path.join(memoryPath,'index.json'),'utf8');
await store('INC_RETRY');
const leftovers=(await fs.readdir(memoryPath)).filter(name=>name.startsWith('.corpus-')||name.endsWith('.tmp'));
process.stdout.write(JSON.stringify({failed:message,unchanged,total:(await s.loadIndex(config)).stats.total_incidents,leftovers}));
""")
        self.assertEqual(result['failed'],'injected write failure')
        self.assertTrue(result['unchanged'])
        self.assertEqual(result['total'],2)
        self.assertEqual(result['leftovers'],[])

    def test_dead_process_owner_recovers_and_interrupted_recovery_fails_visibly(self):
        result = self.probe(f"""
const modulePath={json.dumps(str(DIST / 'corpus-write.js'))};
const worker=`const l=require(${{JSON.stringify(modulePath)}});l.withCorpusWrite(${{JSON.stringify(config)}},async()=>{{process.stdout.write(String(process.pid));process.exit(0)}})`;
const dead=await execFile(process.execPath,['-e',worker]);
await store('INC_RECOVERED');
const deadAgain=await execFile(process.execPath,['-e',worker]);
const lock=path.join(await fs.realpath(memoryPath),'.corpus-write-lock');
const owner=JSON.parse(await fs.readFile(path.join(lock,'owner.json'),'utf8'));
const recovery=path.join(lock,'recovery-'+encodeURIComponent(owner.nonce));
await fs.symlink(JSON.stringify({{host:require('os').hostname(),pid:Number(deadAgain.stdout)}}),recovery);
let message;try{{await store('INC_BLOCKED')}}catch(e){{message=e.message}}
process.stdout.write(JSON.stringify({{total:(await s.loadIndex(config)).stats.total_incidents,message,retained:!!(await fs.lstat(recovery))}}));
""")
        self.assertEqual(result['total'],1)
        self.assertIn('Interrupted or unknown corpus writer recovery',result['message'])
        self.assertTrue(result['retained'])

    def test_delayed_old_generation_recoverer_does_not_poison_next_owner(self):
        result = self.probe(f"""
const modulePath={json.dumps(str(DIST / 'corpus-write.js'))};
const worker=`const l=require(${{JSON.stringify(modulePath)}});l.withCorpusWrite(${{JSON.stringify(config)}},async()=>{{process.stdout.write(String(process.pid));process.exit(0)}})`;
const dead=await execFile(process.execPath,['-e',worker]);
const lock=path.join(await fs.realpath(memoryPath),'.corpus-write-lock');
const oldOwner=JSON.parse(await fs.readFile(path.join(lock,'owner.json'),'utf8'));
const symlink=fs.symlink;let injected=false;
fs.symlink=async function(target,destination,...args){{
  if(!injected&&String(destination).startsWith(lock+path.sep+'recovery')){{
    injected=true;
    // Recoverer C has read G1 and is paused just before marker publication.
    // Recoverer B removes G1; the next owner acquires G2 and then exits.
    const oldLock=lock+'.previous';await fs.rename(lock,oldLock);await fs.rm(oldLock,{{recursive:true}});
    await fs.mkdir(lock);await fs.writeFile(path.join(lock,'owner.json'),JSON.stringify({{...oldOwner,nonce:'next-generation'}}));
  }}
  return symlink.call(this,target,destination,...args);
}};
try{{await store('INC_AFTER_STALE_RECOVERY')}}finally{{fs.symlink=symlink}}
const leftovers=(await fs.readdir(memoryPath)).filter(name=>name.startsWith('.corpus-'));
process.stdout.write(JSON.stringify({{injected,total:(await s.loadIndex(config)).stats.total_incidents,leftovers}}));
""")
        self.assertTrue(result['injected'])
        self.assertEqual(result['total'],1)
        self.assertEqual(result['leftovers'],[])

    def test_atomic_publication_preserves_existing_modes_and_new_file_umask(self):
        result = self.probe("""
const filename=path.join(memoryPath,'permissions.json');
await fs.writeFile(filename,'{}');await fs.chmod(filename,0o640);
const priorUmask=process.umask(0o077);
let replacementMode,newMode;
try{
  await locks.writeJsonAtomic(filename,{updated:true});
  replacementMode=(await fs.stat(filename)).mode&0o777;
  const created=path.join(memoryPath,'new-permissions.json');
  process.umask(0o027);await locks.writeJsonAtomic(created,{created:true});
  newMode=(await fs.stat(created)).mode&0o777;
}finally{process.umask(priorUmask)}
process.stdout.write(JSON.stringify({replacementMode,newMode,body:JSON.parse(await fs.readFile(filename,'utf8'))}));
""")
        self.assertEqual(result['replacementMode'],0o640)
        self.assertEqual(result['newMode'],0o640)
        self.assertEqual(result['body'],{'updated':True})

    def test_private_replacement_is_never_published_to_a_broader_temp_mode(self):
        result = self.probe("""
const filename=path.join(memoryPath,'private.json');
await fs.writeFile(filename,'{}');await fs.chmod(filename,0o600);
const priorUmask=process.umask(0o022), writeFile=fs.writeFile;
let temporaryMode;
fs.writeFile=async function(file,...args){
  const value=await writeFile.call(this,file,...args);
  if(String(file).startsWith(filename+'.')&&String(file).endsWith('.tmp'))temporaryMode=(await fs.stat(file)).mode&0o777;
  return value;
};
try{await locks.writeJsonAtomic(filename,{private:true})}finally{fs.writeFile=writeFile;process.umask(priorUmask)}
process.stdout.write(JSON.stringify({temporaryMode,finalMode:(await fs.stat(filename)).mode&0o777}));
""")
        self.assertEqual(result['temporaryMode'],0o600)
        self.assertEqual(result['finalMode'],0o600)

    def test_concurrent_mcp_store_acknowledgements_match_persisted_indexes(self):
        with tempfile.TemporaryDirectory() as folder:
            project=Path(folder)
            calls=[{'jsonrpc':'2.0','id':i,'method':'tools/call','params':{'name':'store','arguments':{'project_root':str(project),'symptom':f'Shared fixture symptom {i}','root_cause':'Fixture root cause','fix':'Fixture repair','category':'fixture','tags':['shared'],'files_changed':['same.ts']}}} for i in range(8)]
            env={k:v for k,v in os.environ.items() if not k.startswith(('CLAUDE_MEMORY_','DEBUGGER_LOG_'))}
            result=subprocess.run(['node',str(ROOT/'scripts/debugger-server.cjs')],input=''.join(json.dumps(c)+'\n' for c in calls),cwd=project,env=env,text=True,capture_output=True,timeout=20)
            self.assertEqual(result.returncode,0,result.stderr)
            replies=[json.loads(line) for line in result.stdout.splitlines()]
            self.assertEqual({r['id'] for r in replies},set(range(8)))
            self.assertTrue(all(not r.get('error') and not r.get('result',{}).get('isError') for r in replies),replies)
            memory=project/'.claude/memory'
            index=json.loads((memory/'index.json').read_text())
            keywords=json.loads((memory/'keyword-index.json').read_text())
            ids={p.stem for p in (memory/'incidents').glob('*.json')}
            self.assertEqual(len(ids),8)
            self.assertEqual(index['stats']['total_incidents'],8)
            self.assertEqual(set(index['by_category']['fixture']),ids)
            self.assertEqual(set(keywords['keywords']['shared']),ids)

if __name__ == '__main__':
    unittest.main()
