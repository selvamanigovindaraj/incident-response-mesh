from typing import Any

from pydantic import BaseModel, Field


class Lease(BaseModel):
    """
    Represents a distributed lock lease.
    """

    token: str = Field(description="Opaque lease identifier used for renewals/releases")
    fence: int = Field(
        description="Monotonically increasing fencing token for optimistic concurrency"
    )


class Message(BaseModel):
    """
    The standard envelope for all Queue communications.
    """

    payload: dict[str, Any]
    headers: dict[str, str] = Field(default_factory=dict)
    trace_context: dict[str, str] = Field(
        default_factory=dict,
        description="Reserved for 8.1 tracing injection",
    )
    idempotency_key: str
    schema_version: str = Field(
        default="1.0",
        description="Version of the payload schema to allow backwards-compatible routing",
    )
