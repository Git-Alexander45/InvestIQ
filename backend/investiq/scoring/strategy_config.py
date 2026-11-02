"""The baseline (frozen) strategy configuration and helpers for versioning it.

Equity weights come directly from the master specification. Weights for the other asset-class
models are InvestIQ's initial judgement (documented in docs/DECISIONS.md) and are meant to be
tested and revised through experimental strategy versions, never edited in place.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

BASELINE_CONFIG: dict[str, Any] = {
    "models": {
        "equity": {
            "weights": {
                "growth": 25, "financial_strength": 20, "valuation": 15, "competitive_advantage": 10,
                "industry_trends": 10, "catalysts_news": 10, "risk": 10,
            }
        },
        "etf_equity": {
            "weights": {
                "cost": 15, "diversification": 20, "long_term_return": 20, "growth_exposure": 15,
                "valuation": 10, "risk": 10, "structure_liquidity": 10,
            }
        },
        "fixed_income": {
            "weights": {
                "yield": 25, "credit_quality": 20, "duration_risk": 15, "cost": 15, "risk": 15,
                "structure_liquidity": 10,
            }
        },
        "commodity": {
            "weights": {
                "structure": 20, "cost": 15, "diversification_benefit": 25, "long_term_return": 15,
                "trend": 10, "risk": 15,
            }
        },
        "cash_equivalent": {
            "weights": {"yield": 40, "safety": 30, "cost": 20, "structure_liquidity": 10},
        },
    },
    # Categories without data are scored at this neutral value (and reduce coverage/confidence),
    # so a thin data set can never produce a high grade.
    "missing_category_score": 50.0,
    "assessment": {
        "buy_min_overall": 80.0,
        "buy_min_valuation": 50.0,
        "buy_min_risk": 35.0,
        "buy_min_coverage": 0.6,
        "buy_min_confidence": 0.55,
        "watch_min_overall": 70.0,
        "avoid_below": 60.0,
        "sell_below_for_holdings": 60.0,
    },
    "leaderboards": {"size": 10},
}


def config_hash(config: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(config, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate_config(config: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    models = config.get("models", {})
    for name in BASELINE_CONFIG["models"]:
        if name not in models:
            problems.append(f"missing model '{name}'")
            continue
        weights = models[name].get("weights", {})
        expected = set(BASELINE_CONFIG["models"][name]["weights"])
        if set(weights) != expected:
            problems.append(f"model '{name}' must define weights for {sorted(expected)}")
        if any((not isinstance(w, int | float)) or w < 0 for w in weights.values()):
            problems.append(f"model '{name}' has a negative or non-numeric weight")
        if abs(sum(weights.values()) - 100) > 1e-6:
            problems.append(f"model '{name}' weights must sum to 100 (got {sum(weights.values())})")
    a = config.get("assessment", {})
    for key in BASELINE_CONFIG["assessment"]:
        if key not in a:
            problems.append(f"assessment.{key} missing")
    return problems


def baseline() -> dict[str, Any]:
    return copy.deepcopy(BASELINE_CONFIG)
