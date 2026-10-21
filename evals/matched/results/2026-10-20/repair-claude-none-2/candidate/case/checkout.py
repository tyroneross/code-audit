class Checkout:
    def __init__(self,gateway,clock,max_attempts=3):
        if max_attempts<1:raise ValueError("max_attempts must be at least 1")
        self.gateway=gateway;self.clock=clock;self.max_attempts=max_attempts
        self._payloads={}

    def execute(self,operation_id,payload,total_timeout=1.0):
        prior=self._payloads.setdefault(operation_id,dict(payload))
        if prior!=payload:raise ValueError("operation identity reused with different payload")
        deadline=self.clock.now+total_timeout
        for _ in range(self.max_attempts):
            remaining=deadline-self.clock.now
            if remaining<=0:break
            try:return self.gateway.submit(payload,operation_id=operation_id,timeout=remaining)
            except TimeoutError:continue
        raise TimeoutError("checkout did not obtain a receipt within its budget; a charge may still have occurred")
