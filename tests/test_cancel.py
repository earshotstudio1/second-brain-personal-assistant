from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from pa_agent.db import Store, init_db
from pa_agent.obsidian import render_task_note
from pa_agent.providers import DryRunSearchProvider, RuleBasedDraftProvider
from pa_agent.workflow import TaskWorkflow


class CancelTaskTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.conn = sqlite3.connect(self.tmp / "test.sqlite3")
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)
        self.store = Store(self.conn)
        self.workflow = TaskWorkflow(self.store, DryRunSearchProvider(), RuleBasedDraftProvider(), self.tmp / "obsidian")

    def tearDown(self) -> None:
        self.conn.close()
        self._tmp.cleanup()

    def test_cancel_moves_task_to_terminal_stage_and_writes_audit_event(self) -> None:
        task_id = self.store.create_task("research crm options")

        task = self.store.cancel_task(task_id, reason="No longer needed", actor="telegram")

        self.assertEqual(task["stage"], "cancelled")
        self.assertEqual(task["status"], "cancelled")
        events = self.store.task_bundle(task_id)["audit_events"]
        cancelled = [event for event in events if event["action"] == "task_cancelled"]
        self.assertEqual(len(cancelled), 1)
        self.assertEqual(cancelled[0]["actor"], "telegram")
        payload = json.loads(cancelled[0]["payload_json"])
        self.assertEqual(payload["reason"], "No longer needed")
        self.assertEqual(payload["previous_stage"], "created")

    def test_cancel_works_from_a_stuck_drafting_stage(self) -> None:
        task_id = self.store.create_task("research crm options")
        self.store.update_task(task_id, stage="drafting")

        task = self.store.cancel_task(task_id, actor="script")

        self.assertEqual(task["stage"], "cancelled")
        payload = json.loads(self.store.task_bundle(task_id)["audit_events"][-1]["payload_json"])
        self.assertEqual(payload["previous_stage"], "drafting")

    def test_cancelling_twice_is_rejected(self) -> None:
        task_id = self.store.create_task("research crm options")
        self.store.cancel_task(task_id)

        with self.assertRaises(ValueError):
            self.store.cancel_task(task_id)

    def test_cancelling_an_unknown_task_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.store.cancel_task("task_does_not_exist")

    def test_finished_task_cannot_be_cancelled(self) -> None:
        task_id = self.workflow.run_research_and_drafts("find a plumber who can come this week")
        for draft in self.store.task_bundle(task_id)["drafts"]:
            self.store.approve_draft(draft["draft_id"])
        self.assertEqual(self.store.get_task(task_id)["stage"], "manual_send_ready")

        with self.assertRaises(ValueError):
            self.store.cancel_task(task_id)

    def test_cancelled_task_is_not_revived_by_draft_activity(self) -> None:
        task_id = self.workflow.run_research_and_drafts("find a plumber who can come this week")
        draft_id = self.store.task_bundle(task_id)["drafts"][0]["draft_id"]
        self.store.cancel_task(task_id)

        self.store.approve_draft(draft_id)

        self.assertEqual(self.store.get_task(task_id)["stage"], "cancelled")

    def test_cancellable_tasks_lists_only_in_flight_work(self) -> None:
        pending_id = self.store.create_task("still going")
        self.store.update_task(pending_id, stage="drafting")
        cancelled_id = self.store.create_task("already stopped")
        self.store.cancel_task(cancelled_id)
        finished_id = self.store.create_task("already finished")
        self.store.update_task(finished_id, stage="manual_send_ready")

        task_ids = [row["task_id"] for row in self.store.cancellable_tasks()]

        self.assertIn(pending_id, task_ids)
        self.assertNotIn(cancelled_id, task_ids)
        self.assertNotIn(finished_id, task_ids)

    def test_cancelled_task_note_reports_cancelled_status(self) -> None:
        task_id = self.workflow.run_research_and_drafts("find a plumber who can come this week")
        self.store.cancel_task(task_id)

        note = render_task_note(self.store.task_bundle(task_id))

        self.assertIn("status: cancelled", note)
        self.assertIn("Stage: `cancelled`", note)


if __name__ == "__main__":
    unittest.main()
