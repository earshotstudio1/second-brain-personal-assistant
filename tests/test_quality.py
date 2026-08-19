from __future__ import annotations

import json
import unittest
from typing import Any

from pa_agent.models import Contact, DraftReview, ResearchBrief, Source
from pa_agent.providers import (
    BRIEF_SCHEMA,
    REVIEW_SCHEMA,
    AnthropicDraftProvider,
    needs_revision,
)
from pa_agent.voice import better_draft, voice_violations


def _text_payload(text: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}]}


def _json_payload(data: dict[str, Any]) -> dict[str, Any]:
    return _text_payload(json.dumps(data))


class FakeTransport:
    """Stands in for the HTTP call. Records request bodies, returns canned payloads."""

    def __init__(self, responses: list[dict[str, Any]]):
        self._responses = list(responses)
        self.requests: list[dict[str, Any]] = []

    def __call__(self, body: dict[str, Any]) -> dict[str, Any]:
        self.requests.append(body)
        if not self._responses:
            raise AssertionError("FakeTransport ran out of responses; the provider made an extra call.")
        return self._responses.pop(0)


CONTACT = Contact(name="Acme CRM", organization="Acme", email="hello@acme.example", source_url="https://acme.example")
BRIEF = ResearchBrief(summary="Two options found.", recommendation="Start with Acme.", sources=["https://acme.example"])

CLEAN_DRAFT = "Hello Acme, I am comparing CRM options and would like to ask about your CLI access.\n\nThanks,\nDaniel"
DIRTY_DRAFT = "Hello Acme — we want to leverage your robust CRM, not just for sales but for support.\n\nThanks,\nDaniel"

PASSED_REVIEW = {"passed": True, "issues": [], "fixes": []}
FAILED_REVIEW = {"passed": False, "issues": ["Invented a price"], "fixes": ["Remove the price"]}


class VoiceRuleTests(unittest.TestCase):
    def test_clean_text_has_no_violations(self) -> None:
        self.assertEqual(voice_violations(CLEAN_DRAFT), [])

    def test_em_dash_is_flagged(self) -> None:
        self.assertIn("em dash", voice_violations("A sentence — with an em dash."))

    def test_banned_words_are_flagged(self) -> None:
        violations = voice_violations("We delve into robust tooling and streamline the rest.")
        self.assertIn("banned word: delve", violations)
        self.assertIn("banned word: robust", violations)
        self.assertIn("banned word: streamline", violations)

    def test_leverage_as_verb_is_flagged_but_the_noun_is_not(self) -> None:
        self.assertIn("leverage used as a verb", voice_violations("We leverage the API."))
        self.assertIn("leverage used as a verb", voice_violations("They are leveraging the API."))
        self.assertEqual(voice_violations("That gives us leverage in the negotiation."), [])

    def test_false_contrast_is_flagged(self) -> None:
        self.assertIn("false contrast", voice_violations("It is not just a CRM but a platform."))
        self.assertIn("false contrast", voice_violations("Not only fast but cheap."))

    def test_better_draft_prefers_fewer_violations(self) -> None:
        self.assertEqual(better_draft(DIRTY_DRAFT, CLEAN_DRAFT), CLEAN_DRAFT)
        self.assertEqual(better_draft(CLEAN_DRAFT, DIRTY_DRAFT), CLEAN_DRAFT)

    def test_better_draft_keeps_the_revision_on_a_tie(self) -> None:
        self.assertEqual(better_draft(CLEAN_DRAFT, "A different clean draft."), "A different clean draft.")


class ReviewDecisionTests(unittest.TestCase):
    def test_passing_review_on_a_clean_draft_needs_no_revision(self) -> None:
        self.assertFalse(needs_revision(DraftReview(passed=True), CLEAN_DRAFT))

    def test_failing_review_needs_revision(self) -> None:
        self.assertTrue(needs_revision(DraftReview(passed=False, issues=["Invented a price"]), CLEAN_DRAFT))

    def test_local_voice_checks_override_a_passing_review(self) -> None:
        # The reviewing model can be wrong. A draft that breaks a voice rule goes
        # round again whatever the review said.
        self.assertTrue(needs_revision(DraftReview(passed=True), DIRTY_DRAFT))


class StructuredBriefTests(unittest.TestCase):
    def test_brief_request_is_schema_constrained_and_uses_adaptive_thinking(self) -> None:
        transport = FakeTransport(
            [
                _json_payload(
                    {
                        "summary": "Two options found.",
                        "options": [
                            {
                                "rank": 1,
                                "name": "Acme CRM",
                                "reason": "Has a CLI.",
                                "confidence": "medium",
                                "source_url": "https://acme.example",
                            }
                        ],
                        "recommendation": "Start with Acme.",
                        "sources": ["https://acme.example"],
                        "open_questions": ["Free tier limits are unclear."],
                    }
                )
            ]
        )
        provider = AnthropicDraftProvider("key", "claude-sonnet-5", transport=transport)

        brief = provider.create_brief(
            "research crm options",
            [Source(title="Acme", url="https://acme.example", snippet="CLI available")],
            [CONTACT],
        )

        body = transport.requests[0]
        self.assertEqual(body["model"], "claude-sonnet-5")
        self.assertEqual(body["output_config"]["format"], {"type": "json_schema", "schema": BRIEF_SCHEMA})
        self.assertEqual(body["thinking"], {"type": "adaptive"})
        self.assertNotIn("budget_tokens", json.dumps(body))
        self.assertIn("Acceptance criteria", body["system"])
        # Schema keys map onto the fields the rest of the app already uses.
        self.assertEqual(brief.summary, "Two options found.")
        self.assertEqual(brief.ranked_options[0]["name"], "Acme CRM")
        self.assertEqual(brief.recommendation, "Start with Acme.")
        self.assertEqual(brief.sources, ["https://acme.example"])
        self.assertEqual(brief.uncertainty, ["Free tier limits are unclear."])

    def test_brief_prompt_restricts_citations_to_supplied_sources(self) -> None:
        transport = FakeTransport(
            [
                _json_payload(
                    {"summary": "s", "options": [], "recommendation": "r", "sources": [], "open_questions": []}
                )
            ]
        )
        provider = AnthropicDraftProvider("key", "claude-sonnet-5", transport=transport)

        provider.create_brief("research crm options", [Source(title="Acme", url="https://acme.example")], [])

        prompt = transport.requests[0]["messages"][0]["content"]
        self.assertIn("Cite only these URLs", prompt)
        self.assertIn("https://acme.example", prompt)

    def test_schema_objects_are_closed_for_structured_output(self) -> None:
        # The API rejects schemas that leave additionalProperties open.
        self.assertFalse(BRIEF_SCHEMA["additionalProperties"])
        self.assertFalse(BRIEF_SCHEMA["properties"]["options"]["items"]["additionalProperties"])
        self.assertFalse(REVIEW_SCHEMA["additionalProperties"])
        self.assertEqual(sorted(REVIEW_SCHEMA["required"]), ["fixes", "issues", "passed"])


class SelfReviewPassTests(unittest.TestCase):
    def test_clean_draft_that_passes_review_is_returned_without_a_revision(self) -> None:
        transport = FakeTransport([_text_payload(CLEAN_DRAFT), _json_payload(PASSED_REVIEW)])
        provider = AnthropicDraftProvider("key", "claude-sonnet-5", transport=transport)

        result = provider.create_draft("research crm options", CONTACT, BRIEF)

        self.assertEqual(result, CLEAN_DRAFT)
        self.assertEqual(len(transport.requests), 2)

    def test_failed_review_triggers_exactly_one_revision(self) -> None:
        transport = FakeTransport(
            [
                _text_payload(DIRTY_DRAFT),
                _json_payload(FAILED_REVIEW),
                _text_payload(CLEAN_DRAFT),
            ]
        )
        provider = AnthropicDraftProvider("key", "claude-sonnet-5", transport=transport)

        result = provider.create_draft("research crm options", CONTACT, BRIEF)

        self.assertEqual(result, CLEAN_DRAFT)
        self.assertEqual(len(transport.requests), 3)
        revision_prompt = transport.requests[2]["messages"][0]["content"]
        self.assertIn("Invented a price", revision_prompt)
        self.assertIn("Remove the price", revision_prompt)
        self.assertIn("em dash", revision_prompt)

    def test_revision_is_discarded_when_it_reads_worse(self) -> None:
        transport = FakeTransport(
            [
                _text_payload(CLEAN_DRAFT),
                _json_payload(FAILED_REVIEW),
                _text_payload(DIRTY_DRAFT),
            ]
        )
        provider = AnthropicDraftProvider("key", "claude-sonnet-5", transport=transport)

        result = provider.create_draft("research crm options", CONTACT, BRIEF)

        self.assertEqual(result, CLEAN_DRAFT)

    def test_review_call_uses_the_review_model_at_low_effort(self) -> None:
        transport = FakeTransport([_text_payload(CLEAN_DRAFT), _json_payload(PASSED_REVIEW)])
        provider = AnthropicDraftProvider("key", "claude-sonnet-5", review_model="claude-haiku-4-5", transport=transport)

        provider.create_draft("research crm options", CONTACT, BRIEF)

        review_body = transport.requests[1]
        self.assertEqual(review_body["model"], "claude-haiku-4-5")
        self.assertEqual(review_body["output_config"]["effort"], "low")
        self.assertEqual(review_body["output_config"]["format"]["schema"], REVIEW_SCHEMA)
        self.assertNotIn("thinking", review_body)

    def test_review_model_defaults_to_the_drafting_model(self) -> None:
        transport = FakeTransport([_text_payload(CLEAN_DRAFT), _json_payload(PASSED_REVIEW)])
        provider = AnthropicDraftProvider("key", "claude-sonnet-5", transport=transport)

        provider.create_draft("research crm options", CONTACT, BRIEF)

        self.assertEqual(transport.requests[1]["model"], "claude-sonnet-5")

    def test_review_draft_reads_the_structured_verdict(self) -> None:
        transport = FakeTransport([_json_payload(FAILED_REVIEW)])
        provider = AnthropicDraftProvider("key", "claude-sonnet-5", transport=transport)

        review = provider.review_draft("research crm options", BRIEF, DIRTY_DRAFT)

        self.assertFalse(review.passed)
        self.assertEqual(review.issues, ["Invented a price"])
        self.assertEqual(review.fixes, ["Remove the price"])

    def test_no_prefill_is_sent(self) -> None:
        # Assistant prefill is rejected on current models; every request must end
        # on a user turn.
        transport = FakeTransport([_text_payload(CLEAN_DRAFT), _json_payload(PASSED_REVIEW)])
        provider = AnthropicDraftProvider("key", "claude-sonnet-5", transport=transport)

        provider.create_draft("research crm options", CONTACT, BRIEF)

        for body in transport.requests:
            self.assertEqual([message["role"] for message in body["messages"]], ["user"])
            self.assertNotIn("output_format", body)


if __name__ == "__main__":
    unittest.main()
