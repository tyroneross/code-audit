import uuid

class Gateway:
    def __init__(self,provider,policy):
        self.provider=provider;self.policy=policy

    def submit(self,payload,operation_id=None,timeout=None):
        # One provider attempt. The caller owns retries and must reuse operation_id so the
        # provider can deduplicate an effect whose response was lost.
        key=operation_id if operation_id is not None else str(uuid.uuid4())
        limit=self.policy.per_attempt(remaining=timeout)
        return self.provider.send(payload,key,limit)
