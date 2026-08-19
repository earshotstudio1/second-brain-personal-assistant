from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from pa_agent.db import Store, init_db
from pa_agent.providers import DryRunSearchProvider, RuleBasedDraftProvider
from pa_agent.workflow import TaskWorkflow


class WorkflowTests(unittest.TestCase):
    def test_workflow_creates_durable_task_and_obsidian_note(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = sqlite3.connect(Path(tmp) / "test.sqlite3")
            conn.row_factory = sqlite3.Row
            init_db(conn)
            try:
                store = Store(conn)
                workflow = TaskWorkflow(store, DryRunSearchProvider(), RuleBasedDraftProvider(), Path(tmp) / "obsidian")

                task_id = workflow.run_research_and_drafts("research and draft outreach for hair transplant clinics in Turkey")
                bundle = store.task_bundle(task_id)

                self.assertEqual(bundle["task"]["stage"], "awaiting_approval")
                self.assertGreaterEqual(len(bundle["sources"]), 1)
                self.assertGreaterEqual(len(bundle["contacts"]), 1)
                self.assertGreaterEqual(len(bundle["drafts"]), 1)
                self.assertTrue(Path(bundle["task"]["obsidian_path"]).exists())
            finally:
                conn.close()

    def test_approval_stores_exact_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = sqlite3.connect(Path(tmp) / "test.sqlite3")
            conn.row_factory = sqlite3.Row
            init_db(conn)
            try:
                store = Store(conn)
                workflow = TaskWorkflow(store, DryRunSearchProvider(), RuleBasedDraftProvider(), Path(tmp) / "obsidian")

                task_id = workflow.run_research_and_drafts("find a plumber who can come this week")
                draft_id = store.task_bundle(task_id)["drafts"][0]["draft_id"]
                draft = store.approve_draft(draft_id)

                self.assertEqual(draft["status"], "approved")
                self.assertEqual(draft["approved_text"], draft["text"])
                audit_events = store.task_bundle(task_id)["audit_events"]
                approval = [event for event in audit_events if event["action"] == "draft_approved"][0]
                payload = json.loads(approval["payload_json"])
                self.assertEqual(payload["approved_text"], draft["text"])
            finally:
                conn.close()

    def test_start_task_pauses_for_clarification_then_continues(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = sqlite3.connect(Path(tmp) / "test.sqlite3")
            conn.row_factory = sqlite3.Row
            init_db(conn)
            try:
                store = Store(conn)
                workflow = TaskWorkflow(store, DryRunSearchProvider(), RuleBasedDraftProvider(), Path(tmp) / "obsidian")

                result = workflow.start_task("research and draft outreach for hair transplant clinics in Turkey")
                bundle = store.task_bundle(result.task_id)

                self.assertTrue(result.needs_clarification)
                self.assertEqual(bundle["task"]["stage"], "awaiting_clarification")
                self.assertEqual(bundle["clarifications"][0]["answer"], "")

                workflow.continue_after_clarification(result.task_id, "Budget up to 3000 GBP, Istanbul preferred, next 3 months.")
                bundle = store.task_bundle(result.task_id)

                self.assertEqual(bundle["task"]["stage"], "awaiting_approval")
                self.assertEqual(bundle["clarifications"][0]["answer"], "Budget up to 3000 GBP, Istanbul preferred, next 3 months.")
                self.assertGreaterEqual(len(bundle["drafts"]), 1)
            finally:
                conn.close()

    def test_redraft_updates_version_and_audit_trail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = sqlite3.connect(Path(tmp) / "test.sqlite3")
            conn.row_factory = sqlite3.Row
            init_db(conn)
            try:
                store = Store(conn)
                workflow = TaskWorkflow(store, DryRunSearchProvider(), RuleBasedDraftProvider(), Path(tmp) / "obsidian")

                task_id = workflow.run_research_and_drafts("find a plumber who can come this week")
                draft = store.task_bundle(task_id)["drafts"][0]
                updated = workflow.redraft(draft["draft_id"], "Make it shorter and mention Friday morning.")

                self.assertEqual(updated["version"], 2)
                self.assertEqual(updated["status"], "pending")
                self.assertIn("Friday morning", updated["text"])
                audit_events = store.task_bundle(task_id)["audit_events"]
                redraft = [event for event in audit_events if event["action"] == "draft_redrafted"][0]
                payload = json.loads(redraft["payload_json"])
                self.assertEqual(payload["old_text"], draft["text"])
                self.assertEqual(payload["new_text"], updated["text"])
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
