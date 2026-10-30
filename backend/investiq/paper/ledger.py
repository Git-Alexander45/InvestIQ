"""Reconstruct paper-portfolio state from the append-only ledger (fills, cash, adjustments)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from investiq.data import repository as repo
from investiq.data.repository import end_of
from investiq.finance.fx import MissingFxRate
from investiq.models import Instrument, PaperCashEntry, PaperFill, PaperPositionAdjustment, Portfolio


@dataclass
class Lot:
    instrument_id: int
    quantity: float = 0.0
    cost_cad: float = 0.0  # total cost basis (average-cost method)

    @property
    def avg_cost_cad(self) -> float:
        return self.cost_cad / self.quantity if self.quantity else 0.0


@dataclass
class State:
    cash_cad: float
    positions: dict[int, Lot]
    realized_pnl: list[float] = field(default_factory=list)  # per closing/reducing sale, CAD
    realized_by_instrument: dict[int, float] = field(default_factory=dict)


def cash_balance(session: Session, portfolio_id: int, as_of: datetime | None = None) -> float:
    q = select(func.coalesce(func.sum(PaperCashEntry.amount_cad), 0.0)).where(PaperCashEntry.portfolio_id == portfolio_id)
    if as_of is not None:
        q = q.where(PaperCashEntry.ts <= as_of)
    return float(session.execute(q).scalar_one())


def state(session: Session, portfolio_id: int, as_of: datetime | None = None) -> State:
    fills = select(PaperFill).where(PaperFill.portfolio_id == portfolio_id)
    adjs = select(PaperPositionAdjustment).where(PaperPositionAdjustment.portfolio_id == portfolio_id)
    if as_of is not None:
        fills = fills.where(PaperFill.filled_at <= as_of)
        adjs = adjs.where(PaperPositionAdjustment.ts <= as_of)
    events: list[tuple[datetime, int, object]] = []
    for f in session.execute(fills).scalars():
        events.append((f.filled_at, f.id, f))
    for a in session.execute(adjs).scalars():
        events.append((a.ts, a.id, a))
    events.sort(key=lambda e: (e[0], e[1]))
    lots: dict[int, Lot] = {}
    realized: list[float] = []
    by_inst: dict[int, float] = defaultdict(float)
    for _, _, ev in events:
        if isinstance(ev, PaperFill):
            lot = lots.setdefault(ev.instrument_id, Lot(ev.instrument_id))
            costs = ev.commission_cad + ev.fx_fee_cad
            if ev.side == "BUY":
                lot.quantity += ev.quantity
                lot.cost_cad += ev.gross_cad + costs
            else:
                qty = min(ev.quantity, lot.quantity)
                basis = lot.avg_cost_cad * qty
                proceeds = ev.gross_cad - costs
                pnl = proceeds - basis
                realized.append(pnl)
                by_inst[ev.instrument_id] += pnl
                lot.quantity -= qty
                lot.cost_cad -= basis
        else:
            lot = lots.setdefault(ev.instrument_id, Lot(ev.instrument_id))
            lot.quantity += ev.quantity_delta
            lot.cost_cad += ev.cost_delta_cad
    positions = {k: v for k, v in lots.items() if v.quantity > 1e-9}
    return State(cash_balance(session, portfolio_id, as_of), positions, realized, dict(by_inst))


@dataclass
class Valuation:
    total_cad: float
    cash_cad: float
    market_value_cad: float
    holdings: list[dict]
    missing_prices: list[str]
    fx_used: dict[str, dict]


def value(session: Session, portfolio: Portfolio, day: date) -> Valuation:
    st = state(session, portfolio.id, end_of(day))
    fx = repo.fx_table(session, day)
    holdings, missing, fx_used = [], [], {}
    mv = 0.0
    for lot in st.positions.values():
        inst = session.get(Instrument, lot.instrument_id)
        bar = repo.last_bar(session, inst.id, end_of(day))
        if bar is None:
            missing.append(inst.symbol)
            continue
        try:
            px_cad, q = fx.convert(bar.close, bar.currency, "CAD")
        except MissingFxRate:
            missing.append(f"{inst.symbol} (no {bar.currency}/CAD rate)")
            continue
        if bar.currency != "CAD":
            fx_used[bar.currency] = {"rate": q.rate, "as_of": q.as_of.isoformat(), "source": q.source}
        val = px_cad * lot.quantity
        mv += val
        holdings.append({"instrument_id": inst.id, "symbol": inst.symbol, "exchange": inst.exchange,
                         "quantity": round(lot.quantity, 6), "price": bar.close, "currency": bar.currency,
                         "price_date": bar.ts.date().isoformat(), "price_source": bar.source,
                         "data_status": bar.data_status, "value_cad": round(val, 2),
                         "cost_cad": round(lot.cost_cad, 2), "unrealized_cad": round(val - lot.cost_cad, 2),
                         "asset_class": inst.asset_class, "sector": inst.sector, "security_type": inst.security_type})
    return Valuation(round(st.cash_cad + mv, 2), round(st.cash_cad, 2), round(mv, 2), holdings, missing, fx_used)
