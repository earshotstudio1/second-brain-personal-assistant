from __future__ import annotations

import re

from .models import Contact, Source
from .security import detect_prompt_injection


EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?:\+?\d[\d\s().-]{7,}\d)")


def build_research_queries(user_request: str) -> list[str]:
    base = user_request.strip()
    return [
        base,
        f"{base} official contact email WhatsApp",
        f"{base} reviews pricing availability",
    ]


def contacts_from_sources(sources: list[Source], max_contacts: int = 5) -> list[Contact]:
    contacts: list[Contact] = []
    seen: set[str] = set()
    for source in sources:
        label = _clean_title(source.title)
        key = (label or source.url).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        email = _first(EMAIL_RE.findall(source.snippet))
        phone = _first(PHONE_RE.findall(source.snippet))
        injection_hits = detect_prompt_injection(source.snippet)
        confidence = "high" if source.reliability == "high" and source.url else "medium"
        if not email and not phone and "contact" not in source.snippet.lower() and "whatsapp" not in source.snippet.lower():
            confidence = "low"
        notes = "Official or contact-focused source preferred." if "contact" in source.title.lower() or "official" in source.title.lower() else "Needs verification before manual sending."
        if injection_hits:
            notes += f" Possible prompt injection pattern detected: {', '.join(injection_hits)}."
            confidence = "low"
        contacts.append(
            Contact(
                name=label or "Unnamed option",
                organization=label,
                email=email,
                phone=phone,
                whatsapp=phone if "whatsapp" in source.snippet.lower() else "",
                website_url=source.url,
                source_url=source.url,
                confidence=confidence,
                notes=notes,
            )
        )
        if len(contacts) >= max_contacts:
            break
    return contacts


def _first(items: list[str]) -> str:
    return items[0].strip() if items else ""


def _clean_title(title: str) -> str:
    value = re.sub(r"\s+[-|].*$", "", title or "").strip()
    return value[:120]

