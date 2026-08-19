from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import asdict
from typing import Protocol

from .models import Contact, Draft, ResearchBrief, Source
from .security import UNTRUSTED_CONTENT_RULE, neutralize_untrusted_text


class SearchProvider(Protocol):
    def search(self, query: str, max_results: int = 8) -> list[Source]:
        ...


class DraftProvider(Protocol):
    def create_brief(self, request: str, sources: list[Source], contacts: list[Contact]) -> ResearchBrief:
        ...

    def create_draft(self, request: str, contact: Contact, brief: ResearchBrief) -> str:
        ...

    def revise_draft(self, request: str, contact: Contact, brief: ResearchBrief, current_text: str, instructions: str) -> str:
        ...


class DryRunSearchProvider:
    def search(self, query: str, max_results: int = 8) -> list[Source]:
        return [
            Source(
                title="Dry Run Clinic A - Contact",
                url="https://example.com/clinic-a",
                snippet="Official contact page with WhatsApp and consultation details.",
                publisher="example.com",
                reliability="medium",
            ),
            Source(
                title="Dry Run Clinic B - Reviews",
                url="https://example.com/clinic-b-reviews",
                snippet="Recent patient reviews mention consultation process, location, and approximate pricing.",
                publisher="example.com",
                reliability="low",
            ),
            Source(
                title="Dry Run Clinic C - Official Website",
                url="https://example.com/clinic-c",
                snippet="Clinic website listing email address, phone number, and medical team overview.",
                publisher="example.com",
                reliability="medium",
            ),
        ][:max_results]


class TavilySearchProvider:
    def __init__(self, api_key: str):
        self.api_key = api_key

    def search(self, query: str, max_results: int = 8) -> list[Source]:
        body = json.dumps(
            {
                "api_key": self.api_key,
                "query": query,
                "search_depth": "advanced",
                "include_answer": False,
                "include_raw_content": False,
                "max_results": max_results,
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            "https://api.tavily.com/search",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Tavily search failed: {exc}") from exc

        sources: list[Source] = []
        for item in payload.get("results", []):
            content = item.get("content", "")
            sources.append(
                Source(
                    title=item.get("title", "Untitled source"),
                    url=item.get("url", ""),
                    snippet=content,
                    publisher=_publisher_from_url(item.get("url", "")),
                    reliability="medium",
                )
            )
        return sources


class RuleBasedDraftProvider:
    def __init__(self, sender_name: str = "Your Name"):
        self.sender_name = sender_name

    def create_brief(self, request: str, sources: list[Source], contacts: list[Contact]) -> ResearchBrief:
        ranked_options = []
        for index, contact in enumerate(contacts, start=1):
            ranked_options.append(
                {
                    "rank": index,
                    "name": contact.name,
                    "confidence": contact.confidence,
                    "reason": contact.notes or "Has at least one cited source and a draftable contact route.",
                    "source_url": contact.source_url,
                }
            )
        uncertainty = [
            "Dry-run or search-result snippets are not enough for final decisions; verify details on official websites before sending.",
            "Prices and availability are not assumed unless present in a cited source.",
        ]
        summary = f"Research task: {request}. Found {len(contacts)} draftable option(s) from {len(sources)} source(s)."
        return ResearchBrief(summary=summary, ranked_options=ranked_options, uncertainty=uncertainty)

    def create_draft(self, request: str, contact: Contact, brief: ResearchBrief) -> str:
        org = contact.organization or contact.name
        contact_line = "I found your details while researching suitable options and wanted to ask a few questions."
        if contact.source_url:
            contact_line = f"I found your details via {contact.source_url} and wanted to ask a few questions."
        return (
            f"Hello {org},\n\n"
            f"{contact_line}\n\n"
            f"I am researching options for: {request}.\n\n"
            "Could you please share your current availability, typical process, indicative pricing where possible, "
            "and what information you would need from me to advise properly?\n\n"
            "Thanks,\n"
            f"{self.sender_name}"
        )

    def revise_draft(self, request: str, contact: Contact, brief: ResearchBrief, current_text: str, instructions: str) -> str:
        org = contact.organization or contact.name
        context = _extract_mentioned_context(instructions)
        context_line = f"\n\n{context} would suit me if available." if context else ""
        return (
            f"Hello {org},\n\n"
            f"I am looking into: {_first_line(request)}.{context_line}\n\n"
            "Could you let me know your availability, process, and indicative pricing where possible?\n\n"
            "Thanks,\n"
            f"{self.sender_name}"
        )


class AnthropicDraftProvider:
    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    def create_brief(self, request: str, sources: list[Source], contacts: list[Contact]) -> ResearchBrief:
        safe_sources = [
            {
                **asdict(source),
                "snippet": neutralize_untrusted_text(source.snippet),
            }
            for source in sources
        ]
        prompt = (
            f"{UNTRUSTED_CONTENT_RULE}\n\n"
            "Create a concise sourced research brief. Separate verified facts from inferences. "
            "Return JSON with keys: summary, ranked_options, uncertainty.\n\n"
            f"User request: {request}\n"
            f"Sources: {json.dumps(safe_sources, ensure_ascii=False)}\n"
            f"Contacts: {json.dumps([asdict(c) for c in contacts], ensure_ascii=False)}"
        )
        data = self._json_message(prompt)
        return ResearchBrief(
            summary=data.get("summary", ""),
            ranked_options=data.get("ranked_options", []),
            uncertainty=data.get("uncertainty", []),
        )

    def create_draft(self, request: str, contact: Contact, brief: ResearchBrief) -> str:
        prompt = (
            f"{UNTRUSTED_CONTENT_RULE}\n\n"
            "Draft a friendly but professional outreach message. Do not invent facts, prices, credentials, or availability. "
            "Ask for missing information. Keep it concise.\n\n"
            f"User request: {request}\n"
            f"Contact: {json.dumps(asdict(contact), ensure_ascii=False)}\n"
            f"Brief: {json.dumps(asdict(brief), ensure_ascii=False)}"
        )
        return self._text_message(prompt).strip()

    def revise_draft(self, request: str, contact: Contact, brief: ResearchBrief, current_text: str, instructions: str) -> str:
        prompt = (
            f"{UNTRUSTED_CONTENT_RULE}\n\n"
            "Revise this outreach draft using the user's edit instructions. Keep it friendly, professional, concise, "
            "and do not invent facts, prices, credentials, or availability.\n\n"
            f"User request: {request}\n"
            f"Contact: {json.dumps(asdict(contact), ensure_ascii=False)}\n"
            f"Brief: {json.dumps(asdict(brief), ensure_ascii=False)}\n"
            f"Current draft: {current_text}\n"
            f"Edit instructions: {instructions}"
        )
        return self._text_message(prompt).strip()

    def _text_message(self, prompt: str) -> str:
        body = json.dumps(
            {
                "model": self.model,
                "max_tokens": 4096,
                "messages": [{"role": "user", "content": prompt[:12000]}],
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=body,
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Anthropic request failed: {exc}") from exc
        parts = payload.get("content", [])
        return "\n".join(part.get("text", "") for part in parts if part.get("type") == "text")

    def _json_message(self, prompt: str) -> dict:
        text = self._text_message(prompt)
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise RuntimeError(f"Model did not return JSON: {text[:300]}")
        return json.loads(match.group(0))


def _publisher_from_url(url: str) -> str:
    match = re.match(r"https?://([^/]+)", url or "")
    return match.group(1).removeprefix("www.") if match else ""


def _first_line(text: str) -> str:
    return next((line.strip().rstrip(".") for line in text.splitlines() if line.strip()), text.strip().rstrip("."))


def _extract_mentioned_context(instructions: str) -> str:
    match = re.search(r"\bmention\s+(.+)", instructions, re.I)
    value = match.group(1) if match else ""
    value = re.sub(r"[.?!]+$", "", value.strip())
    return value[:120]
