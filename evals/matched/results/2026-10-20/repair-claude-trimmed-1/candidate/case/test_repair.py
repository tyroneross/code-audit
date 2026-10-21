import json,os,unittest
from policy import Policy
from simulator import Clock,Provider
from gateway import Gateway
from checkout import Checkout

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),"profile.json")) as f:
    PROFILE=json.load(f)

def build(steps=(),profile=PROFILE,max_attempts=3):
    clock=Clock();provider=Provider(clock,steps)
    return clock,provider,Checkout(Gateway(provider,Policy(profile)),clock,max_attempts)

class Repair(unittest.TestCase):
    def test_lost_ack_retry_reuses_identity_single_charge(self):
        clock,provider,co=build([(0.01,True)])
        result=co.execute("op",{"amount":5})
        self.assertEqual(result,{"receipt":"receipt-1","amount":5})
        self.assertEqual(len(provider.charges),1)
        self.assertEqual({c["operation_id"] for c in provider.calls},{"op"})

    def test_caller_repeat_after_uncertain_response_no_second_charge(self):
        clock,provider,co=build([(0.01,True)],max_attempts=1)
        with self.assertRaises(TimeoutError):co.execute("op",{"amount":5})
        self.assertEqual(co.execute("op",{"amount":5}),{"receipt":"receipt-1","amount":5})
        self.assertEqual(len(provider.charges),1)

    def test_different_id_is_new_action(self):
        clock,provider,co=build()
        co.execute("a",{"amount":1});co.execute("b",{"amount":1})
        self.assertEqual(len(provider.charges),2)

    def test_reused_id_different_payload(self):
        clock,provider,co=build()
        co.execute("a",{"amount":1})
        with self.assertRaises(ValueError):co.execute("a",{"amount":2})
        self.assertEqual(len(provider.charges),1)

    def test_cold_start_succeeds_first_attempt(self):
        clock,provider,co=build([(0.30,False)])
        self.assertEqual(co.execute("cold",{"amount":3})["amount"],3)
        self.assertEqual(len(provider.calls),1)

    def test_profile_drives_limit(self):
        self.assertAlmostEqual(Policy(PROFILE).per_attempt(),0.32)
        changed=dict(PROFILE,cold_p99=0.60)
        self.assertAlmostEqual(Policy(changed).per_attempt(),0.62)
        self.assertEqual(Policy(assumed_timeout=0.7).per_attempt(),0.7)

    def test_remaining_caps_and_exhausted_refuses(self):
        self.assertAlmostEqual(Policy(PROFILE).per_attempt(remaining=0.1),0.1)
        for r in (0,-1):
            with self.assertRaises(TimeoutError):Policy(PROFILE).per_attempt(remaining=r)

    def test_deadline_respected(self):
        clock,provider,co=build([(5.0,False)]*5)
        with self.assertRaises(TimeoutError):co.execute("slow",{"amount":1},total_timeout=0.5)
        self.assertLessEqual(clock.now,0.5+1e-9)

    def test_attempts_bounded_no_hidden_retries(self):
        clock,provider,co=build([(5.0,False)]*10,max_attempts=2)
        with self.assertRaises(TimeoutError):co.execute("slow",{"amount":1},total_timeout=10)
        self.assertEqual(len(provider.calls),2)

    def test_zero_budget_starts_no_work(self):
        clock,provider,co=build()
        with self.assertRaises(TimeoutError):co.execute("z",{"amount":1},total_timeout=0)
        self.assertEqual(provider.calls,[])

    def test_standalone_submit_one_identity_per_invocation(self):
        clock=Clock();provider=Provider(clock,[(0.01,True)])
        gw=Gateway(provider,Policy(PROFILE))
        with self.assertRaises(TimeoutError):gw.submit({"amount":1})
        self.assertEqual(len(provider.calls),1)
        gw.submit({"amount":1})
        self.assertEqual(len(provider.charges),2)

if __name__=="__main__":unittest.main()
