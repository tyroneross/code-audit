import unittest

from checkout import Checkout
from gateway import Gateway
from policy import Policy
from simulator import Clock, Provider


PROFILE = {"warm_p99": 0.08, "cold_p99": 0.30, "network_allowance": 0.02}


class Repair(unittest.TestCase):
    def stack(self, steps=(), max_attempts=3):
        clock = Clock()
        provider = Provider(clock, steps)
        gateway = Gateway(provider, Policy(dict(PROFILE)))
        return clock, provider, gateway, Checkout(gateway, clock, max_attempts)

    def test_lost_response_and_caller_replay_share_receipt(self):
        clock, provider, gateway, checkout = self.stack([(0.01, True)])
        first = checkout.execute("same", {"amount": 12})
        self.assertEqual(checkout.execute("same", {"amount": 12}), first)
        self.assertEqual(len(provider.charges), 1)
        self.assertEqual([call["operation_id"] for call in provider.calls], ["same"] * 3)

    def test_exhausted_execution_can_be_replayed(self):
        clock, provider, gateway, checkout = self.stack([(0.01, True)], 1)
        with self.assertRaises(TimeoutError):
            checkout.execute("uncertain", {"amount": 12})
        self.assertEqual(checkout.execute("uncertain", {"amount": 12})["receipt"], "receipt-1")
        self.assertEqual(len(provider.charges), 1)

    def test_recovery_after_deadline_with_new_coordinator(self):
        clock, provider, gateway, checkout = self.stack([(1, False)])
        with self.assertRaises(TimeoutError):
            checkout.execute("recover", {"amount": 12}, 0.02)
        replacement = Checkout(Gateway(provider, Policy(dict(PROFILE))), clock)
        self.assertEqual(replacement.execute("recover", {"amount": 12}),
                         {"receipt": "receipt-1", "amount": 12})
        self.assertEqual(len(provider.charges), 1)

    def test_budget_is_relative_to_current_clock(self):
        clock, provider, gateway, checkout = self.stack([(1, False)] * 10)
        clock.advance(10)
        with self.assertRaises(TimeoutError):
            checkout.execute("later", {"amount": 12}, 0.4)
        self.assertLessEqual(clock.now, 10.4)
        self.assertAlmostEqual(clock.now, 10.4)

    def test_empty_supplied_identity_is_preserved(self):
        clock, provider, gateway, checkout = self.stack()
        self.assertEqual(gateway.submit({"amount": 12}, ""),
                         gateway.submit({"amount": 12}, ""))
        self.assertEqual(provider.calls[0]["operation_id"], "")
        self.assertEqual(len(provider.charges), 1)

    def test_payload_conflict_surfaces_without_charge(self):
        clock, provider, gateway, checkout = self.stack([(0.01, True)], 1)
        with self.assertRaises(TimeoutError):
            checkout.execute("conflict", {"amount": 12})
        with self.assertRaises(ValueError):
            checkout.execute("conflict", {"amount": 13})
        self.assertEqual(len(provider.charges), 1)

    def test_different_ids_are_new_actions(self):
        clock, provider, gateway, checkout = self.stack()
        self.assertNotEqual(checkout.execute("one", {"amount": 12}),
                            checkout.execute("two", {"amount": 12}))
        self.assertEqual(len(provider.charges), 2)

    def test_gateway_is_one_attempt(self):
        clock, provider, gateway, checkout = self.stack([(0.01, True)])
        with self.assertRaises(TimeoutError):
            gateway.submit({"amount": 12}, operation_id="direct")
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(provider.calls[0]["operation_id"], "direct")

    def test_standalone_identity_is_new_per_invocation(self):
        clock, provider, gateway, checkout = self.stack()
        gateway.submit({"amount": 12})
        gateway.submit({"amount": 12})
        self.assertEqual(len(provider.charges), 2)
        self.assertNotEqual(provider.calls[0]["operation_id"], provider.calls[1]["operation_id"])

    def test_cold_success_uses_profile(self):
        clock, provider, gateway, checkout = self.stack([(0.30, False)] * 10, 1)
        self.assertEqual(checkout.execute("cold", {"amount": 12})["amount"], 12)
        self.assertAlmostEqual(provider.calls[0]["timeout"], 0.32)
        self.assertAlmostEqual(clock.now, 0.30)

    def test_deadline_caps_every_attempt(self):
        clock, provider, gateway, checkout = self.stack([(2, False)] * 10)
        with self.assertRaises(TimeoutError):
            checkout.execute("slow", {"amount": 12}, total_timeout=0.4)
        self.assertLessEqual(clock.now, 0.4)
        self.assertEqual(len(provider.calls), 2)
        self.assertAlmostEqual(provider.calls[0]["timeout"], 0.32)
        self.assertAlmostEqual(provider.calls[1]["timeout"], 0.08)
        self.assertEqual(len(provider.charges), 1)

    def test_configurable_attempt_limit(self):
        for attempts in (0, 1, 2, 4):
            with self.subTest(attempts=attempts):
                clock, provider, gateway, checkout = self.stack([(0.01, True)] * 10, attempts)
                with self.assertRaises(TimeoutError):
                    checkout.execute("lost", {"amount": 12}, 10)
                self.assertEqual(len(provider.calls), attempts)

    def test_small_budget_stops_at_deadline(self):
        clock, provider, gateway, checkout = self.stack([(2, False)] * 10)
        with self.assertRaises(TimeoutError):
            checkout.execute("short", {"amount": 12}, total_timeout=0.07)
        self.assertEqual(clock.now, 0.07)
        self.assertEqual(len(provider.calls), 1)

    def test_nonpositive_budgets_do_not_start_work(self):
        for budget in (0, -1):
            clock, provider, gateway, checkout = self.stack()
            with self.assertRaises(TimeoutError):
                checkout.execute("expired", {"amount": 12}, budget)
            with self.assertRaises(TimeoutError):
                gateway.submit({"amount": 12}, timeout=budget)
            self.assertEqual(provider.calls, [])
            self.assertEqual(provider.charges, [])
            self.assertEqual(clock.now, 0)

    def test_explicit_gateway_timeout_caps_policy(self):
        clock, provider, gateway, checkout = self.stack([(1, False)])
        with self.assertRaises(TimeoutError):
            gateway.submit({"amount": 12}, "bounded", timeout=0.02)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(clock.now, 0.02)

    def test_profile_and_fallback_limits(self):
        self.assertAlmostEqual(Policy(PROFILE).per_attempt(), 0.32)
        self.assertAlmostEqual(Policy({**PROFILE, "cold_p99": 0.6}).per_attempt(), 0.62)
        self.assertAlmostEqual(Policy({**PROFILE, "warm_p99": 0.7}).per_attempt(), 0.72)
        self.assertAlmostEqual(Policy({**PROFILE, "network_allowance": 0.1}).per_attempt(), 0.4)
        self.assertEqual(Policy(assumed_timeout=0.7).per_attempt(), 0.7)
        self.assertEqual(Policy(PROFILE).per_attempt(0.01), 0.01)
        for remaining in (0, -1):
            with self.assertRaises(TimeoutError):
                Policy(PROFILE).per_attempt(remaining)


if __name__ == "__main__":
    unittest.main()
