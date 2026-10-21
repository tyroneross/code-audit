import json
from itertools import product
from pathlib import Path
import unittest

from checkout import Checkout
from gateway import Gateway
from policy import Policy
from simulator import Clock, Provider


class Repair(unittest.TestCase):
    def stack(self, steps=(), policy=None, max_attempts=3):
        clock = Clock()
        provider = Provider(clock, steps)
        gateway = Gateway(provider, policy or Policy())
        return clock, provider, gateway, Checkout(gateway, clock, max_attempts)

    def test_lost_ack_retries_same_effect(self):
        clock, provider, _, checkout = self.stack([(0.01, True), (0.01, False)])
        self.assertEqual(checkout.execute('order', {'amount': 12}),
                         {'receipt': 'receipt-1', 'amount': 12})
        self.assertEqual(len(provider.charges), 1)
        self.assertEqual([call['operation_id'] for call in provider.calls], ['order'] * 2)

    def test_repeat_after_exhaustion_and_payload_conflict(self):
        _, provider, _, checkout = self.stack([(0.01, True)], max_attempts=1)
        with self.assertRaises(TimeoutError):
            checkout.execute('order', {'amount': 12})
        result = checkout.execute('order', {'amount': 12})
        self.assertEqual(result, {'receipt': 'receipt-1', 'amount': 12})
        with self.assertRaises(ValueError):
            checkout.execute('order', {'amount': 13})
        self.assertEqual(len(provider.charges), 1)
        self.assertEqual(checkout.execute('other', {'amount': 12})['receipt'], 'receipt-2')

    def test_standalone_calls_have_independent_identity(self):
        _, provider, gateway, _ = self.stack()
        gateway.submit({'amount': 12})
        gateway.submit({'amount': 12})
        self.assertEqual(len(provider.charges), 2)
        self.assertNotEqual(provider.calls[0]['operation_id'], provider.calls[1]['operation_id'])

    def test_gateway_is_one_attempt_even_after_loss(self):
        _, provider, gateway, _ = self.stack([(0.01, True)])
        with self.assertRaises(TimeoutError):
            gateway.submit({'amount': 12})
        self.assertEqual(len(provider.calls), 1)

    def test_attempt_limit_is_owned_by_checkout(self):
        for attempts in (1, 2, 3, 4):
            with self.subTest(attempts=attempts):
                _, provider, _, checkout = self.stack([(0.01, True)] * 10,
                                                       max_attempts=attempts)
                with self.assertRaises(TimeoutError):
                    checkout.execute('order', {'amount': 12}, 10)
                self.assertEqual(len(provider.calls), attempts)
                self.assertEqual(len(provider.charges), 1)

    def test_cold_profile_succeeds_on_first_attempt(self):
        profile = json.loads(Path(__file__).with_name('profile.json').read_text())
        clock, provider, _, checkout = self.stack([(profile['cold_p99'], False)], Policy(profile))
        self.assertEqual(checkout.execute('cold', {'amount': 12})['receipt'], 'receipt-1')
        self.assertEqual(len(provider.calls), 1)
        self.assertGreaterEqual(provider.calls[0]['timeout'],
                                profile['cold_p99'] + profile['network_allowance'])
        self.assertEqual(clock.now, profile['cold_p99'])

    def test_profile_and_fallback_limits(self):
        self.assertEqual(Policy(assumed_timeout=0.7).per_attempt(), 0.7)
        for warm, cold, allowance in ((0.08, 0.3, 0.02), (0.08, 0.6, 0.02),
                                      (0.8, 0.3, 0.02), (0.08, 0.3, 0.2)):
            with self.subTest(warm=warm, cold=cold, allowance=allowance):
                policy = Policy(dict(warm_p99=warm, cold_p99=cold,
                                     network_allowance=allowance))
                self.assertAlmostEqual(policy.per_attempt(), max(warm, cold) + allowance)
                self.assertEqual(policy.per_attempt(0.01), 0.01)

    def test_gateway_caps_policy_with_explicit_timeout(self):
        clock, provider, gateway, _ = self.stack([(1, False)])
        with self.assertRaises(TimeoutError):
            gateway.submit({'amount': 12}, 'order', timeout=0.03)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(provider.calls[0]['timeout'], 0.03)
        self.assertEqual(clock.now, 0.03)

    def test_deadline_caps_each_attempt(self):
        for budget in (0.01, 0.1, 0.5, 0.75, 1.0):
            with self.subTest(budget=budget):
                clock, provider, _, checkout = self.stack([(10, False)] * 10)
                clock.advance(2)
                with self.assertRaises(TimeoutError):
                    checkout.execute('order', {'amount': 12}, budget)
                self.assertLessEqual(clock.now, 2 + budget)
                self.assertLessEqual(len(provider.calls), checkout.max_attempts)
                elapsed = 0
                for call in provider.calls:
                    self.assertLessEqual(call['timeout'], 2 + budget - (2 + elapsed))
                    elapsed += min(call['delay'], call['timeout'])

    def test_nonpositive_budgets_do_not_start_work(self):
        for budget in (0, -1):
            with self.subTest(budget=budget):
                clock, provider, gateway, checkout = self.stack()
                with self.assertRaises(TimeoutError):
                    checkout.execute('order', {'amount': 12}, budget)
                with self.assertRaises(TimeoutError):
                    gateway.submit({'amount': 12}, 'order', timeout=budget)
                with self.assertRaises(TimeoutError):
                    Policy().per_attempt(budget)
                self.assertEqual(provider.calls, [])
                self.assertEqual(provider.charges, [])
                self.assertEqual(clock.now, 0)

    def test_zero_attempts_raises_timeout_without_work(self):
        _, provider, _, checkout = self.stack(max_attempts=0)
        with self.assertRaises(TimeoutError):
            checkout.execute('order', {'amount': 12})
        self.assertEqual(provider.charges, [])

    def test_identity_survives_new_coordinator_and_gateway(self):
        clock, provider, _, checkout = self.stack([(0.01, True)], max_attempts=1)
        with self.assertRaises(TimeoutError):
            checkout.execute('', {'amount': 12})
        recreated = Checkout(Gateway(provider, Policy()), clock)
        self.assertEqual(recreated.execute('', {'amount': 12}),
                         {'receipt': 'receipt-1', 'amount': 12})
        self.assertEqual(len(provider.charges), 1)
        with self.assertRaises(ValueError):
            recreated.execute('', {'amount': 13})

    def test_receipt_at_exact_timeout_is_preserved(self):
        clock, provider, _, checkout = self.stack([(0.125, False)])
        self.assertEqual(checkout.execute('order', {'amount': 12}, 0.125),
                         {'receipt': 'receipt-1', 'amount': 12})
        self.assertEqual(clock.now, 0.125)
        self.assertEqual(len(provider.calls), 1)

    def test_deterministic_failure_path_matrix(self):
        # 1,536 combinations, with time advanced solely by the simulator.
        profiles = (None, dict(warm_p99=0.08, cold_p99=0.3, network_allowance=0.02))
        for profile, budget, attempts, delay1, delay2, lost1, lost2 in product(
                profiles, (0, 0.01, 0.125, 0.8), (0, 1, 3),
                (0, 0.01, 0.3, 1), (0, 0.01, 0.3, 1), (False, True), (False, True)):
            case = (profile, budget, attempts, delay1, delay2, lost1, lost2)
            with self.subTest(case=case):
                clock, provider, _, checkout = self.stack(
                    [(delay1, lost1), (delay2, lost2), (10, True)],
                    Policy(profile), attempts)
                try:
                    result = checkout.execute('order', {'amount': 12}, budget)
                except TimeoutError:
                    self.assertTrue(clock.now >= budget or len(provider.calls) == attempts)
                else:
                    self.assertEqual(result, {'receipt': 'receipt-1', 'amount': 12})
                    last = provider.calls[-1]
                    last_lost = (lost1, lost2, True)[len(provider.calls) - 1]
                    self.assertFalse(last_lost)
                    self.assertLessEqual(last['delay'], last['timeout'])
                self.assertLessEqual(clock.now, budget)
                self.assertLessEqual(len(provider.calls), attempts)
                self.assertEqual(len(provider.charges), int(bool(provider.calls)))
                self.assertTrue(all(call['operation_id'] == 'order' for call in provider.calls))
                elapsed = 0
                for call in provider.calls:
                    self.assertGreater(call['timeout'], 0)
                    self.assertLessEqual(call['timeout'], budget - elapsed)
                    elapsed += min(call['delay'], call['timeout'])


if __name__ == '__main__':
    unittest.main()
