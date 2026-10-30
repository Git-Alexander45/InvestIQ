from datetime import date

import numpy as np
import pytest

from investiq.finance import indicators as ind
from investiq.finance import returns as r
from investiq.finance.fundamentals import derive
from investiq.finance.fx import FxQuote, FxTable, MissingFxRate


def test_total_return_and_cagr():
    assert r.total_return(100, 150) == pytest.approx(0.5)
    assert r.cagr(100, 121, date(2020, 1, 1), date(2022, 1, 1)) == pytest.approx(0.1, abs=1e-3)
    assert r.cagr(100, 121, date(2020, 1, 1), date(2020, 1, 1)) is None
    with pytest.raises(ValueError):
        r.total_return(0, 10)


def test_max_drawdown():
    assert r.max_drawdown([100, 120, 90, 130, 65]) == pytest.approx(65 / 130 - 1)
    assert r.max_drawdown([1, 2, 3]) == 0.0
    assert r.max_drawdown([]) == 0.0


def test_volatility_and_sharpe():
    rng = np.random.default_rng(1)
    rets = rng.normal(0.0005, 0.01, 2000)
    vol = r.annualized_volatility(rets)
    assert vol == pytest.approx(0.01 * np.sqrt(252), rel=0.05)
    s = r.sharpe_ratio(rets)
    assert s == pytest.approx(0.0005 / 0.01 * np.sqrt(252), rel=0.35)
    assert r.sharpe_ratio([0.01, 0.01, 0.01]) is None  # zero variance


def test_beta_and_correlation():
    rng = np.random.default_rng(2)
    m = rng.normal(0, 0.01, 500)
    a = 1.5 * m + rng.normal(0, 0.001, 500)
    assert r.beta(a, m) == pytest.approx(1.5, rel=0.05)
    corr = r.correlation_matrix({"a": a, "m": m})
    assert corr["a"]["m"] > 0.95
    assert corr["a"]["a"] == 1.0


def test_win_rate():
    assert r.win_rate([10, -5, 3, -1]) == 0.5
    assert r.win_rate([]) is None


def test_sma_ema_rsi():
    vals = [1, 2, 3, 4, 5, 6]
    assert ind.sma(vals, 3) == [None, None, 2, 3, 4, 5]
    e = ind.ema(vals, 3)
    assert e[:2] == [None, None] and e[2] == 2
    assert ind.rsi([float(i) for i in range(30)], 14)[-1] == 100.0
    down = [float(30 - i) for i in range(30)]
    assert ind.rsi(down, 14)[-1] == pytest.approx(0.0)


def test_macd_and_bollinger_shapes():
    vals = [100 + np.sin(i / 5) * 5 for i in range(80)]
    m = ind.macd(vals)
    assert len(m["macd"]) == len(vals) and m["signal"][-1] is not None
    b = ind.bollinger(vals, 20)
    assert b["upper"][-1] > b["middle"][-1] > b["lower"][-1]


def test_resample_weekly():
    from datetime import UTC, datetime, timedelta

    start = datetime(2024, 1, 1, tzinfo=UTC)  # Monday
    bars = [{"ts": start + timedelta(days=i), "open": i, "high": i + 1, "low": i - 1, "close": i + 0.5, "volume": 10}
            for i in range(10)]
    weekly = ind.resample_ohlcv(bars, "1wk")
    assert len(weekly) == 2
    assert weekly[0]["open"] == 0 and weekly[0]["close"] == 6.5 and weekly[0]["volume"] == 70


def test_fx_conversion_and_cross():
    t = FxTable([FxQuote("USD", "CAD", 1.35, date(2026, 1, 2), "boc"),
                 FxQuote("EUR", "CAD", 1.50, date(2026, 1, 2), "boc")])
    cad, q = t.convert(100, "USD", "CAD")
    assert cad == pytest.approx(135)
    usd, _ = t.convert(135, "CAD", "USD")
    assert usd == pytest.approx(100)
    eur_usd = t.get("EUR", "USD")
    assert eur_usd.rate == pytest.approx(1.5 / 1.35)
    assert "cross" in eur_usd.source
    assert t.convert(5, "CAD", "CAD")[0] == 5
    with pytest.raises(MissingFxRate):
        t.get("JPY", "CAD")
    with pytest.raises(ValueError):
        t.add(FxQuote("USD", "CAD", 0, date(2026, 1, 3), "x"))


def test_fx_keeps_latest():
    t = FxTable([FxQuote("USD", "CAD", 1.30, date(2026, 1, 3), "boc"),
                 FxQuote("USD", "CAD", 1.20, date(2026, 1, 1), "boc")])
    assert t.get("USD", "CAD").rate == 1.30


def test_derive_fundamentals():
    m = {
        "revenue_history": [{"year": 2020 + i, "value": v} for i, v in enumerate([100, 110, 121, 133.1])],
        "eps_history": [{"year": 2020 + i, "value": v} for i, v in enumerate([1, 1.2, 1.44, 1.728])],
        "fcf_history": [{"year": 2023, "value": 20}],
        "gross_profit_history": [{"year": 2020 + i, "value": v * 0.6} for i, v in enumerate([100, 110, 121, 133.1])],
        "total_debt": 50, "cash": 10, "total_equity": 100, "ebitda": 40, "market_cap": 1000,
        "current_assets": 60, "current_liabilities": 30, "pe_ttm": 30,
    }
    d = derive(m)
    assert d["revenue_growth_1y_pct"] == pytest.approx(10)
    assert d["revenue_cagr_3y_pct"] == pytest.approx(10, abs=1e-6)
    assert d["eps_cagr_3y_pct"] == pytest.approx(20, abs=1e-6)
    assert d["debt_to_equity"] == 0.5
    assert d["net_debt_to_ebitda"] == pytest.approx(1.0)
    assert d["current_ratio"] == 2.0
    assert d["fcf_yield_pct"] == pytest.approx(2.0)
    assert d["gross_margin_pct"] == pytest.approx(60)
    assert d["gross_margin_stability_pp"] == pytest.approx(0, abs=1e-9)
    assert d["peg"] == pytest.approx(30 / 20)
    assert d["interest_coverage"] is None  # no data -> None, never invented


def test_derive_handles_missing_and_negative():
    d = derive({"revenue_history": [{"year": 2023, "value": -5}, {"year": 2024, "value": 10}]})
    assert d["revenue_growth_1y_pct"] is None
    assert d["pe"] is None and d["peg"] is None
    neg_equity = derive({"total_debt": 10, "total_equity": -5})
    assert neg_equity["debt_to_equity"] == 10.0
