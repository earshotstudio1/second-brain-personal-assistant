from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import asdict
from typing import Any, Callable, Protocol

from .config import model_capabilities
from .models import Contact, Draft, DraftReview, ResearchBrief, Source
from .security import UNTRUSTED_CONTENT_RULE, neutralize_untrusted_text
from .voice import QUALITY_CHECKLIST, VOICE_RULES, better_draft, voice_violations

# Structured output schemas. Constraining the response to a schema removes the
# "find the JSON somewhere in the prose" step, which is where a cheaper model is
# most likely to wobble.
BRIEF_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "options": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "rank": {"type": "integer"},
                    "name": {"type": "string"},
                    "reason": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                    "source_url": {"type": "string"},
                },
                "required": ["rank", "name", "reason", "confidence", "source_url"],
                "additionalProperties": False,
            },
        },
        "recommendation": {"type": "string"},
        "sources": {"type": "array", "items": {"type": "string"}},
        "open_questions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "options", "recommendation", "sources", "open_questions"],
    "additionalProperties": False,
}

REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "passed": {"type": "boolean"},
        "issues": {"type": "array", "items": {"type": "string"}},
        "fixes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["passed", "issues", "fixes"],
    "additionalProperties": False,
}

DRAFT_SYSTEM_PROMPT = f"{UNTRUSTED_CONTENT_RULE}\n\n{QUALITY_CHECKLIST}"

REVIEW_SYSTEM_PROMPT = (
    f"{UNTRUSTED_CONTENT_RULE}\n\n"
    "You are reviewing another model's output against acceptance criteria. Be strict and specific. "
    "Report only breaches you can point at in the text.\n\n"
    f"{QUALITY_CHECKLIST}"
)


def needs_revision(review: DraftReview, draft_text: str) -> bool:
    """Decide whether a draft goes round again.

    The reviewing model can say the draft passed while the draft still breaks a
    voice rule, so the local checks get a veto.
    """
    return not review.passed or bool(voice_violations(draft_text))


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
        recommendation = (
            f"Start with {ranked_options[0]['name']} and confirm details directly."
            if ranked_options
            else "No option has enough evidence to recommend yet."
        )
        return ResearchBrief(
            summary=summary,
            ranked_options=ranked_options,
            uncertainty=uncertainty,
            recommendation=recommendation,
            sources=[source.url for source in sources if source.url],
        )

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
    """Drafting provider with the quality scaffolding a cheaper model needs.

    Three things carry the quality: the research brief is constrained to a JSON
    schema, the acceptance criteria travel in the system prompt on every call,
    and each outreach draft gets one self-review pass with at most one revision.
    """

    ENDPOINT = "https://api.anthropic.com/v1/messages"

    def __init__(
        self,
        api_key: str,
        model: str,
        review_model: str | None = None,
        transport: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ):
        self.api_key = api_key
        self.model = model
        self.review_model = review_model or model
        # Injectable so tests can exercise the full decision path without network.
        self._transport = transport or self._http_post

    def create_brief(self, request: str, sources: list[Source], contacts: list[Contact]) -> ResearchBrief:
        safe_sources = [
            {
                **asdict(source),
                "snippet": neutralize_untrusted_text(source.snippet),
            }
            for source in sources
        ]
        allowed_urls = [source.url for source in sources if source.url]
        prompt = (
            "Create a concise sourced research brief. Separate verified facts from inferences. "
            "Rank the options, give one recommendation, and list the questions the sources do not answer.\n"
            f"Cite only these URLs: {json.dumps(allowed_urls, ensure_ascii=False)}\n\n"
            f"User request: {request}\n"
            f"Sources: {json.dumps(safe_sources, ensure_ascii=False)}\n"
            f"Contacts: {json.dumps([asdict(c) for c in contacts], ensure_ascii=False)}"
        )
        data = self._structured_message(prompt, BRIEF_SCHEMA, thinking=True)
        # Schema keys are written for the model; the dataclass keeps the names the
        # rest of the app and the Obsidian note already use.
        return ResearchBrief(
            summary=data.get("summary", ""),
            ranked_options=data.get("options", []),
            uncertainty=data.get("open_questions", []),
            recommendation=data.get("recommendation", ""),
            sources=data.get("sources", []),
        )

    def create_draft(self, request: str, contact: Contact, brief: ResearchBrief) -> str:
        prompt = (
            "Draft a friendly but professional outreach message. Do not invent facts, prices, credentials, or availability. "
            "Ask for missing information. Keep it concise.\n\n"
            f"User request: {request}\n"
            f"Contact: {json.dumps(asdict(contact), ensure_ascii=False)}\n"
            f"Brief: {json.dumps(asdict(brief), ensure_ascii=False)}"
        )
        draft = self._text_message(prompt, thinking=True).strip()

        review = self.review_draft(request, brief, draft)
        if not needs_revision(review, draft):
            return draft

        revision_prompt = (
            "Revise the draft so it satisfies every acceptance criterion. Change only what the review calls out.\n\n"
            f"User request: {request}\n"
            f"Contact: {json.dumps(asdict(contact), ensure_ascii=False)}\n"
            f"Brief: {json.dumps(asdict(brief), ensure_ascii=False)}\n"
            f"Current draft: {draft}\n"
            f"Review issues: {json.dumps(review.issues, ensure_ascii=False)}\n"
            f"Required fixes: {json.dumps(review.fixes, ensure_ascii=False)}\n"
            f"Local checks also flagged: {json.dumps(voice_violations(draft), ensure_ascii=False)}"
        )
        revised = self._text_message(revision_prompt, thinking=True).strip()
        # One revision only, so cost stays bounded. Keep whichever version reads cleaner.
        return better_draft(draft, revised)

    def review_draft(self, request: str, brief: ResearchBrief, draft_text: str) -> DraftReview:
        prompt = (
            "Check this outreach draft against the acceptance criteria. "
            "Return passed=false if any criterion is breached, with the specific issues and the fixes needed.\n\n"
            f"User request: {request}\n"
            f"Brief: {json.dumps(asdict(brief), ensure_ascii=False)}\n"
            f"Draft: {draft_text}"
        )
        data = self._structured_message(
            prompt,
            REVIEW_SCHEMA,
            model=self.review_model,
            system=REVIEW_SYSTEM_PROMPT,
            max_tokens=4096,
            effort="low",
        )
        return DraftReview(
            passed=bool(data.get("passed", False)),
            issues=list(data.get("issues", [])),
            fixes=list(data.get("fixes", [])),
        )

    def revise_draft(self, request: str, contact: Contact, brief: ResearchBrief, current_text: str, instructions: str) -> str:
        prompt = (
            "Revise this outreach draft using the user's edit instructions. Keep it friendly, professional, concise, "
            "and do not invent facts, prices, credentials, or availability.\n\n"
            f"User request: {request}\n"
            f"Contact: {json.dumps(asdict(contact), ensure_ascii=False)}\n"
            f"Brief: {json.dumps(asdict(brief), ensure_ascii=False)}\n"
            f"Current draft: {current_text}\n"
            f"Edit instructions: {instructions}\n\n"
            f"{VOICE_RULES}"
        )
        return self._text_message(prompt, thinking=True).strip()

    def _request_body(
        self,
        prompt: str,
        *,
        model: str | None = None,
        system: str = DRAFT_SYSTEM_PROMPT,
        max_tokens: int = 16000,
        thinking: bool = False,
        schema: dict[str, Any] | None = None,
        effort: str | None = None,
    ) -> dict[str, Any]:
        resolved_model = model or self.model
        caps = model_capabilities(resolved_model)
        body: dict[str, Any] = {
            "model": resolved_model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": prompt[:12000]}],
        }
        if thinking and caps.adaptive_thinking:
            # Adaptive thinking: the model decides how much reasoning the task
            # needs. No budget_tokens - modern models reject it.
            body["thinking"] = {"type": "adaptive"}
        # Legacy models (caps.budget_thinking) only support the older
        # enabled+budget_tokens form, which needs a budget picked below
        # max_tokens for every call site. Omitting `thinking` entirely there
        # is the simplest correct option, so `thinking=True` is a no-op on
        # them rather than an error.
        output_config: dict[str, Any] = {}
        if schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": schema}
        if effort is not None and caps.effort:
            # output_config.effort errors on models that don't support it
            # (e.g. Haiku 4.5) - only send it when the capability map says so.
            output_config["effort"] = effort
        if output_config:
            body["output_config"] = output_config
        return body

    def _text_message(self, prompt: str, *, thinking: bool = False) -> str:
        payload = self._transport(self._request_body(prompt, thinking=thinking))
        return _text_from_payload(payload)

    def _structured_message(
        self,
        prompt: str,
        schema: dict[str, Any],
        *,
        model: str | None = None,
        system: str = DRAFT_SYSTEM_PROMPT,
        max_tokens: int = 16000,
        thinking: bool = False,
        effort: str | None = None,
    ) -> dict[str, Any]:
        payload = self._transport(
            self._request_body(
                prompt,
                model=model,
                system=system,
                max_tokens=max_tokens,
                thinking=thinking,
                schema=schema,
                effort=effort,
            )
        )
        return _parse_json_response(_text_from_payload(payload))

    def _http_post(self, body: dict[str, Any]) -> dict[str, Any]:
        req = urllib.request.Request(
            self.ENDPOINT,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # The API puts the actual reason in the response body. Without it the
            # caller sees "HTTP Error 400: Bad Request" and learns nothing.
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"Anthropic request failed ({exc.code}): {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Anthropic request failed: {exc}") from exc


def _text_from_payload(payload: dict[str, Any]) -> str:
    parts = payload.get("content", [])
    return "\n".join(part.get("text", "") for part in parts if part.get("type") == "text")


def _parse_json_response(text: str) -> dict[str, Any]:
    # A schema-constrained response is already valid JSON. The fallback covers the
    # edge cases the schema does not, such as a truncated or refused response.
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise RuntimeError(f"Model did not return JSON: {text[:300]}") from None
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
