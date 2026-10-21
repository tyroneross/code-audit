import json,os,unittest
from policy import Policy
from simulator import Clock,Provider
from gateway import Gateway
from checkout import Checkout

PROFILE=json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),"profile.json")))

def build(steps=(),profile=PROFILE,max_attempts=3):
    clock=Clock();provider=Provider(clock,steps)
    return clock,provider,Checkout(Gateway(provider,Policy(profile)),clock,max_attempts)

class LostResponse(unittest.TestCase):
    def test_lost_ack_retry_reuses_identity(self):
        clock,provider,checkout=build([(0.01,True)])
        result=checkout.execute("op-1",{"amount":5})
        self.assertEqual(result,{"receipt":"receipt-1","amount":5})
        self.assertEqual(len(provider.charges),1)
        self.assertEqual({c["operation_id"] for c in provider.calls},{"op-1"})

    def test_caller_repeat_after_uncertain_response_does_not_charge_again(self):
        clock,provider,checkout=build([(0.01,True)],max_attempts=1)
        with self.assertRaises(TimeoutError):checkout.execute("op-1",{"amount":5})
        self.assertEqual(checkout.execute("op-1",{"amount":5}),{"receipt":"receipt-1","amount":5})
        self.assertEqual(len(provider.charges),1)

    def test_different_payload_same_id_raises_without_charge(self):
        clock,provider,checkout=build()
        checkout.execute("op-1",{"amount":5})
        with self.assertRaises(ValueError):checkout.execute("op-1",{"amount":6})
        self.assertEqual(len(provider.charges),1)

    def test_different_ids_are_distinct_actions(self):
        clock,provider,checkout=build()
        self.assertEqual(checkout.execute("a",{"amount":1})["receipt"],"receipt-1")
        self.assertEqual(checkout.execute("b",{"amount":1})["receipt"],"receipt-2")

    def test_standalone_submit_keeps_one_identity_per_invocation(self):
        clock=Clock();provider=Provider(clock,[(0.01,True)])
        gateway=Gateway(provider,Policy(PROFILE))
        with self.assertRaises(TimeoutError):gateway.submit({"amount":1})
        gateway.submit({"amount":1})
        self.assertEqual(len(provider.calls),2)
        self.assertNotEqual(provider.calls[0]["operation_id"],provider.calls[1]["operation_id"])

class Attempts(unittest.TestCase):
    def test_gateway_makes_exactly_one_attempt(self):
        clock=Clock();provider=Provider(clock,[(0.01,True),(0.01,False)])
        with self.assertRaises(TimeoutError):Gateway(provider,Policy(PROFILE)).submit({"amount":1},operation_id="x")
        self.assertEqual(len(provider.calls),1)

    def test_attempts_bounded_by_max_attempts(self):
        for n in (1,2,3,5):
            clock,provider,checkout=build([(0.01,True)]*10,max_attempts=n)
            with self.assertRaises(TimeoutError):checkout.execute("op",{"amount":1},total_timeout=10)
            self.assertEqual(len(provider.calls),n)
            self.assertEqual(len(provider.charges),1)

    def test_invalid_max_attempts_rejected(self):
        with self.assertRaises(ValueError):build(max_attempts=0)

class ColdStart(unittest.TestCase):
    def test_cold_call_succeeds_first_attempt(self):
        clock,provider,checkout=build([(0.30,False)])
        self.assertEqual(checkout.execute("cold",{"amount":9}),{"receipt":"receipt-1","amount":9})
        self.assertEqual(len(provider.calls),1)

    def test_limit_follows_profile(self):
        self.assertAlmostEqual(Policy(PROFILE).per_attempt(),0.32)
        self.assertAlmostEqual(Policy(dict(PROFILE,cold_p99=0.5)).per_attempt(),0.52)
        self.assertAlmostEqual(Policy(dict(PROFILE,network_allowance=0.1)).per_attempt(),0.40)

    def test_assumed_timeout_without_profile(self):
        self.assertEqual(Policy().per_attempt(),0.5)
        self.assertEqual(Policy(assumed_timeout=0.7).per_attempt(),0.7)

    def test_remaining_caps_and_exhaustion_refuses(self):
        policy=Policy(PROFILE)
        self.assertAlmostEqual(policy.per_attempt(remaining=0.1),0.1)
        self.assertAlmostEqual(policy.per_attempt(remaining=5),0.32)
        for remaining in (0,-1):
            with self.assertRaises(TimeoutError):policy.per_attempt(remaining=remaining)

class Deadline(unittest.TestCase):
    def test_never_exceeds_total_timeout(self):
        for total in (0.05,0.2,0.33,0.5,1.0):
            for steps in ([(10,False)]*5,[(0.31,True)]*5,[(0.01,True)]*5):
                clock,provider,checkout=build(steps)
                with self.assertRaises(TimeoutError):checkout.execute("op",{"amount":1},total_timeout=total)
                self.assertLessEqual(clock.now,total+1e-9,(total,steps))
                self.assertLessEqual(len(provider.calls),3)

    def test_nonpositive_budget_starts_no_work(self):
        for total in (0,-1):
            clock,provider,checkout=build()
            with self.assertRaises(TimeoutError):checkout.execute("op",{"amount":1},total_timeout=total)
            self.assertEqual(provider.calls,[])

    def test_slow_then_success_within_budget(self):
        clock,provider,checkout=build([(10,False),(0.01,False)])
        self.assertEqual(checkout.execute("op",{"amount":3},total_timeout=1.0)["receipt"],"receipt-1")
        self.assertEqual(len(provider.charges),1)
        self.assertLessEqual(clock.now,1.0)

if __name__=="__main__":unittest.main()
