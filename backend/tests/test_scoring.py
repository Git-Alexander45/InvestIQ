from datetime import UTC, datetime

import pytest

from investiq.scoring import assessment as asm
from investiq.scoring.engine import Facts, InstrumentInfo, model_for, score
from investiq.scoring.grades import GRADE_DISCLAIMER, grade_for, grade_steps
from investiq.scoring.leaderboards import Candidate, build_boards
from investiq.scoring.strategy_config import baseline, config_hash, validate_config

NOW = datetime(2026, 10, 1, tzinfo=UTC)
CFG = baseline()


def stock(**kw):
    base = dict(symbol="GRW", exchange="NASDAQ", name="Growth Co", asset_class="equity", security_type="common_stock",
                currency="USD", country="US", sector="Technology")
    base.update(kw)
    return InstrumentInfo(**base)


STRONG = {
    "revenue_growth_1y_pct": 30, "revenue_cagr_3y_pct": 28, "eps_cagr_3y_pct": 32, "fcf_cagr_3y_pct": 30,
    "debt_to_equity": 0.1, "net_debt_to_ebitda": -0.5, "current_ratio": 2.6, "interest_coverage": 40,
    "fcf_margin_pct": 28, "fcf_yield_pct": 5, "peg": 0.9, "pe": 26, "ev_ebitda": 16, "gross_margin_pct": 72,
    "gross_margin_stability_pp": 1, "roic_pct": 30, "operating_margin_pct": 36,
}
PRICES = {"volatility_1y_pct": 24, "max_drawdown_3y_pct": -22, "beta": 1.1, "avg_dollar_volume_m": 800}


def test_grade_bands():
    assert [grade_for(x) for x in (100, 95, 94.99, 90, 85, 80, 75, 70, 65, 60, 59.9, 0)] == \
        ["A+", "A+", "A", "A", "B", "B", "C", "C", "D", "D", "F", "F"]
    with pytest.raises(ValueError):
        grade_for(101)
    assert grade_steps("B", "A") == 1 and grade_steps("A", "D") == -3
    assert "not probabilities" in GRADE_DISCLAIMER


def test_baseline_config_valid_and_matches_spec():
    assert validate_config(CFG) == []
    w = CFG["models"]["equity"]["weights"]
    assert w == {"growth": 25, "financial_strength": 20, "valuation": 15, "competitive_advantage": 10,
                 "industry_trends": 10, "catalysts_news": 10, "risk": 10}
    bad = baseline()
    bad["models"]["equity"]["weights"]["growth"] = 30
    assert any("sum to 100" in p for p in validate_config(bad))
    assert config_hash(CFG) == config_hash(baseline())


def test_strong_stock_scores_high_with_evidence():
    f = Facts(stock(), NOW, fundamentals=STRONG, fundamentals_source="fmp", price_stats=PRICES, price_source="fmp",
              news_signal={"net": 0.2, "count": 2, "collected": True})
    r = score(f, CFG)
    assert r.model == "equity"
    assert r.overall > 75
    assert r.categories["industry_trends"].available is False  # no AI input -> neutral, not invented
    assert r.categories["industry_trends"].score == 50
    assert 0.8 < r.coverage < 1.0
    assert r.evidence and all("source" in e for e in r.evidence)
    assert r.positives


def test_risk_score_higher_is_better():
    calm = score(Facts(stock(), NOW, price_stats={"volatility_1y_pct": 12, "max_drawdown_3y_pct": -8, "beta": 0.5}), CFG)
    wild = score(Facts(stock(), NOW, price_stats={"volatility_1y_pct": 80, "max_drawdown_3y_pct": -70, "beta": 2.5}), CFG)
    assert calm.score_of("risk") > 85 > 20 > wild.score_of("risk")


def test_missing_data_cannot_produce_high_grade():
    r = score(Facts(stock(), NOW, fundamentals={"fcf_yield_pct": 12}), CFG)
    assert r.coverage < 0.2
    assert r.overall < 60
    assert any("Insufficient data" in a for a in r.avoid_reasons)
    assert r.confidence < 0.4


def test_model_selection():
    assert model_for(stock()) == "equity"
    assert model_for(stock(security_type="etf")) == "etf_equity"
    assert model_for(stock(security_type="etf", asset_class="bond")) == "fixed_income"
    assert model_for(stock(security_type="etf", asset_class="precious_metal")) == "commodity"
    assert model_for(stock(security_type="etf", asset_class="cash_equivalent")) == "cash_equivalent"


def test_etf_uses_different_criteria():
    etf = stock(symbol="BROAD", security_type="etf", mer_pct=0.08)
    f = Facts(etf, NOW, fundamentals={"aum": 5e10}, etf_stats={"holdings_count": 3000, "top10_pct": 22, "effective_n": 250},
              price_stats={**PRICES, "return_5y_ann_pct": 11, "sharpe_3y": 0.9})
    r = score(f, CFG)
    assert r.model == "etf_equity"
    assert set(r.categories) == set(CFG["models"]["etf_equity"]["weights"])
    assert r.score_of("cost") > 95


def test_leveraged_product_is_avoided():
    lev = stock(symbol="LEV", security_type="etf", is_leveraged=True)
    r = score(Facts(lev, NOW, price_stats=PRICES), CFG)
    assert any("Leveraged" in a for a in r.avoid_reasons)
    res = asm.assess(r, CFG, brokerage={"wealthsimple": "VERIFIED", "questrade": "VERIFIED"}, fit=asm.FitResult(),
                     held=False)
    assert res.assessment == "AVOID"


def _strong_result():
    f = Facts(stock(), NOW, fundamentals=STRONG, price_stats=PRICES, news_signal={"net": 0.5, "count": 3, "collected": True},
              ai_inputs={"industry_trends": {"score": 85, "evidence": ["N1"]},
                         "competitive_advantage": {"score": 90, "evidence": ["F2"]}})
    return score(f, CFG)


def test_buy_requires_both_brokerages_verified():
    r = _strong_result()
    assert r.overall >= 80
    verified = {"wealthsimple": "VERIFIED", "questrade": "VERIFIED"}
    assert asm.assess(r, CFG, brokerage=verified, fit=asm.FitResult(), held=False).assessment == "BUY"
    one = asm.assess(r, CFG, brokerage={"wealthsimple": "VERIFIED", "questrade": "UNVERIFIED"}, fit=asm.FitResult(),
                     held=False)
    assert one.assessment == "WATCH"
    assert "not verified" in one.why_not_now
    assert one.primary_eligible is False


def test_attractive_but_poor_fit_is_watch_with_explanation():
    r = _strong_result()
    res = asm.assess(r, CFG, brokerage={"wealthsimple": "VERIFIED", "questrade": "VERIFIED"},
                     fit=asm.FitResult(False, ["Technology exposure is 34%"]), held=False)
    assert res.assessment == "WATCH"
    assert "diversification" in res.why_not_now


def test_expensive_quality_company_waits():
    data = {**STRONG, "fcf_yield_pct": 0.5, "peg": 4.5, "pe": 90, "ev_ebitda": 60}
    r = score(Facts(stock(), NOW, fundamentals=data, price_stats=PRICES), CFG)
    res = asm.assess(r, CFG, brokerage={"wealthsimple": "VERIFIED", "questrade": "VERIFIED"}, fit=asm.FitResult(),
                     held=False)
    assert res.assessment == "WATCH"
    assert "valuation" in res.why_not_now


def test_held_positions_hold_or_sell():
    r = _strong_result()
    v = {"wealthsimple": "VERIFIED", "questrade": "VERIFIED"}
    assert asm.assess(r, CFG, brokerage=v, fit=asm.FitResult(), held=True).assessment == "HOLD"
    weak = score(Facts(stock(), NOW, fundamentals={k: (v * -1 if isinstance(v, int | float) else v) for k, v in STRONG.items()},
                       price_stats={"volatility_1y_pct": 90, "max_drawdown_3y_pct": -80, "beta": 2.5}), CFG)
    assert asm.assess(weak, CFG, brokerage=v, fit=asm.FitResult(), held=True).assessment == "SELL"


def test_more_cautious():
    assert asm.more_cautious("BUY", "WATCH") == "WATCH"
    assert asm.more_cautious("AVOID", "BUY") == "AVOID"


def test_leaderboards_methods_and_exclusions():
    good = _strong_result()
    cands = [Candidate(1, Facts(stock(themes=["artificial_intelligence"]), NOW, fundamentals=STRONG), good,
                       assessment="WATCH"),
             Candidate(2, Facts(stock(symbol="BAD"), NOW), good, assessment="AVOID")]
    boards = build_boards(cands)
    assert len(boards) == 10
    assert [r["symbol"] for r in boards["best_overall"]] == ["GRW"]  # AVOID excluded
    assert boards["emerging_industries"][0]["symbol"] == "GRW"
    assert boards["tfsa"] == []  # no TFSA evaluation -> not listed
    assert all(r["method"] for b in boards.values() for r in b)
