"""Private behavioral oracle; no network or real waiting."""
from pathlib import Path
import importlib
import json
import random
import sys
import unittest

ARM=Path(sys.argv[1]).resolve();OUTPUT=Path(sys.argv[2]).resolve()
sys.path.insert(0,str(ARM/'case'))
Policy=importlib.import_module('policy').Policy
sim=importlib.import_module('simulator')
Gateway=importlib.import_module('gateway').Gateway
Checkout=importlib.import_module('checkout').Checkout
PROFILE={'warm_p99':0.08,'cold_p99':0.30,'network_allowance':0.02}

class Checks(unittest.TestCase):
    def make(self,steps=(),profile=PROFILE,attempts=3,start=0):
        clock=sim.Clock();clock.now=start
        provider=sim.Provider(clock,steps)
        policy=Policy(profile=profile)
        gateway=Gateway(provider,policy)
        return clock,provider,policy,gateway,Checkout(gateway,clock,max_attempts=attempts)

    def test_warm_success(self):
        clock,p,_,_,c=self.make()
        self.assertEqual(c.execute('op',{'amount':12}),{'receipt':'receipt-1','amount':12})
        self.assertEqual(len(p.charges),1)

    def test_ordinary_cold_completion(self):
        clock,p,_,_,c=self.make([(0.25,False)])
        self.assertEqual(c.execute('cold-variable',{'amount':7})['amount'],7)
        self.assertEqual(len(p.calls),1)
        self.assertEqual(len(p.charges),1)

    def test_lost_ack_same_effect(self):
        clock,p,_,_,c=self.make([(0.01,True),(0.01,False)])
        self.assertEqual(c.execute('identity-variable',{'amount':9})['receipt'],'receipt-1')
        self.assertEqual(len(p.calls),2)
        self.assertEqual(len(p.charges),1)
        self.assertEqual(len({r['operation_id'] for r in p.calls}),1)

    def test_repeat_with_fresh_wrappers(self):
        clock,p,policy,_,c=self.make()
        first=c.execute('repeat',{'amount':3})
        second=Checkout(Gateway(p,policy),clock).execute('repeat',{'amount':3})
        self.assertEqual(first,second)
        self.assertEqual(len(p.charges),1)

    def test_distinct_operations(self):
        clock,p,_,_,c=self.make()
        first=c.execute('first',{'amount':3});second=c.execute('second',{'amount':3})
        self.assertNotEqual(first['receipt'],second['receipt'])
        self.assertEqual(len(p.charges),2)

    def test_identity_payload_conflict(self):
        clock,p,_,_,c=self.make()
        c.execute('same',{'amount':3})
        with self.assertRaises(ValueError):c.execute('same',{'amount':4})
        self.assertEqual(len(p.charges),1)

    def test_total_budget_caps_attempt(self):
        clock,p,_,_,c=self.make([(1.0,False)]*10)
        with self.assertRaises(TimeoutError):c.execute('budget',{'amount':3},total_timeout=0.07)
        self.assertLessEqual(clock.now,0.07+1e-12)
        self.assertTrue(p.calls)
        self.assertTrue(all(r['timeout']<=0.07+1e-12 for r in p.calls))

    def test_exhausted_budget_starts_nothing(self):
        for budget in [0,-1]:
            clock,p,_,_,c=self.make()
            with self.assertRaises((TimeoutError,ValueError)):c.execute('empty',{'amount':2},total_timeout=budget)
            self.assertEqual(p.calls,[])
            self.assertEqual(p.charges,[])

    def test_attempt_budget_not_multiplied(self):
        for attempts in [1,2,4]:
            clock,p,_,_,c=self.make([(0.01,True)]*20,attempts=attempts)
            with self.assertRaises(TimeoutError):c.execute('attempts',{'amount':2},total_timeout=2.0)
            self.assertGreaterEqual(len(p.calls),1)
            self.assertLessEqual(len(p.calls),attempts)
            self.assertEqual(len(p.charges),1)

    def test_gateway_is_one_attempt(self):
        clock,p,_,gateway,_=self.make([(0.01,True)]*4)
        with self.assertRaises(TimeoutError):gateway.submit({'amount':2},operation_id='single')
        self.assertEqual(len(p.calls),1)

    def test_gateway_honors_explicit_timeout(self):
        clock,p,_,gateway,_=self.make([(1.0,False)]*4)
        with self.assertRaises(TimeoutError):gateway.submit({'amount':2},operation_id='single',timeout=0.07)
        self.assertEqual(len(p.calls),1)
        self.assertAlmostEqual(clock.now,0.07)

    def test_gateway_default_identity_per_invocation(self):
        clock,p,_,gateway,_=self.make()
        first=gateway.submit({'amount':2});second=gateway.submit({'amount':2})
        self.assertNotEqual(first['receipt'],second['receipt'])
        self.assertEqual(len(p.charges),2)

    def test_profile_informs_limit(self):
        low=Policy(profile={'warm_p99':0.03,'cold_p99':0.12,'network_allowance':0.02}).per_attempt(remaining=3)
        high=Policy(profile={'warm_p99':0.03,'cold_p99':0.70,'network_allowance':0.02}).per_attempt(remaining=3)
        self.assertGreaterEqual(low,0.14-1e-12)
        self.assertGreaterEqual(high,0.72-1e-12)
        self.assertGreater(high,low)
        self.assertLessEqual(high,3)

    def test_explicit_assumption_without_data(self):
        policy=Policy(profile=None,assumed_timeout=0.47)
        self.assertAlmostEqual(policy.per_attempt(),0.47)
        self.assertAlmostEqual(policy.per_attempt(remaining=0.02),0.02)

    def test_remaining_limit(self):
        policy=Policy(profile=PROFILE)
        self.assertGreater(policy.per_attempt(remaining=0.03),0)
        self.assertLessEqual(policy.per_attempt(remaining=0.03),0.03)
        for value in [0,-1]:
            with self.assertRaises((TimeoutError,ValueError)):policy.per_attempt(remaining=value)

    def test_expiry_does_not_erase_uncertain_effect(self):
        clock,p,_,_,c=self.make([(1.0,False)]*5)
        with self.assertRaises(TimeoutError):c.execute('unknown',{'amount':6},total_timeout=0.02)
        self.assertEqual(len(p.charges),1)

    def test_clock_offset(self):
        clock,p,_,_,c=self.make([(1.0,False)]*5,start=10)
        with self.assertRaises(TimeoutError):c.execute('offset',{'amount':6},total_timeout=0.09)
        self.assertLessEqual(clock.now,10.09+1e-12)

    def test_generated_profile_and_identity_cases(self):
        rng=random.Random(31)
        for i in range(12):
            cold=rng.uniform(0.08,0.5)
            profile={'warm_p99':cold/4,'cold_p99':cold,'network_allowance':0.03}
            clock,p,_,_,c=self.make([(cold,False)],profile=profile)
            key=f'generated-{i}-{rng.randrange(10000)}'
            first=c.execute(key,{'amount':i},total_timeout=2)
            second=c.execute(key,{'amount':i},total_timeout=2)
            self.assertEqual(first,second)
            self.assertEqual(len(p.charges),1)
            self.assertGreaterEqual(len(p.calls),1)
            self.assertLessEqual(len(p.calls),2)

class Receipt(unittest.TextTestResult):
    def __init__(self,*args,**kwargs):super().__init__(*args,**kwargs);self.rows=[]
    def addSuccess(self,test):super().addSuccess(test);self.rows.append({'test':test.id(),'status':'pass'})
    def addFailure(self,test,err):super().addFailure(test,err);self.rows.append({'test':test.id(),'status':'fail','detail':self._exc_info_to_string(err,test)})
    def addError(self,test,err):super().addError(test,err);self.rows.append({'test':test.id(),'status':'error','detail':self._exc_info_to_string(err,test)})

result=unittest.TextTestRunner(verbosity=1,resultclass=Receipt).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks))
receipt={'arm':str(ARM),'tests':result.testsRun,'passed':sum(r['status']=='pass' for r in result.rows),'cases':result.rows}
OUTPUT.write_text(json.dumps(receipt,indent=2))
print(json.dumps({k:v for k,v in receipt.items() if k!='cases'}))
sys.exit(not result.wasSuccessful())
