"""Regression checks for independently observed protocol and read-only failures."""
from pathlib import Path
import hashlib,json,os,re,subprocess,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1]

class Boundaries(unittest.TestCase):
    def run_server(self,project,messages,**extra):
        env={k:v for k,v in os.environ.items() if not k.startswith(('CLAUDE_MEMORY_','DEBUGGER_LOG_'))}
        env.update(extra)
        payload=''.join((m if isinstance(m,str) else json.dumps(m))+'\n' for m in messages)
        result=subprocess.run(['node',str(ROOT/'scripts/debugger-server.cjs')],input=payload,cwd=project,env=env,text=True,capture_output=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        return [json.loads(line) for line in result.stdout.splitlines()]
    def request(self,i,name,args=None):return {'jsonrpc':'2.0','id':i,'method':'tools/call','params':{'name':name,'arguments':args or {}}}

    def test_read_only_tools_create_no_project_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls=[self.request(1,'search',{'symptom':'private user@example.test token=abc123'}),self.request(2,'status'),self.request(3,'list'),self.request(4,'patterns'),self.request(5,'detail',{'id':'INC_missing'}),self.request(6,'read_logs',{'source':'project'})]
            rows=self.run_server(tmp,calls);self.assertEqual(len(rows),6)
            self.assertEqual(list(Path(tmp).iterdir()),[])
            text=next(m['result']['content'][0]['text'] for m in rows if m['id']==1)
            self.assertIn('not calibrated repair confidence',text)

    def test_malformed_input_recovery_ping_and_versions(self):
        for version in ['2024-11-05','2025-03-26','2025-06-18','2025-11-25','unsupported']:
            with tempfile.TemporaryDirectory() as tmp:
                rows=self.run_server(tmp,['{bad',{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':version}},{'jsonrpc':'2.0','id':2,'method':'ping'},{'jsonrpc':'2.0','id':3,'method':'tools/list'}])
                self.assertEqual(rows[0]['error']['code'],-32700)
                byid={m['id']:m for m in rows[1:]};self.assertEqual(byid[1]['result']['protocolVersion'],version if version!='unsupported' else '2025-11-25')
                self.assertEqual(byid[1]['result']['serverInfo']['version'],'1.9.1')
                self.assertEqual(byid[2]['result'],{});self.assertEqual(len(byid[3]['result']['tools']),8)

    def test_log_reader_rejects_outside_symlink_and_large_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);project=base/'project';project.mkdir();outside=base/'private.log';outside.write_text('ERROR api_key=must-not-leak\n')
            (project/'escape.log').symlink_to(outside)
            with (project/'large.log').open('wb') as f:f.truncate(1024*1024+1)
            (project/'inside.log').write_text('ERROR safe local event\n')
            calls=[self.request(i,'read_logs',{'source':'path','path':str(p)}) for i,p in enumerate([outside,project/'escape.log',project/'large.log',project/'inside.log'],1)]
            rows=self.run_server(project,calls);byid={m['id']:m['result'] for m in rows}
            for i in [1,2,3]:self.assertTrue(byid[i].get('isError'),byid[i])
            self.assertFalse(byid[4].get('isError'));self.assertNotIn('must-not-leak',json.dumps(rows));self.assertIn('safe local event',json.dumps(byid[4]))

    def test_discovery_reports_skipped_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            project=Path(tmp);logs=project/'logs';logs.mkdir()
            (logs/'bad.log').symlink_to(project.parent/'missing.log')
            rows=self.run_server(tmp,[self.request(1,'read_logs',{'source':'project'})])
            text=rows[0]['result']['content'][0]['text'];self.assertIn('Skipped 1 file',text);self.assertNotIn('Files checked:',text)

    def test_outcome_rejects_unknown_incident_and_is_not_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows=self.run_server(tmp,[self.request(1,'outcome',{'incident_id':'INC_missing','result':'worked'}),{'jsonrpc':'2.0','id':2,'method':'tools/list'}])
            byid={m['id']:m for m in rows};self.assertTrue(byid[1]['result']['isError']);self.assertEqual(list(Path(tmp).iterdir()),[])
            tool=next(t for t in byid[2]['result']['tools'] if t['name']=='outcome');self.assertFalse(tool['annotations']['idempotentHint']);self.assertNotIn('improves future verdict accuracy',tool['description'].lower())

    def test_long_log_lines_have_an_explicit_tool_output_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp)/'long.log').write_text('ERROR '+('x'*131072)+'\n')
            rows=self.run_server(tmp,[self.request(1,'read_logs',{'source':'path','path':'long.log'})])
            result=rows[0]['result'];self.assertFalse(result.get('isError'))
            text=result['content'][0]['text'];self.assertIn('Output truncated at 32 KiB',text);self.assertLess(len(text.encode()),33000)

    def test_seeded_reads_are_write_free_and_concurrent_stdout_is_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            project=Path(tmp);symptom='duplicate checkout receipts after lost acknowledgement'
            rows=self.run_server(tmp,[self.request(1,'store',{'symptom':symptom,'root_cause':'Transport retry regenerated identity, allowing repeated checkout effects.','fix':'Preserve logical identity across attempts','category':'logic'})])
            incident=re.search(r'INC_[\w-]+',rows[0]['result']['content'][0]['text']).group()
            def snapshot():return {str(p.relative_to(project)):(p.stat().st_mtime_ns,hashlib.sha256(p.read_bytes()).hexdigest()) for p in project.rglob('*') if p.is_file()}
            calls=[self.request(i,'search',{'symptom':symptom}) for i in range(1,21)]
            calls += [self.request(21,'status'),self.request(22,'list'),self.request(23,'patterns'),self.request(24,'detail',{'id':incident})]
            before=snapshot();rows=self.run_server(tmp,calls);self.assertEqual(len(rows),24);self.assertEqual(snapshot(),before)
            # Missing indexes must remain a read coverage gap, not trigger a rebuild.
            (project/'.claude/memory/index.json').unlink();before=snapshot();self.run_server(tmp,calls);self.assertEqual(snapshot(),before)

    def test_known_fix_is_a_historical_candidate_in_the_built_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/'.claude/memory/patterns';folder.mkdir(parents=True)
            pattern={'pattern_id':'PTN_CHECKOUT_IDENTITY','description':'Duplicate checkout effects','detection_signature':['checkout','duplicate'],'solution_template':'Preserve identity','success_rate':0.8,'tags':['checkout','duplicate'],'usage_history':{'total_uses':10}}
            (folder/'PTN_CHECKOUT_IDENTITY.json').write_text(json.dumps(pattern))
            rows=self.run_server(tmp,[self.request(1,'search',{'symptom':'duplicate checkout'})]);text=rows[0]['result']['content'][0]['text']
            self.assertIn('KNOWN_FIX',text);self.assertIn('Candidate fix: validate cause and contracts',text);self.assertNotIn('Apply the known fix',text);self.assertNotIn('% similarity',text);self.assertIn('Retrieval tier: pattern',text)

    def test_log_reader_refuses_home_and_filesystem_root_scopes(self):
        for cwd in [str(Path.home()),str(Path.home().parent),str(Path.cwd().anchor)]:
            rows=self.run_server(cwd,[self.request(1,'read_logs',{'source':'project'})]);self.assertTrue(rows[0]['result'].get('isError'));self.assertIn('specific project working directory',rows[0]['result']['content'][0]['text'])

    def test_fifo_and_invalid_event_times_do_not_block_other_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            project=Path(tmp);os.mkfifo(project/'pipe.log')
            (project/'mixed.log').write_text('2026-10-16 10:00:00 ERROR first\n0000-00-00 00:00:00 ERROR bad date\n2026-10-16 10:00:01 ERROR last\n')
            rows=self.run_server(tmp,[self.request(1,'read_logs',{'source':'path','path':'pipe.log'}),self.request(2,'read_logs',{'source':'path','path':'mixed.log'})]);byid={m['id']:m['result'] for m in rows};self.assertTrue(byid[1].get('isError'));self.assertFalse(byid[2].get('isError'));text=byid[2]['content'][0]['text'];self.assertIn('first',text);self.assertIn('last',text);self.assertIn('time unknown',text)
            rows=self.run_server(tmp,[self.request(1,'read_logs',{'source':'path','path':'mixed.log','since':'2026-10-16T00:00:00Z'})]);self.assertIn('Skipped 1 entries without valid event times',rows[0]['result']['content'][0]['text'])

    def test_invalid_ids_and_notifications_do_not_write_or_poison_the_stream(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows=self.run_server(tmp,[self.request(1,'detail',{'id':'INC_/../../other'}),{'jsonrpc':'2.0','method':'tools/list'},{'jsonrpc':'2.0','id':{},'method':'ping'},{'jsonrpc':'2.0','id':2,'method':'ping'}]);byid={str(m['id']):m for m in rows};self.assertTrue(byid['1']['result']['isError']);self.assertEqual(byid['None']['error']['code'],-32600);self.assertEqual(byid['2']['result'],{});self.assertEqual(len(rows),3);self.assertEqual(list(Path(tmp).iterdir()),[])

    def test_package_hygiene_and_import_provenance(self):
        if (ROOT/'.git').exists():
            paths=subprocess.check_output(['git','-C',str(ROOT),'ls-files','-z'],text=True).split('\0')
        else:
            paths=[str(p.relative_to(ROOT)) for p in ROOT.rglob('*') if p.is_file() and 'node_modules' not in p.parts]
        for name in paths:
            self.assertFalse(set(Path(name).parts)&{'.bookmark','.build-loop','.claude-code-debugger','__pycache__'},name)
        provenance=json.loads((ROOT/'docs/source-provenance.json').read_text())
        for entry in provenance['imported_files']:
            p=ROOT/entry['path'];self.assertTrue(p.is_file(),entry['path']);self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),entry['current_sha256']);self.assertEqual(entry['modified_from_import'],entry['source_sha256']!=entry['current_sha256'])
        for p in (ROOT/'skills').rglob('*.md'):
            text=p.read_text();self.assertNotIn('npx @tyroneross/claude-code-debugger',text);self.assertNotIn('Apply documented fix directly',text)

if __name__=='__main__':unittest.main()
