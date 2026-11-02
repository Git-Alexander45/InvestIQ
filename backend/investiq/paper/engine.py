"""Paper-trading simulation.

Timing rules prevent look-ahead bias:
* A decision made at time T uses only data with timestamps <= T (recorded in decision_context).
* Its order fills at the OPEN of the first daily bar strictly after T, adjusted for slippage.
* Dividends are credited only when the pay date has passed; shares held on the ex-date qualify.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from investiq.data import repository as repo
from investiq.data.repository import end_of
from investiq.finance.fx import MissingFxRate
from investiq.models import (
    CorporateAction,
    Instrument,
    PaperCashEntry,
    PaperDividend,
    PaperFill,
    PaperOrder,
    PaperPositionAdjustment,
    Portfolio,
    PortfolioSnapshot,
)
from investiq.paper import ledger
from investiq.services.preferences import PaperTrading
from investiq.tfsa.rules import OTHER_FOREIGN_WITHHOLDING_ASSUMPTION, US_DIVIDEND_WITHHOLDING

log = logging.getLogger(__name__)
DEFENSIVE_MODELS = {"fixed_income", "cash_equivalent"}


def initialize(session: Session, portfolio: Portfolio, when: datetime) -> bool:
    if session.execute(select(PaperCashEntry.id).where(PaperCashEntry.portfolio_id == portfolio.id).limit(1)).first():
        return False
    session.add(PaperCashEntry(portfolio_id=portfolio.id, ts=when, amount_cad=portfolio.initial_cash, kind="deposit",
                               reference="initial virtual capital"))
    if portfolio.inception_date is None:
        portfolio.inception_date = when.date()
    return True


# ------------------------------------------------------------------------------------------------
# Order planning
# ------------------------------------------------------------------------------------------------


def plan_orders(session: Session, portfolio: Portfolio, candidates: list[dict[str, Any]], decision_at: datetime,
                prefs: PaperTrading) -> list[PaperOrder]:
    """candidates: rows with instrument_id, assessment, overall, model, primary_eligible, sector, region,
    is_speculative, recommendation_id, security_type. Only data known at decision_at is used."""
    policy = portfolio.policy or {}
    if session.execute(select(PaperOrder.id).where(PaperOrder.portfolio_id == portfolio.id,
                                                   PaperOrder.status == "pending").limit(1)).first():
        return []  # wait for pending orders to fill first
    val = ledger.value(session, portfolio, decision_at.date())
    total = val.total_cad
    if total <= 0:
        return []
    held = {h["instrument_id"]: h for h in val.holdings}
    by_id = {c["instrument_id"]: c for c in candidates}
    orders: list[PaperOrder] = []

    def order(inst_id: int, side: str, qty: float, reason: str, rec_id: int | None) -> None:
        bar = repo.last_bar(session, inst_id, decision_at)
        if bar is None or qty <= 0:
            return
        o = PaperOrder(portfolio_id=portfolio.id, instrument_id=inst_id, side=side, quantity=qty, decision_at=decision_at,
                       decision_price=bar.close, decision_price_as_of=bar.ts, recommendation_id=rec_id, reason=reason,
                       decision_context={"price_source": bar.source, "data_status": bar.data_status,
                                         "portfolio_value_cad": total, "policy": policy,
                                         "candidate": by_id.get(inst_id)})
        session.add(o)
        orders.append(o)

    # 1) Sell holdings whose latest research assessment is SELL or AVOID.
    for inst_id, h in held.items():
        c = by_id.get(inst_id)
        if c and c["assessment"] in ("SELL", "AVOID"):
            order(inst_id, "SELL", h["quantity"], f"Research assessment {c['assessment']}", c.get("recommendation_id"))

    # 2) Trim positions above their cap by more than the rebalance band.
    for inst_id, h in held.items():
        c = by_id.get(inst_id, {})
        cap = _cap(policy, c or {"security_type": h["security_type"]})
        weight = h["value_cad"] / total * 100
        if weight > cap + prefs.rebalance_band_pct and not (c and c["assessment"] in ("SELL", "AVOID")):
            excess_cad = (weight - cap) / 100 * total
            qty = _qty(excess_cad / (h["value_cad"] / h["quantity"]), prefs.allow_fractional_shares)
            order(inst_id, "SELL", qty, f"Rebalance: weight {weight:.1f}% above cap {cap:.0f}%", c.get("recommendation_id"))

    # 3) Buy new BUY-rated candidates that fit this portfolio's policy.
    allowed = set(policy.get("allowed_models", []))
    pool = [c for c in candidates if c["assessment"] == "BUY" and c["model"] in allowed and c["instrument_id"] not in held
            and (c.get("primary_eligible") or not prefs.require_brokerage_verification)]
    style = policy.get("style")
    if style == "global_growth":
        pool.sort(key=lambda c: (c.get("region") in ("canada", "united_states") or c.get("country") in ("CA", "US"),
                                 -c["overall"]))
    elif style == "growth_protection":
        pool.sort(key=lambda c: (c["model"] not in DEFENSIVE_MODELS, -c["overall"]))
    else:
        pool.sort(key=lambda c: -c["overall"])

    max_positions = int(policy.get("max_positions", 15))
    slots = max(0, max_positions - len(held))
    cash_target = float(policy.get("target_cash_pct", 2.0))
    investable = val.cash_cad - total * cash_target / 100
    sector_w = _sector_weights(val.holdings, total)
    region_w: dict[str, float] = {}
    for c in pool[:slots]:
        if investable <= 0:
            break
        cap = _cap(policy, c)
        target = min(cap, float(policy.get("target_position_pct", cap)))
        amount = min(total * target / 100, investable)
        sector = c.get("sector") or "Diversified"
        if sector != "Diversified" and sector_w.get(sector, 0) + amount / total * 100 > policy.get("sector_cap_pct", 30):
            continue
        region = c.get("region") or c.get("country") or "unknown"
        if style == "global_growth" and region_w.get(region, 0) + amount / total * 100 > policy.get("max_region_pct", 50):
            continue
        bar = repo.last_bar(session, c["instrument_id"], decision_at)
        if bar is None:
            continue
        try:
            px_cad, _ = repo.fx_table(session, decision_at.date()).convert(bar.close, bar.currency, "CAD")
        except MissingFxRate:
            continue
        qty = _qty(amount / px_cad, prefs.allow_fractional_shares)
        if qty <= 0:
            continue
        order(c["instrument_id"], "BUY", qty, f"BUY assessment, grade {c.get('grade')} ({c['overall']:.1f}); "
                                              f"target {target:.1f}% of portfolio", c.get("recommendation_id"))
        investable -= qty * px_cad
        sector_w[sector] = sector_w.get(sector, 0) + qty * px_cad / total * 100
        region_w[region] = region_w.get(region, 0) + qty * px_cad / total * 100
    return orders


def _cap(policy: dict[str, Any], c: dict[str, Any]) -> float:
    if c.get("security_type") in ("etf", "mutual_fund"):
        return float(policy.get("max_etf_pct", 25.0))
    if c.get("is_speculative"):
        return float(policy.get("max_speculative_pct", 2.0))
    return float(policy.get("max_single_stock_pct", 6.0))


def _qty(q: float, fractional: bool) -> float:
    return round(q, 4) if fractional else float(int(q))


def _sector_weights(holdings: list[dict], total: float) -> dict[str, float]:
    out: dict[str, float] = {}
    for h in holdings:
        s = h.get("sector") or "Diversified"
        out[s] = out.get(s, 0) + h["value_cad"] / total * 100
    return out


# ------------------------------------------------------------------------------------------------
# Execution, corporate actions, dividends
# ------------------------------------------------------------------------------------------------


def execute_pending(session: Session, portfolio: Portfolio, up_to: datetime, prefs: PaperTrading) -> list[PaperFill]:
    fills = []
    pending = session.execute(select(PaperOrder).where(PaperOrder.portfolio_id == portfolio.id,
                                                       PaperOrder.status == "pending").order_by(PaperOrder.id)).scalars()
    # Sells first so their proceeds can fund buys placed in the same decision.
    for o in sorted(pending, key=lambda o: (o.side != "SELL", o.id)):
        bar = repo.bar_on_or_after(session, o.instrument_id, o.decision_at + timedelta(seconds=1))
        if bar is None or bar.ts > up_to:
            continue  # no later market data yet
        inst = session.get(Instrument, o.instrument_id)
        fx = repo.fx_table(session, bar.ts.date())
        try:
            rate = fx.get(bar.currency, "CAD")
        except MissingFxRate:
            continue
        slip = prefs.slippage_bps / 10_000
        price = bar.open * (1 + slip if o.side == "BUY" else 1 - slip)
        qty = o.quantity
        if o.side == "SELL":
            qty = min(qty, ledger.state(session, portfolio.id, bar.ts).positions.get(o.instrument_id,
                                                                                    ledger.Lot(0)).quantity)
        gross_cad = qty * price * rate.rate
        fx_fee = gross_cad * prefs.fx_fee_pct / 100 if bar.currency != "CAD" else 0.0
        commission = prefs.commission_per_trade_cad
        if o.side == "BUY":
            cash = ledger.cash_balance(session, portfolio.id, bar.ts)
            if gross_cad + fx_fee + commission > cash:
                affordable = (cash - commission) / (price * rate.rate * (1 + (prefs.fx_fee_pct / 100 if bar.currency != "CAD" else 0)))
                qty = _qty(max(affordable, 0), prefs.allow_fractional_shares)
                gross_cad = qty * price * rate.rate
                fx_fee = gross_cad * prefs.fx_fee_pct / 100 if bar.currency != "CAD" else 0.0
        if qty <= 0:
            o.status, o.status_reason = "cancelled", "insufficient cash or no position at fill time"
            continue
        fill = PaperFill(order_id=o.id, portfolio_id=portfolio.id, instrument_id=o.instrument_id, side=o.side,
                         quantity=qty, market_price=bar.open, fill_price=price, currency=bar.currency,
                         fx_rate_to_cad=rate.rate, fx_as_of=rate.as_of if rate.as_of != date.min else bar.ts.date(),
                         gross_cad=round(gross_cad, 6), commission_cad=commission, fx_fee_cad=round(fx_fee, 6),
                         slippage_cad=round(abs(price - bar.open) * qty * rate.rate, 6), filled_at=bar.ts,
                         price_source=bar.source)
        session.add(fill)
        session.flush()
        sign = -1 if o.side == "BUY" else 1
        session.add(PaperCashEntry(portfolio_id=portfolio.id, ts=bar.ts, amount_cad=sign * gross_cad, kind=o.side.lower(),
                                   reference=f"fill:{fill.id} {inst.symbol}"))
        if commission:
            session.add(PaperCashEntry(portfolio_id=portfolio.id, ts=bar.ts, amount_cad=-commission, kind="fee",
                                       reference=f"commission fill:{fill.id}"))
        if fx_fee:
            session.add(PaperCashEntry(portfolio_id=portfolio.id, ts=bar.ts, amount_cad=-fx_fee, kind="fee",
                                       reference=f"fx conversion fill:{fill.id}"))
        o.status = "filled"
        fills.append(fill)
        session.flush()
    return fills


def process_splits(session: Session, portfolio: Portfolio, up_to: date) -> int:
    n = 0
    st = ledger.state(session, portfolio.id, end_of(up_to))
    for inst_id in list(st.positions):
        for ca in session.execute(select(CorporateAction).where(
                CorporateAction.instrument_id == inst_id, CorporateAction.kind == "split",
                CorporateAction.effective_date <= up_to)).scalars():
            ref = f"split:{ca.id}"
            if session.execute(select(PaperPositionAdjustment.id).where(
                    PaperPositionAdjustment.portfolio_id == portfolio.id, PaperPositionAdjustment.reference == ref)).first():
                continue
            ts = datetime.combine(ca.effective_date, time(0), UTC)
            held = ledger.state(session, portfolio.id, ts - timedelta(seconds=1)).positions.get(inst_id)
            if held is None or not ca.ratio:
                continue
            session.add(PaperPositionAdjustment(portfolio_id=portfolio.id, instrument_id=inst_id, ts=ts,
                                                quantity_delta=held.quantity * (ca.ratio - 1), kind="split", reference=ref))
            n += 1
    session.flush()
    return n


def withholding_rate(inst: Instrument, account_type: str) -> float:
    """Withholding applied at the account level. Funds' internal foreign withholding is already
    reflected in their distributions, so only directly-held foreign issuers are taxed here."""
    if inst.country in (None, "CA") or inst.security_type in ("etf", "mutual_fund") and inst.exchange in (
            "TSX", "NEO", "CBOE_CA", "TSXV"):
        return 0.0
    if inst.country == "US" or inst.currency == "USD":
        if account_type == "RRSP":
            return 0.0  # treaty exemption for retirement accounts
        return US_DIVIDEND_WITHHOLDING
    return OTHER_FOREIGN_WITHHOLDING_ASSUMPTION


def process_dividends(session: Session, portfolio: Portfolio, up_to: date, prefs: PaperTrading) -> int:
    n = 0
    inception = portfolio.inception_date or up_to
    instrument_ids = {f.instrument_id for f in session.execute(
        select(PaperFill).where(PaperFill.portfolio_id == portfolio.id)).scalars()}
    for inst_id in instrument_ids:
        inst = session.get(Instrument, inst_id)
        for d in repo.dividends_between(session, inst_id, inception - timedelta(days=1), up_to):
            pay = d.pay_date or d.ex_date + timedelta(days=14)
            if pay > up_to:
                continue
            if session.execute(select(PaperDividend.id).where(PaperDividend.portfolio_id == portfolio.id,
                                                              PaperDividend.dividend_id == d.id)).first():
                continue
            ex_ts = datetime.combine(d.ex_date, time(0), UTC) - timedelta(seconds=1)
            lot = ledger.state(session, portfolio.id, ex_ts).positions.get(inst_id)
            if lot is None:
                continue
            fx = repo.fx_table(session, pay)
            try:
                gross_cad, _ = fx.convert(lot.quantity * d.amount, d.currency, "CAD")
            except MissingFxRate:
                continue
            wh = gross_cad * withholding_rate(inst, portfolio.account_type)
            net = gross_cad - wh
            pay_ts = datetime.combine(pay, time(16), UTC)
            pd = PaperDividend(portfolio_id=portfolio.id, dividend_id=d.id, instrument_id=inst_id, shares=lot.quantity,
                               gross_cad=round(gross_cad, 6), withholding_cad=round(wh, 6), net_cad=round(net, 6),
                               reinvested=False, paid_at=pay_ts)
            session.add(pd)
            session.add(PaperCashEntry(portfolio_id=portfolio.id, ts=pay_ts, amount_cad=gross_cad, kind="dividend",
                                       reference=f"dividend:{d.id} {inst.symbol}"))
            if wh:
                session.add(PaperCashEntry(portfolio_id=portfolio.id, ts=pay_ts, amount_cad=-wh, kind="withholding",
                                           reference=f"withholding dividend:{d.id}"))
            if prefs.reinvest_dividends:
                bar = repo.last_bar(session, inst_id, end_of(pay))
                if bar is not None:
                    px_cad, _ = fx.convert(bar.close, bar.currency, "CAD")
                    shares = _qty(net / px_cad, prefs.allow_fractional_shares)
                    if shares > 0:
                        cost = shares * px_cad
                        session.add(PaperPositionAdjustment(portfolio_id=portfolio.id, instrument_id=inst_id,
                                                            ts=pay_ts + timedelta(seconds=1), quantity_delta=shares,
                                                            cost_delta_cad=cost, kind="drip", reference=f"drip:{d.id}"))
                        session.add(PaperCashEntry(portfolio_id=portfolio.id, ts=pay_ts + timedelta(seconds=1),
                                                   amount_cad=-cost, kind="drip", reference=f"drip:{d.id}"))
                        pd.reinvested = True
            n += 1
            session.flush()
    return n


def snapshot(session: Session, portfolio: Portfolio, day: date) -> PortfolioSnapshot | None:
    existing = session.execute(select(PortfolioSnapshot).where(PortfolioSnapshot.portfolio_id == portfolio.id,
                                                               PortfolioSnapshot.as_of == day)).scalar_one_or_none()
    if existing is not None:
        return existing
    v = ledger.value(session, portfolio, day)
    if v.missing_prices:
        log.warning("snapshot %s %s missing prices: %s", portfolio.code, day, v.missing_prices)
    snap = PortfolioSnapshot(portfolio_id=portfolio.id, as_of=day, cash_cad=v.cash_cad, market_value_cad=v.market_value_cad,
                             total_value_cad=v.total_cad, holdings=v.holdings,
                             priced_with={"fx": v.fx_used, "missing_prices": v.missing_prices})
    session.add(snap)
    session.flush()
    return snap


def setup_benchmark(session: Session, portfolio: Portfolio, decision_at: datetime) -> list[PaperOrder]:
    """Benchmarks buy their fixed weights once, then hold (dividends reinvested, same costs)."""
    if session.execute(select(PaperOrder.id).where(PaperOrder.portfolio_id == portfolio.id).limit(1)).first():
        return []
    total = ledger.cash_balance(session, portfolio.id)
    orders = []
    for key, w in (portfolio.policy or {}).get("weights", {}).items():
        sym, ex = key.split(":")
        inst = repo.instrument_by_symbol(session, sym, ex)
        if inst is None:
            continue
        bar = repo.last_bar(session, inst.id, decision_at)
        if bar is None:
            continue
        try:
            px_cad, _ = repo.fx_table(session, decision_at.date()).convert(bar.close, bar.currency, "CAD")
        except MissingFxRate:
            continue
        # Leave room for slippage/fees so the order is fully affordable.
        qty = float(int(total * w / 100 * 0.995 / px_cad))
        o = PaperOrder(portfolio_id=portfolio.id, instrument_id=inst.id, side="BUY", quantity=qty, decision_at=decision_at,
                       decision_price=bar.close, decision_price_as_of=bar.ts, reason=f"Benchmark allocation {w:.0f}%",
                       decision_context={"benchmark": True, "price_source": bar.source})
        session.add(o)
        orders.append(o)
    return orders


def run_day(session: Session, portfolio: Portfolio, now: datetime, prefs: PaperTrading,
            candidates: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """One simulation step: fill pending orders, apply actions, credit dividends, decide, snapshot."""
    initialize(session, portfolio, now)
    session.flush()
    fills = execute_pending(session, portfolio, now, prefs)
    splits = process_splits(session, portfolio, now.date())
    divs = process_dividends(session, portfolio, now.date(), prefs)
    if portfolio.kind == "benchmark":
        orders = setup_benchmark(session, portfolio, now)
    else:
        orders = plan_orders(session, portfolio, candidates or [], now, prefs)
    session.flush()
    snap = snapshot(session, portfolio, now.date())
    return {"portfolio": portfolio.code, "fills": len(fills), "orders": len(orders), "splits": splits,
            "dividends": divs, "value_cad": snap.total_value_cad if snap else None}
