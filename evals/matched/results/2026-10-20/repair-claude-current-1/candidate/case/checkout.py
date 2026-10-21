class Checkout:
    def __init__(self,gateway,clock,max_attempts=3):
        self.gateway=gateway;self.clock=clock;self.max_attempts=max_attempts

    def execute(self,operation_id,payload,total_timeout=1.0):
        # Sole retry owner: every attempt reuses operation_id so the provider returns
        # the original receipt after a lost response, and each attempt is capped by
        # the remaining budget so the operation cannot overrun total_timeout.
        deadline=self.clock.now+total_timeout
        for attempt in range(self.max_attempts):
            remaining=deadline-self.clock.now
            if remaining<=0:break
            try:return self.gateway.submit(payload,operation_id=operation_id,timeout=remaining)
            except TimeoutError:pass
        raise TimeoutError("checkout got no receipt within its budget; a charge may have occurred")
