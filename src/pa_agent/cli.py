from __future__ import annotations

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

from .app import build_store, build_workflow, refresh_obsidian_export
from .config import load_settings
from .db import connect, init_db
from .telegram import run_telegram_bot

# Load values from the project-root .env, if present. Real environment
# variables already set take precedence (override=False is dotenv's default).
load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)


def main() -> None:
    parser = argparse.ArgumentParser(prog="pa-agent")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db")

    task_parser = sub.add_parser("task")
    task_parser.add_argument("request")

    clarify_parser = sub.add_parser("clarify")
    clarify_parser.add_argument("task_id")
    clarify_parser.add_argument("answer")

    sub.add_parser("status")

    debug_parser = sub.add_parser("debug")
    debug_parser.add_argument("task_id")

    approve_parser = sub.add_parser("approve")
    approve_parser.add_argument("draft_id")

    reject_parser = sub.add_parser("reject")
    reject_parser.add_argument("draft_id")
    reject_parser.add_argument("--reason", default="")

    cancel_parser = sub.add_parser("cancel")
    cancel_parser.add_argument("task_id", help="Task ID to cancel, or 'all' for every pending task.")
    cancel_parser.add_argument("--reason", default="")

    redraft_parser = sub.add_parser("redraft")
    redraft_parser.add_argument("draft_id")
    redraft_parser.add_argument("instructions")

    sub.add_parser("telegram")

    args = parser.parse_args()
    settings = load_settings()

    if args.command == "init-db":
        conn = connect(settings.db_path)
        init_db(conn)
        print(f"Initialized database: {settings.db_path}")
        return

    if args.command == "task":
        workflow = build_workflow(settings)
        result = workflow.start_task(args.request)
        bundle = workflow.store.task_bundle(result.task_id)
        print(f"Created {result.task_id}")
        if result.needs_clarification:
            print(f"Clarification needed: {result.question}")
            print(f"Continue with: pa-agent clarify {result.task_id} \"your answer\"")
        else:
            print(f"Obsidian note: {bundle['task']['obsidian_path']}")
            print(f"Drafts awaiting approval: {len(bundle['drafts'])}")
        return

    if args.command == "clarify":
        workflow = build_workflow(settings)
        task_id = workflow.continue_after_clarification(args.task_id, args.answer)
        bundle = workflow.store.task_bundle(task_id)
        print(f"Continued {task_id}")
        print(f"Obsidian note: {bundle['task']['obsidian_path']}")
        print(f"Drafts awaiting approval: {len(bundle['drafts'])}")
        return

    store = build_store(settings)
    if args.command == "status":
        tasks = store.list_tasks()
        if not tasks:
            print("No tasks yet.")
            return
        for task in tasks:
            print(f"{task['task_id']} | {task['stage']} | {task['status']} | {task['user_request']}")
        return

    if args.command == "debug":
        print(json.dumps(store.task_bundle(args.task_id), indent=2, ensure_ascii=False))
        return

    if args.command == "approve":
        draft = store.approve_draft(args.draft_id)
        refresh_obsidian_export(settings, store, draft["task_id"])
        print(f"Approved {args.draft_id}. Manual-send text:\n")
        print(draft["approved_text"])
        return

    if args.command == "reject":
        draft = store.reject_draft(args.draft_id, reason=args.reason)
        refresh_obsidian_export(settings, store, draft["task_id"])
        print(f"Rejected {args.draft_id}")
        return

    if args.command == "cancel":
        if args.task_id == "all":
            task_ids = [row["task_id"] for row in store.cancellable_tasks()]
            if not task_ids:
                print("No pending tasks to cancel.")
                return
            for task_id in task_ids:
                store.cancel_task(task_id, reason=args.reason, actor="cli")
                refresh_obsidian_export(settings, store, task_id)
                print(f"Cancelled {task_id}")
            return
        task = store.cancel_task(args.task_id, reason=args.reason, actor="cli")
        refresh_obsidian_export(settings, store, task["task_id"])
        print(f"Cancelled {task['task_id']} (stage: {task['stage']})")
        return

    if args.command == "redraft":
        workflow = build_workflow(settings)
        draft = workflow.redraft(args.draft_id, args.instructions)
        print(f"Redrafted {args.draft_id} as version {draft['version']}:\n")
        print(draft["text"])
        return

    if args.command == "telegram":
        run_telegram_bot(settings)
        return


if __name__ == "__main__":
    main()
