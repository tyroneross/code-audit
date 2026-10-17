class Policy:
    def __init__(self, profile=None, assumed_timeout=0.5):
        self.profile=profile
        self.assumed_timeout=assumed_timeout

    def per_attempt(self, remaining=None):
        # One attempt must cover the slow (cold) path plus network allowance;
        # without profile data fall back to the explicit assumption.
        if remaining is not None and remaining<=0:raise TimeoutError("no time budget remaining")
        if self.profile:
            p=self.profile
            limit=max(p["warm_p99"],p["cold_p99"])+p["network_allowance"]
        else:
            limit=self.assumed_timeout
        if limit<=0:raise ValueError("per-attempt timeout must be positive")
        return limit if remaining is None else min(limit,remaining)
