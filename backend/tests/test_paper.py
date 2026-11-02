from datetime import UTC, date, datetime, time, timedelta

import pytest

from investiq.models import (
    CorporateAction,
    Dividend,
    FxRate,
    Instrument,
    PaperDividend,
    PaperFill,
    PaperOrder,
    Portfolio,
    PriceBar,
)
from investiq.paper import engine, ledger, performance
from investiq.services.preferences import PaperTrading

D0 = date(2026, 3, 2)  # a Monday


def ts(d: date) -> datetime:
    return datetime.combine(d, time(21), UTC)


def add_instrument(session, symbol, currency="CAD", exchange="TSX", country="CA", security_type="common_stock",
                   sector="Financials"):
    inst = Instrument(symbol=symbol, exchange=exchange, name=symbol, asset_class="equity",
                      security_type=security_type, currency=currency, country=country, sector=sector)
    session.add(inst)
    session.flush()
    return inst


def add_bars(session, inst, prices, start=D0):
    """prices: list of (open, close) per business day from start."""
    d = start
    for o, c in prices:
        while d.weekday() >= 5:
            d += timedelta(days=1)
        session.add(PriceBar(instrument_id=inst.id, interval="1d", ts=ts(d), source="test", open=o, high=max(o, c) + 1,
                             low=min(o, c) - 1, close=c, currency=inst.currency))
        d += timedelta(days=1)
    session.flush()


def add_fx(session, rate=1.40, start=D0 - timedelta(days=10), days=60):
    for i in range(days):
        session.add(FxRate(base="USD", quote="CAD", rate=rate, as_of=start + timedelta(days=i), source="test"))
    session.flush()


def paper_portfolio(session, code="A", policy=None, account_type="TFSA"):
    p = Portfolio(code=code, kind="paper", name=code, initial_cash=100_000.0, account_type=account_type,
                  policy=policy or {"allowed_models": ["equity"], "max_positions": 10, "target_cash_pct": 2.0,
                                    "max_single_stock_pct": 6.0, "sector_cap_pct": 30.0})
    session.add(p)
    session.flush()
    return p


def candidate(inst, assessment="BUY", overall=85.0, **kw):
    return {"instrument_id": inst.id, "assessment": assessment, "overall": overall, "model": "equity",
            "primary_eligible": True, "sector": inst.sector, "security_type": inst.security_type,
            "is_speculative": False, "recommendation_id": None, "grade": "A-", **kw}


PREFS = PaperTrading(slippage_bps=10.0, fx_fee_pct=1.5, commission_per_trade_cad=0.0)


def test_buy_fills_at_next_open_with_slippage_and_no_lookahead(session):
    ry = add_instrument(session, "RY")
    add_bars(session, ry, [(100, 100), (101, 102), (103, 104)])
    p = paper_portfolio(session)
    decision = ts(D0)
    engine.initialize(session, p, decision)
    orders = engine.plan_orders(session, p, [candidate(ry)], decision, PREFS)
    assert len(orders) == 1 and orders[0].side == "BUY"
    assert orders[0].quantity == 60  # 6% of 100k at 100 CAD
    session.flush()
    # Nothing can fill using the decision day's own bar.
    assert engine.execute_pending(session, p, decision, PREFS) == []
    fills = engine.execute_pending(session, p, ts(D0 + timedelta(days=1)), PREFS)
    assert len(fills) == 1
    f = fills[0]
    assert f.market_price == 101 and f.fill_price == pytest.approx(101 * 1.001)
    assert f.fx_fee_cad == 0  # CAD security: no conversion
    assert ledger.cash_balance(session, p.id) == pytest.approx(100_000 - 60 * 101 * 1.001)


def test_usd_purchase_charges_fx_fee_and_records_rate(session):
    add_fx(session, 1.40)
    aapl = add_instrument(session, "AAPL", currency="USD", exchange="NASDAQ", country="US", sector="Technology")
    add_bars(session, aapl, [(200, 200), (210, 210)])
    p = paper_portfolio(session)
    engine.initialize(session, p, ts(D0))
    engine.plan_orders(session, p, [candidate(aapl)], ts(D0), PREFS)
    session.flush()
    (f,) = engine.execute_pending(session, p, ts(D0 + timedelta(days=1)), PREFS)
    assert f.fx_rate_to_cad == 1.40
    assert f.fx_fee_cad == pytest.approx(f.gross_cad * 0.015)
    v = ledger.value(session, p, D0 + timedelta(days=1))
    assert v.fx_used["USD"]["rate"] == 1.40
    assert v.total_cad < 100_000  # fees and slippage cost money


def test_unverified_candidates_are_not_bought(session):
    ry = add_instrument(session, "RY")
    add_bars(session, ry, [(100, 100), (100, 100)])
    p = paper_portfolio(session)
    engine.initialize(session, p, ts(D0))
    assert engine.plan_orders(session, p, [candidate(ry, primary_eligible=False)], ts(D0), PREFS) == []
    assert engine.plan_orders(session, p, [candidate(ry, assessment="WATCH")], ts(D0), PREFS) == []


def test_sector_cap_limits_purchases(session):
    banks = [add_instrument(session, s) for s in ("RY", "TD", "BMO", "BNS", "CM", "NA")]
    for b in banks:
        add_bars(session, b, [(50, 50), (50, 50)])
    p = paper_portfolio(session)
    engine.initialize(session, p, ts(D0))
    orders = engine.plan_orders(session, p, [candidate(b) for b in banks], ts(D0), PREFS)
    assert len(orders) == 5  # 5 x 6% = 30% sector cap; the sixth would breach it


def test_avoid_triggers_sale_and_realized_pnl(session):
    ry = add_instrument(session, "RY")
    add_bars(session, ry, [(100, 100), (100, 100), (110, 110), (120, 120)])
    p = paper_portfolio(session)
    engine.run_day(session, p, ts(D0), PREFS, [candidate(ry)])
    engine.run_day(session, p, ts(D0 + timedelta(days=1)), PREFS, [candidate(ry, assessment="HOLD")])
    engine.run_day(session, p, ts(D0 + timedelta(days=2)), PREFS, [candidate(ry, assessment="AVOID")])
    engine.run_day(session, p, ts(D0 + timedelta(days=3)), PREFS, [candidate(ry, assessment="AVOID")])
    st = ledger.state(session, p.id)
    assert ry.id not in st.positions
    assert st.realized_pnl and st.realized_pnl[0] == pytest.approx(60 * (120 * 0.999 - 100 * 1.001), rel=1e-6)
    sides = [f.side for f in session.query(PaperFill).order_by(PaperFill.id)]
    assert sides == ["BUY", "SELL"]


def test_us_dividend_withholding_in_tfsa_and_drip(session):
    add_fx(session, 1.40)
    jnj = add_instrument(session, "JNJ", currency="USD", exchange="NYSE", country="US", sector="Health Care")
    add_bars(session, jnj, [(100, 100)] * 15)
    p = paper_portfolio(session)
    engine.run_day(session, p, ts(D0), PREFS, [candidate(jnj)])
    engine.run_day(session, p, ts(D0 + timedelta(days=1)), PREFS, [])
    session.add(Dividend(instrument_id=jnj.id, ex_date=D0 + timedelta(days=3), pay_date=D0 + timedelta(days=8),
                         amount=1.0, currency="USD", source="test"))
    session.flush()
    assert engine.process_dividends(session, p, D0 + timedelta(days=7), PREFS) == 0  # not paid yet
    assert engine.process_dividends(session, p, D0 + timedelta(days=8), PREFS) == 1
    assert engine.process_dividends(session, p, D0 + timedelta(days=9), PREFS) == 0  # never twice
    (pd,) = session.query(PaperDividend).all()
    shares = ledger.state(session, p.id, ts(D0 + timedelta(days=1))).positions[jnj.id].quantity
    assert pd.gross_cad == pytest.approx(shares * 1.0 * 1.40)
    assert pd.withholding_cad == pytest.approx(pd.gross_cad * 0.15)  # TFSA does not recover US withholding
    assert pd.reinvested is False  # 50 CAD buys no whole 140 CAD share; cash stays as cash


def test_rrsp_has_no_us_withholding(session):
    inst = Instrument(symbol="KO", exchange="NYSE", name="KO", asset_class="equity", security_type="common_stock",
                      currency="USD", country="US")
    assert engine.withholding_rate(inst, "RRSP") == 0.0
    assert engine.withholding_rate(inst, "TFSA") == 0.15
    cdn_etf = Instrument(symbol="VFV", exchange="TSX", name="VFV", asset_class="equity", security_type="etf",
                         currency="CAD", country="CA")
    assert engine.withholding_rate(cdn_etf, "TFSA") == 0.0


def test_split_adjusts_position_once(session):
    shop = add_instrument(session, "SHOP", sector="Technology")
    add_bars(session, shop, [(100, 100), (100, 100), (100, 100), (10, 10), (10, 10)])
    p = paper_portfolio(session)
    engine.run_day(session, p, ts(D0), PREFS, [candidate(shop)])
    engine.run_day(session, p, ts(D0 + timedelta(days=1)), PREFS, [candidate(shop, assessment="HOLD")])
    session.add(CorporateAction(instrument_id=shop.id, effective_date=D0 + timedelta(days=3), kind="split", ratio=10.0,
                                source="test"))
    session.flush()
    assert engine.process_splits(session, p, D0 + timedelta(days=3)) == 1
    assert engine.process_splits(session, p, D0 + timedelta(days=4)) == 0
    assert ledger.state(session, p.id).positions[shop.id].quantity == 600


def test_benchmark_buys_once_and_holds(session):
    xeqt = add_instrument(session, "XEQT", security_type="etf", sector=None)
    add_bars(session, xeqt, [(30, 30), (30.5, 31), (32, 32)])
    bm = Portfolio(code="BM_GLOBAL", kind="benchmark", name="bm", initial_cash=100_000.0,
                   policy={"weights": {"XEQT:TSX": 100.0}})
    session.add(bm)
    session.flush()
    r1 = engine.run_day(session, bm, ts(D0), PREFS)
    r2 = engine.run_day(session, bm, ts(D0 + timedelta(days=1)), PREFS)
    r3 = engine.run_day(session, bm, ts(D0 + timedelta(days=2)), PREFS)
    assert (r1["orders"], r2["fills"], r3["orders"]) == (1, 1, 0)
    assert session.query(PaperOrder).filter(PaperOrder.portfolio_id == bm.id).count() == 1
    assert r3["value_cad"] > r2["value_cad"]


def test_snapshots_and_performance_metrics(session):
    ry = add_instrument(session, "RY")
    add_bars(session, ry, [(100, 100 + i) for i in range(12)])
    p = paper_portfolio(session)
    d = D0
    for _ in range(12):
        while d.weekday() >= 5:
            d += timedelta(days=1)
        engine.run_day(session, p, ts(d), PREFS, [candidate(ry, assessment="BUY" if d == D0 else "HOLD")])
        d += timedelta(days=1)
    perf = performance.metrics(session, p)
    assert perf["observations"] >= 10
    assert perf["total_return_pct"] is not None
    assert perf["closed_trades"] == 0 and perf["trading_costs_cad"]["slippage"] > 0
    assert "annualized_return_note" in perf  # too short to annualise honestly


def test_excess_uses_common_dates_only():
    a = [(D0, 100.0), (D0 + timedelta(days=1), 110.0), (D0 + timedelta(days=2), 121.0)]
    b = [(D0 + timedelta(days=1), 50.0), (D0 + timedelta(days=2), 50.0)]
    assert performance._excess_over_common_dates(a, b) == pytest.approx(10.0)
    assert performance._excess_over_common_dates(a, b[:1]) is None
