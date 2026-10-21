import uuid

class Gateway:
    def __init__(self,provider,policy):
        self.provider=provider;self.policy=policy

    def submit(self,payload,operation_id=None,timeout=None):
        # Only Checkout retries; the provider owns idempotency and payload checks.
        limit=self.policy.per_attempt(remaining=timeout)
        key=str(uuid.uuid4()) if operation_id is None else operation_id
        return self.provider.send(payload,key,limit)
