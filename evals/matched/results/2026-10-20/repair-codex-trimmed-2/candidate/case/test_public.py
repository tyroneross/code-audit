import unittest
from policy import Policy
from simulator import Clock,Provider
from gateway import Gateway
from checkout import Checkout

class Public(unittest.TestCase):
    def test_warm_success(self):
        clock=Clock();provider=Provider(clock)
        result=Checkout(Gateway(provider,Policy()),clock).execute("warm",{"amount":12})
        self.assertEqual(result,{"receipt":"receipt-1","amount":12})
