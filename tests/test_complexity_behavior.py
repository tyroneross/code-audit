"""Frozen pre-refactor output contracts, including overlapping matches and legacy inputs."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / 'runtime/debugger/dist/src'

class ComplexityBehavior(unittest.TestCase):
    def test_frozen_output_contracts(self):
        cases = json.loads((ROOT / 'tests/fixtures/complexity-behavior.json').read_text())
        with tempfile.TemporaryDirectory() as folder:
            script = f"""
const fs=require('fs'), fsp=require('fs/promises'), path=require('path'), Module=require('module'), assert=require('assert/strict');
const base={json.dumps(str(DIST))}, data={json.dumps(cases)}, root={json.dumps(folder)};
const storage=require(path.join(base,'storage.js')), retrieval=require(path.join(base,'retrieval.js'));
function expose(file,name){{const mod=new Module(file,module);mod.filename=file;mod.paths=Module._nodeModulePaths(path.dirname(file));mod._compile(fs.readFileSync(file,'utf8')+'\\nexports.__probe='+name+';',file);return mod.exports.__probe;}}
const category=expose(path.join(base,'audit-miner.js'),'inferCategory'), detail=expose(path.join(base,'mcp/tools.js'),'handleDetail');
const config={{storageMode:'local',memoryPath:root,autoMine:false,defaultSimilarityThreshold:.5,defaultMaxResults:5}};
(async()=>{{
for(const c of data.normal)assert.deepEqual(storage.normalizeLegacyIncident(structuredClone(c.input),c.filename),c.expected);
for(const c of data.categories){{assert.equal(category(c.text),c.expected);assert.equal(category('',c.text),c.expected)}}
await fsp.mkdir(path.join(root,'incidents'));
for(const row of data.incidents)await fsp.writeFile(path.join(root,'incidents',row.incident_id+'.json'),JSON.stringify(row));
for(const c of data.search){{
 const actual=await retrieval.enhancedSearch(c.query,{{...c.options,memoryConfig:config}});
 for(const result of actual)assert.deepEqual(result.incident,data.incidents.find(row=>row.incident_id===result.incident.incident_id));
 assert.deepEqual(actual.map(({{incident,...match}})=>({{incident_id:incident.incident_id,...match}})),c.expected);
}}
await fsp.mkdir(path.join(root,'patterns'));
await fsp.writeFile(path.join(root,'patterns',data.pattern.pattern_id+'.json'),JSON.stringify(data.pattern));
await fsp.writeFile(path.join(root,'incidents',data.detailed.incident_id+'.json'),JSON.stringify(data.detailed));
for(const c of data.details)assert.deepEqual(await detail({{id:c.id}},config),c.expected);
}})().catch(e=>{{console.error(e);process.exit(1)}});
"""
            result = subprocess.run(['node','-e',script],capture_output=True,text=True,timeout=20)
            self.assertEqual(result.returncode,0,result.stderr)

if __name__ == '__main__':
    unittest.main()
