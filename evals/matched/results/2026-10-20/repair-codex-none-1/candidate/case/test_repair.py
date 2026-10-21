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
        gateway = Gateway(provider, policy if policy is not None else Policy())
        return clock, provider, Checkout(gateway, clock, max_attempts)

    def test_lost_ack_retry_keeps_identity_and_receipt(self):
        clock, provider, checkout = self.make_checkout([(0.01, True)])
        result = checkout.execute("order", {"amount": 12})
        self.assertEqual(result, {"receipt": "receipt-1", "amount": 12})
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual([call["operation_id"] for call in provider.calls],
                         ["order", "order"])
        self.assertEqual(len(provider.charges), 1)

    def test_replay_after_exhaustion_and_payload_conflict(self):
        clock, provider, checkout = self.make_checkout(
            [(0.01, True)], max_attempts=1)
        with self.assertRaises(TimeoutError):
            checkout.execute("order", {"amount": 12})
        self.assertEqual(len(provider.charges), 1)
        # Replay through a fresh coordinator/gateway: identity belongs to the
        # logical operation, not to a particular object or execution.
        replay = Checkout(Gateway(provider, Policy()), clock)
        self.assertEqual(replay.execute("order", {"amount": 12}),
                         {"receipt": "receipt-1", "amount": 12})
        with self.assertRaises(ValueError):
            replay.execute("order", {"amount": 13})
        self.assertEqual(len(provider.charges), 1)
        self.assertEqual(replay.execute("another", {"amount": 12})["receipt"],
                         "receipt-2")

    def test_deadline_caps_each_attempt_from_nonzero_clock(self):
        clock, provider, checkout = self.make_checkout([(1, False)] * 5)
        clock.advance(10)
        with self.assertRaises(TimeoutError):
            checkout.execute("slow", {"amount": 12}, total_timeout=0.7)
        self.assertEqual(len(provider.calls), 2)
        self.assertAlmostEqual(provider.calls[0]["timeout"], 0.5)
        self.assertAlmostEqual(provider.calls[1]["timeout"], 0.2)
        self.assertEqual(clock.now, 10.7)
        self.assertEqual(len(provider.charges), 1)

    def test_short_budget_can_succeed(self):
        clock, provider, checkout = self.make_checkout([(0.02, False)])
        checkout.execute("short", {"amount": 1}, total_timeout=0.03)
        self.assertEqual(provider.calls[0]["timeout"], 0.03)
        self.assertEqual(clock.now, 0.02)

    def test_attempt_limit_is_not_multiplied(self):
        for attempts in (0, 1, 2, 4):
            with self.subTest(attempts=attempts):
                clock, provider, checkout = self.make_checkout(
                    [(0.01, True)] * 10, max_attempts=attempts)
                with self.assertRaises(TimeoutError):
                    checkout.execute("lost", {"amount": 1}, total_timeout=10)
                self.assertEqual(len(provider.calls), attempts)
                self.assertEqual(len(provider.charges), min(attempts, 1))

    def test_nonpositive_budget_starts_no_work(self):
        for budget in (0, -1):
            with self.subTest(budget=budget):
                clock, provider, checkout = self.make_checkout()
                with self.assertRaises(TimeoutError):
                    checkout.execute("expired", {"amount": 1}, budget)
                with self.assertRaises(TimeoutError):
                    checkout.gateway.submit({"amount": 1}, timeout=budget)
                self.assertEqual(provider.calls, [])
                self.assertEqual(provider.charges, [])
                self.assertEqual(clock.now, 0)

    def test_gateway_is_one_attempt_and_standalone_ids_are_new(self):
        clock = Clock()
        provider = Provider(clock, [(1, False)])
        gateway = Gateway(provider, Policy())
        with self.assertRaises(TimeoutError):
            gateway.submit({"amount": 1}, timeout=0.04)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(clock.now, 0.04)
        gateway.submit({"amount": 1})
        self.assertEqual(len(provider.charges), 2)
        self.assertNotEqual(provider.calls[0]["operation_id"],
                            provider.calls[1]["operation_id"])

    def test_falsy_explicit_identity_is_preserved(self):
        clock, provider, checkout = self.make_checkout()
        checkout.execute("", {"amount": 1})
        checkout.execute("", {"amount": 1})
        self.assertEqual(len(provider.charges), 1)
        self.assertEqual(provider.calls[0]["operation_id"], "")

    def test_profile_covers_cold_start_and_allowance(self):
        profile = json.loads(Path(__file__).with_name("profile.json").read_text())
        limit = max(profile["warm_p99"], profile["cold_p99"])
        limit += profile["network_allowance"]
        policy = Policy(profile)
        self.assertEqual(policy.per_attempt(), limit)
        clock, provider, checkout = self.make_checkout([(limit, False)],
                                                       policy=policy)
        checkout.execute("cold", {"amount": 1})
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(clock.now, limit)

    def test_policy_responds_to_profile_and_remaining_budget(self):
        profile = {"warm_p99": 0.1, "cold_p99": 0.3,
                   "network_allowance": 0.02}
        policy = Policy(profile)
        self.assertAlmostEqual(policy.per_attempt(), 0.32)
        for field, value, expected in (("cold_p99", 0.6, 0.62),
                                       ("network_allowance", 0.1, 0.7),
                                       ("warm_p99", 0.8, 0.9)):
            profile[field] = value
            self.assertAlmostEqual(policy.per_attempt(), expected)
        self.assertEqual(policy.per_attempt(0.04), 0.04)
        self.assertAlmostEqual(policy.per_attempt(2), 0.9)
        self.assertEqual(Policy(assumed_timeout=0.7).per_attempt(), 0.7)
        self.assertEqual(Policy({}, assumed_timeout=0.7).per_attempt(), 0.7)
        self.assertEqual(Policy(assumed_timeout=0.7).per_attempt(0.2), 0.2)
        for remaining in (0, -0.1):
            with self.assertRaises(TimeoutError):
                policy.per_attempt(remaining)


if __name__ == "__main__":
    unittest.main()
