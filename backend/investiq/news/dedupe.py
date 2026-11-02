"""Duplicate and related-story detection on headlines (deterministic, no AI)."""

from __future__ import annotations

import hashlib
import re

STOPWORDS = {
    "a", "an", "the", "of", "to", "in", "on", "for", "and", "or", "at", "by", "with", "as", "is", "are", "be", "its",
    "from", "after", "over", "says", "said", "new", "update", "amid", "into", "up", "down", "vs", "will", "may",
}
_WORD = re.compile(r"[a-z0-9$%.]+")


def tokens(title: str) -> set[str]:
    words = (w.strip(".") for w in _WORD.findall(title.lower()))
    return {w for w in words if w and w not in STOPWORDS and len(w) > 1}


def fingerprint(title: str) -> str:
    return hashlib.sha1(" ".join(sorted(tokens(title))).encode(), usedforsecurity=False).hexdigest()


def similarity(a: str, b: str) -> float:
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


RELATED_THRESHOLD = 0.5
