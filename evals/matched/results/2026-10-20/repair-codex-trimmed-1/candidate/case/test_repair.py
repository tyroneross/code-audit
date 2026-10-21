import json
from pathlib import Path
import unittest

from checkout import Checkout
from gateway import Gateway
from policy import Policy
from simulator import Clock, Provider


class Repair(unittest.TestCase):
    def make_checkout(self, steps=(), max_attempts=3, policy=None):
        clock = Clock()
        provider = Provider(clock, steps)
        checkout = Checkout(Gateway(provider, policy or Policy()), clock, max_attempts)
        return clock, provider, checkout

    def test_lost_response_retries_same_identity(self):
        _, provider, checkout = self.make_checkout([(0.01, True), (0.01, False)])
        receipt = checkout.execute("order", {"amount": 12})
        self.assertEqual(receipt, {"receipt": "receipt-1", "amount": 12})
        self.assertEqual(len(provider.charges), 1)
        self.assertEqual([call["operation_id"] for call in provider.calls], ["order", "order"])

    def test_recovery_across_executions_and_payload_conflict(self):
        _, provider, checkout = self.make_checkout([(0.01, True)], max_attempts=1)
        with self.assertRaises(TimeoutError):
            checkout.execute("order", {"amount": 12})
        checkout = Checkout(Gateway(provider, Policy()), checkout.clock, max_attempts=1)
        self.assertEqual(checkout.execute("order", {"amount": 12})["receipt"], "receipt-1")
        with self.assertRaises(ValueError):
            checkout.execute("order", {"amount": 13})
        self.assertEqual(len(provider.charges), 1)
        self.assertEqual(checkout.execute("another", {"amount": 12})["receipt"], "receipt-2")

    def test_gateway_is_one_attempt_and_honors_timeout(self):
        clock = Clock()
        provider = Provider(clock, [(1.0, False)])
        gateway = Gateway(provider, Policy())
        with self.assertRaises(TimeoutError):
            gateway.submit({"amount": 12}, operation_id="order", timeout=0.02)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(provider.calls[0]["timeout"], 0.02)
        self.assertEqual(clock.now, 0.02)

    def test_standalone_invocations_have_distinct_identities(self):
        clock = Clock()
        provider = Provider(clock)
        gateway = Gateway(provider, Policy())
        gateway.submit({"amount": 12})
        gateway.submit({"amount": 12})
        self.assertEqual(len(provider.charges), 2)
        self.assertNotEqual(provider.calls[0]["operation_id"], provider.calls[1]["operation_id"])

    def test_deadline_caps_each_attempt(self):
        clock, provider, checkout = self.make_checkout([(0.2, True), (1.0, False)])
        with self.assertRaises(TimeoutError):
            checkout.execute("order", {"amount": 12}, total_timeout=0.25)
        self.assertLessEqual(clock.now, 0.25)
        self.assertEqual(len(provider.calls), 2)
        self.assertAlmostEqual(provider.calls[1]["timeout"], 0.05)
        self.assertEqual(len(provider.charges), 1)

    def test_slow_provider_cannot_overrun_total_budget(self):
        for budget in (0.001, 0.12, 0.6):
            with self.subTest(budget=budget):
                clock, provider, checkout = self.make_checkout([(10, False)] * 10)
                with self.assertRaises(TimeoutError):
                    checkout.execute("order", {"amount": 12}, total_timeout=budget)
                self.assertLessEqual(clock.now, budget)
                self.assertLessEqual(len(provider.calls), checkout.max_attempts)
                self.assertEqual(len(provider.charges), 1)

    def test_explicit_empty_identity_is_preserved(self):
        _, provider, checkout = self.make_checkout()
        first = checkout.execute("", {"amount": 12})
        self.assertEqual(checkout.execute("", {"amount": 12}), first)
        self.assertEqual(len(provider.charges), 1)
        self.assertEqual(provider.calls[0]["operation_id"], "")

    def test_attempt_exhaustion(self):
        for attempts in (0, 1, 2, 4):
            with self.subTest(attempts=attempts):
                _, provider, checkout = self.make_checkout([(0.01, True)] * 10, attempts)
                with self.assertRaises(TimeoutError):
                    checkout.execute("order", {"amount": 12}, total_timeout=10)
                self.assertEqual(len(provider.calls), attempts)

    def test_nonpositive_budgets_do_not_start_work(self):
        for budget in (0, -1):
            clock, provider, checkout = self.make_checkout()
            with self.assertRaises(TimeoutError):
                checkout.execute("order", {"amount": 12}, total_timeout=budget)
            with self.assertRaises(TimeoutError):
                checkout.gateway.submit({"amount": 12}, timeout=budget)
            with self.assertRaises(TimeoutError):
                Policy().per_attempt(budget)
            self.assertEqual(provider.charges, [])
            self.assertEqual(clock.now, 0)

    def test_profile_covers_cold_behavior_and_tracks_changes(self):
        profile = json.loads(Path(__file__).with_name("profile.json").read_text())
        policy = Policy(profile)
        expected = max(profile["warm_p99"], profile["cold_p99"]) + profile["network_allowance"]
        self.assertAlmostEqual(policy.per_attempt(), expected)
        _, provider, checkout = self.make_checkout([(expected, False)], policy=policy)
        checkout.execute("cold", {"amount": 12})
        self.assertEqual(len(provider.calls), 1)
        for field, value in (("cold_p99", 0.6), ("warm_p99", 0.7), ("network_allowance", 0.2)):
            changed = dict(profile, **{field: value})
            self.assertAlmostEqual(Policy(changed).per_attempt(), max(changed["warm_p99"], changed["cold_p99"]) + changed["network_allowance"])
            self.assertNotEqual(Policy(changed).per_attempt(), policy.per_attempt())
        self.assertEqual(policy.per_attempt(0.02), 0.02)

    def test_explicit_fallback(self):
        self.assertEqual(Policy(assumed_timeout=0.7).per_attempt(), 0.7)
        self.assertEqual(Policy(assumed_timeout=0.7).per_attempt(0.1), 0.1)


if __name__ == "__main__":
    unittest.main()
