"""Request-local identity for the stateless hosted transport."""

from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class HostedRequest:
    api_key: str
    artifact_store: Any
    max_media_bytes: int = 100 * 1024 * 1024
    artifacts: list[dict[str, Any]] = field(default_factory=list)


hosted_request: ContextVar[HostedRequest | None] = ContextVar("nativ_hosted_request", default=None)
