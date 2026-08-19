from __future__ import annotations

import json
from dataclasses import asdict
from dataclasses import dataclass

from .clarification import clarification_question
from .db import Store
from .models import Contact, Draft, ResearchBrief
from .obsidian import export_task_note
from .providers import DraftProvider, SearchProvider
from .research import build_research_queries, contacts_from_sources


@dataclass(frozen=True)
class TaskStart:
    task_id: str
    needs_clarification: bool
    question: str = ""


class TaskWorkflow:
    def __init__(self, store: Store, search_provider: SearchProvider, draft_provider: DraftProvider, obsidian_export_root):
        self.store = store
        self.search_provider = search_provider
        self.draft_provider = draft_provider
        self.obsidian_export_root = obsidian_export_root

    def start_task(self, user_request: str) -> TaskStart:
        task_id = self.store.create_task(user_request)
        question = clarification_question(user_request)
        if question:
            self.store.add_clarification(task_id, question)
            self.store.add_audit_event(task_id, None, "clarification_requested", "agent", {"question": question})
            self.store.update_task(task_id, stage="awaiting_clarification")
            self._export(task_id)
            return TaskStart(task_id=task_id, needs_clarification=True, question=question)
        self._run_research_for_existing_task(task_id)
        return TaskStart(task_id=task_id, needs_clarification=False)

    def continue_after_clarification(self, task_id: str, answer: str) -> str:
        task = self.store.get_task(task_id)
        if task is None:
            raise ValueError(f"Task not found: {task_id}")
        self.store.answer_pending_clarification(task_id, answer)
        self._run_research_for_existing_task(task_id)
        return task_id

    def run_research_and_drafts(self, user_request: str) -> str:
        task_id = self.store.create_task(user_request)
        self._run_research_for_existing_task(task_id)
        return task_id

    def redraft(self, draft_id: str, instructions: str, actor: str = "user"):
        draft = self.store.get_draft(draft_id)
        if draft is None:
            raise ValueError(f"Draft not found: {draft_id}")
        task = self.store.get_task(draft["task_id"])
        contact_row = self.store.get_contact(draft["contact_id"])
        if task is None or contact_row is None:
            raise ValueError(f"Could not load context for draft: {draft_id}")

        brief_data = json.loads(task["research_brief"] or "{}")
        brief = ResearchBrief(
            summary=brief_data.get("summary", ""),
            ranked_options=brief_data.get("ranked_options", []),
            uncertainty=brief_data.get("uncertainty", []),
        )
        contact = Contact(
            name=contact_row["name"],
            organization=contact_row["organization"],
            email=contact_row["email"],
            phone=contact_row["phone"],
            whatsapp=contact_row["whatsapp"],
            website_url=contact_row["website_url"],
            source_url=contact_row["source_url"],
            confidence=contact_row["confidence"],
            notes=contact_row["notes"],
        )
        new_text = self.draft_provider.revise_draft(task["user_request"], contact, brief, draft["text"], instructions)
        updated = self.store.update_draft_text(draft_id, new_text, instructions, actor=actor)
        self._export(updated["task_id"])
        return updated

    def _run_research_for_existing_task(self, task_id: str) -> None:
        task = self.store.get_task(task_id)
        if task is None:
            raise ValueError(f"Task not found: {task_id}")
        user_request = task["user_request"]
        clarified_request = self._clarified_request(task_id, user_request)
        self.store.update_task(task_id, stage="researching")

        all_sources = []
        for query in build_research_queries(clarified_request):
            sources = self.search_provider.search(query, max_results=5)
            all_sources.extend(sources)
            self.store.add_audit_event(task_id, None, "search_completed", "agent", {"query": query, "source_count": len(sources)})

        deduped_sources = self._dedupe_sources(all_sources)
        for source in deduped_sources:
            self.store.add_source(task_id, source)

        contacts = contacts_from_sources(deduped_sources)
        contact_ids = []
        for contact in contacts:
            contact_ids.append(self.store.add_contact(task_id, contact))

        self.store.update_task(task_id, stage="drafting")
        brief = self.draft_provider.create_brief(clarified_request, deduped_sources, contacts)
        self.store.update_task(task_id, research_brief=asdict(brief))

        for contact_id, contact in zip(contact_ids, contacts, strict=True):
            channel = "whatsapp" if contact.whatsapp else "email" if contact.email else "manual"
            text = self.draft_provider.create_draft(clarified_request, contact, brief)
            draft_id = self.store.add_draft(task_id, Draft(contact_id=contact_id, channel=channel, text=text))
            self.store.add_audit_event(task_id, draft_id, "draft_created", "agent", {"contact_id": contact_id, "channel": channel})

        self.store.update_task(task_id, stage="awaiting_approval")
        self._export(task_id)
        self.store.update_task(task_id, stage="awaiting_approval")

    def _export(self, task_id: str) -> None:
        note_path = export_task_note(self.obsidian_export_root, self.store.task_bundle(task_id))
        self.store.update_task(task_id, obsidian_path=str(note_path))
        self.store.add_audit_event(task_id, None, "obsidian_exported", "agent", {"path": str(note_path)})
        self.store.conn.commit()

    def _clarified_request(self, task_id: str, user_request: str) -> str:
        clarifications = self.store.task_bundle(task_id)["clarifications"]
        answered = [item for item in clarifications if item["answer"]]
        if not answered:
            return user_request
        lines = [user_request, "", "User constraints:"]
        for item in answered:
            lines.append(f"- {item['answer']}")
        return "\n".join(lines)

    @staticmethod
    def _dedupe_sources(sources):
        seen = set()
        deduped = []
        for source in sources:
            key = source.url or source.title
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(source)
        return deduped
