import json
from pathlib import Path
import unittest

from checkout import Checkout
from gateway import Gateway
from policy import Policy
from simulator import Clock, Provider


class Repair(unittest.TestCase):
    def make_checkout(self, steps=(), max_attempts=3, profile=None):
        clock = Clock()
        provider = Provider(clock, steps)
        gateway = Gateway(provider, Policy(profile))
        return clock, provider, gateway, Checkout(gateway, clock, max_attempts)

    def test_lost_response_retry_preserves_identity(self):
        clock, provider, _, checkout = self.make_checkout([(0.01, True)])
        self.assertEqual(checkout.execute('sale', {'amount': 12})['receipt'], 'receipt-1')
        self.assertEqual(len(provider.charges), 1)
        self.assertEqual([c['operation_id'] for c in provider.calls], ['sale', 'sale'])

    def test_repeated_execution_after_exhaustion_reconciles(self):
        _, provider, _, checkout = self.make_checkout([(0.01, True)], max_attempts=1)
        with self.assertRaises(TimeoutError):
            checkout.execute('sale', {'amount': 12})
        result = checkout.execute('sale', {'amount': 12})
        self.assertEqual(result, {'receipt': 'receipt-1', 'amount': 12})
        self.assertEqual(len(provider.charges), 1)

    def test_repeated_success_conflict_and_new_action(self):
        _, provider, _, checkout = self.make_checkout()
        first = checkout.execute('sale', {'amount': 12})
        self.assertEqual(checkout.execute('sale', {'amount': 12}), first)
        with self.assertRaises(ValueError):
            checkout.execute('sale', {'amount': 13})
        self.assertEqual(len(provider.charges), 1)
        self.assertNotEqual(checkout.execute('new-sale', {'amount': 12}), first)
        self.assertEqual(len(provider.charges), 2)

    def test_gateway_is_one_attempt_even_on_failure(self):
        _, provider, gateway, _ = self.make_checkout([(0.01, True)])
        with self.assertRaises(TimeoutError):
            gateway.submit({'amount': 12}, operation_id='sale')
        self.assertEqual(len(provider.calls), 1)

    def test_standalone_identities_and_explicit_empty_identity(self):
        _, provider, gateway, _ = self.make_checkout()
        gateway.submit({'amount': 12})
        gateway.submit({'amount': 12})
        self.assertNotEqual(provider.calls[0]['operation_id'], provider.calls[1]['operation_id'])
        first = gateway.submit({'amount': 12}, operation_id='')
        self.assertEqual(gateway.submit({'amount': 12}, operation_id=''), first)
        self.assertEqual(len(provider.charges), 3)

    def test_cold_profile_success(self):
        profile = json.loads(Path(__file__).with_name('profile.json').read_text())
        clock, provider, _, checkout = self.make_checkout(
            [(profile['cold_p99'] + profile['network_allowance'], False)], profile=profile)
        checkout.execute('cold', {'amount': 12})
        self.assertEqual(len(provider.calls), 1)
        self.assertAlmostEqual(clock.now, 0.32)

    def test_profile_selection_and_changes(self):
        profile = {'warm_p99': 0.08, 'cold_p99': 0.30, 'network_allowance': 0.02}
        policy = Policy(profile)
        self.assertAlmostEqual(policy.per_attempt(), 0.32)
        profile['cold_p99'] = 0.60
        self.assertAlmostEqual(policy.per_attempt(), 0.62)
        profile['warm_p99'] = 0.70
        self.assertAlmostEqual(policy.per_attempt(), 0.72)
        profile['network_allowance'] = 0.04
        self.assertAlmostEqual(policy.per_attempt(), 0.74)
        self.assertEqual(policy.per_attempt(0.1), 0.1)

    def test_assumed_timeout_and_exhausted_policy_budget(self):
        policy = Policy(assumed_timeout=0.7)
        self.assertEqual(policy.per_attempt(), 0.7)
        self.assertEqual(policy.per_attempt(0.2), 0.2)
        for remaining in (0, -1):
            with self.subTest(remaining=remaining), self.assertRaises(TimeoutError):
                policy.per_attempt(remaining)

    def test_gateway_timeout_is_cap(self):
        clock, provider, gateway, _ = self.make_checkout([(1, False)])
        with self.assertRaises(TimeoutError):
            gateway.submit({'amount': 12}, 'sale', timeout=0.03)
        self.assertEqual(provider.calls[0]['timeout'], 0.03)
        self.assertAlmostEqual(clock.now, 0.03)
        for timeout in (0, -1):
            with self.subTest(timeout=timeout), self.assertRaises(TimeoutError):
                gateway.submit({'amount': 12}, 'other', timeout=timeout)
        self.assertEqual(len(provider.calls), 1)

    def test_attempt_budget_and_deadline_matrix(self):
        for attempts in (0, 1, 2, 3, 5):
            for total in (0, -0.1, 0.03, 0.5, 0.7, 2.0):
                with self.subTest(attempts=attempts, total=total):
                    clock, provider, _, checkout = self.make_checkout(
                        [(10, False)] * 20, max_attempts=attempts)
                    clock.advance(5)
                    start = clock.now
                    with self.assertRaises(TimeoutError):
                        checkout.execute('sale', {'amount': 12}, total)
                    self.assertLessEqual(len(provider.calls), attempts)
                    self.assertLessEqual(clock.now, start + max(0, total))
                    self.assertTrue(all(c['timeout'] > 0 for c in provider.calls))
                    self.assertLessEqual(len(provider.charges), 1)
                    if attempts > 0 and total > 0:
                        self.assertGreater(len(provider.calls), 0)

    def test_retry_uses_remaining_time(self):
        clock, provider, _, checkout = self.make_checkout([(0.02, True), (10, False)])
        with self.assertRaises(TimeoutError):
            checkout.execute('sale', {'amount': 12}, 0.03)
        self.assertEqual(len(provider.calls), 2)
        self.assertAlmostEqual(provider.calls[1]['timeout'], 0.01)
        self.assertLessEqual(clock.now, 0.03)
        self.assertEqual(len(provider.charges), 1)

    def test_payload_error_is_not_retried(self):
        _, provider, _, checkout = self.make_checkout()
        with self.assertRaises(KeyError):
            checkout.execute('sale', {})
        self.assertEqual(len(provider.charges), 0)
        self.assertEqual(len(provider.calls), 0)


if __name__ == '__main__':
    unittest.main()
