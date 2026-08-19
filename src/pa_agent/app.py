from __future__ import annotations

from .config import Settings
from .db import Store, connect, init_db
from .obsidian import export_task_note
from .providers import AnthropicDraftProvider, DryRunSearchProvider, RuleBasedDraftProvider, TavilySearchProvider
from .workflow import TaskWorkflow


def build_store(settings: Settings) -> Store:
    conn = connect(settings.db_path)
    init_db(conn)
    return Store(conn)


def build_workflow(settings: Settings) -> TaskWorkflow:
    store = build_store(settings)
    search_provider = TavilySearchProvider(settings.tavily_api_key) if settings.tavily_api_key else DryRunSearchProvider()
    draft_provider = (
        AnthropicDraftProvider(settings.anthropic_api_key, settings.anthropic_model)
        if settings.anthropic_api_key
        else RuleBasedDraftProvider(settings.sender_name)
    )
    return TaskWorkflow(store, search_provider, draft_provider, settings.obsidian_export_root)


def refresh_obsidian_export(settings: Settings, store: Store, task_id: str) -> str:
    note_path = export_task_note(settings.obsidian_export_root, store.task_bundle(task_id))
    store.update_task(task_id, obsidian_path=str(note_path))
    store.add_audit_event(task_id, None, "obsidian_exported", "agent", {"path": str(note_path)})
    store.conn.commit()
    return str(note_path)
