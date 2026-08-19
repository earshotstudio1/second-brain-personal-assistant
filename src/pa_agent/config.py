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
    sender_name: str

    @property
    def obsidian_export_root(self) -> Path:
        return self.obsidian_vault / self.obsidian_task_dir


def load_settings() -> Settings:
    vault = Path(os.getenv("PA_AGENT_OBSIDIAN_VAULT", str(DEFAULT_OBSIDIAN_VAULT)))
    task_dir = Path(os.getenv("PA_AGENT_OBSIDIAN_TASK_DIR", r"Projects\Active\Personal Assistant Agent Tasks"))
    db_path = Path(os.getenv("PA_AGENT_DB_PATH", str(PROJECT_ROOT / "data" / "pa_agent.sqlite3")))
    return Settings(
        db_path=db_path,
        obsidian_vault=vault,
        obsidian_task_dir=task_dir,
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
        telegram_allowed_chat_id=os.getenv("TELEGRAM_ALLOWED_CHAT_ID"),
        tavily_api_key=os.getenv("TAVILY_API_KEY"),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
        anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest"),
        sender_name=os.getenv("PA_AGENT_SENDER_NAME", "Your Name"),
    )

