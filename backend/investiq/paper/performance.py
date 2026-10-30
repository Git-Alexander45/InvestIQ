"""Performance analytics for paper and benchmark portfolios (deterministic)."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from investiq.finance.returns import (
    annualized_volatility,
    cagr,
    max_drawdown,
    sharpe_ratio,
    simple_returns,
    win_rate,
)
from investiq.models import Instrument, PaperDividend, PaperFill, Portfolio, PortfolioSnapshot
from investiq.paper import ledger


def series(session: Session, portfolio_id: int) -> list[tuple[date, float]]:
    rows = session.execute(select(PortfolioSnapshot.as_of, PortfolioSnapshot.total_value_cad)
                           .where(PortfolioSnapshot.portfolio_id == portfolio_id).order_by(PortfolioSnapshot.as_of)).all()
    return [(d, v) for d, v in rows if v and v > 0]


def metrics(session: Session, portfolio: Portfolio, risk_free_annual: float = 0.0) -> dict[str, Any]:
    s = series(session, portfolio.id)
    out: dict[str, Any] = {"portfolio": portfolio.code, "name": portfolio.name, "kind": portfolio.kind,
                           "initial_cad": portfolio.initial_cash, "observations": len(s)}
    if not s:
        out["note"] = "no valuation history yet"
        return out
    start_value = portfolio.initial_cash or s[0][1]
    end_value = s[-1][1]
    values = [v for _, v in s]
    rets = simple_returns(values) if len(values) > 1 else []
    out.update({
        "start_date": s[0][0].isoformat(), "end_date": s[-1][0].isoformat(), "value_cad": round(end_value, 2),
        "total_return_pct": round((end_value / start_value - 1) * 100, 4),
        "annualized_return_pct": None, "max_drawdown_pct": round(max_drawdown(values) * 100, 4),
        "volatility_pct": None, "sharpe": None,
    })
    if (s[-1][0] - s[0][0]).days >= 90:
        a = cagr(start_value, end_value, s[0][0], s[-1][0])
        out["annualized_return_pct"] = None if a is None else round(a * 100, 4)
    else:
        out["annualized_return_note"] = "fewer than 90 days of history: annualised figures are not meaningful"
    if len(rets) >= 20:
        vol = annualized_volatility(rets)
        sh = sharpe_ratio(rets, risk_free_annual)
        out["volatility_pct"] = None if vol is None else round(vol * 100, 4)
        out["sharpe"] = None if sh is None else round(sh, 4)
    st = ledger.state(session, portfolio.id)
    wr = win_rate(st.realized_pnl)
    out["closed_trades"] = len(st.realized_pnl)
    out["win_rate_pct"] = None if wr is None else round(wr * 100, 2)
    div = session.execute(select(func.coalesce(func.sum(PaperDividend.net_cad), 0.0), func.coalesce(
        func.sum(PaperDividend.withholding_cad), 0.0)).where(PaperDividend.portfolio_id == portfolio.id)).one()
    out["dividends_net_cad"] = round(float(div[0]), 2)
    out["withholding_tax_cad"] = round(float(div[1]), 2)
    out["dividend_contribution_pct"] = round(float(div[0]) / start_value * 100, 4)
    costs = session.execute(select(func.coalesce(func.sum(PaperFill.commission_cad), 0.0),
                                   func.coalesce(func.sum(PaperFill.fx_fee_cad), 0.0),
                                   func.coalesce(func.sum(PaperFill.slippage_cad), 0.0))
                            .where(PaperFill.portfolio_id == portfolio.id)).one()
    out["trading_costs_cad"] = {"commissions": round(float(costs[0]), 2), "fx_fees": round(float(costs[1]), 2),
                                "slippage": round(float(costs[2]), 2), "total": round(float(sum(costs)), 2)}
    out["by_asset_class"], out["by_sector"] = _breakdown(session, portfolio, st)
    return out


def _breakdown(session: Session, portfolio: Portfolio, st: ledger.State) -> tuple[dict, dict]:
    """P&L contribution (realised + unrealised, CAD) grouped by asset class and by sector."""
    snap = session.execute(select(PortfolioSnapshot).where(PortfolioSnapshot.portfolio_id == portfolio.id)
                           .order_by(PortfolioSnapshot.as_of.desc()).limit(1)).scalar_one_or_none()
    unreal = {h["instrument_id"]: h.get("unrealized_cad", 0.0) for h in (snap.holdings if snap else [])}
    divs = dict(session.execute(select(PaperDividend.instrument_id, func.sum(PaperDividend.net_cad))
                                .where(PaperDividend.portfolio_id == portfolio.id)
                                .group_by(PaperDividend.instrument_id)).all())
    by_class: dict[str, float] = defaultdict(float)
    by_sector: dict[str, float] = defaultdict(float)
    for inst_id in set(unreal) | set(st.realized_by_instrument) | set(divs):
        inst = session.get(Instrument, inst_id)
        pnl = unreal.get(inst_id, 0.0) + st.realized_by_instrument.get(inst_id, 0.0) + float(divs.get(inst_id) or 0.0)
        by_class[inst.asset_class] += pnl
        by_sector[inst.sector or "Diversified"] += pnl
    return ({k: round(v, 2) for k, v in by_class.items()}, {k: round(v, 2) for k, v in by_sector.items()})


def _excess_over_common_dates(a: list[tuple[date, float]], b: list[tuple[date, float]]) -> float | None:
    """Return difference (percentage points) measured over the dates both series have."""
    common = sorted({d for d, _ in a} & {d for d, _ in b})
    if len(common) < 2:
        return None
    da, db = dict(a), dict(b)
    ra = da[common[-1]] / da[common[0]] - 1
    rb = db[common[-1]] / db[common[0]] - 1
    return round((ra - rb) * 100, 4)


def comparison(session: Session) -> dict[str, Any]:
    """All paper portfolios vs all benchmarks over their common dates (no cherry-picking: every
    portfolio and benchmark is always reported)."""
    ports = list(session.execute(select(Portfolio).where(Portfolio.kind.in_(("paper", "benchmark")))
                                 .order_by(Portfolio.kind, Portfolio.code)).scalars())
    data = {p.code: metrics(session, p) for p in ports}
    curves = {p.code: [(d.isoformat(), round(v / (p.initial_cash or 1) * 100, 4)) for d, v in series(session, p.id)]
              for p in ports}
    excess: dict[str, dict[str, float | None]] = {}
    for p in ports:
        if p.kind != "paper":
            continue
        excess[p.code] = {}
        for b in ports:
            if b.kind == "benchmark":
                excess[p.code][b.code] = _excess_over_common_dates(series(session, p.id), series(session, b.id))
    strategy = {}
    for p in ports:
        if p.strategy_version_id:
            strategy.setdefault(p.strategy_version_id, []).append(p.code)
    return {"portfolios": data, "curves": curves, "excess_vs_benchmarks_pct": excess, "strategy_portfolios": strategy}
