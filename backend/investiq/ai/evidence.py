"""Evidence packs: numbered facts the model may cite, and validation of the citations it returns."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel


@dataclass
class Fact:
    id: str
    kind: str  # fundamentals, price, news, score, holdings, brokerage, portfolio, owner_note, prior_analysis
    text: str
    source: str
    as_of: str | None = None


@dataclass
class EvidencePack:
    subject: str
    facts: list[Fact] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    _counters: dict[str, int] = field(default_factory=dict)

    PREFIX = {"fundamentals": "F", "price": "P", "news": "N", "score": "S", "holdings": "H", "brokerage": "B",
              "portfolio": "D", "owner_note": "O", "prior_analysis": "A", "macro": "M", "analysis": "X"}

    def add(self, kind: str, text: str, source: str, as_of: str | None = None) -> str:
        prefix = self.PREFIX.get(kind, "E")
        self._counters[prefix] = self._counters.get(prefix, 0) + 1
        fid = f"{prefix}{self._counters[prefix]}"
        self.facts.append(Fact(fid, kind, text, source, as_of))
        return fid

    @property
    def ids(self) -> set[str]:
        return {f.id for f in self.facts}

    def render(self) -> str:
        lines = [f"# Evidence pack: {self.subject}", ""]
        for f in self.facts:
            stamp = f" (as of {f.as_of})" if f.as_of else ""
            lines.append(f"[{f.id}] {f.text} — source: {f.source}{stamp}")
        if self.context:
            lines += ["", "# Context (not citable)", json.dumps(self.context, default=str, indent=1)]
        return "\n".join(lines)

    def as_dict(self) -> dict[str, Any]:
        return {"subject": self.subject, "facts": [f.__dict__ for f in self.facts], "context": self.context}


def _claims(obj: Any, path: str = "") -> list[tuple[str, str, list[str]]]:
    """Find every {text|rationale, evidence} pair in a validated output."""
    out: list[tuple[str, str, list[str]]] = []
    if isinstance(obj, BaseModel):
        obj = obj.model_dump()
    if isinstance(obj, dict):
        if "evidence" in obj and isinstance(obj["evidence"], list):
            text = obj.get("text") or obj.get("rationale") or obj.get("reasoning") or obj.get("what_happened") or ""
            out.append((path, str(text), [str(e) for e in obj["evidence"]]))
        for k, v in obj.items():
            if k != "evidence":
                out.extend(_claims(v, f"{path}.{k}" if path else k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.extend(_claims(v, f"{path}[{i}]"))
    return out


@dataclass
class CitationCheck:
    total_claims: int
    unsupported: list[dict[str, Any]]
    invalid_ids: list[str]

    @property
    def unsupported_ratio(self) -> float:
        return len(self.unsupported) / self.total_claims if self.total_claims else 0.0

    @property
    def acceptable(self) -> bool:
        # Fabricated citations are never acceptable; a minority of uncited claims is tolerated
        # (they are listed so the UI and reports can show them as unsupported).
        return not self.invalid_ids and self.unsupported_ratio <= 0.5


def check_citations(output: Any, pack: EvidencePack) -> CitationCheck:
    valid = pack.ids
    unsupported, invalid = [], []
    claims = _claims(output)
    for path, text, ids in claims:
        bad = [i for i in ids if i not in valid]
        invalid.extend(bad)
        if not [i for i in ids if i in valid]:
            unsupported.append({"path": path, "text": text[:300]})
    return CitationCheck(len(claims), unsupported, sorted(set(invalid)))
