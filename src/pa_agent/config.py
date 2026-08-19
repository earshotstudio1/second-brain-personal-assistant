from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OBSIDIAN_VAULT = PROJECT_ROOT / "sample_vault"


@dataclass(frozen=True)
class ModelCapabilities:
    """Which request-shaping features a given Claude model accepts.

    Model generations use different wire formats for the same idea ("let the
    model reason before answering"). Keeping that difference here as data -
    rather than as `if model == "claude-haiku-4-5"` checks scattered through
    the request-building code - means a call site never needs to know which
    model it is talking to: it asks this map and builds the request
    accordingly. That matters because the model is a one-line env var change
    (`ANTHROPIC_MODEL`) and the request shaping has to follow automatically.
    """

    effort: bool  # output_config.effort ("low".."max"); errors on legacy models
    adaptive_thinking: bool  # thinking: {"type": "adaptive"}; 4.6+/5-gen only
    budget_thinking: bool  # thinking: {"type": "enabled", "budget_tokens": N}; legacy models only


# Capability sets. "Modern" covers the 4.6+ and 5-generation models (adaptive
# thinking replaced the fixed token budget, and `effort` was introduced as the
# depth control). "Legacy" covers everything before that (Haiku 4.5, Sonnet
# 4.5, and older), which never got `effort` and only supports the older
# enabled+budget_tokens form of thinking.
_MODERN = ModelCapabilities(effort=True, adaptive_thinking=True, budget_thinking=False)
_LEGACY = ModelCapabilities(effort=False, adaptive_thinking=False, budget_thinking=True)

# Exceptions to the version-suffix heuristic below, keyed by exact model ID.
# Populate this if a future model doesn't fit the "-4-6 or later is modern"
# rule (for example, a model that supports `effort` but not adaptive
# thinking). Empty today - Haiku 4.5 and the current 4.6+/5-gen models all
# fit the heuristic.
_CAPABILITY_OVERRIDES: dict[str, ModelCapabilities] = {}

# Matches the trailing version suffix of a Claude model ID: "-5" (bare major,
# e.g. claude-sonnet-5) or "-4-6" (major-minor, e.g. claude-haiku-4-5).
_VERSION_SUFFIX = re.compile(r"-(\d+)(?:-(\d+))?$")


def model_capabilities(model: str) -> ModelCapabilities:
    """Look up which request features `model` accepts.

    Checks `_CAPABILITY_OVERRIDES` first, then falls back to a heuristic on
    the model ID's version suffix: bare-major IDs (`claude-{family}-5`, e.g.
    Sonnet 5 / Opus 5 / Fable 5) and major.minor IDs of 4.6 or later
    (`claude-{family}-4-6`, `-4-7`, `-4-8`, ...) are treated as modern;
    anything older (`claude-haiku-4-5`, `claude-sonnet-4-5`, ...) is legacy.
    An ID with no recognisable version suffix is treated as modern, since a
    newly released model is far more likely to be current-generation than a
    legacy holdout.
    """
    if model in _CAPABILITY_OVERRIDES:
        return _CAPABILITY_OVERRIDES[model]

    match = _VERSION_SUFFIX.search(model)
    if not match:
        return _MODERN

    major = int(match.group(1))
    minor = int(match.group(2)) if match.group(2) else 0
    return _MODERN if (major, minor) >= (4, 6) else _LEGACY


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
    model = os.getenv("ANTHROPIC_MODEL") or "claude-haiku-4-5"
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

