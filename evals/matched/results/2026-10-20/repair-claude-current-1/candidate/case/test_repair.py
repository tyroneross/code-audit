import json,os,unittest
from policy import Policy
from simulator import Clock,Provider
from gateway import Gateway
from checkout import Checkout

HERE=os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE,"profile.json")) as f:PROFILE=json.load(f)

def build(steps=(),profile=PROFILE,max_attempts=3,**policy_kw):
    clock=Clock();provider=Provider(clock,steps)
    checkout=Checkout(Gateway(provider,Policy(profile,**policy_kw)),clock,max_attempts)
    return clock,provider,checkout

class LostResponse(unittest.TestCase):
    def test_lost_ack_retry_returns_same_receipt_one_charge(self):
        clock,provider,checkout=build([(0.01,True),(0.01,False)])
        result=checkout.execute("op-1",{"amount":5})
        self.assertEqual(result,{"receipt":"receipt-1","amount":5})
        self.assertEqual(len(provider.charges),1)
        self.assertEqual({c["operation_id"] for c in provider.calls},{"op-1"})

    def test_caller_repeat_after_uncertain_failure_does_not_charge_twice(self):
        clock,provider,checkout=build([(0.01,True)]*3,max_attempts=3)
        with self.assertRaises(TimeoutError):checkout.execute("op-2",{"amount":7})
        self.assertEqual(checkout.execute("op-2",{"amount":7}),{"receipt":"receipt-1","amount":7})
        self.assertEqual(len(provider.charges),1)

    def test_different_payload_same_id_raises_without_new_charge(self):
        clock,provider,checkout=build()
        checkout.execute("op-3",{"amount":1})
        with self.assertRaises(ValueError):checkout.execute("op-3",{"amount":2})
        self.assertEqual(len(provider.charges),1)

    def test_different_ids_are_distinct_actions(self):
        clock,provider,checkout=build()
        a=checkout.execute("a",{"amount":1});b=checkout.execute("b",{"amount":1})
        self.assertNotEqual(a["receipt"],b["receipt"])
        self.assertEqual(len(provider.charges),2)

    def test_standalone_submit_uses_one_identity_per_call(self):
        clock=Clock();provider=Provider(clock,[(0.01,True)])
        gateway=Gateway(provider,Policy(PROFILE))
        with self.assertRaises(TimeoutError):gateway.submit({"amount":3})
        self.assertEqual(len(provider.calls),1)  # no hidden retry
        gateway.submit({"amount":3})
        self.assertEqual(len({c["operation_id"] for c in provider.calls}),2)

class ColdStart(unittest.TestCase):
    def test_cold_first_call_succeeds_on_first_attempt(self):
        clock,provider,checkout=build([(0.30,False)])
        self.assertEqual(checkout.execute("cold",{"amount":9}),{"receipt":"receipt-1","amount":9})
        self.assertEqual(len(provider.calls),1)

    def test_limit_follows_profile(self):
        self.assertAlmostEqual(Policy(PROFILE).per_attempt(),0.32)
        slower=dict(PROFILE,cold_p99=0.6)
        self.assertAlmostEqual(Policy(slower).per_attempt(),0.62)

    def test_assumed_timeout_without_profile(self):
        self.assertEqual(Policy().per_attempt(),0.5)
        self.assertEqual(Policy(assumed_timeout=0.2).per_attempt(),0.2)

class Deadline(unittest.TestCase):
    def test_remaining_caps_limit_and_exhausted_budget_refuses(self):
        p=Policy(PROFILE)
        self.assertAlmostEqual(p.per_attempt(remaining=0.1),0.1)
        for r in (0,-1):
            with self.assertRaises(TimeoutError):p.per_attempt(remaining=r)

    def test_slow_provider_never_exceeds_total_timeout(self):
        for total in (0.05,0.32,0.5,1.0):
            clock,provider,checkout=build([(5.0,False)]*10,max_attempts=5)
            with self.assertRaises(TimeoutError):checkout.execute("slow",{"amount":1},total)
            self.assertLessEqual(clock.now,total+1e-9)
            self.assertLessEqual(len(provider.calls),5)
            self.assertTrue(all(c["timeout"]>0 for c in provider.calls))

    def test_attempt_limit_respected(self):
        for n in (1,2,4):
            clock,provider,checkout=build([(0.01,True)]*10,max_attempts=n)
            with self.assertRaises(TimeoutError):checkout.execute("x",{"amount":1},100)
            self.assertEqual(len(provider.calls),n)

    def test_zero_budget_starts_no_work(self):
        clock,provider,checkout=build()
        with self.assertRaises(TimeoutError):checkout.execute("z",{"amount":1},0)
        self.assertEqual(provider.calls,[])

if __name__=="__main__":unittest.main()
