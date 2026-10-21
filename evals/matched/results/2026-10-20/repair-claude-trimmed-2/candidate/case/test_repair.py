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
        clock,provider,checkout=build([(0.01,True)])
        self.assertEqual(checkout.execute("op",{"amount":5}),{"receipt":"receipt-1","amount":5})
        self.assertEqual(len(provider.charges),1)
        self.assertEqual({c["operation_id"] for c in provider.calls},{"op"})

    def test_caller_repeat_after_uncertain_response_no_second_charge(self):
        clock,provider,checkout=build([(0.01,True)],max_attempts=1)
        with self.assertRaises(TimeoutError):checkout.execute("op",{"amount":5})
        self.assertEqual(checkout.execute("op",{"amount":5}),{"receipt":"receipt-1","amount":5})
        self.assertEqual(len(provider.charges),1)

    def test_different_id_is_new_action(self):
        clock,provider,checkout=build()
        checkout.execute("a",{"amount":1});checkout.execute("b",{"amount":1})
        self.assertEqual(len(provider.charges),2)

    def test_reused_id_different_payload_valueerror(self):
        clock,provider,checkout=build()
        checkout.execute("a",{"amount":1})
        with self.assertRaises(ValueError):checkout.execute("a",{"amount":2})
        self.assertEqual(len(provider.charges),1)

    def test_cold_start_succeeds_first_attempt(self):
        clock,provider,checkout=build([(0.30,False)])
        self.assertEqual(checkout.execute("cold",{"amount":3})["receipt"],"receipt-1")
        self.assertEqual(len(provider.calls),1)

    def test_attempts_bounded_no_hidden_gateway_retry(self):
        clock,provider,checkout=build([(0.01,True)]*10,max_attempts=2)
        with self.assertRaises(TimeoutError):checkout.execute("op",{"amount":1},total_timeout=10)
        self.assertEqual(len(provider.calls),2)

    def test_deadline_never_exceeded(self):
        clock,provider,checkout=build([(5,False)]*10)
        with self.assertRaises(TimeoutError):checkout.execute("op",{"amount":1},total_timeout=0.5)
        self.assertLessEqual(clock.now,0.5)
        self.assertTrue(all(c["timeout"]>0 for c in provider.calls))

    def test_nonpositive_budget_starts_no_work(self):
        clock,provider,checkout=build()
        for budget in (0,-1):
            with self.assertRaises(TimeoutError):checkout.execute("op",{"amount":1},total_timeout=budget)
        self.assertEqual(provider.calls,[])
        with self.assertRaises(TimeoutError):Policy(PROFILE).per_attempt(0)

    def test_policy_profile_driven_and_capped(self):
        self.assertAlmostEqual(Policy(PROFILE).per_attempt(),0.32)
        self.assertAlmostEqual(Policy(dict(PROFILE,cold_p99=0.6)).per_attempt(),0.62)
        self.assertAlmostEqual(Policy(PROFILE).per_attempt(0.1),0.1)
        self.assertEqual(Policy(assumed_timeout=0.7).per_attempt(),0.7)

    def test_standalone_submit_new_identity_per_invocation(self):
        clock=Clock();provider=Provider(clock,[(0.01,True)])
        gateway=Gateway(provider,Policy(PROFILE))
        with self.assertRaises(TimeoutError):gateway.submit({"amount":1})
        self.assertEqual(len(provider.calls),1)
        gateway.submit({"amount":1})
        self.assertEqual(len({c["operation_id"] for c in provider.calls}),2)

if __name__=="__main__":unittest.main()
