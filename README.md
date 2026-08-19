# Personal Assistant Agent

An agent that researches, drafts outreach, and files everything into Obsidian. It cannot send anything.

## The safety design, first

That last sentence is the point of the project, so it goes before the feature list.

- **No external sending exists in the codebase.** Not disabled, not gated behind a flag. There is no email path, no WhatsApp path, no calendar invite path. Approving a draft marks it approved and shows you the text to send yourself.
- **Web and email content is data, never instruction.** Anything the agent fetches is treated as untrusted input. Text inside a fetched page that tells the agent to do something does not get to be a command.
- **Every sourced claim keeps its URL.** A research brief you cannot check is not a research brief.
- **Approvals are recorded immutably** - exact text, recipient, channel, timestamp, action. Once a draft is approved, that version of the text is fixed. Edits create a new version rather than rewriting history.
- **SQLite is the source of truth, Obsidian is the export.** The audit trail lives somewhere that cannot be accidentally edited by a human reading their notes.

I built it this way because an agent that can research and draft is genuinely useful, and an agent that can send is a category of mistake I do not want to make at three in the morning.

## What it does

Give it an admin task in plain language. It works out what it needs, asks one clarifying question if the context is missing, researches with sources, produces a brief, drafts the outreach messages, and saves the lot into the vault. Then it stops and waits for you.

Runs as a CLI or as a Telegram bot with approve, edit and reject buttons. Editing means replying with revision instructions; the agent redrafts and increments the version.

## Architecture

- **Provider abstraction** (`providers.py`) - Anthropic for drafting, Tavily for search, behind one interface. With no keys present it runs in dry-run mode on realistic sample data, so the workflow is testable without spending anything.
- **Workflow as an explicit state machine** (`workflow.py`, `clarification.py`) - a task that is missing context pauses and waits for a human answer rather than guessing, which is what makes the single-clarification-question behaviour possible.
- **Security is its own module** (`security.py`) - untrusted-content handling is a named concern with a file of its own, not a comment somewhere in the fetch path.
- **Durable state in SQLite** (`db.py`) with the Obsidian export as a derived view (`obsidian.py`) - the human-readable copy can be deleted or edited without losing the record.
- **Packaged properly** - `pyproject.toml`, installable, entry point via `python -m pa_agent`.

## Status

Milestone 1, working. Around 1,400 lines of Python with tests. Single-user, local, Windows-first in the scheduling but not in the code. The task database is deliberately excluded from this repo.

Not built and not planned for this milestone: any form of external sending.

## Setup

Requires Python 3.13.

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e .
.\.venv\Scripts\python -m pa_agent init-db
.\.venv\Scripts\python -m pa_agent task "research and draft outreach for hair transplant clinics in Turkey"
.\.venv\Scripts\python -m pa_agent clarify task_xxxxxxxxxx "Budget up to 3000 GBP, Istanbul preferred, next 3 months"
.\.venv\Scripts\python -m pa_agent status
```

Copy `.env.example` to `.env` and add `ANTHROPIC_API_KEY` and `TAVILY_API_KEY` for live mode; without them it runs dry on realistic sample data.

## Draft quality

The drafting model defaults to `claude-sonnet-5` (`ANTHROPIC_MODEL`). Four things hold quality up rather than model size:

- **Structured output** - the research brief is constrained to a JSON schema (summary, options, recommendation, sources, open questions) through `output_config.format`, so nothing depends on finding JSON inside prose.
- **Acceptance criteria in the system prompt** (`voice.py`) - cite only supplied source URLs, invent no figures, state uncertainty, British English, and Daniel's writing rules.
- **A self-review pass** - every outreach draft is checked against those criteria by a second short call (`ANTHROPIC_REVIEW_MODEL`, defaults to the drafting model). On a fail the agent gets exactly one revision attempt, then keeps whichever version breaks fewer rules.
- **Adaptive thinking** on the drafting calls, with the review call pinned to low effort.

The voice rules run twice: as prompt text, and as local checks in `voice.py` that do not depend on the model agreeing it followed them. Those local checks can veto a passing review.

## Telegram mode

Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_ALLOWED_CHAT_ID`, then:

```powershell
.\.venv\Scripts\python -m pa_agent telegram
```

Commands:

- `/task research and draft outreach for ...`
- `/status`
- `/cancel <task_id>` or `/cancel all` - moves a task to the terminal `cancelled` stage and records it in the audit trail. Research, contacts, and drafts are kept.
- `/debug <task_id>`
- If context is missing, the bot asks one clarification question. Reply to that message to continue the task.
- Draft buttons support approve, edit, and reject. Edit means replying to the draft message with revision instructions; the agent redrafts and increments the draft version.
- Approval only marks a draft approved and shows the manual-send text.

The allowed-chat check is not optional.

## Running the tests

No install needed to run the test suite, just a working `pip install pytest` and the project source on the path:

```powershell
pip install pytest
$env:PYTHONPATH="src"
python -m pytest
```

Or, from inside the project's own virtualenv after `pip install -e .`, just `python -m pytest`. Four tests cover the workflow end to end: task creation, clarification pausing and resuming, and that draft approval stores exact text immutably.

## License

MIT. See [LICENSE](LICENSE).
