from __future__ import annotations

import unittest
from unittest import mock

from pa_agent.config import load_settings


class LoadSettingsEmptyEnvTests(unittest.TestCase):
    def test_empty_string_env_value_falls_back_to_default_model(self) -> None:
        # A key present in .env with a blank value (e.g. "ANTHROPIC_MODEL=") must
        # not silently produce an empty model string - it should behave the same
        # as the key being absent entirely.
        with mock.patch.dict("os.environ", {"ANTHROPIC_MODEL": ""}, clear=False):
            settings = load_settings()
        self.assertEqual(settings.anthropic_model, "claude-opus-5")

    def test_missing_env_value_also_falls_back_to_default_model(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=False) as env:
            env.pop("ANTHROPIC_MODEL", None)
            settings = load_settings()
        self.assertEqual(settings.anthropic_model, "claude-opus-5")

    def test_non_empty_env_value_is_used_as_is(self) -> None:
        with mock.patch.dict("os.environ", {"ANTHROPIC_MODEL": "some-other-model"}, clear=False):
            settings = load_settings()
        self.assertEqual(settings.anthropic_model, "some-other-model")

    def test_empty_sender_name_falls_back_to_default(self) -> None:
        with mock.patch.dict("os.environ", {"PA_AGENT_SENDER_NAME": ""}, clear=False):
            settings = load_settings()
        self.assertEqual(settings.sender_name, "Your Name")


if __name__ == "__main__":
    unittest.main()
