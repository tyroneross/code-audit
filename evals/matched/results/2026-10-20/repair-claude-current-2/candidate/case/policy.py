class Policy:
    def __init__(self, profile=None, assumed_timeout=0.5):
        if assumed_timeout<=0:raise ValueError("assumed_timeout must be positive")
        self.profile=profile
        self.assumed_timeout=assumed_timeout

    def per_attempt(self, remaining=None):
        # Fit ordinary cold behavior plus network allowance; without data use the stated assumption.
        if self.profile:
            p=self.profile
            limit=max(p["warm_p99"],p["cold_p99"])+p["network_allowance"]
        else:
            limit=self.assumed_timeout
        if remaining is None:return limit
        if remaining<=0:raise TimeoutError("no budget remaining for another attempt")
        return min(limit,remaining)
