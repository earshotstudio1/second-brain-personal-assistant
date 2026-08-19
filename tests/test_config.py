from __future__ import annotations

import unittest
from unittest import mock

from pa_agent.config import load_settings, model_capabilities


class LoadSettingsEmptyEnvTests(unittest.TestCase):
    def test_empty_string_env_value_falls_back_to_default_model(self) -> None:
        # A key present in .env with a blank value (e.g. "ANTHROPIC_MODEL=") must
        # not silently produce an empty model string - it should behave the same
        # as the key being absent entirely.
        with mock.patch.dict("os.environ", {"ANTHROPIC_MODEL": ""}, clear=False):
            settings = load_settings()
        self.assertEqual(settings.anthropic_model, "claude-haiku-4-5")

    def test_missing_env_value_also_falls_back_to_default_model(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=False) as env:
            env.pop("ANTHROPIC_MODEL", None)
            settings = load_settings()
        self.assertEqual(settings.anthropic_model, "claude-haiku-4-5")

    def test_non_empty_env_value_is_used_as_is(self) -> None:
        with mock.patch.dict("os.environ", {"ANTHROPIC_MODEL": "some-other-model"}, clear=False):
            settings = load_settings()
        self.assertEqual(settings.anthropic_model, "some-other-model")

    def test_review_model_defaults_to_drafting_model(self) -> None:
        with mock.patch.dict("os.environ", {"ANTHROPIC_MODEL": "some-other-model", "ANTHROPIC_REVIEW_MODEL": ""}, clear=False):
            settings = load_settings()
        self.assertEqual(settings.anthropic_review_model, "some-other-model")

    def test_review_model_can_be_set_independently(self) -> None:
        with mock.patch.dict(
            "os.environ",
            {"ANTHROPIC_MODEL": "some-other-model", "ANTHROPIC_REVIEW_MODEL": "some-review-model"},
            clear=False,
        ):
            settings = load_settings()
        self.assertEqual(settings.anthropic_model, "some-other-model")
        self.assertEqual(settings.anthropic_review_model, "some-review-model")

    def test_review_model_falls_back_to_default_when_neither_is_set(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=False) as env:
            env.pop("ANTHROPIC_MODEL", None)
            env.pop("ANTHROPIC_REVIEW_MODEL", None)
            settings = load_settings()
        self.assertEqual(settings.anthropic_review_model, "claude-haiku-4-5")

    def test_empty_sender_name_falls_back_to_default(self) -> None:
        with mock.patch.dict("os.environ", {"PA_AGENT_SENDER_NAME": ""}, clear=False):
            settings = load_settings()
        self.assertEqual(settings.sender_name, "Your Name")


class ModelCapabilitiesTests(unittest.TestCase):
    def test_haiku_4_5_is_legacy(self) -> None:
        caps = model_capabilities("claude-haiku-4-5")
        self.assertFalse(caps.effort)
        self.assertFalse(caps.adaptive_thinking)
        self.assertTrue(caps.budget_thinking)

    def test_sonnet_4_5_is_also_legacy(self) -> None:
        # Same generation as Haiku 4.5 (pre-4.6), so it should take the same path.
        caps = model_capabilities("claude-sonnet-4-5")
        self.assertFalse(caps.effort)
        self.assertFalse(caps.adaptive_thinking)
        self.assertTrue(caps.budget_thinking)

    def test_bare_major_5_generation_models_are_modern(self) -> None:
        for model in ("claude-sonnet-5", "claude-opus-5", "claude-fable-5"):
            with self.subTest(model=model):
                caps = model_capabilities(model)
                self.assertTrue(caps.effort)
                self.assertTrue(caps.adaptive_thinking)
                self.assertFalse(caps.budget_thinking)

    def test_4_6_and_later_models_are_modern(self) -> None:
        for model in ("claude-sonnet-4-6", "claude-opus-4-6", "claude-opus-4-7", "claude-opus-4-8"):
            with self.subTest(model=model):
                caps = model_capabilities(model)
                self.assertTrue(caps.effort)
                self.assertTrue(caps.adaptive_thinking)
                self.assertFalse(caps.budget_thinking)

    def test_unrecognised_model_id_defaults_to_modern(self) -> None:
        # An ID with no version suffix this heuristic understands is far more
        # likely to be a new current-generation model than a legacy holdout.
        caps = model_capabilities("some-future-model")
        self.assertTrue(caps.effort)
        self.assertTrue(caps.adaptive_thinking)


if __name__ == "__main__":
    unittest.main()
