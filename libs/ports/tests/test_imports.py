from ports.interfaces import AuditSink, BlobStore, LockService, Queue, SecretStore
from ports.types import Lease, Message


def test_imports_and_instantiation() -> None:
    # Ensure types can be instantiated
    lease = Lease(token="test", fence=1)
    msg = Message(payload={"data": "test"}, idempotency_key="123")

    assert lease.fence == 1
    assert msg.schema_version == "1.0"

    # Ensure protocols are runtime checkable
    class DummyQueue:
        pass

    assert not isinstance(DummyQueue(), Queue)
    assert not isinstance(DummyQueue(), LockService)
    assert not isinstance(DummyQueue(), BlobStore)
    assert not isinstance(DummyQueue(), SecretStore)
    assert not isinstance(DummyQueue(), AuditSink)


def test_valid_implementation_runtime_checkable() -> None:
    class MockSecretStore:
        async def get(self, key: str) -> str:
            return "secret"

    assert isinstance(MockSecretStore(), SecretStore)
