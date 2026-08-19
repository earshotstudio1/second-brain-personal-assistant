from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class Source:
    title: str
    url: str
    snippet: str = ""
    publisher: str = ""
    published_at: str = ""
    reliability: str = "medium"


@dataclass(frozen=True)
class Contact:
    name: str
    organization: str = ""
    email: str = ""
    phone: str = ""
    whatsapp: str = ""
    website_url: str = ""
    source_url: str = ""
    confidence: str = "medium"
    notes: str = ""


@dataclass(frozen=True)
class Draft:
    contact_id: str
    channel: str
    text: str
    status: str = "pending"
    approved_text: str = ""
    version: int = 1


@dataclass(frozen=True)
class ResearchBrief:
    summary: str
    ranked_options: list[dict[str, Any]] = field(default_factory=list)
    uncertainty: list[str] = field(default_factory=list)

