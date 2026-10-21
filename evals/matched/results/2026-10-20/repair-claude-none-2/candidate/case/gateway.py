import uuid

class Gateway:
    def __init__(self,provider,policy):
        self.provider=provider;self.policy=policy

    def submit(self,payload,operation_id=None,timeout=None):
        # Exactly one provider attempt; retries belong to the caller so they stay within its budget.
        key=operation_id if operation_id is not None else str(uuid.uuid4())
        limit=self.policy.per_attempt(timeout)
        return self.provider.send(payload,key,limit)
