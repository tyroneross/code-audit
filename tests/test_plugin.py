"""Integration checks at the combined package boundary; no network."""
from pathlib import Path
import json, os, re, select, shutil, subprocess, tempfile, unittest
ROOT=Path(__file__).resolve().parents[1]

class Package(unittest.TestCase):
    def test_manifests_share_identity_and_resources(self):
        manifests=[json.loads((ROOT/p).read_text()) for p in ['plugin.json','.claude-plugin/plugin.json','.codex-plugin/plugin.json']]
        self.assertEqual({m['name'] for m in manifests},{'code-audit'})
        self.assertEqual(len({m['version'] for m in manifests}),1)
        self.assertFalse((ROOT/'hooks').exists())
        self.assertNotIn('postinstall',json.loads((ROOT/'runtime/debugger/package.json').read_text())['scripts'])
        servers=json.loads((ROOT/'mcp.json').read_text())['mcpServers']
        legacy=json.loads((ROOT/'.mcp.json').read_text())['mcpServers']
        self.assertEqual(servers['code-audit-debugger']['args'],legacy['code-audit-debugger']['args'])
        self.assertEqual(servers['code-audit-debugger']['type'],'stdio')

    def test_packaged_markdown_links_are_local_and_present(self):
        missing=[]
        for base in ['skills','research','docs','evals']:
            for p in (ROOT/base).rglob('*.md'):
                targets = re.findall(r'\]\(([^\s)]+)\)',p.read_text())
                targets += re.findall(r'`((?:references/|\.\./)[^`\s<>*]+\.md)`', p.read_text())
                for target in targets:
                    if target.startswith(('https:','http:','mailto:','#')):continue
                    dest=(p.parent/target.split('#')[0]).resolve()
                    if not dest.is_relative_to(ROOT) or not dest.exists():missing.append(f'{p.relative_to(ROOT)} -> {target}')
        self.assertEqual(missing,[])

    def test_relocated_mcp_memory_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);plugin=folder/'installed';project=folder/'project';project.mkdir()
            shutil.copytree(ROOT/'runtime/debugger/dist',plugin/'runtime/debugger/dist')
            shutil.copytree(ROOT/'scripts',plugin/'scripts')
            env={k:v for k,v in os.environ.items() if not k.startswith('CLAUDE_MEMORY_')}
            env['CLAUDE_MEMORY_PATH']=str(project/'memory');env['CLAUDE_MEMORY_MODE']='local'
            # Ten seconds is a conservative assumption for local startup/I/O; no remote calls.
            with (folder/'stderr').open('w') as err:
                proc=subprocess.Popen(['node',str(plugin/'scripts/debugger-server.cjs')],cwd=project,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=err,text=True,bufsize=1)
                seq=0
                def rpc(method,params=None):
                    nonlocal seq
                    seq+=1;proc.stdin.write(json.dumps({'jsonrpc':'2.0','id':seq,'method':method,'params':params or {}})+'\n');proc.stdin.flush()
                    if not select.select([proc.stdout],[],[],10)[0]:self.fail(f'Local MCP response unavailable: {method}')
                    msg=json.loads(proc.stdout.readline());self.assertEqual(msg['id'],seq);self.assertNotIn('error',msg);return msg['result']
                def tool(name,args=None):
                    result=rpc('tools/call',{'name':name,'arguments':args or {}});self.assertFalse(result.get('isError'),result);return '\n'.join(c.get('text','') for c in result['content'])
                try:
                    self.assertIn('serverInfo',rpc('initialize',{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'package-test','version':'1'}}))
                    names={t['name'] for t in rpc('tools/list')['tools']}
                    self.assertEqual(names,{'search','store','detail','status','list','patterns','outcome','read_logs'})
                    symptom='Duplicate checkout receipts after lost acknowledgement'
                    self.assertIn('NO_MATCH',tool('search',{'symptom':symptom}))
                    stored=tool('store',{'symptom':symptom,'root_cause':'Gateway regenerated logical identity during transport retries, creating repeated effects.','fix':'Keep one identity across attempts; deterministic regression checks passed.','category':'logic','tags':['checkout','duplicate']})
                    incident=re.search(r'INC_[\w-]+',stored).group()
                    self.assertIn(symptom,tool('detail',{'id':incident}))
                    self.assertIn('INC_',tool('search',{'symptom':symptom}))
                    tool('outcome',{'incident_id':incident,'result':'worked','notes':'Synthetic roundtrip only; not production acceptance.'})
                    self.assertIn(str(project),tool('status'))
                    invalidated=tool('store',{
                        'symptom':f'Superseded {incident}: {symptom}',
                        'root_cause':f'The assumptions behind {incident} changed in this synthetic fixture.',
                        'fix':f'Do not reuse {incident}; inspect the new contract. Invalidation record, not a performed repair.',
                        'category':'logic','tags':['invalidation',incident]})
                    invalidation_id=re.search(r'INC_[\w-]+',invalidated).group()
                    self.assertIn(invalidation_id,tool('search',{'symptom':incident}))
                    self.assertIn(f'Do not reuse {incident}',tool('detail',{'id':invalidation_id}))
                    self.assertIn('logic',tool('list'))
                    self.assertTrue(list((project/'memory').rglob('*.json')))
                    self.assertFalse((plugin/'.claude').exists())
                finally:
                    proc.stdin.close()
                    try:proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:proc.terminate();proc.wait(timeout=5)
                    proc.stdout.close()
                self.assertEqual(proc.returncode,0,(folder/'stderr').read_text())

if __name__=='__main__':unittest.main()
