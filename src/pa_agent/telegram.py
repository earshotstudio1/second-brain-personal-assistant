from __future__ import annotations

import http.client
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

from .app import build_store, build_workflow, refresh_obsidian_export
from .config import Settings

# Transient network failures the long-poll loop must survive rather than die from.
# Anything not covered here (bad JSON, a genuine bug in a handler, etc.) still
# propagates and crashes the process loudly, which is what we want for real bugs.
NETWORK_ERRORS = (OSError, urllib.error.URLError, http.client.HTTPException)


class NetworkRetry:
    """Runs a call, retrying on transient network errors with geometric backoff.

    Backoff starts at `initial` seconds, doubles on each consecutive network
    failure up to `maximum`, and resets to `initial` as soon as a call succeeds.
    Non-network exceptions are never caught here.
    """

    def __init__(
        self,
        initial: float = 5.0,
        maximum: float = 60.0,
        sleep: Callable[[float], None] = time.sleep,
        on_retry: Callable[[BaseException, float], None] | None = None,
    ) -> None:
        self.initial = initial
        self.maximum = maximum
        self._sleep = sleep
        self._on_retry = on_retry
        self._current = initial

    def call(self, func: Callable[[], Any]) -> Any:
        while True:
            try:
                result = func()
            except NETWORK_ERRORS as exc:
                if self._on_retry:
                    self._on_retry(exc, self._current)
                self._sleep(self._current)
                self._current = min(self._current * 2, self.maximum)
                continue
            self._current = self.initial
            return result


def run_telegram_bot(settings: Settings) -> None:
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required for Telegram mode.")
    offset = 0

    def _log_retry(exc: BaseException, delay: float) -> None:
        print(f"WARNING: Telegram network error ({exc!r}); retrying in {delay:.0f}s")

    retry = NetworkRetry(on_retry=_log_retry)
    print("PA Agent Telegram polling started.")
    while True:
        def _poll() -> None:
            nonlocal offset
            updates = _api(settings, "getUpdates", {"offset": offset, "timeout": 30})
            for update in updates.get("result", []):
                offset = max(offset, update["update_id"] + 1)
                handle_update(settings, update)

        retry.call(_poll)
        time.sleep(0.5)


def handle_update(settings: Settings, update: dict[str, Any]) -> None:
    if "callback_query" in update:
        _handle_callback(settings, update["callback_query"])
        return
    message = update.get("message") or {}
    chat_id = str((message.get("chat") or {}).get("id", ""))
    if not _allowed(settings, chat_id):
        return
    text = message.get("text", "").strip()
    if message.get("reply_to_message") and text:
        if _handle_reply(settings, chat_id, message):
            return
    if text.startswith("/task"):
        request = text.removeprefix("/task").strip()
        if not request:
            _send(settings, chat_id, "Send `/task` followed by the admin task.")
            return
        workflow = build_workflow(settings)
        result = workflow.start_task(request)
        bundle = workflow.store.task_bundle(result.task_id)
        if result.needs_clarification:
            _send(settings, chat_id, f"Clarification for `{result.task_id}`:\n\n{result.question}\n\nReply to this message with your answer.")
        else:
            _send_task_summary(settings, chat_id, bundle)
    elif text.startswith("/status"):
        store = build_store(settings)
        tasks = store.list_tasks()
        if not tasks:
            _send(settings, chat_id, "No PA tasks yet.")
            return
        lines = [f"{row['task_id']} | {row['stage']} | {row['user_request']}" for row in tasks[:10]]
        _send(settings, chat_id, "\n".join(lines))
    elif text.startswith("/debug"):
        task_id = text.removeprefix("/debug").strip()
        store = build_store(settings)
        try:
            bundle = store.task_bundle(task_id)
        except ValueError as exc:
            _send(settings, chat_id, str(exc))
            return
        _send(settings, chat_id, json.dumps(bundle["task"], indent=2))


def _handle_reply(settings: Settings, chat_id: str, message: dict[str, Any]) -> bool:
    reply_text = (message.get("reply_to_message") or {}).get("text", "")
    text = message.get("text", "").strip()
    draft_id = _extract_id(reply_text, "draft")
    if draft_id:
        workflow = build_workflow(settings)
        try:
            draft = workflow.redraft(draft_id, text, actor="telegram")
        except ValueError as exc:
            _send(settings, chat_id, str(exc))
            return True
        _send(
            settings,
            chat_id,
            f"Redrafted `{draft_id}` as version `{draft['version']}`.\n\n{draft['text']}",
            reply_markup=_draft_actions(draft_id),
        )
        return True

    task_id = _extract_id(reply_text, "task")
    if task_id and "Clarification" in reply_text:
        workflow = build_workflow(settings)
        try:
            workflow.continue_after_clarification(task_id, text)
        except ValueError as exc:
            _send(settings, chat_id, str(exc))
            return True
        bundle = workflow.store.task_bundle(task_id)
        _send_task_summary(settings, chat_id, bundle)
        return True
    return False


def _handle_callback(settings: Settings, callback: dict[str, Any]) -> None:
    message = callback.get("message") or {}
    chat_id = str((message.get("chat") or {}).get("id", ""))
    if not _allowed(settings, chat_id):
        return
    data = callback.get("data", "")
    store = build_store(settings)
    if data.startswith("approve:"):
        draft_id = data.split(":", 1)[1]
        draft = store.approve_draft(draft_id, actor="telegram")
        refresh_obsidian_export(settings, store, draft["task_id"])
        _answer_callback(settings, callback["id"], "Approved. Manual sending only.")
        _send(settings, chat_id, f"Approved `{draft_id}`. Manual-send text:\n\n{draft['approved_text']}")
    elif data.startswith("reject:"):
        draft_id = data.split(":", 1)[1]
        draft = store.reject_draft(draft_id, reason="Rejected in Telegram", actor="telegram")
        refresh_obsidian_export(settings, store, draft["task_id"])
        _answer_callback(settings, callback["id"], "Rejected.")
        _send(settings, chat_id, f"Rejected `{draft_id}`.")
    elif data.startswith("edit:"):
        draft_id = data.split(":", 1)[1]
        _answer_callback(settings, callback["id"], "Reply to the draft message with edit instructions.")
        _send(settings, chat_id, f"To edit `{draft_id}`, reply to the draft message with your instructions.")


def _send_task_summary(settings: Settings, chat_id: str, bundle: dict[str, Any]) -> None:
    task = bundle["task"]
    note = task["obsidian_path"]
    _send(settings, chat_id, f"Created `{task['task_id']}`\nStage: `{task['stage']}`\nObsidian note:\n{note}")
    for draft in bundle["drafts"][:6]:
        contact = next((item for item in bundle["contacts"] if item["contact_id"] == draft["contact_id"]), {})
        text = (
            f"*{contact.get('name', 'Draft')}*\n"
            f"Draft ID: `{draft['draft_id']}`\n"
            f"Channel: `{draft['channel']}`\n"
            f"Version: `{draft['version']}`\n\n"
            f"{draft['text']}"
        )
        _send(
            settings,
            chat_id,
            text,
            reply_markup=_draft_actions(draft["draft_id"]),
        )


def _allowed(settings: Settings, chat_id: str) -> bool:
    return not settings.telegram_allowed_chat_id or chat_id == settings.telegram_allowed_chat_id


def _draft_actions(draft_id: str) -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": "Approve", "callback_data": f"approve:{draft_id}"},
                {"text": "Edit", "callback_data": f"edit:{draft_id}"},
                {"text": "Reject", "callback_data": f"reject:{draft_id}"},
            ]
        ]
    }


def _extract_id(text: str, prefix: str) -> str:
    match = re.search(rf"\b{prefix}_[A-Za-z0-9]+\b", text or "")
    return match.group(0) if match else ""


def _send(settings: Settings, chat_id: str, text: str, reply_markup: dict[str, Any] | None = None) -> None:
    payload: dict[str, Any] = {"chat_id": chat_id, "text": text[:3900], "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    _api(settings, "sendMessage", payload)


def _answer_callback(settings: Settings, callback_id: str, text: str) -> None:
    _api(settings, "answerCallbackQuery", {"callback_query_id": callback_id, "text": text})


def _api(settings: Settings, method: str, payload: dict[str, Any]) -> dict[str, Any]:
    assert settings.telegram_bot_token
    data = urllib.parse.urlencode(payload).encode("utf-8")
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/{method}"
    with urllib.request.urlopen(url, data=data, timeout=35) as resp:
        return json.loads(resp.read().decode("utf-8"))
