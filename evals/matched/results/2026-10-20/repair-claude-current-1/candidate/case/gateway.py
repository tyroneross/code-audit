import uuid

class Gateway:
    def __init__(self,provider,policy):
        self.provider=provider;self.policy=policy

    def submit(self,payload,operation_id=None,timeout=None):
        # One provider attempt. Retries belong to the caller, which reuses the same
        # operation_id so a lost response cannot produce a second charge.
        key=operation_id if operation_id is not None else str(uuid.uuid4())
        limit=self.policy.per_attempt(remaining=timeout)
        return self.provider.send(payload,key,limit)
