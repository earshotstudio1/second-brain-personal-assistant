from __future__ import annotations

import re

# Daniel's writing rules. These exist twice on purpose: as prompt text the model
# is asked to follow, and as deterministic checks that run locally on whatever
# the model actually produced. The local checks cost nothing and do not depend
# on the model agreeing that it followed the rules.

BANNED_WORDS = (
    "delve",
    "harness",
    "robust",
    "streamline",
    "passionate about",
    "proven track record",
)

EM_DASH = "—"

# "leverage" is fine as a noun and banned as a verb. Inflected forms are always
# verbs; the bare form is only treated as a verb after a subject or modal.
LEVERAGE_AS_VERB = re.compile(
    r"\b(?:leverages|leveraged|leveraging)\b|\b(?:to|we|i|you|they|it|can|will|would|should|could)\s+leverage\b",
    re.I,
)

# "not just X but Y" and its close relatives.
FALSE_CONTRAST = re.compile(r"\bnot (?:just|only|merely|simply)\b[^.!?]{0,120}?\bbut\b", re.I)

VOICE_RULES = f"""Write in Daniel's voice and in British English:
- Never use an em dash ({EM_DASH}). Use a full stop, a comma, or " - " instead.
- Never use false contrasts of the form "not just X but Y", "not only X but Y".
- Never use these words or phrases: {", ".join(BANNED_WORDS)}.
- Never use "leverage" as a verb. Say "use".
- Prefer exact numbers and named specifics over abstractions."""

QUALITY_CHECKLIST = f"""Acceptance criteria. The output is only finished when all of these hold:
1. Every factual claim traces to a source URL that was supplied to you in this request. Do not cite a URL that is not in the supplied sources.
2. No invented figures. No prices, dates, ratings, headcounts, or availability unless a supplied source states them.
3. State uncertainty plainly where the sources do not settle a question, rather than smoothing over it.
4. {VOICE_RULES}
5. Be concise. Cut any sentence that carries no information."""


def voice_violations(text: str) -> list[str]:
    """Return a list of rule breaches found in `text`. Empty means it reads clean."""
    content = text or ""
    lowered = content.lower()
    violations: list[str] = []
    if EM_DASH in content:
        violations.append("em dash")
    for word in BANNED_WORDS:
        if word in lowered:
            violations.append(f"banned word: {word}")
    if LEVERAGE_AS_VERB.search(content):
        violations.append("leverage used as a verb")
    if FALSE_CONTRAST.search(content):
        violations.append("false contrast")
    return violations


def better_draft(original: str, revised: str) -> str:
    """Pick the version with fewer rule breaches.

    Ties go to the revision, because it also carries the reviewer's fixes.
    """
    if len(voice_violations(revised)) <= len(voice_violations(original)):
        return revised
    return original
