"""Stable, source-neutral records used by every public collector."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class Target:
    """One explicitly configured public source target."""

    source: str
    name: str
    config: dict[str, Any]


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    """One attributable public discussion unit, not a claimed pain point."""

    source: str
    source_id: str
    thread_id: str
    source_type: str
    title: str
    author: str
    url: str
    text: str
    created_at: str | None = None
    updated_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-safe audit representation."""
        return asdict(self)
