"""Older Coding Debugger incident shapes load through read-time normalization; files stay untouched.

Fixtures are synthetic. They mirror only the structure of legacy records seen in one private corpus
(key names and value types), never its text.
"""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / 'runtime/debugger/dist/src'


class LegacyIncidents(unittest.TestCase):
    def probe(self, body):
        with tempfile.TemporaryDirectory() as folder:
            prefix = f"""
const fs = require('fs/promises');
const st = require({json.dumps(str(DIST / 'storage.js'))});
const {{checkMemory}} = require({json.dumps(str(DIST / 'retrieval.js'))});
console.log = () => {{}};
const day = 86400000, now = Date.UTC(2026,9,20); Date.now = () => now;
const memoryPath = {json.dumps(folder)};
const memoryConfig = {{storageMode:'local',memoryPath,autoMine:false,defaultSimilarityThreshold:0.5,defaultMaxResults:20}};
const base = (id) => ({{incident_id:id,timestamp:now-5*day,symptom:'fixture symptom text',root_cause:{{description:'Fixture cause',category:'test',confidence:0.5}},fix:{{approach:'Fixture only',changes:[]}},verification:{{status:'verified'}},tags:[],files_changed:[]}});
const write = async (name, value) => {{await fs.mkdir(memoryPath+'/incidents',{{recursive:true}});await fs.writeFile(memoryPath+'/incidents/'+name,typeof value==='string'?value:JSON.stringify(value));}};
const load = async () => {{const coverage=st.emptyCorpusCoverage();const rows=await st.loadAllIncidents(memoryConfig,coverage);const byId={{}};for(const r of rows)byId[r.incident_id]=r;return {{byId,coverage}};}};
(async()=>{{
"""
            result = subprocess.run(['node', '-e', prefix + body + '\n})().catch(e=>{console.error(e);process.exit(1)});'], text=True, capture_output=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)

    def test_structured_symptom_reads_as_text_and_keeps_the_object(self):
        out = self.probe("""
await write('INC_DESC.json', {...base('INC_DESC'), symptom:{description:'Widget list renders empty after refresh', severity:'high', error_messages:['E1'], context:'ctx'}});
await write('INC_NODESC.json', {...base('INC_NODESC'), symptom:{reproduction_steps:['step one'], user_description:'Saved filters vanish', observed_behavior:'List resets to default', error_messages:['timeout waiting for list', 7], affected_components:['list']}});
const {byId,coverage} = await load();
const hit = await checkMemory('saved filters vanish list resets', {memoryConfig,max_results:5,similarity_threshold:0.2});
process.stdout.write(JSON.stringify([byId.INC_DESC, byId.INC_NODESC, coverage.skipped, hit.incidents.map(x=>x.incident_id)]));
""")
        desc, nodesc, skipped, hits = out
        self.assertEqual(desc['symptom'], 'Widget list renders empty after refresh')
        self.assertEqual(desc['legacy']['symptom']['severity'], 'high')
        # No description: preferred text keys in a fixed order; arrays contribute their strings only.
        self.assertEqual(nodesc['symptom'], 'Saved filters vanish. List resets to default. timeout waiting for list')
        self.assertEqual(nodesc['legacy']['symptom']['reproduction_steps'], ['step one'])
        self.assertEqual(skipped, 0)
        self.assertIn('INC_NODESC', hits)

    def test_unknown_verification_status_reads_as_unverified_with_raw_value_kept(self):
        out = self.probe("""
await write('INC_PENDING.json', {...base('INC_PENDING'), verification:{status:'pending_user_test', success_criteria:['x']}});
await write('INC_INVESTIGATING.json', {...base('INC_INVESTIGATING'), verification:{status:'investigating'}});
await write('INC_BADTYPE.json', {...base('INC_BADTYPE'), verification:{status:3}});
const {byId,coverage} = await load();
process.stdout.write(JSON.stringify([byId.INC_PENDING, byId.INC_INVESTIGATING, Object.keys(byId).sort(), coverage.skipped]));
""")
        pending, investigating, ids, skipped = out
        self.assertEqual((pending['verification']['status'], pending['legacy']['verification_status']), ('unverified', 'pending_user_test'))
        self.assertEqual(pending['verification']['success_criteria'], ['x'])
        self.assertEqual(investigating['legacy']['verification_status'], 'investigating')
        # A non-string status is not a legacy shape; it stays visibly invalid.
        self.assertEqual((ids, skipped), (['INC_INVESTIGATING', 'INC_PENDING'], 1))

    def test_string_and_command_changes_map_to_files_and_notes_not_fake_files(self):
        out = self.probe("""
await write('INC_STRINGS.json', {...base('INC_STRINGS'), fix:{approach:'a', changes:['src/app/page.tsx','lib/api-client.ts','Reworded the banner copy']}});
await write('INC_COMMANDS.json', {...base('INC_COMMANDS'), fix:{approach:'a', changes:[{command:'npm run build',summary:'Rebuilt the bundle'},{command:'git push',summary:'Shipped'}]}});
await write('INC_ODD.json', {...base('INC_ODD'), fix:{approach:'a', changes:[42]}});
const {byId,coverage} = await load();
process.stdout.write(JSON.stringify([byId.INC_STRINGS.fix, byId.INC_STRINGS.legacy, byId.INC_COMMANDS.fix, Object.keys(byId).sort(), coverage.skipped]));
""")
        strings_fix, strings_legacy, commands_fix, ids, skipped = out
        self.assertEqual(strings_fix['changes'], [{'file': 'src/app/page.tsx'}, {'file': 'lib/api-client.ts'}])
        self.assertEqual(strings_fix['notes'], ['Reworded the banner copy'])
        self.assertEqual(len(strings_legacy['fix_changes']), 3)
        self.assertEqual(commands_fix['changes'], [])
        self.assertEqual(commands_fix['notes'], ['Rebuilt the bundle — command: npm run build', 'Shipped — command: git push'])
        self.assertEqual((ids, skipped), (['INC_COMMANDS', 'INC_STRINGS'], 1))

    def test_missing_id_and_timestamp_come_from_a_matching_filename_and_disk_is_untouched(self):
        out = self.probe("""
const {incident_id, timestamp, ...rest} = base('x');
await write('INC_20261015_101500_alpha_beta.json', {...rest, sessionId:'s1', security_notes:'n'});
await write('notes.json', {...rest});
await write('INC_NOSTAMP.json', {...base('INC_NOSTAMP'), timestamp:undefined});
const before = {};
for (const f of await fs.readdir(memoryPath+'/incidents')) { const p=memoryPath+'/incidents/'+f; before[f]=[await fs.readFile(p,'utf8'), (await fs.stat(p)).mtimeMs]; }
const {byId,coverage} = await load();
const detail = await st.loadIncident('INC_20261015_101500_alpha_beta', memoryConfig);
const after = {};
for (const f of await fs.readdir(memoryPath+'/incidents')) { const p=memoryPath+'/incidents/'+f; after[f]=[await fs.readFile(p,'utf8'), (await fs.stat(p)).mtimeMs]; }
process.stdout.write(JSON.stringify([byId['INC_20261015_101500_alpha_beta'], detail, Object.keys(byId), coverage, JSON.stringify(before)===JSON.stringify(after)]));
""")
        loaded, detail, ids, coverage, unchanged = out
        self.assertEqual(loaded['timestamp'], 1792059300000)  # 2026-10-15T10:15:00Z from the ID, not file mtime
        self.assertEqual(loaded['legacy'], {'incident_id_source': 'filename', 'timestamp_source': 'incident_id'})
        self.assertEqual((detail['incident_id'], detail['timestamp']), ('INC_20261015_101500_alpha_beta', 1792059300000))
        self.assertEqual(ids, ['INC_20261015_101500_alpha_beta'])
        reasons = sorted(x['reason'] for x in coverage['examples'])
        self.assertEqual(reasons, ['invalid_record', 'missing_timestamp'])
        self.assertTrue(unchanged)

    def test_session_records_and_id_filename_mismatches_stay_skipped_with_named_reasons(self):
        out = self.probe("""
const {incident_id, ...rest} = base('x');
await write('SESSION_1761200000_abcd.json', {...rest, session_id:'SESSION_1761200000_abcd', symptom:{description:'looks like an incident'}});
await write('INCIDENT_1761200000_one.json', {...base('INCIDENT_1761200000_two')});
await write('INC_OK.json', base('INC_OK'));
const {byId,coverage} = await load();
process.stdout.write(JSON.stringify([Object.keys(byId), coverage]));
""")
        ids, coverage = out
        self.assertEqual(ids, ['INC_OK'])
        self.assertEqual((coverage['checked'], coverage['loaded'], coverage['skipped']), (3, 1, 2))
        self.assertEqual({x['file']: x['reason'] for x in coverage['examples']},
                         {'INCIDENT_1761200000_one.json': 'id_filename_mismatch', 'SESSION_1761200000_abcd.json': 'session_record'})


if __name__ == '__main__':
    unittest.main()
