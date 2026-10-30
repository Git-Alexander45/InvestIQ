"""Research assessments: BUY, WATCH, HOLD, SELL, AVOID.

These are research opinions only. Nothing here places or simulates a real trade.
BUY is deliberately hard to reach: strong evidence, sensible valuation, acceptable risk,
enough data, verified availability at BOTH brokerages and an acceptable portfolio fit.
WATCH is the "wait" outcome and is the default for good investments that fail any BUY test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from investiq.scoring.engine import ScoreResult

ASSESSMENTS = ("BUY", "WATCH", "HOLD", "SELL", "AVOID")
_ORDER = {"AVOID": 0, "SELL": 1, "WATCH": 2, "HOLD": 3, "BUY": 4}


@dataclass
class FitResult:
    acceptable: bool = True
    flags: list[str] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class AssessmentResult:
    assessment: str
    primary_eligible: bool
    rationale: str
    why_not_now: str | None
    blockers: list[str]


def assess(score: ScoreResult, cfg: dict[str, Any], *, brokerage: dict[str, str], fit: FitResult,
           held: bool, excluded_reason: str | None = None) -> AssessmentResult:
    a = cfg["assessment"]
    overall = score.overall
    valuation = score.score_of("valuation")
    risk = score.score_of("risk")
    both_verified = all(brokerage.get(b) == "VERIFIED" for b in ("wealthsimple", "questrade"))
    any_unavailable = any(v == "UNAVAILABLE" for v in brokerage.values())

    if excluded_reason:
        return AssessmentResult("AVOID", False, excluded_reason, None, [excluded_reason])

    if score.avoid_reasons or overall < a["avoid_below"]:
        reasons = list(score.avoid_reasons)
        if overall < a["avoid_below"]:
            reasons.append(f"Overall score {overall:.1f} is below {a['avoid_below']:.0f}.")
        if held:
            return AssessmentResult("SELL", False, "Held position no longer meets minimum standards: "
                                    + " ".join(reasons), None, reasons)
        return AssessmentResult("AVOID", False, " ".join(reasons), None, reasons)

    if held:
        if overall < a["sell_below_for_holdings"]:
            return AssessmentResult("SELL", False, f"Held position scores {overall:.1f}.", None, [])
        blockers = _buy_blockers(score, a, valuation, risk, both_verified, any_unavailable, fit)
        why = "; ".join(blockers) if blockers else None
        return AssessmentResult("HOLD", both_verified,
                                f"Held position remains acceptable (grade {score.grade}).",
                                f"Not adding more now: {why}" if why else None, blockers)

    blockers = _buy_blockers(score, a, valuation, risk, both_verified, any_unavailable, fit)
    if not blockers:
        return AssessmentResult("BUY", True,
                                f"Grade {score.grade} ({overall:.1f}) with acceptable valuation, risk, data coverage, "
                                "portfolio fit and verified availability at both brokerages.", None, [])
    if overall >= a["watch_min_overall"]:
        return AssessmentResult("WATCH", False,
                                f"Attractive candidate (grade {score.grade}, {overall:.1f}) but not a purchase today.",
                                "; ".join(blockers), blockers)
    return AssessmentResult("WATCH", False, f"Below conviction threshold (grade {score.grade}, {overall:.1f}).",
                            "; ".join(blockers), blockers)


def _buy_blockers(score: ScoreResult, a: dict[str, Any], valuation: float | None, risk: float | None,
                  both_verified: bool, any_unavailable: bool, fit: FitResult) -> list[str]:
    blockers: list[str] = []
    if score.overall < a["buy_min_overall"]:
        blockers.append(f"overall score {score.overall:.1f} below {a['buy_min_overall']:.0f}")
    if valuation is not None and valuation < a["buy_min_valuation"] and score.categories["valuation"].available:
        blockers.append(f"valuation score {valuation:.0f} is stretched (minimum {a['buy_min_valuation']:.0f})")
    if risk is not None and risk < a["buy_min_risk"] and score.categories["risk"].available:
        blockers.append(f"risk characteristics score {risk:.0f} below {a['buy_min_risk']:.0f}")
    if score.coverage < a["buy_min_coverage"]:
        blockers.append(f"data coverage {score.coverage:.0%} below {a['buy_min_coverage']:.0%}")
    if score.confidence < a["buy_min_confidence"]:
        blockers.append(f"confidence {score.confidence:.2f} below {a['buy_min_confidence']:.2f}")
    if any_unavailable:
        blockers.append("reported UNAVAILABLE at a required brokerage")
    elif not both_verified:
        blockers.append("availability not verified at both Wealthsimple and Questrade")
    if not fit.acceptable:
        blockers.append("would weaken portfolio diversification: " + "; ".join(fit.flags))
    return blockers


def more_cautious(a: str, b: str) -> str:
    """Return the more cautious of two assessments (an AI review may downgrade, never upgrade)."""
    return a if _ORDER[a] <= _ORDER[b] else b
