class Checkout:
    def __init__(self, gateway, clock, max_attempts=3):
        self.gateway = gateway
        self.clock = clock
        self.max_attempts = max_attempts

    def execute(self, operation_id, payload, total_timeout=1.0):
        deadline = self.clock.now + total_timeout
        for attempt in range(self.max_attempts):
            remaining = deadline - self.clock.now
            if remaining <= 0:
                raise TimeoutError("checkout deadline exceeded")
            try:
                return self.gateway.submit(
                    payload, operation_id=operation_id, timeout=remaining
                )
            except TimeoutError:
                if attempt == self.max_attempts - 1:
                    raise
        raise TimeoutError("checkout attempts exhausted")
