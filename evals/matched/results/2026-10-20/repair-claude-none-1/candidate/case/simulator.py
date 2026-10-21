class Clock:
    def __init__(self):self.now=0.0
    def advance(self,seconds):self.now+=seconds

class Provider:
    def __init__(self,clock,steps=()):
        self.clock=clock;self.steps=list(steps);self.calls=[];self.charges=[];self.receipts={}

    def send(self,payload,operation_id,timeout):
        if timeout<=0:raise ValueError("timeout must be positive")
        if operation_id in self.receipts:
            prior_payload,receipt=self.receipts[operation_id]
            if prior_payload!=payload:raise ValueError("operation identity reused with different payload")
        else:
            receipt={"receipt":f"receipt-{len(self.charges)+1}","amount":payload["amount"]}
            self.receipts[operation_id]=(dict(payload),dict(receipt))
            self.charges.append((operation_id,dict(payload)))
        delay,lost_ack=self.steps.pop(0) if self.steps else (0.01,False)
        self.calls.append({"operation_id":operation_id,"timeout":timeout,"delay":delay})
        self.clock.advance(min(delay,timeout))
        if delay>timeout or lost_ack:raise TimeoutError("response unavailable; effect may have happened")
        return dict(receipt)
