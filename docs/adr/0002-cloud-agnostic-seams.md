# 2. Cloud-Agnostic Seams
Date: 2026-09-02

## Status
Accepted

## Context
The Incident Response Mesh requires core infrastructure capabilities—such as message queues, distributed locks, blob storage, secrets management, and audit logging—while remaining portable across AWS, GCP, and local development environments without vendor lock-in. We need clean, strongly-typed boundaries separating domain logic from underlying infrastructure implementations.

## Decision
We will define cloud-agnostic seams as Python Protocols (`typing.Protocol` with `@runtime_checkable`) in the `libs/ports` package:
1. `Queue`: Message queuing with at-least-once delivery, visibility timeouts, and ack/nack semantics.
2. `LockService`: Distributed locking with TTL expiration and fencing tokens.
3. `BlobStore`: Object storage with content-addressable storage support.
4. `SecretStore`: Strongly-consistent secret retrieval.
5. `AuditSink`: Append-only, immutable audit logging with monotonic sequence numbers.

Deliberately NOT Abstracted:
- **Postgres Checkpointer:** LangGraph already provides a native Checkpointer interface. Wrapping an existing checkpointer abstraction in another custom abstraction introduces unnecessary leaky layers.
- **Kubernetes API:** Kubernetes serves as the universal baseline deployment and runtime platform. Creating a generic container/workload abstraction would be an anti-pattern.

## Consequences
- Agents and services depend only on `libs/ports` interfaces, enabling pluggable adapters for local mocks, AWS (e.g. SQS, S3, Secrets Manager, DynamoDB), or GCP (e.g. Pub/Sub, GCS, Secret Manager).
- Testing can use lightweight in-memory or fake implementations conforming to the protocols.
- Avoids over-abstraction by relying directly on established standards (LangGraph checkpointer, Kubernetes API) where appropriate.
