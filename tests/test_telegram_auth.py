from __future__ import annotations

import unittest
from pathlib import Path

from pa_agent.config import Settings
from pa_agent.telegram import _allowed, run_telegram_bot


def _settings(*, bot_token: str | None, allowed_chat_id: str | None) -> Settings:
    return Settings(
        db_path=Path("unused.sqlite3"),
        obsidian_vault=Path("unused-vault"),
        obsidian_task_dir=Path("unused-tasks"),
        telegram_bot_token=bot_token,
        telegram_allowed_chat_id=allowed_chat_id,
        tavily_api_key=None,
        anthropic_api_key=None,
        anthropic_model="claude-haiku-4-5",
        anthropic_review_model="claude-haiku-4-5",
        sender_name="Test Sender",
    )


class AllowedChatFailsClosedTests(unittest.TestCase):
    def test_matching_chat_id_is_allowed(self) -> None:
        settings = _settings(bot_token="token", allowed_chat_id="12345")
        self.assertTrue(_allowed(settings, "12345"))

    def test_non_matching_chat_id_is_rejected(self) -> None:
        settings = _settings(bot_token="token", allowed_chat_id="12345")
        self.assertFalse(_allowed(settings, "67890"))

    def test_unset_allowed_chat_id_rejects_every_chat(self) -> None:
        # Previously an unset TELEGRAM_ALLOWED_CHAT_ID failed OPEN and allowed
        # any chat to command the agent. It must now fail CLOSED.
        settings = _settings(bot_token="token", allowed_chat_id=None)
        self.assertFalse(_allowed(settings, "12345"))
        self.assertFalse(_allowed(settings, ""))

    def test_empty_string_allowed_chat_id_rejects_every_chat(self) -> None:
        settings = _settings(bot_token="token", allowed_chat_id="")
        self.assertFalse(_allowed(settings, "12345"))
        self.assertFalse(_allowed(settings, ""))


class RunTelegramBotStartupGuardTests(unittest.TestCase):
    def test_missing_bot_token_refuses_to_start(self) -> None:
        settings = _settings(bot_token=None, allowed_chat_id="12345")
        with self.assertRaises(RuntimeError) as ctx:
            run_telegram_bot(settings)
        self.assertIn("TELEGRAM_BOT_TOKEN", str(ctx.exception))

    def test_missing_allowed_chat_id_refuses_to_start(self) -> None:
        settings = _settings(bot_token="token", allowed_chat_id=None)
        with self.assertRaises(RuntimeError) as ctx:
            run_telegram_bot(settings)
        self.assertIn("TELEGRAM_ALLOWED_CHAT_ID", str(ctx.exception))

    def test_empty_allowed_chat_id_refuses_to_start(self) -> None:
        settings = _settings(bot_token="token", allowed_chat_id="")
        with self.assertRaises(RuntimeError) as ctx:
            run_telegram_bot(settings)
        self.assertIn("TELEGRAM_ALLOWED_CHAT_ID", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
