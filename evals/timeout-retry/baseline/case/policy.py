class Policy:
    def __init__(self, profile=None, assumed_timeout=0.5):
        self.profile=profile
        self.assumed_timeout=assumed_timeout

    def per_attempt(self, remaining=None):
        return 0.05
