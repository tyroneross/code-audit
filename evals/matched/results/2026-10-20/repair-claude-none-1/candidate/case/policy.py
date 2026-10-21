class Policy:
    def __init__(self, profile=None, assumed_timeout=0.5):
        if assumed_timeout is None or assumed_timeout<=0:raise ValueError("assumed_timeout must be positive")
        self.profile=profile
        self.assumed_timeout=assumed_timeout

    def per_attempt(self, remaining=None):
        if remaining is not None and remaining<=0:raise TimeoutError("no budget left for another attempt")
        if self.profile:
            # Ordinary cold behavior (which bounds warm too) plus the network allowance.
            base=max(self.profile["cold_p99"],self.profile.get("warm_p99",0))+self.profile.get("network_allowance",0)
        else:
            base=self.assumed_timeout
        if base<=0:raise ValueError("profile yields a nonpositive timeout")
        return base if remaining is None else min(base,remaining)
