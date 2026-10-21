class Policy:
    def __init__(self, profile=None, assumed_timeout=0.5):
        self.profile=profile
        self.assumed_timeout=assumed_timeout

    def per_attempt(self, remaining=None):
        # Cover ordinary cold-start latency plus network allowance; without
        # profile data use the explicit assumption.
        if self.profile:
            p=self.profile
            limit=max(p["warm_p99"],p["cold_p99"])+p["network_allowance"]
        else:
            limit=self.assumed_timeout
        if limit<=0:raise ValueError("per-attempt timeout must be positive")
        if remaining is not None:
            if remaining<=0:raise TimeoutError("no time budget remaining")
            limit=min(limit,remaining)
        return limit
