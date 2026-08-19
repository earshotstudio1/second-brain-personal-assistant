from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from .models import Contact, Draft, Source, utc_now


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            task_id TEXT PRIMARY KEY,
            user_request TEXT NOT NULL,
            status TEXT NOT NULL,
            stage TEXT NOT NULL,
            research_brief TEXT NOT NULL DEFAULT '{}',
            obsidian_path TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS clarifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sources (
            source_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            snippet TEXT NOT NULL,
            publisher TEXT NOT NULL,
            published_at TEXT NOT NULL,
            reliability TEXT NOT NULL,
            retrieved_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS contacts (
            contact_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            organization TEXT NOT NULL,
            email TEXT NOT NULL,
            phone TEXT NOT NULL,
            whatsapp TEXT NOT NULL,
            website_url TEXT NOT NULL,
            source_url TEXT NOT NULL,
            confidence TEXT NOT NULL,
            notes TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS drafts (
            draft_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
            contact_id TEXT NOT NULL REFERENCES contacts(contact_id) ON DELETE CASCADE,
            channel TEXT NOT NULL,
            text TEXT NOT NULL,
            status TEXT NOT NULL,
            approved_text TEXT NOT NULL,
            version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS audit_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
            draft_id TEXT,
            action TEXT NOT NULL,
            actor TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    conn.commit()


class Store:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def create_task(self, user_request: str) -> str:
        now = utc_now()
        task_id = f"task_{uuid.uuid4().hex[:10]}"
        self.conn.execute(
            """
            INSERT INTO tasks (task_id, user_request, status, stage, created_at, updated_at)
            VALUES (?, ?, 'active', 'created', ?, ?)
            """,
            (task_id, user_request, now, now),
        )
        self.add_audit_event(task_id, None, "task_created", "user", {"user_request": user_request})
        self.conn.commit()
        return task_id

    def update_task(self, task_id: str, *, stage: str | None = None, status: str | None = None, research_brief: dict[str, Any] | None = None, obsidian_path: str | None = None) -> None:
        fields: list[str] = ["updated_at = ?"]
        values: list[Any] = [utc_now()]
        if stage is not None:
            fields.append("stage = ?")
            values.append(stage)
        if status is not None:
            fields.append("status = ?")
            values.append(status)
        if research_brief is not None:
            fields.append("research_brief = ?")
            values.append(json.dumps(research_brief, ensure_ascii=False, indent=2))
        if obsidian_path is not None:
            fields.append("obsidian_path = ?")
            values.append(obsidian_path)
        values.append(task_id)
        self.conn.execute(f"UPDATE tasks SET {', '.join(fields)} WHERE task_id = ?", values)
        self.conn.commit()

    def add_source(self, task_id: str, source: Source) -> str:
        source_id = f"src_{uuid.uuid4().hex[:10]}"
        self.conn.execute(
            """
            INSERT INTO sources (source_id, task_id, title, url, snippet, publisher, published_at, reliability, retrieved_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (source_id, task_id, source.title, source.url, source.snippet, source.publisher, source.published_at, source.reliability, utc_now()),
        )
        return source_id

    def add_contact(self, task_id: str, contact: Contact) -> str:
        contact_id = f"contact_{uuid.uuid4().hex[:10]}"
        self.conn.execute(
            """
            INSERT INTO contacts (contact_id, task_id, name, organization, email, phone, whatsapp, website_url, source_url, confidence, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                contact_id,
                task_id,
                contact.name,
                contact.organization,
                contact.email,
                contact.phone,
                contact.whatsapp,
                contact.website_url,
                contact.source_url,
                contact.confidence,
                contact.notes,
                utc_now(),
            ),
        )
        return contact_id

    def add_clarification(self, task_id: str, question: str, answer: str = "") -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO clarifications (task_id, question, answer, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (task_id, question, answer, utc_now()),
        )
        return int(cursor.lastrowid)

    def answer_pending_clarification(self, task_id: str, answer: str) -> sqlite3.Row:
        clarification = self.pending_clarification(task_id)
        if clarification is None:
            raise ValueError(f"No pending clarification for task: {task_id}")
        self.conn.execute(
            "UPDATE clarifications SET answer = ? WHERE id = ?",
            (answer, clarification["id"]),
        )
        self.add_audit_event(
            task_id,
            None,
            "clarification_answered",
            "user",
            {"question": clarification["question"], "answer": answer},
        )
        self.conn.commit()
        return self.conn.execute("SELECT * FROM clarifications WHERE id = ?", (clarification["id"],)).fetchone()

    def pending_clarification(self, task_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            """
            SELECT * FROM clarifications
            WHERE task_id = ? AND answer = ''
            ORDER BY id DESC
            LIMIT 1
            """,
            (task_id,),
        ).fetchone()

    def add_draft(self, task_id: str, draft: Draft) -> str:
        draft_id = f"draft_{uuid.uuid4().hex[:10]}"
        now = utc_now()
        self.conn.execute(
            """
            INSERT INTO drafts (draft_id, task_id, contact_id, channel, text, status, approved_text, version, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (draft_id, task_id, draft.contact_id, draft.channel, draft.text, draft.status, draft.approved_text, draft.version, now, now),
        )
        return draft_id

    def update_draft_text(self, draft_id: str, text: str, instructions: str, actor: str = "user") -> sqlite3.Row:
        draft = self.get_draft(draft_id)
        if draft is None:
            raise ValueError(f"Draft not found: {draft_id}")
        if draft["status"] == "approved":
            raise ValueError(f"Draft is already approved and cannot be edited: {draft_id}")
        old_text = draft["text"]
        self.conn.execute(
            """
            UPDATE drafts
            SET text = ?, status = 'pending', approved_text = '', version = version + 1, updated_at = ?
            WHERE draft_id = ?
            """,
            (text, utc_now(), draft_id),
        )
        self.add_audit_event(
            draft["task_id"],
            draft_id,
            "draft_redrafted",
            actor,
            {
                "instructions": instructions,
                "old_text": old_text,
                "new_text": text,
                "new_version": draft["version"] + 1,
            },
        )
        self.recompute_task_stage(draft["task_id"])
        self.conn.commit()
        return self.get_draft(draft_id)

    def add_audit_event(self, task_id: str, draft_id: str | None, action: str, actor: str, payload: dict[str, Any]) -> None:
        self.conn.execute(
            """
            INSERT INTO audit_events (task_id, draft_id, action, actor, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (task_id, draft_id, action, actor, json.dumps(payload, ensure_ascii=False), utc_now()),
        )

    def approve_draft(self, draft_id: str, actor: str = "user") -> sqlite3.Row:
        draft = self.get_draft(draft_id)
        if draft is None:
            raise ValueError(f"Draft not found: {draft_id}")
        self.conn.execute(
            "UPDATE drafts SET status = 'approved', approved_text = text, updated_at = ? WHERE draft_id = ?",
            (utc_now(), draft_id),
        )
        self.add_audit_event(
            draft["task_id"],
            draft_id,
            "draft_approved",
            actor,
            {
                "recipient": draft["contact_id"],
                "channel": draft["channel"],
                "approved_text": draft["text"],
            },
        )
        self.recompute_task_stage(draft["task_id"])
        self.conn.commit()
        return self.get_draft(draft_id)

    def reject_draft(self, draft_id: str, reason: str = "", actor: str = "user") -> sqlite3.Row:
        draft = self.get_draft(draft_id)
        if draft is None:
            raise ValueError(f"Draft not found: {draft_id}")
        self.conn.execute(
            "UPDATE drafts SET status = 'rejected', updated_at = ? WHERE draft_id = ?",
            (utc_now(), draft_id),
        )
        self.add_audit_event(draft["task_id"], draft_id, "draft_rejected", actor, {"reason": reason})
        self.recompute_task_stage(draft["task_id"])
        self.conn.commit()
        return self.get_draft(draft_id)

    def recompute_task_stage(self, task_id: str) -> None:
        rows = self.conn.execute(
            "SELECT status, COUNT(*) AS count FROM drafts WHERE task_id = ? GROUP BY status",
            (task_id,),
        ).fetchall()
        counts = {row["status"]: row["count"] for row in rows}
        if not counts:
            return
        if counts.get("pending", 0) > 0:
            stage = "awaiting_approval"
        elif counts.get("approved", 0) > 0:
            stage = "manual_send_ready"
        else:
            stage = "closed_no_send"
        self.conn.execute(
            "UPDATE tasks SET stage = ?, updated_at = ? WHERE task_id = ?",
            (stage, utc_now(), task_id),
        )

    def get_task(self, task_id: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()

    def get_draft(self, draft_id: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM drafts WHERE draft_id = ?", (draft_id,)).fetchone()

    def get_contact(self, contact_id: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM contacts WHERE contact_id = ?", (contact_id,)).fetchone()

    def list_tasks(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM tasks ORDER BY created_at DESC").fetchall()

    def task_bundle(self, task_id: str) -> dict[str, Any]:
        task = self.get_task(task_id)
        if task is None:
            raise ValueError(f"Task not found: {task_id}")
        return {
            "task": dict(task),
            "clarifications": [dict(row) for row in self.conn.execute("SELECT * FROM clarifications WHERE task_id = ? ORDER BY id", (task_id,))],
            "sources": [dict(row) for row in self.conn.execute("SELECT * FROM sources WHERE task_id = ? ORDER BY retrieved_at", (task_id,))],
            "contacts": [dict(row) for row in self.conn.execute("SELECT * FROM contacts WHERE task_id = ? ORDER BY name", (task_id,))],
            "drafts": [dict(row) for row in self.conn.execute("SELECT * FROM drafts WHERE task_id = ? ORDER BY created_at", (task_id,))],
            "audit_events": [dict(row) for row in self.conn.execute("SELECT * FROM audit_events WHERE task_id = ? ORDER BY event_id", (task_id,))],
        }
