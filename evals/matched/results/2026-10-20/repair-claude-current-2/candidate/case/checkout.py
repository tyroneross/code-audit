class Checkout:
    def __init__(self,gateway,clock,max_attempts=3):
        if max_attempts<1:raise ValueError("max_attempts must be at least 1")
        self.gateway=gateway;self.clock=clock;self.max_attempts=max_attempts

    def execute(self,operation_id,payload,total_timeout=1.0):
        # Sole retry owner: every attempt reuses operation_id and is capped by the remaining budget.
        deadline=self.clock.now+total_timeout
        for attempt in range(self.max_attempts):
            remaining=deadline-self.clock.now
            if remaining<=0:raise TimeoutError("checkout deadline exceeded; a charge may have happened")
            try:return self.gateway.submit(payload,operation_id=operation_id,timeout=remaining)
            except TimeoutError:
                if attempt==self.max_attempts-1:raise
