"""Trusted parent oracle adapter. Candidate code runs only across the sandboxed JSON boundary."""
import importlib.util
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
import time

verification_deadline=float('inf')
from isolation import sandbox_command

sys.dont_write_bytecode=True

class HarnessFailure(Exception):pass

faults=[]

class Remote:
    def __init__(self,candidate,pristine,protected):
        self.temp=tempfile.TemporaryDirectory(prefix='code-audit-worker-',dir='/private/tmp');root=Path(self.temp.name).resolve()
        shutil.copytree(candidate/'case',root/'case');shutil.copyfile(Path(__file__).with_name('worker.py'),root/'worker.py')
        env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','TMPDIR':str(root)}
        command=sandbox_command([sys.executable,'-u',str(root/'worker.py'),str(root/'case')],root,protected)
        self.process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,bufsize=1,env=env)
        self.handles={};self.buffer=b'';self.failed=False;self.closed=False
    def bind(self,value):
        handle=str(id(value));self.handles[handle]=value;return handle
    def fail(self,message):
        self.failed=True;self.process.kill();faults.append({'test':getattr(self,'test_id',None),'kind':'HarnessFailure','reason':message});raise HarnessFailure(message)
    def send(self,value):
        try:self.process.stdin.write(json.dumps(value)+'\n');self.process.stdin.flush()
        except (TypeError,ValueError,OSError) as error:self.fail('candidate protocol write/serialization failure: '+type(error).__name__)
    def ask(self,request):
        if self.failed:raise HarnessFailure('candidate worker unavailable after protocol failure')
        if time.monotonic()>=verification_deadline:self.fail('verification time budget exhausted')
        self.send(request)
        for _ in range(10000):
            if time.monotonic()>=verification_deadline:self.fail('verification time budget exhausted')
            while b'\n' not in self.buffer:
                if not select.select([self.process.stdout],[],[],max(0,min(5,verification_deadline-time.monotonic())))[0]:
                    self.fail('candidate RPC timeout')
                chunk=os.read(self.process.stdout.fileno(),65536)
                if not chunk:self.fail('candidate worker exited without a result')
                self.buffer+=chunk
                if len(self.buffer)>1048576:self.fail('candidate protocol budget exceeded')
            line,self.buffer=self.buffer.split(b'\n',1)
            try:result=json.loads(line)
            except (ValueError,UnicodeDecodeError):self.fail('invalid candidate protocol JSON')
            if not isinstance(result,dict):self.fail('candidate protocol row must be an object')
            if 'callback' not in result:
                if 'error' in result:raise {'TimeoutError':TimeoutError,'ValueError':ValueError,'TypeError':TypeError}.get(result['error'],RuntimeError)(result.get('message','candidate error'))
                return result.get('value')
            try:
                target=self.handles[result['handle']];args=result.get('args',[]);kwargs=result.get('kwargs',{});method=result['callback']
                if method=='provider.send':value=target.send(*args,**kwargs)
                elif method=='clock.now':value=target.now
                elif method in ['provider.receipts','provider.calls','provider.charges']:value=getattr(target,method.split('.')[1])
                else:raise ValueError('unsupported candidate callback')
                response={'value':value}
            except Exception as error:response={'error':type(error).__name__,'message':str(error)}
            self.send(response)
        self.fail('candidate callback budget exceeded')
    def close(self):
        if self.closed:return
        self.closed=True
        try:
            self.process.kill();self.process.wait()
        finally:
            try:
                for stream in [self.process.stdin,self.process.stdout]:
                    try:stream.close()
                    except (OSError,ValueError):pass
            finally:self.temp.cleanup()

def main():
    global verification_deadline
    budget=float(sys.argv[6]) if len(sys.argv)>6 else 20
    if not 0<budget<=20:raise ValueError('verification budget must be within (0,20] seconds')
    verification_deadline=time.monotonic()+budget
    verifier,candidate,receipt,pristine=map(Path,sys.argv[1:5]);candidate=candidate.resolve()
    protected=json.loads(sys.argv[5]) if len(sys.argv)>5 else []
    remote=None
    original_start=unittest.TextTestResult.startTest
    original_stop=unittest.TextTestResult.stopTest
    def start_test(result,test):
        nonlocal remote
        if remote is not None:remote.close()
        remote=Remote(candidate,pristine,[verifier.parent,Path(__file__).parent,*protected]);remote.test_id=test.id()
        original_start(result,test)
    def stop_test(result,test):
        original_stop(result,test)
        rows=getattr(result,'rows',[])
        receipt.write_text(json.dumps({'tests':len(rows),'passed':sum(r['status']=='pass' for r in rows),'cases':rows,'harness_faults':faults,'partial':True},indent=2))
    unittest.TextTestResult.startTest=start_test
    unittest.TextTestResult.stopTest=stop_test
    class Policy:
        def __init__(self,*args,**kwargs):self.handle=remote.ask({'op':'policy','args':args,'kwargs':kwargs})
        def per_attempt(self,*args,**kwargs):return remote.ask({'op':'call','handle':self.handle,'method':'per_attempt','args':args,'kwargs':kwargs})
    class Gateway:
        def __init__(self,provider,policy):
            self.provider=provider;self.policy=policy
            self.handle=remote.ask({'op':'gateway','provider':remote.bind(provider),'clock':remote.bind(provider.clock),'policy':policy.handle})
        def submit(self,*args,**kwargs):return remote.ask({'op':'call','handle':self.handle,'method':'submit','args':args,'kwargs':kwargs})
    class Checkout:
        def __init__(self,gateway,clock,**kwargs):self.handle=remote.ask({'op':'checkout','gateway':gateway.handle,'clock':remote.bind(clock),'kwargs':kwargs})
        def execute(self,*args,**kwargs):return remote.ask({'op':'call','handle':self.handle,'method':'execute','args':args,'kwargs':kwargs})
    for name,cls in [('policy',Policy),('gateway',Gateway),('checkout',Checkout)]:
        module=types.ModuleType(name);setattr(module,cls.__name__,cls);sys.modules[name]=module
    spec=importlib.util.spec_from_file_location('simulator',pristine/'case/simulator.py');sim=importlib.util.module_from_spec(spec);spec.loader.exec_module(sim);sys.modules['simulator']=sim
    sys.argv=[str(verifier),str(candidate),str(receipt)]
    try:exec(compile(verifier.read_bytes(),str(verifier),'exec'),{'__name__':'__main__'})
    finally:
        unittest.TextTestResult.startTest=original_start
        unittest.TextTestResult.stopTest=original_stop
        if remote is not None:remote.close()
        if receipt.exists():
            data=json.loads(receipt.read_text());data['harness_faults']=faults;receipt.write_text(json.dumps(data,indent=2))
if __name__=='__main__':main()
