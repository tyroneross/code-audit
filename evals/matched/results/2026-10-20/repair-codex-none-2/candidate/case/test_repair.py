import json
from pathlib import Path
import unittest
from unittest.mock import patch

from checkout import Checkout
from gateway import Gateway
from policy import Policy
from simulator import Clock, Provider


class Repair(unittest.TestCase):
    def setUp(self):
        self.profile = json.loads(Path(__file__).with_name("profile.json").read_text())

    def stack(self, steps=(), max_attempts=3):
        clock = Clock()
        provider = Provider(clock, steps)
        gateway = Gateway(provider, Policy(self.profile))
        return clock, provider, gateway, Checkout(gateway, clock, max_attempts)

    def test_lost_ack_retry_returns_original_receipt(self):
        clock, provider, _, checkout = self.stack([(0.01, True), (0.01, False)])
        self.assertEqual(checkout.execute("purchase", {"amount": 12}),
                         {"receipt": "receipt-1", "amount": 12})
        self.assertEqual(len(provider.charges), 1)
        self.assertEqual([call["operation_id"] for call in provider.calls],
                         ["purchase", "purchase"])
        self.assertAlmostEqual(clock.now, 0.02)

    def test_replay_after_exhaustion_and_client_recreation(self):
        clock, provider, _, checkout = self.stack([(0.01, True)], max_attempts=1)
        with self.assertRaises(TimeoutError):
            checkout.execute("purchase", {"amount": 12})
        replay = Checkout(Gateway(provider, Policy(self.profile)), clock)
        self.assertEqual(replay.execute("purchase", {"amount": 12}),
                         {"receipt": "receipt-1", "amount": 12})
        self.assertEqual(len(provider.charges), 1)
        self.assertEqual(replay.execute("another", {"amount": 12})["receipt"],
                         "receipt-2")
        self.assertEqual(len(provider.charges), 2)

    def test_changed_payload_is_rejected_after_success_or_lost_ack(self):
        for lost in (False, True):
            with self.subTest(lost=lost):
                _, provider, _, checkout = self.stack([(0.01, lost)], max_attempts=1)
                if lost:
                    with self.assertRaises(TimeoutError):
                        checkout.execute("purchase", {"amount": 12})
                else:
                    checkout.execute("purchase", {"amount": 12})
                with self.assertRaises(ValueError):
                    checkout.execute("purchase", {"amount": 13})
                self.assertEqual(len(provider.charges), 1)
                self.assertEqual(len(provider.calls), 1)

    def test_profile_covers_cold_call_with_allowance(self):
        delay = self.profile["cold_p99"] + self.profile["network_allowance"]
        clock, provider, _, checkout = self.stack([(delay, False)])
        checkout.execute("cold", {"amount": 12})
        self.assertEqual(len(provider.calls), 1)
        self.assertAlmostEqual(provider.calls[0]["timeout"], delay)
        self.assertAlmostEqual(clock.now, delay)

    def test_policy_fallback_and_profile_changes(self):
        self.assertEqual(Policy().per_attempt(), 0.5)
        self.assertEqual(Policy(assumed_timeout=0.7).per_attempt(), 0.7)
        self.assertEqual(Policy(assumed_timeout=0.7).per_attempt(0.02), 0.02)
        policy = Policy(self.profile)
        self.assertAlmostEqual(policy.per_attempt(), 0.32)
        self.profile["cold_p99"] = 0.6
        self.assertAlmostEqual(policy.per_attempt(), 0.62)
        self.profile["network_allowance"] = 0.1
        self.assertAlmostEqual(policy.per_attempt(), 0.7)
        self.profile["warm_p99"] = 0.8
        self.assertAlmostEqual(policy.per_attempt(), 0.9)
        self.assertEqual(policy.per_attempt(0.04), 0.04)
        for remaining in (0, -0.1):
            with self.assertRaises(TimeoutError):
                policy.per_attempt(remaining)

    def test_gateway_is_one_attempt_and_caps_timeout(self):
        clock, provider, gateway, _ = self.stack([(1, False)])
        with self.assertRaises(TimeoutError):
            gateway.submit({"amount": 12}, operation_id="purchase", timeout=0.03)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(provider.calls[0]["operation_id"], "purchase")
        self.assertEqual(provider.calls[0]["timeout"], 0.03)
        self.assertEqual(clock.now, 0.03)

    def test_standalone_identity_created_once_per_invocation(self):
        _, provider, gateway, _ = self.stack([(0.01, True)])
        with patch("gateway.uuid.uuid4", side_effect=["first", "second"]) as uuid:
            with self.assertRaises(TimeoutError):
                gateway.submit({"amount": 12})
            self.assertEqual(len(provider.calls), 1)
            self.assertEqual(gateway.submit({"amount": 12})["receipt"], "receipt-2")
        self.assertEqual(uuid.call_count, 2)
        self.assertEqual([call["operation_id"] for call in provider.calls],
                         ["first", "second"])

    def test_falsy_explicit_identity_is_preserved(self):
        _, provider, gateway, _ = self.stack()
        with patch("gateway.uuid.uuid4") as uuid:
            first = gateway.submit({"amount": 12}, operation_id="")
            self.assertEqual(gateway.submit({"amount": 12}, operation_id=""), first)
            uuid.assert_not_called()
        self.assertEqual(len(provider.charges), 1)

    def test_nonpositive_budgets_do_not_start_work(self):
        for budget in (0, -1):
            with self.subTest(budget=budget):
                clock, provider, gateway, checkout = self.stack()
                with self.assertRaises(TimeoutError):
                    checkout.execute("purchase", {"amount": 12}, budget)
                with self.assertRaises(TimeoutError):
                    gateway.submit({"amount": 12}, timeout=budget)
                self.assertEqual(provider.calls, [])
                self.assertEqual(provider.charges, [])
                self.assertEqual(clock.now, 0)

    def test_attempt_and_deadline_exhaustion_matrix(self):
        for attempts in (0, 1, 2, 3, 5):
            for budget in (0.01, 0.1, 0.32, 0.33, 0.65, 2):
                for delay in (0.01, 0.3, 10):
                    with self.subTest(attempts=attempts, budget=budget, delay=delay):
                        clock, provider, _, checkout = self.stack(
                            [(delay, True)] * attempts, max_attempts=attempts)
                        clock.advance(4)
                        deadline = clock.now + budget
                        with self.assertRaises(TimeoutError):
                            checkout.execute("purchase", {"amount": 12}, budget)
                        self.assertLessEqual(clock.now, deadline)
                        self.assertLessEqual(len(provider.calls), attempts)
                        self.assertLessEqual(len(provider.charges), 1)
                        now = 4
                        for call in provider.calls:
                            self.assertGreater(call["timeout"], 0)
                            self.assertLessEqual(call["timeout"], deadline - now)
                            self.assertLessEqual(call["timeout"], 0.32)
                            now += min(call["delay"], call["timeout"])

    def test_success_on_last_permitted_attempt(self):
        _, provider, _, checkout = self.stack(
            [(0.01, True), (0.01, True), (0.01, False)])
        self.assertEqual(checkout.execute("purchase", {"amount": 12})["receipt"],
                         "receipt-1")
        self.assertEqual(len(provider.calls), 3)
        self.assertEqual(len(provider.charges), 1)


if __name__ == "__main__":
    unittest.main()
