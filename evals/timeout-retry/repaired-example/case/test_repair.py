import json,os,unittest
from policy import Policy
from simulator import Clock,Provider
from gateway import Gateway
from checkout import Checkout

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),"profile.json")) as f:PROFILE=json.load(f)
STALL=(10.0,False)

def build(steps=(),profile=PROFILE,max_attempts=3,start=0.0):
    clock=Clock();clock.advance(start);provider=Provider(clock,steps)
    return clock,provider,Checkout(Gateway(provider,Policy(profile)),clock,max_attempts)

class Idempotency(unittest.TestCase):
    def test_lost_ack_retry_reuses_identity(self):
        clock,provider,checkout=build([(0.01,True)])
        self.assertEqual(checkout.execute("op",{"amount":5}),{"receipt":"receipt-1","amount":5})
        self.assertEqual(len(provider.charges),1)
        self.assertEqual({c["operation_id"] for c in provider.calls},{"op"})

    def test_caller_repeat_after_timeout_does_not_recharge(self):
        clock,provider,checkout=build([(0.01,True)]*3)
        with self.assertRaises(TimeoutError):checkout.execute("op",{"amount":5})
        self.assertEqual(checkout.execute("op",{"amount":5}),{"receipt":"receipt-1","amount":5})
        self.assertEqual(len(provider.charges),1)

    def test_different_operation_id_is_new_action(self):
        clock,provider,checkout=build()
        checkout.execute("a",{"amount":5});checkout.execute("b",{"amount":5})
        self.assertEqual(len(provider.charges),2)

    def test_reused_id_with_different_payload_raises_without_charge(self):
        clock,provider,checkout=build()
        checkout.execute("op",{"amount":5})
        with self.assertRaises(ValueError):checkout.execute("op",{"amount":6})
        self.assertEqual(len(provider.charges),1)

    def test_standalone_submit_creates_identity_once_per_invocation(self):
        clock=Clock();provider=Provider(clock,[(0.01,True)])
        gateway=Gateway(provider,Policy(PROFILE))
        with self.assertRaises(TimeoutError):gateway.submit({"amount":5})
        self.assertEqual(len(provider.calls),1)
        gateway.submit({"amount":5})
        self.assertEqual(len(provider.charges),2)
        self.assertNotEqual(provider.calls[0]["operation_id"],provider.calls[1]["operation_id"])

class Attempts(unittest.TestCase):
    def test_submit_is_one_provider_attempt(self):
        clock=Clock();provider=Provider(clock,[STALL]*5)
        with self.assertRaises(TimeoutError):Gateway(provider,Policy(PROFILE)).submit({"amount":5},operation_id="op")
        self.assertEqual(len(provider.calls),1)

    def test_max_attempts_bounds_provider_attempts(self):
        for n in (1,2,3,5):
            clock,provider,checkout=build([STALL]*10,max_attempts=n)
            with self.assertRaises(TimeoutError):checkout.execute("op",{"amount":5},total_timeout=100.0)
            self.assertEqual(len(provider.calls),n)
            self.assertEqual(len(provider.charges),1)

    def test_invalid_max_attempts_rejected(self):
        with self.assertRaises(ValueError):build(max_attempts=0)

class Timing(unittest.TestCase):
    def test_cold_start_fits_first_attempt(self):
        clock,provider,checkout=build([(PROFILE["cold_p99"],False)])
        self.assertEqual(checkout.execute("op",{"amount":5})["receipt"],"receipt-1")
        self.assertEqual(len(provider.calls),1)

    def test_limit_follows_profile(self):
        base=Policy(PROFILE).per_attempt()
        self.assertGreaterEqual(base,PROFILE["cold_p99"]+PROFILE["network_allowance"])
        for key in ("cold_p99","network_allowance"):
            changed=dict(PROFILE,**{key:PROFILE[key]+0.1})
            self.assertNotEqual(Policy(changed).per_attempt(),base)

    def test_assumed_timeout_without_profile(self):
        self.assertEqual(Policy().per_attempt(),0.5)
        self.assertEqual(Policy(assumed_timeout=0.7).per_attempt(),0.7)

    def test_remaining_caps_and_exhausted_budget_refuses(self):
        policy=Policy(PROFILE)
        self.assertEqual(policy.per_attempt(remaining=0.1),0.1)
        self.assertEqual(policy.per_attempt(remaining=10),policy.per_attempt())
        for remaining in (0,-1):
            with self.assertRaises(TimeoutError):policy.per_attempt(remaining=remaining)

    def test_nonpositive_budget_starts_no_work(self):
        for total in (0,-0.5):
            clock,provider,checkout=build()
            with self.assertRaises(TimeoutError):checkout.execute("op",{"amount":5},total_timeout=total)
            self.assertEqual(provider.calls,[])

    def test_never_exceeds_total_timeout(self):
        for start in (0.0,0.1,7.3,1e6):
            for total in (0.01,0.07,0.12,0.33,0.5,0.95,1.0,1.37):
                for profile in (PROFILE,None):
                    clock,provider,checkout=build([STALL]*10,profile=profile,max_attempts=10,start=start)
                    with self.assertRaises(TimeoutError):checkout.execute("op",{"amount":5},total_timeout=total)
                    self.assertLessEqual(clock.now-start,total+1e-9)
                    self.assertLessEqual(clock.now,start+total)

if __name__=="__main__":unittest.main()
