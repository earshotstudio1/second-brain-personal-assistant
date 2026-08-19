from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OBSIDIAN_VAULT = PROJECT_ROOT / "sample_vault"


@dataclass(frozen=True)
class Settings:
    db_path: Path
    obsidian_vault: Path
    obsidian_task_dir: Path
    telegram_bot_token: str | None
    telegram_allowed_chat_id: str | None
    tavily_api_key: str | None
    anthropic_api_key: str | None
    anthropic_model: str
    anthropic_review_model: str
    sender_name: str

    @property
    def obsidian_export_root(self) -> Path:
        return self.obsidian_vault / self.obsidian_task_dir


def load_settings() -> Settings:
    # `os.getenv(key, default)` only falls back when the key is entirely absent -
    # a key present in .env with an empty value still returns "". Since an empty
    # string silently sent as a model name, a path, or a display name is worse
    # than the default, use `or default` everywhere a blank value would matter.
    vault = Path(os.getenv("PA_AGENT_OBSIDIAN_VAULT") or str(DEFAULT_OBSIDIAN_VAULT))
    task_dir = Path(os.getenv("PA_AGENT_OBSIDIAN_TASK_DIR") or r"Projects\Active\Personal Assistant Agent Tasks")
    db_path = Path(os.getenv("PA_AGENT_DB_PATH") or str(PROJECT_ROOT / "data" / "pa_agent.sqlite3"))
    model = os.getenv("ANTHROPIC_MODEL") or "claude-sonnet-5"
    return Settings(
        db_path=db_path,
        obsidian_vault=vault,
        obsidian_task_dir=task_dir,
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
        telegram_allowed_chat_id=os.getenv("TELEGRAM_ALLOWED_CHAT_ID"),
        tavily_api_key=os.getenv("TAVILY_API_KEY"),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
        anthropic_model=model,
        # The self-review pass is a short second call. It defaults to the same
        # model as drafting so there is only one model to think about, but it can
        # be pointed at a cheaper model independently.
        anthropic_review_model=os.getenv("ANTHROPIC_REVIEW_MODEL") or model,
        sender_name=os.getenv("PA_AGENT_SENDER_NAME") or "Your Name",
    )

