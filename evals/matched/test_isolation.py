import importlib.util,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
from isolation import check_boundary
import repair

class Isolation(unittest.TestCase):
    def test_kernel_denies_foreign_reads_and_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            result=check_boundary(Path(folder),Path(__file__).resolve())
            self.assertEqual(result,{'own_read':'allowed','protected_read':'denied','foreign_temp_read':'denied','outside_write':'denied'})

    def test_baseline_comparison_uses_frozen_bytes(self):
        baseline,_=repair.snapshot()
        with tempfile.TemporaryDirectory() as folder:
            candidate=Path(folder);repair.materialize(baseline,candidate)
            frozen={**baseline,'case/simulator.py':b'pristine snapshot'}
            self.assertEqual(repair.protected_changes(candidate,frozen),['case/simulator.py'])

    def test_verifier_timeout_is_a_retained_row(self):
        import subprocess
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            # First call is the mocked host, second the parent verifier.
            output='{"type":"turn.completed","usage":{}}\n'
            with patch.object(repair,'check_boundary',return_value={'test':'mocked'}),patch.object(repair,'sandbox_command',side_effect=lambda command,*args:command),patch.object(repair,'run_bounded',side_effect=[subprocess.CompletedProcess([],0,output,''),subprocess.TimeoutExpired(['verifier'],30)]):
                meta=repair.run('codex','none',1,Path(folder),'fixture',1)
            self.assertEqual(meta['verification_status'],'timeout');self.assertTrue((Path(folder)/'repair-codex-none-1/meta.json').exists())


class UnsafeCandidates(unittest.TestCase):
    def test_links_and_special_files_are_rejected_before_parent_reads(self):
        import os
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'private';source.write_text('protected')
            candidate=root/'candidate';candidate.mkdir();(candidate/'checkout.py').symlink_to(source)
            with self.assertRaises(ValueError):repair.candidate_bytes(candidate)
            (candidate/'checkout.py').unlink();os.link(source,candidate/'checkout.py')
            with self.assertRaises(ValueError):repair.candidate_bytes(candidate)
            (candidate/'checkout.py').unlink();os.mkfifo(candidate/'pipe')
            with self.assertRaises(ValueError):repair.candidate_bytes(candidate)


class ParentOracle(unittest.TestCase):
    def verify(self,candidate,receipt,pristine):
        import subprocess
        result=subprocess.run([sys.executable,str(Path(__file__).with_name('bridge.py')),str(repair.VERIFIER),str(candidate),str(receipt),str(pristine),__import__('json').dumps([str(repair.ROOT.parents[1])])],text=True,capture_output=True,timeout=30)
        return result,__import__('json').loads(receipt.read_text())

    def test_parent_boundary_preserves_known_baseline_and_repair(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            baseline,row=self.verify(repair.BASELINE,root/'baseline.json',repair.BASELINE)
            fixed,done=self.verify(repair.ROOT.parent/'timeout-retry/repaired-example',root/'fixed.json',repair.BASELINE)
            self.assertNotEqual(baseline.returncode,0);self.assertEqual(row['passed'],4)
            self.assertEqual(fixed.returncode,0,fixed.stderr);self.assertEqual(done['passed'],18)

    def test_candidate_cannot_forge_parent_receipt_or_exit_parent(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);candidate=root/'candidate';repair.materialize(repair.snapshot()[0],candidate)
            receipt=root/'receipt.json'
            (candidate/'case/checkout.py').write_text('import os\nfrom pathlib import Path\nPath('+repr(str(receipt))+').write_text(\'{"tests":18,"passed":18,"cases":[]}\')\nos._exit(0)\n')
            result,data=self.verify(candidate,receipt,repair.BASELINE)
            self.assertNotEqual(result.returncode,0);self.assertNotEqual(data['passed'],18);self.assertEqual(len(data['cases']),18)

class ProcessCleanup(unittest.TestCase):
    def test_owned_background_process_is_stopped(self):
        import subprocess,time,os
        from isolation import run_bounded
        result=run_bounded(['/bin/sh','-c','sleep 1000 >/dev/null 2>&1 & echo $!'],text=True,timeout=5)
        pid=int(result.stdout.strip())
        for _ in range(20):
            state=subprocess.run(['ps','-p',str(pid),'-o','stat='],text=True,capture_output=True).stdout.strip()
            if not state or state.startswith('Z'):break
            time.sleep(.02)
        self.assertTrue(not state or state.startswith('Z'),state)



class ClosureRegressions(unittest.TestCase):
    def test_worker_print_does_not_corrupt_protocol(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);candidate=root/'candidate'
            files={p.relative_to(repair.ROOT.parent/'timeout-retry/repaired-example').as_posix():p.read_bytes() for p in (repair.ROOT.parent/'timeout-retry/repaired-example').rglob('*') if p.is_file() and '__pycache__' not in p.parts}
            repair.materialize(files,candidate)
            p=candidate/'case/gateway.py';p.write_text("print('candidate import noise')\n"+p.read_text())
            # Mirror repair.run's TMPDIR inside its protected private verifier tree.
            import subprocess,os,json
            result=subprocess.run([sys.executable,str(Path(__file__).with_name('bridge.py')),str(repair.VERIFIER),str(candidate),str(root/'result.json'),str(repair.BASELINE),json.dumps([str(root),str(repair.ROOT.parents[1])])],env={**os.environ,'TMPDIR':str(root)},text=True,capture_output=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(json.loads((root/'result.json').read_text())['passed'],18)

    def test_stalled_rpc_is_harness_failure_and_stops_worker(self):
        from bridge import Remote,HarnessFailure
        import json
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);repair.materialize(repair.snapshot()[0],root/'candidate')
            remote=Remote(root/'candidate',repair.BASELINE,[])
            try:
                with patch('bridge.select.select',return_value=([],[],[])):
                    with self.assertRaises(HarnessFailure):remote.ask({'op':'policy','args':[],'kwargs':{}})
                with self.assertRaises(HarnessFailure):remote.ask({})
            finally:remote.close()

    def test_protected_comparison_uses_exact_saved_snapshot(self):
        baseline,_=repair.snapshot();files=dict(baseline);files['case/simulator.py']=b'modified'
        self.assertEqual(repair.protected_changes(files,baseline),['case/simulator.py'])

    def test_host_timeout_is_distinct(self):
        import subprocess
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(repair,'check_boundary',return_value={}),patch.object(repair,'sandbox_command',side_effect=lambda command,*args:command),patch.object(repair,'run_bounded',side_effect=[subprocess.TimeoutExpired(['host'],1),subprocess.TimeoutExpired(['verifier'],30)]):
                meta=repair.run('codex','none',1,Path(folder),'fixture',1)
            self.assertEqual(meta['status'],'host_timeout')

    def test_repair_runner_verifies_saved_repair_in_its_private_layout(self):
        import subprocess,json
        from unittest.mock import patch
        real=repair.run_bounded
        def execute(command,**kwargs):
            if '--ignore-user-config' not in command:return real(command,**kwargs)
            candidate=Path(kwargs['cwd'])
            for name in ['checkout.py','gateway.py','policy.py']:
                (candidate/'case'/name).write_bytes((repair.ROOT.parent/'timeout-retry/repaired-example/case'/name).read_bytes())
            return subprocess.CompletedProcess(command,0,'{"type":"turn.completed","usage":{}}\n','')
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(repair,'run_bounded',side_effect=execute):
                meta=repair.run('codex','none',1,Path(folder),'fixture',1)
            self.assertEqual(meta['verification_status'],'passed',meta);self.assertEqual(meta['verification']['passed'],18);self.assertEqual(meta['protected_changes'],[])

    def test_timeout_retains_partial_output(self):
        import subprocess
        from isolation import run_bounded
        with self.assertRaises(subprocess.TimeoutExpired) as caught:
            run_bounded([sys.executable,'-u','-c',"print('saved row');import time;time.sleep(10)"],text=False,timeout=.1)
        self.assertIn(b'saved row',caught.exception.stdout)

    def test_protocol_fault_kills_worker_and_cannot_be_candidate_value_error(self):
        from bridge import Remote,HarnessFailure
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);repair.materialize(repair.snapshot()[0],root/'candidate')
            remote=Remote(root/'candidate',repair.BASELINE,[])
            try:
                remote.buffer=b'[]\n'
                with self.assertRaises(HarnessFailure):remote.ask({'op':'policy','args':[],'kwargs':{}})
                with self.assertRaises(HarnessFailure):remote.ask({})
            finally:remote.close()

    def test_bad_host_bytes_retained_and_integrity_present_on_early_failure(self):
        import subprocess
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(repair,'check_boundary',return_value={}),patch.object(repair,'sandbox_command',side_effect=lambda command,*args:command),patch.object(repair,'run_bounded',side_effect=[subprocess.CompletedProcess([],0,b'\xffbad\n',b''),subprocess.TimeoutExpired(['verifier'],30)]):
                meta=repair.run('codex','none',1,Path(folder),'fixture',1)
            self.assertEqual(meta['status'],'host_protocol_error');self.assertEqual((Path(folder)/'repair-codex-none-1/host-output.jsonl').read_bytes(),b'\xffbad\n')
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(repair,'check_boundary',side_effect=RuntimeError('canary')):
                meta=repair.run('codex','none',1,Path(folder),'fixture',1)
            self.assertTrue(meta['source_integrity_unchanged'])

    def test_descriptor_walk_rejects_directory_swap(self):
        import os
        from unittest.mock import patch
        real=os.open
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);candidate=root/'candidate';(candidate/'case').mkdir(parents=True);(candidate/'case/public').write_text('local');secret=root/'outside';secret.mkdir();(secret/'secret').write_text('private')
            def swap(path,*args,**kwargs):
                if path=='case':
                    (candidate/'case').rename(candidate/'old');(candidate/'case').symlink_to(secret)
                return real(path,*args,**kwargs)
            with patch('repair.os.open',side_effect=swap):
                with self.assertRaises(OSError):repair.candidate_bytes(candidate)

    def test_escaped_pipe_drain_is_bounded(self):
        import subprocess,os,signal,time,json
        from isolation import run_bounded
        with tempfile.TemporaryDirectory() as folder:
            pidfile=Path(folder)/'child.pid'
            code="import os,time;pid=os.fork();"+"\nif pid==0:\n os.setsid();time.sleep(20)\nelse:\n open("+repr(str(pidfile))+",'w').write(str(pid));os.write(1,b'\\xffsaved');time.sleep(20)"
            start=time.monotonic()
            try:
                with self.assertRaises(subprocess.TimeoutExpired) as caught:run_bounded([sys.executable,'-u','-c',code],text=False,timeout=.3)
                self.assertLess(time.monotonic()-start,2);self.assertIn(b'\xffsaved',caught.exception.stdout);self.assertTrue(caught.exception.escaped_pipe)
            finally:
                if pidfile.exists():
                    try:os.kill(int(pidfile.read_text()),signal.SIGKILL)
                    except ProcessLookupError:pass

    def test_candidate_artifact_oserror_is_contamination(self):
        import subprocess
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(repair,'check_boundary',return_value={}),patch.object(repair,'sandbox_command',side_effect=lambda command,*args:command),patch.object(repair,'run_bounded',return_value=subprocess.CompletedProcess([],0,b'{"type":"turn.completed"}\n',b'')),patch.object(repair,'candidate_bytes',side_effect=PermissionError('candidate mode')):
                meta=repair.run('codex','none',1,Path(folder),'fixture',1)
            self.assertEqual(meta['status'],'contaminated');self.assertTrue(meta['source_integrity_unchanged'])

    def test_serialization_fault_poisoned_and_single_stall_does_not_shift_rows(self):
        from bridge import Remote,HarnessFailure
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);candidate=root/'candidate';repair.materialize(repair.snapshot()[0],candidate);remote=Remote(candidate,repair.BASELINE,[])
            try:
                with self.assertRaises(HarnessFailure):remote.send(object())
                with self.assertRaises(HarnessFailure):remote.ask({})
            finally:remote.close()
            fixed=repair.ROOT.parent/'timeout-retry/repaired-example'
            for name in ['checkout.py','gateway.py','policy.py']:(candidate/'case'/name).write_bytes((fixed/'case'/name).read_bytes())
            p=candidate/'case/checkout.py';p.write_text(p.read_text().replace('        deadline=',"        if operation_id=='offset':\n            import time;time.sleep(6)\n        deadline="))
            result,row=ParentOracle().verify(candidate,root/'receipt.json',repair.BASELINE)
            self.assertEqual(row['passed'],17);self.assertEqual(len(row['cases']),18);self.assertEqual(len(row['harness_faults']),1);self.assertIn('clock_offset',row['harness_faults'][0]['test'])

    def test_global_verifier_budget_keeps_all_rows(self):
        import subprocess,json
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);candidate=root/'candidate';repair.materialize(repair.snapshot()[0],candidate)
            p=candidate/'case/policy.py';p.write_text(p.read_text().replace('    def per_attempt(', '    def per_attempt(').replace('        return ', '        import time;time.sleep(4)\n        return '))
            receipt=root/'receipt.json'
            result=subprocess.run([sys.executable,str(Path(__file__).with_name('bridge.py')),str(repair.VERIFIER),str(candidate),str(receipt),str(repair.BASELINE),'[]','.3'],text=True,capture_output=True,timeout=30)
            data=json.loads(receipt.read_text());self.assertEqual(data['tests'],18);self.assertEqual(len(data['cases']),18);self.assertTrue(data['harness_faults']);self.assertNotEqual(result.returncode,0)

    def test_close_flush_failure_is_best_effort_and_idempotent(self):
        from bridge import Remote
        from unittest.mock import Mock
        remote=Remote.__new__(Remote);remote.closed=False;remote.process=Mock();remote.temp=Mock()
        remote.process.stdin.close.side_effect=BrokenPipeError('flush')
        remote.close();remote.close();remote.temp.cleanup.assert_called_once();remote.process.stdout.close.assert_called_once()

    def test_outer_verifier_timeout_preserves_partial_parent_rows(self):
        import subprocess,json
        from unittest.mock import patch
        def execute(command,**kwargs):
            if '--ignore-user-config' in command:return subprocess.CompletedProcess(command,0,b'{"type":"turn.completed"}\n',b'')
            Path(command[4]).write_text(json.dumps({'tests':1,'passed':1,'cases':[{'test':'completed','status':'pass'}],'partial':True}))
            raise subprocess.TimeoutExpired(command,30)
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(repair,'check_boundary',return_value={}),patch.object(repair,'sandbox_command',side_effect=lambda command,*args:command),patch.object(repair,'run_bounded',side_effect=execute):meta=repair.run('codex','none',1,Path(folder),'fixture',1)
            self.assertEqual(meta['verification_status'],'timeout');self.assertTrue(meta['verification_partial']);self.assertEqual(meta['verification']['tests'],1);self.assertTrue((Path(folder)/'repair-codex-none-1/verification.json').exists())

    def test_fifo_swap_cannot_block_parent_open(self):
        import os,time
        from unittest.mock import patch
        real=os.open
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'file.py').write_text('public')
            def swap(name,flags,*args,**kwargs):
                if name=='file.py':
                    self.assertTrue(flags & os.O_NONBLOCK);(root/'file.py').unlink();os.mkfifo(root/'file.py')
                return real(name,flags,*args,**kwargs)
            start=time.monotonic()
            with patch('repair.os.open',side_effect=swap):
                with self.assertRaises(ValueError):repair.candidate_bytes(root)
            self.assertLess(time.monotonic()-start,10)

if __name__=='__main__':unittest.main()
