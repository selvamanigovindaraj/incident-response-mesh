"""
Reusable pytest contract test suites for cloud-agnostic ports.
"""

from ports_testing.contracts.lock import (
    LockConfig,
    lock_config,
    test_lock_concurrency_twenty_contenders,
    test_lock_fencing_tokens_are_strictly_monotonic,
    test_lock_renew_successfully_extends_ttl,
    test_lock_stale_lease_release_noop,
    test_lock_ttl_expiration_allows_takeover,
)
from ports_testing.contracts.queue import (
    QueueConfig,
    queue_config,
    test_queue_consumer_group_fanout,
    test_queue_dlq_routing_after_max_retries,
    test_queue_idempotency_deduplication,
    test_queue_nack_redelivery,
    test_queue_nack_without_requeue_routes_to_dlq,
    test_queue_publish_and_consume,
    test_queue_visibility_timeout_redelivery,
)

__all__ = [
    "LockConfig",
    "QueueConfig",
    "lock_config",
    "queue_config",
    "test_lock_concurrency_twenty_contenders",
    "test_lock_fencing_tokens_are_strictly_monotonic",
    "test_lock_renew_successfully_extends_ttl",
    "test_lock_stale_lease_release_noop",
    "test_lock_ttl_expiration_allows_takeover",
    "test_queue_consumer_group_fanout",
    "test_queue_dlq_routing_after_max_retries",
    "test_queue_idempotency_deduplication",
    "test_queue_nack_redelivery",
    "test_queue_nack_without_requeue_routes_to_dlq",
    "test_queue_publish_and_consume",
    "test_queue_visibility_timeout_redelivery",
]
