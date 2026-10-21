class Policy:
    def __init__(self, profile=None, assumed_timeout=0.5):
        self.profile = profile
        self.assumed_timeout = assumed_timeout

    def per_attempt(self, remaining=None):
        if remaining is not None and remaining <= 0:
            raise TimeoutError("attempt budget exhausted")
        if self.profile is None:
            limit = self.assumed_timeout
        else:
            limit = max(self.profile["warm_p99"], self.profile["cold_p99"])
            limit += self.profile["network_allowance"]
        if limit <= 0:
            raise ValueError("attempt timeout must be positive")
        return limit if remaining is None else min(limit, remaining)
