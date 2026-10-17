import uuid

class Gateway:
    def __init__(self,provider,policy):
        self.provider=provider;self.policy=policy

    def submit(self,payload,operation_id=None,timeout=None):
        for attempt in range(2):
            key=str(uuid.uuid4())
            limit=self.policy.per_attempt()
            try:return self.provider.send(payload,key,limit)
            except TimeoutError:
                if attempt==1:raise
