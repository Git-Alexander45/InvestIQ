"""Letter grades. A grade summarises research quality; it is not a probability of success."""

from __future__ import annotations

GRADE_BANDS = [(95, "A+"), (90, "A"), (80, "B"), (70, "C"), (60, "D")]
GRADE_ORDER = ["F", "D", "C", "B", "A", "A+"]
GRADE_DISCLAIMER = (
    "Grades summarise the evidence available at the time of analysis. They are not probabilities "
    "of success and do not guarantee returns."
)


def grade_for(score: float) -> str:
    if not 0 <= score <= 100:
        raise ValueError("score must be within 0..100")
    for threshold, grade in GRADE_BANDS:
        if score >= threshold:
            return grade
    return "F"


def grade_steps(old: str, new: str) -> int:
    return GRADE_ORDER.index(new) - GRADE_ORDER.index(old)
