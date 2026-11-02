"""Idempotent first-run setup: universe, news sources, baseline strategy, paper portfolios."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from investiq.models import Instrument, NewsSource, Portfolio, StrategyVersion, Watchlist
from investiq.scoring.strategy_config import baseline, config_hash
from investiq.services.audit import audit

SEED_DIR = Path(__file__).resolve().parents[1] / "seed"
FROZEN_NAME = "frozen-baseline"
EXPERIMENTAL_NAME = "experimental"

PAPER_PORTFOLIOS: list[dict[str, Any]] = [
    {"code": "A", "name": "Portfolio A - AI Aggressive Growth",
     "description": "Aggressive growth with diversification and risk controls.",
     "strategy": FROZEN_NAME,
     "policy": {"style": "aggressive_growth", "max_positions": 15, "target_cash_pct": 2.0,
                "allowed_models": ["equity", "etf_equity", "commodity"], "min_assessment": "BUY",
                "max_single_stock_pct": 8.0, "max_speculative_pct": 3.0, "max_etf_pct": 25.0,
                "sector_cap_pct": 30.0}},
    {"code": "B", "name": "Portfolio B - Global Growth",
     "description": "Growth opportunities across multiple countries and regions.",
     "strategy": FROZEN_NAME,
     "policy": {"style": "global_growth", "max_positions": 15, "target_cash_pct": 2.0,
                "allowed_models": ["equity", "etf_equity"], "min_assessment": "BUY",
                "max_single_stock_pct": 6.0, "max_speculative_pct": 2.0, "max_etf_pct": 25.0,
                "sector_cap_pct": 30.0, "max_region_pct": 50.0}},
    {"code": "C", "name": "Portfolio C - Growth + Protection",
     "description": "Growth assets combined with defensive investments.",
     "strategy": FROZEN_NAME,
     "policy": {"style": "growth_protection", "max_positions": 15, "target_cash_pct": 5.0,
                "allowed_models": ["equity", "etf_equity", "fixed_income", "commodity", "cash_equivalent"],
                "min_assessment": "BUY", "defensive_min_pct": 30.0, "max_single_stock_pct": 6.0,
                "max_speculative_pct": 1.0, "max_etf_pct": 30.0, "sector_cap_pct": 25.0}},
    {"code": "D", "name": "Portfolio D - AI Experimental",
     "description": "Tests new scoring systems, investment approaches and asset allocations.",
     "strategy": EXPERIMENTAL_NAME,
     "policy": {"style": "experimental", "max_positions": 15, "target_cash_pct": 2.0,
                "allowed_models": ["equity", "etf_equity", "fixed_income", "commodity", "cash_equivalent"],
                "min_assessment": "BUY", "max_single_stock_pct": 8.0, "max_speculative_pct": 3.0,
                "max_etf_pct": 25.0, "sector_cap_pct": 30.0}},
]
BENCHMARKS: list[dict[str, Any]] = [
    {"code": "BM_GLOBAL", "name": "Benchmark - Global equity (XEQT)", "weights": {"XEQT:TSX": 100.0}},
    {"code": "BM_SP500_CAD", "name": "Benchmark - S&P 500 in CAD (VFV)", "weights": {"VFV:TSX": 100.0}},
    {"code": "BM_TSX", "name": "Benchmark - Canadian equity (XIC)", "weights": {"XIC:TSX": 100.0}},
    {"code": "BM_GROWTH_80_20", "name": "Benchmark - 80/20 growth portfolio (XGRO)", "weights": {"XGRO:TSX": 100.0}},
]
INITIAL_CAPITAL_CAD = 100_000.0


def seed_universe(session: Session, path: Path | None = None) -> int:
    data = yaml.safe_load((path or SEED_DIR / "universe.yaml").read_text(encoding="utf-8"))
    defaults = data.get("defaults", {})
    existing = {(s, e) for s, e in session.execute(select(Instrument.symbol, Instrument.exchange))}
    added = 0
    for row in data["instruments"]:
        key = (row["symbol"].upper(), row["exchange"].upper())
        if key in existing:
            continue
        fields = {**defaults, **row}
        fields["symbol"], fields["exchange"] = key
        session.add(Instrument(**fields))
        added += 1
    return added


def seed_news_sources(session: Session) -> int:
    data = yaml.safe_load((SEED_DIR / "news_sources.yaml").read_text(encoding="utf-8"))
    existing = {k for (k,) in session.execute(select(NewsSource.key))}
    added = 0
    for row in data["sources"]:
        if row["key"] in existing:
            continue
        session.add(NewsSource(**row))
        added += 1
    return added


def ensure_strategies(session: Session) -> dict[str, StrategyVersion]:
    out = {}
    for name, kind in ((FROZEN_NAME, "frozen"), (EXPERIMENTAL_NAME, "experimental")):
        sv = session.execute(select(StrategyVersion).where(StrategyVersion.name == name)
                             .order_by(StrategyVersion.version.desc()).limit(1)).scalar_one_or_none()
        if sv is None:
            cfg = baseline()
            sv = StrategyVersion(name=name, version=1, kind=kind, config=cfg, config_hash=config_hash(cfg),
                                 notes="Initial weights from the master specification." if kind == "frozen"
                                 else "Starts identical to the baseline; changes are new versions.")
            session.add(sv)
            session.flush()
            audit(session, "strategy.created", entity_type="strategy_version", entity_id=sv.id, name=name)
        out[name] = sv
    return out


def ensure_portfolios(session: Session, inception: date | None = None) -> None:
    strategies = ensure_strategies(session)
    existing = {c for (c,) in session.execute(select(Portfolio.code))}
    if "OWNER" not in existing:
        session.add(Portfolio(code="OWNER", kind="owner", name="My actual portfolio",
                              description="Holdings entered manually by the owner. Never assumed.",
                              initial_cash=0.0, account_type="TFSA"))
    for spec in PAPER_PORTFOLIOS:
        if spec["code"] in existing:
            continue
        session.add(Portfolio(code=spec["code"], kind="paper", name=spec["name"], description=spec["description"],
                              initial_cash=INITIAL_CAPITAL_CAD, inception_date=inception,
                              strategy_version_id=strategies[spec["strategy"]].id, policy=spec["policy"]))
    for spec in BENCHMARKS:
        if spec["code"] in existing:
            continue
        session.add(Portfolio(code=spec["code"], kind="benchmark", name=spec["name"],
                              description="Buy-and-hold benchmark, simulated with the same costs as paper portfolios.",
                              initial_cash=INITIAL_CAPITAL_CAD, inception_date=inception,
                              policy={"weights": spec["weights"]}))


def ensure_default_watchlist(session: Session) -> None:
    if session.execute(select(Watchlist).limit(1)).scalar_one_or_none() is None:
        session.add(Watchlist(name="My Watchlist", description="Default watchlist"))


def bootstrap(session: Session, universe_path: Path | None = None) -> dict[str, int]:
    added = seed_universe(session, universe_path)
    sources = seed_news_sources(session)
    ensure_portfolios(session)
    ensure_default_watchlist(session)
    session.flush()
    return {"instruments_added": added, "news_sources_added": sources}
