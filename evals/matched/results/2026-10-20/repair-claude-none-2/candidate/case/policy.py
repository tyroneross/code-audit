import json

class Policy:
    def __init__(self, profile=None, assumed_timeout=0.5):
        if isinstance(profile,str):
            with open(profile) as f:profile=json.load(f)
        if assumed_timeout is None or assumed_timeout<=0:raise ValueError("assumed_timeout must be positive")
        self.profile=profile
        self.assumed_timeout=assumed_timeout

    def per_attempt(self, remaining=None):
        if remaining is not None and remaining<=0:raise TimeoutError("no budget remaining for another attempt")
        if self.profile:
            # Size for the ordinary cold path, not the warm one, plus network slack.
            limit=max(self.profile["warm_p99"],self.profile["cold_p99"])+self.profile["network_allowance"]
        else:
            limit=self.assumed_timeout
        if limit<=0:raise ValueError("profile yields a nonpositive timeout")
        return limit if remaining is None else min(limit,remaining)
