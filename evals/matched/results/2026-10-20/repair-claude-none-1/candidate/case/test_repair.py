import json,os,unittest
from policy import Policy
from simulator import Clock,Provider
from gateway import Gateway
from checkout import Checkout

HERE=os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE,"profile.json")) as f:PROFILE=json.load(f)

def build(steps=(),profile=PROFILE,max_attempts=3):
    clock=Clock();provider=Provider(clock,steps)
    return clock,provider,Checkout(Gateway(provider,Policy(profile)),clock,max_attempts)

class Repair(unittest.TestCase):
    def test_lost_ack_retry_reuses_identity_single_charge(self):
        clock,provider,checkout=build([(0.01,True)])
        result=checkout.execute("op-1",{"amount":5})
        self.assertEqual(result,{"receipt":"receipt-1","amount":5})
        self.assertEqual(len(provider.charges),1)
        self.assertEqual({c["operation_id"] for c in provider.calls},{"op-1"})

    def test_caller_repeat_after_uncertain_response_no_second_charge(self):
        clock,provider,checkout=build([(0.01,True)],max_attempts=1)
        with self.assertRaises(TimeoutError):checkout.execute("op-2",{"amount":7})
        self.assertEqual(checkout.execute("op-2",{"amount":7}),{"receipt":"receipt-1","amount":7})
        self.assertEqual(len(provider.charges),1)

    def test_new_id_is_new_action(self):
        clock,provider,checkout=build()
        checkout.execute("a",{"amount":1});checkout.execute("b",{"amount":1})
        self.assertEqual(len(provider.charges),2)

    def test_payload_mismatch_raises_without_charge(self):
        clock,provider,checkout=build()
        checkout.execute("x",{"amount":1})
        with self.assertRaises(ValueError):checkout.execute("x",{"amount":2})
        self.assertEqual(len(provider.charges),1)
        # Mismatch is also enforced by a fresh Checkout via the stable provider key.
        fresh=Checkout(Gateway(provider,Policy(PROFILE)),clock)
        with self.assertRaises(ValueError):fresh.execute("x",{"amount":2})
        self.assertEqual(len(provider.charges),1)

    def test_cold_start_fits(self):
        clock,provider,checkout=build([(PROFILE["cold_p99"],False)])
        self.assertEqual(checkout.execute("cold",{"amount":3})["amount"],3)
        self.assertEqual(len(provider.calls),1)

    def test_policy_tracks_profile_and_caps(self):
        base=Policy(PROFILE).per_attempt()
        self.assertGreaterEqual(base,PROFILE["cold_p99"]+PROFILE["network_allowance"])
        slower=dict(PROFILE,cold_p99=PROFILE["cold_p99"]+0.2)
        self.assertGreater(Policy(slower).per_attempt(),base)
        self.assertEqual(Policy(PROFILE).per_attempt(0.1),0.1)
        self.assertEqual(Policy(None,assumed_timeout=0.7).per_attempt(),0.7)
        for bad in (0,-1):
            with self.assertRaises(TimeoutError):Policy(PROFILE).per_attempt(bad)

    def test_deadline_respected_and_attempts_bounded(self):
        for total in (0.05,0.5,1.0,2.0):
            clock,provider,checkout=build([(5.0,False)]*10)
            with self.assertRaises(TimeoutError):checkout.execute("slow",{"amount":1},total)
            self.assertLessEqual(clock.now,total+1e-9)
            self.assertLessEqual(len(provider.calls),3)

    def test_max_attempts_configurable_and_not_multiplied(self):
        clock,provider,checkout=build([(0.01,True)]*10,max_attempts=2)
        with self.assertRaises(TimeoutError):checkout.execute("m",{"amount":1},10.0)
        self.assertEqual(len(provider.calls),2)

    def test_exhausted_budget_starts_no_work(self):
        clock,provider,checkout=build()
        with self.assertRaises(TimeoutError):checkout.execute("z",{"amount":1},0)
        self.assertEqual(provider.calls,[])

    def test_standalone_submit_gets_fresh_identity_per_call(self):
        clock=Clock();provider=Provider(clock)
        gw=Gateway(provider,Policy(PROFILE))
        gw.submit({"amount":1});gw.submit({"amount":1})
        self.assertEqual(len(provider.charges),2)

    def test_gateway_single_attempt(self):
        clock=Clock();provider=Provider(clock,[(0.01,True),(0.01,False)])
        with self.assertRaises(TimeoutError):Gateway(provider,Policy(PROFILE)).submit({"amount":1},operation_id="g")
        self.assertEqual(len(provider.calls),1)

if __name__=="__main__":unittest.main()
