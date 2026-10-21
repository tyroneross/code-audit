import json,os,unittest
from policy import Policy
from simulator import Clock,Provider
from gateway import Gateway
from checkout import Checkout

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),"profile.json")) as f:PROFILE=json.load(f)

def build(steps=(),profile=PROFILE,max_attempts=3):
    clock=Clock();provider=Provider(clock,steps)
    return clock,provider,Checkout(Gateway(provider,Policy(profile)),clock,max_attempts)

class Repair(unittest.TestCase):
    def test_lost_ack_retry_reuses_identity_single_charge(self):
        clock,provider,co=build([(0.01,True)])
        self.assertEqual(co.execute("op",{"amount":5}),{"receipt":"receipt-1","amount":5})
        self.assertEqual(len(provider.charges),1)
        self.assertEqual({c["operation_id"] for c in provider.calls},{"op"})

    def test_caller_repeat_after_uncertain_response(self):
        clock,provider,co=build([(0.01,True)],max_attempts=1)
        with self.assertRaises(TimeoutError):co.execute("op",{"amount":5})
        self.assertEqual(co.execute("op",{"amount":5})["receipt"],"receipt-1")
        self.assertEqual(len(provider.charges),1)

    def test_new_id_is_new_action(self):
        clock,provider,co=build()
        co.execute("a",{"amount":1});co.execute("b",{"amount":1})
        self.assertEqual(len(provider.charges),2)

    def test_reuse_with_different_payload(self):
        clock,provider,co=build()
        co.execute("a",{"amount":1})
        with self.assertRaises(ValueError):co.execute("a",{"amount":2})
        # A fresh coordinator still gets ValueError from the provider, without a charge.
        co2=Checkout(Gateway(provider,Policy(PROFILE)),clock)
        with self.assertRaises(ValueError):co2.execute("a",{"amount":2})
        self.assertEqual(len(provider.charges),1)

    def test_cold_start_fits(self):
        clock,provider,co=build([(0.30,False)])
        self.assertEqual(co.execute("cold",{"amount":3})["receipt"],"receipt-1")
        self.assertEqual(len(provider.calls),1)

    def test_deadline_respected_and_attempts_bounded(self):
        for total in (0.1,0.5,1.0,2.0):
            clock,provider,co=build([(5.0,False)]*10)
            with self.assertRaises(TimeoutError):co.execute("slow",{"amount":1},total_timeout=total)
            self.assertLessEqual(clock.now,total+1e-9)
            self.assertLessEqual(len(provider.calls),3)
            self.assertEqual(len(provider.charges),1)

    def test_max_attempts_configurable_no_hidden_retries(self):
        clock,provider,co=build([(5.0,False)]*10,max_attempts=2)
        with self.assertRaises(TimeoutError):co.execute("x",{"amount":1},total_timeout=100)
        self.assertEqual(len(provider.calls),2)

    def test_nonpositive_budget_starts_no_work(self):
        clock,provider,co=build()
        for t in (0,-1):
            with self.assertRaises(TimeoutError):co.execute("z%s"%t,{"amount":1},total_timeout=t)
        self.assertEqual(provider.calls,[])
        with self.assertRaises(TimeoutError):Policy(PROFILE).per_attempt(0)

    def test_policy_tracks_profile_and_caps(self):
        p=Policy(PROFILE)
        self.assertAlmostEqual(p.per_attempt(),0.32)
        self.assertAlmostEqual(Policy(dict(PROFILE,cold_p99=0.6)).per_attempt(),0.62)
        self.assertAlmostEqual(Policy(dict(PROFILE,network_allowance=0.1)).per_attempt(),0.40)
        self.assertAlmostEqual(p.per_attempt(0.1),0.1)
        self.assertEqual(Policy().per_attempt(),0.5)
        self.assertEqual(Policy(assumed_timeout=0.7).per_attempt(),0.7)

    def test_standalone_gateway_fresh_identity_per_call(self):
        clock=Clock();provider=Provider(clock,[(0.01,True)])
        g=Gateway(provider,Policy(PROFILE))
        with self.assertRaises(TimeoutError):g.submit({"amount":1})
        self.assertEqual(len(provider.calls),1)
        g.submit({"amount":1})
        self.assertEqual(len(provider.charges),2)
        self.assertNotEqual(provider.calls[0]["operation_id"],provider.calls[1]["operation_id"])

if __name__=="__main__":unittest.main()
