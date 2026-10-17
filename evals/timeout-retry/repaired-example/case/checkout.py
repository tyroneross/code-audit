class Checkout:
    def __init__(self,gateway,clock,max_attempts=3):
        if max_attempts<1:raise ValueError("max_attempts must be at least 1")
        self.gateway=gateway;self.clock=clock;self.max_attempts=max_attempts

    def execute(self,operation_id,payload,total_timeout=1.0):
        deadline=self.clock.now+total_timeout
        error=None
        for attempt in range(self.max_attempts):
            remaining=deadline-self.clock.now
            if remaining<=0:break
            try:return self.gateway.submit(payload,operation_id=operation_id,timeout=remaining)
            except TimeoutError as exc:error=exc
        raise TimeoutError("checkout deadline or attempts exhausted; charge may have happened") from error
