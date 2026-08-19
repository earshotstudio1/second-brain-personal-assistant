from __future__ import annotations


KEYWORDS_THAT_USUALLY_NEED_CONTEXT = (
    "book",
    "clinic",
    "clinics",
    "consultation",
    "consultations",
    "insurance",
    "quote",
    "quotes",
    "venue",
    "venues",
    "plumber",
    "outreach",
)

CONTEXT_MARKERS = (
    "budget",
    "timeline",
    "deadline",
    "location",
    "area",
    "preference",
    "preferences",
    "date",
    "when",
    "this week",
    "next week",
)


def clarification_question(user_request: str) -> str | None:
    text = user_request.lower()
    if not any(keyword in text for keyword in KEYWORDS_THAT_USUALLY_NEED_CONTEXT):
        return None
    if any(marker in text for marker in CONTEXT_MARKERS):
        return None
    return (
        "Before I research, what constraints should I use? "
        "Share any budget range, location preference, timeline, must-haves, or deal-breakers. "
        "Reply 'no preference' if I should proceed broadly."
    )

