"""Public compiled-runtime regression checks for recency and corpus coverage."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class Retrieval(unittest.TestCase):
    def probe(self, body):
        with tempfile.TemporaryDirectory() as folder:
            prefix = f"""
const fs = require('fs/promises');
const {{checkMemory, checkMemoryScaled}} = require({json.dumps(str(ROOT / 'runtime/debugger/dist/src/retrieval.js'))});
const {{storeIncident}} = require({json.dumps(str(ROOT / 'runtime/debugger/dist/src/storage.js'))});
console.log = () => {{}};
const day = 86400000, now = Date.UTC(2026,9,20); Date.now = () => now;
const memoryPath = {json.dumps(folder)};
const memoryConfig = {{storageMode:'local',memoryPath,autoMine:false,defaultSimilarityThreshold:0.5,defaultMaxResults:20}};
const incident = (id, age) => ({{incident_id:id,timestamp:now-age*day,symptom:'alpha beta gamma',root_cause:{{description:'Fixture cause',category:'test',confidence:0}},fix:{{approach:'Fixture only',changes:[]}},verification:{{status:'unverified'}},tags:[],files_changed:[],quality_gates:{{guardian_validated:false}},completeness:{{quality_score:0.1}}}});
const write = async (name, value) => {{await fs.mkdir(memoryPath+'/incidents',{{recursive:true}});await fs.writeFile(memoryPath+'/incidents/'+name,typeof value==='string'?value:JSON.stringify(value));}};
(async()=>{{
"""
            result = subprocess.run(['node', '-e', prefix + body + '\n})().catch(e=>{console.error(e);process.exit(1)});'], text=True, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)

    def test_recent_cutoff_old_and_future_in_both_paths(self):
        rows = self.probe("""
for (let i=0;i<10;i++) await storeIncident(incident('INC_PROBE_'+i,[10,90,90.0001,200,-1,200,200,200,200,200][i]),{config:memoryConfig});
const options={memoryConfig,max_results:20};
const standard=await checkMemory('alpha beta gamma delta',options);
const scaled=await checkMemoryScaled('alpha beta gamma delta',options);
process.stdout.write(JSON.stringify([standard,scaled]));
""")
        for result in rows:
            self.assertEqual([r['incident_id'] for r in result['incidents']], ['INC_PROBE_0', 'INC_PROBE_1'])
            self.assertTrue(all(abs(r['similarity_score']-.54)<1e-9 for r in result['incidents']))

    def test_validation_filter_matches_standard_and_scaled_even_at_zero_threshold(self):
        rows = self.probe("""
for(let i=0;i<10;i++) { const row=incident('INC_PROBE_'+i,10);row.quality_gates.guardian_validated=i===0;await storeIncident(row,{config:memoryConfig}); }
const options={memoryConfig,max_results:20,include_unvalidated:false,similarity_threshold:0};
process.stdout.write(JSON.stringify([await checkMemory('alpha beta gamma delta',options),await checkMemoryScaled('alpha beta gamma delta',options)]));
""")
        for result in rows:self.assertEqual([row['incident_id'] for row in result['incidents']],['INC_PROBE_0'])

    def test_zero_temporal_preference_is_not_ninety_days(self):
        result = self.probe("""
await write('INC_RECENT.json',incident('INC_RECENT',10));
process.stdout.write(JSON.stringify(await checkMemory('alpha beta gamma delta',{memoryConfig,temporal_preference:0})));
""")
        self.assertEqual(result['incidents'], [])

    def test_mixed_corrupt_unreadable_and_invalid_records_keep_matches(self):
        result = self.probe("""
await write('INC_VALID.json',incident('INC_VALID',10));
await write('INC_BAD.json','{bad');await write('INC_NULL.json','null');
await fs.mkdir(memoryPath+'/incidents/INC_DIRECTORY.json');
await fs.mkdir(memoryPath+'/patterns');await fs.writeFile(memoryPath+'/patterns/PTN_BAD.json','{}');
process.stdout.write(JSON.stringify(await checkMemory('alpha beta gamma delta',{memoryConfig})));
""")
        self.assertEqual([r['incident_id'] for r in result['incidents']], ['INC_VALID'])
        coverage = result['coverage']['incidents']
        self.assertEqual((coverage['checked'], coverage['loaded'], coverage['skipped']), (4,1,3))
        self.assertEqual({x['reason'] for x in coverage['examples']}, {'invalid_json','invalid_record','read_failed'})
        self.assertEqual(result['coverage']['patterns']['skipped'], 1)

    def test_empty_and_all_corrupt_have_distinct_coverage_and_bounded_examples(self):
        result = self.probe("""
const empty=await checkMemory('alpha beta gamma delta',{memoryConfig});
for(let i=0;i<12;i++) await write('INC_BAD_'+i+'.json','{secret fixture payload');
const corrupt=await checkMemory('alpha beta gamma delta',{memoryConfig});
process.stdout.write(JSON.stringify([empty,corrupt]));
""")
        self.assertEqual(result[0]['coverage']['incidents']['skipped'],0)
        self.assertEqual(result[1]['coverage']['incidents']['skipped'],12)
        self.assertEqual(len(result[1]['coverage']['incidents']['examples']),5)
        self.assertNotIn('secret fixture payload',json.dumps(result))

    def test_scaled_partial_candidate_read_is_visible(self):
        result = self.probe("""
for(let i=0;i<10;i++) await storeIncident(incident('INC_PROBE_'+i,10),{config:memoryConfig});
await write('INC_PROBE_0.json','{bad');
process.stdout.write(JSON.stringify(await checkMemoryScaled('alpha beta gamma delta',{memoryConfig,max_results:20})));
""")
        self.assertEqual(len(result['incidents']),9)
        self.assertEqual(result['coverage']['incidents']['skipped'],1)
        self.assertEqual(result['coverage']['scope'],'keyword candidates')

if __name__ == '__main__': unittest.main()
