"""Turn owner or paper holdings into diversification-engine positions (valued in CAD, point in time)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from investiq.data import repository as repo
from investiq.data.stats import price_stats
from investiq.diversification.engine import Position, analyse
from investiq.finance.fx import MissingFxRate
from investiq.models import Instrument, OwnerHoldingEntry, Portfolio
from investiq.paper import ledger
from investiq.research.facts import etf_stats
from investiq.services.preferences import get_pref


def owner_portfolio(session: Session) -> Portfolio:
    return session.execute(select(Portfolio).where(Portfolio.code == "OWNER")).scalar_one()


def owner_holdings(session: Session) -> list[OwnerHoldingEntry]:
    """Latest entry per (instrument, account); zero quantity means closed."""
    rows = session.execute(select(OwnerHoldingEntry).order_by(OwnerHoldingEntry.id)).scalars()
    latest: dict[tuple[int, str], OwnerHoldingEntry] = {}
    for r in rows:
        latest[(r.instrument_id, r.account_type)] = r
    return [r for r in latest.values() if r.quantity > 0]


def build_positions(session: Session, items: list[tuple[Instrument, float]], as_of: datetime
                    ) -> tuple[list[Position], list[str]]:
    fx = repo.fx_table(session, as_of.date())
    positions, problems = [], []
    for inst, qty in items:
        bars = repo.daily_bars(session, inst.id, as_of, lookback_days=365 * 3 + 30)
        if not bars:
            problems.append(f"{inst.symbol}: no price data")
            continue
        try:
            px_cad, _ = fx.convert(bars[-1].close, bars[-1].currency, "CAD")
        except MissingFxRate:
            problems.append(f"{inst.symbol}: no {bars[-1].currency}/CAD rate")
            continue
        stats = price_stats(bars, as_of) or {}
        cons = None
        if inst.security_type in ("etf", "mutual_fund"):
            _, cons, _ = etf_stats(session, inst, as_of)
        positions.append(Position(instrument_id=inst.id, symbol=inst.symbol, exchange=inst.exchange, name=inst.name,
                                  asset_class=inst.asset_class, security_type=inst.security_type,
                                  value_cad=px_cad * qty, currency=inst.currency, country=inst.country,
                                  sector=inst.sector, is_speculative=inst.is_speculative,
                                  currency_hedged=inst.currency_hedged, constituents=cons,
                                  daily_returns=stats.get("daily_returns")))
    return positions, problems


def owner_report(session: Session, as_of: datetime) -> dict[str, Any]:
    holdings = owner_holdings(session)
    items = [(session.get(Instrument, h.instrument_id), h.quantity) for h in holdings]
    positions, problems = build_positions(session, items, as_of)
    limits = get_pref(session, "risk_limits").model_dump()
    report = analyse(positions, 0.0, limits).as_dict()
    report["data_problems"] = problems
    report["holdings_entered"] = len(holdings)
    return report


def paper_positions(session: Session, portfolio: Portfolio, as_of: datetime) -> tuple[list[Position], float]:
    st = ledger.state(session, portfolio.id, as_of)
    items = [(session.get(Instrument, iid), lot.quantity) for iid, lot in st.positions.items()]
    positions, _ = build_positions(session, items, as_of)
    return positions, st.cash_cad
