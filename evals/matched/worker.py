"""Untrusted-candidate process for the bounded timeout/retry fixture; never owns test results."""
import importlib
import json
import sys
import os

protocol_in=os.fdopen(os.dup(0))
protocol_out=os.fdopen(os.dup(1),'w',buffering=1)
with open(os.devnull,'r+') as null:
    os.dup2(null.fileno(),0);os.dup2(null.fileno(),1)
sys.stdin=open(os.devnull);sys.stdout=open(os.devnull,'w')

sys.path.insert(0,sys.argv[1])
ERRORS={'TimeoutError':TimeoutError,'ValueError':ValueError,'TypeError':TypeError,'RuntimeError':RuntimeError}
def callback(method,handle,*args,**kwargs):
    print(json.dumps({'callback':method,'handle':handle,'args':args,'kwargs':kwargs}),flush=True,file=protocol_out)
    response=json.loads(protocol_in.readline())
    if 'error' in response:raise ERRORS.get(response['error'],RuntimeError)(response.get('message','remote error'))
    return response.get('value')
class Clock:
    def __init__(self,handle):self.handle=handle
    @property
    def now(self):return callback('clock.now',self.handle)
    def advance(self,seconds):raise RuntimeError('Clock advances only through the trusted provider')
class Provider:
    def __init__(self,handle,clock):self.handle=handle;self.clock=Clock(clock)
    def send(self,*args,**kwargs):return callback('provider.send',self.handle,*args,**kwargs)
    @property
    def receipts(self):return callback('provider.receipts',self.handle)
    @property
    def calls(self):return callback('provider.calls',self.handle)
    @property
    def charges(self):return callback('provider.charges',self.handle)
objects={}
for line in protocol_in:
    try:
        request=json.loads(line);op=request['op']
        if op=='policy':value=importlib.import_module('policy').Policy(*request['args'],**request['kwargs'])
        elif op=='gateway':value=importlib.import_module('gateway').Gateway(Provider(request['provider'],request['clock']),objects[request['policy']])
        elif op=='checkout':value=importlib.import_module('checkout').Checkout(objects[request['gateway']],Clock(request['clock']),**request['kwargs'])
        elif op=='call':
            if request['method'] not in ['per_attempt','submit','execute']:raise ValueError('unsupported method')
            value=getattr(objects[request['handle']],request['method'])(*request['args'],**request['kwargs'])
            print(json.dumps({'value':value}),flush=True,file=protocol_out);continue
        else:raise ValueError('unsupported operation')
        handle=str(len(objects));objects[handle]=value;print(json.dumps({'value':handle}),flush=True,file=protocol_out)
    except Exception as error:print(json.dumps({'error':type(error).__name__,'message':str(error)}),flush=True,file=protocol_out)
