from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def export_task_note(export_root: Path, bundle: dict[str, Any]) -> Path:
    export_root.mkdir(parents=True, exist_ok=True)
    task = bundle["task"]
    filename = f"{task['created_at'][:10]}-{slugify(task['user_request'])}-{task['task_id']}.md"
    path = export_root / filename
    path.write_text(render_task_note(bundle), encoding="utf-8")
    return path


def render_task_note(bundle: dict[str, Any]) -> str:
    task = bundle["task"]
    brief = json.loads(task.get("research_brief") or "{}")
    lines = [
        "---",
        f"title: PA Task - {escape_yaml(task['user_request'])}",
        f"date: '{task['created_at'][:10]}'",
        "type: pa-agent-task",
        "status: active",
        "tags:",
        "- pa-agent",
        "- admin",
        f"task_id: {task['task_id']}",
        f"stage: {task['stage']}",
        "---",
        "",
        f"# PA Task - {task['user_request']}",
        "",
        "## Status",
        f"- Task ID: `{task['task_id']}`",
        f"- Stage: `{task['stage']}`",
        f"- Status: `{task['status']}`",
        f"- Created: `{task['created_at']}`",
        f"- Updated: `{task['updated_at']}`",
        "",
        "## Clarifications",
    ]
    for clarification in bundle["clarifications"]:
        answer = clarification["answer"] or "Pending"
        lines.extend(
            [
                f"- Question: {clarification['question']}",
                f"  Answer: {answer}",
            ]
        )
    if not bundle["clarifications"]:
        lines.append("- None requested.")

    lines.extend(
        [
        "",
        "## Research Brief",
        brief.get("summary", "No brief yet."),
        "",
        "### Ranked Options",
        ]
    )
    for option in brief.get("ranked_options", []):
        lines.append(f"- **{option.get('rank', '?')}. {option.get('name', 'Unnamed')}** ({option.get('confidence', 'unknown')} confidence): {option.get('reason', '')} [{option.get('source_url', 'source')}]({option.get('source_url', '')})")
    if not brief.get("ranked_options"):
        lines.append("- No ranked options yet.")

    lines.extend(["", "### Uncertainty"])
    for item in brief.get("uncertainty", []):
        lines.append(f"- {item}")
    if not brief.get("uncertainty"):
        lines.append("- None recorded.")

    lines.extend(["", "## Contacts"])
    for contact in bundle["contacts"]:
        lines.extend(
            [
                f"### {contact['name']}",
                f"- Organization: {contact['organization']}",
                f"- Email: {contact['email'] or 'Not found'}",
                f"- Phone: {contact['phone'] or 'Not found'}",
                f"- WhatsApp: {contact['whatsapp'] or 'Not found'}",
                f"- Confidence: {contact['confidence']}",
                f"- Source: [{contact['source_url']}]({contact['source_url']})",
                f"- Notes: {contact['notes']}",
                "",
            ]
        )
    if not bundle["contacts"]:
        lines.append("- No contacts found.")

    lines.extend(["", "## Drafts"])
    contact_by_id = {contact["contact_id"]: contact for contact in bundle["contacts"]}
    for draft in bundle["drafts"]:
        contact = contact_by_id.get(draft["contact_id"], {})
        lines.extend(
            [
                f"### {contact.get('name', draft['contact_id'])}",
                f"- Draft ID: `{draft['draft_id']}`",
                f"- Channel: `{draft['channel']}`",
                f"- Status: `{draft['status']}`",
                f"- Version: `{draft['version']}`",
                "",
                "```text",
                draft["approved_text"] if draft["status"] == "approved" else draft["text"],
                "```",
                "",
            ]
        )
    if not bundle["drafts"]:
        lines.append("- No drafts yet.")

    lines.extend(["", "## Sources"])
    for source in bundle["sources"]:
        lines.append(f"- [{source['title']}]({source['url']}) - {source['reliability']} confidence. {source['snippet']}")
    if not bundle["sources"]:
        lines.append("- No sources yet.")

    lines.extend(["", "## Audit Trail"])
    for event in bundle["audit_events"]:
        lines.append(f"- `{event['created_at']}` **{event['action']}** by `{event['actor']}`: `{event['payload_json']}`")
    return "\n".join(lines).rstrip() + "\n"


def slugify(text: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", text.strip().lower()).strip("-")
    return slug[:70] or "task"


def escape_yaml(text: str) -> str:
    return text.replace(":", " -").replace("\n", " ")
