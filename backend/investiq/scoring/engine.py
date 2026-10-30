"""Deterministic, explainable scoring for each asset-class model.

Every category score is built from named components. Each component records the metric value,
its 0..100 sub-score and the data source, so every grade can be traced back to evidence.
Categories without data fall back to a neutral score and lower the coverage and confidence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from investiq.scoring.curves import scale
from investiq.scoring.grades import grade_for

# --------------------------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------------------------


@dataclass
class InstrumentInfo:
    symbol: str
    exchange: str
    name: str
    asset_class: str
    security_type: str
    currency: str
    country: str | None = None
    region: str | None = None
    sector: str | None = None
    themes: list[str] = field(default_factory=list)
    is_reit: bool = False
    is_leveraged: bool = False
    is_inverse: bool = False
    is_speculative: bool = False
    currency_hedged: bool | None = None
    mer_pct: float | None = None


@dataclass
class Facts:
    """Everything known about an instrument at ``as_of`` (point in time)."""

    instrument: InstrumentInfo
    as_of: datetime
    fundamentals: dict[str, Any] | None = None  # derived metrics (finance.fundamentals.derive)
    fundamentals_source: str | None = None
    fundamentals_as_of: datetime | None = None
    price_stats: dict[str, Any] | None = None
    price_source: str | None = None
    etf_stats: dict[str, Any] | None = None
    news_signal: dict[str, Any] | None = None  # {"net": -1..1, "count": n, "items": [...], "collected": bool}
    ai_inputs: dict[str, Any] | None = None  # {"competitive_advantage": {"score":..,"evidence":[..]}, ...}
    quality_issues: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------------------------
# Outputs
# --------------------------------------------------------------------------------------------


@dataclass
class Component:
    metric: str
    label: str
    value: float | str | None
    subscore: float
    source: str


@dataclass
class CategoryScore:
    name: str
    weight: float
    score: float
    available: bool
    components: list[Component] = field(default_factory=list)
    note: str | None = None


@dataclass
class ScoreResult:
    model: str
    overall: float
    grade: str
    confidence: float
    coverage: float
    categories: dict[str, CategoryScore]
    positives: list[str]
    negatives: list[str]
    risks: list[str]
    avoid_reasons: list[str]
    horizon: str
    evidence: list[dict[str, Any]]

    def category_dict(self) -> dict[str, Any]:
        return {k: asdict(v) for k, v in self.categories.items()}

    def score_of(self, category: str) -> float | None:
        c = self.categories.get(category)
        return c.score if c else None


# --------------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------------


class _Builder:
    def __init__(self, facts: Facts) -> None:
        self.facts = facts
        self.f = facts.fundamentals or {}
        self.p = facts.price_stats or {}
        self.e = facts.etf_stats or {}
        self.fsrc = facts.fundamentals_source or "fundamentals"
        self.psrc = facts.price_source or "prices"

    def comp(self, comps: list[Component], metric: str, label: str, value: Any,
             points: list[tuple[float, float]], source: str) -> None:
        if value is None:
            return
        comps.append(Component(metric, label, round(float(value), 4), round(scale(float(value), points), 2), source))


def _category(name: str, weight: float, comps: list[Component], missing_score: float,
              note: str | None = None) -> CategoryScore:
    if not comps:
        return CategoryScore(name, weight, missing_score, False, [], note or "no data available")
    avg = sum(c.subscore for c in comps) / len(comps)
    return CategoryScore(name, weight, round(avg, 2), True, comps, note)


def _ai_category(name: str, weight: float, facts: Facts, base: list[Component], missing: float) -> CategoryScore:
    """Blend quantitative proxies with an AI qualitative judgement when one exists and cites evidence."""
    ai = (facts.ai_inputs or {}).get(name)
    comps = list(base)
    note = None
    if ai and ai.get("score") is not None and ai.get("evidence"):
        comps.append(Component(f"ai_{name}", f"AI assessment ({ai.get('model', 'model')})",
                               float(ai["score"]), float(max(0, min(100, ai["score"]))),
                               f"ai:{ai.get('analysis_id', '')}"))
        note = "includes AI qualitative assessment with cited evidence"
    return _category(name, weight, comps, missing, note)


# --------------------------------------------------------------------------------------------
# Category definitions per model
# --------------------------------------------------------------------------------------------

PCT_GROWTH = [(-10, 0), (0, 30), (10, 60), (20, 80), (35, 100)]
RISK_VOL = [(12, 95), (20, 80), (30, 60), (45, 35), (70, 10)]
RISK_MDD = [(-60, 10), (-45, 30), (-30, 60), (-15, 90), (-5, 100)]
COST_MER = [(0.05, 100), (0.2, 85), (0.5, 60), (0.8, 40), (1.5, 10)]


def _risk_components(b: _Builder) -> list[Component]:
    comps: list[Component] = []
    b.comp(comps, "volatility_1y_pct", "1-year annualised volatility (%)", b.p.get("volatility_1y_pct"), RISK_VOL, b.psrc)
    b.comp(comps, "max_drawdown_3y_pct", "3-year maximum drawdown (%)", b.p.get("max_drawdown_3y_pct"), RISK_MDD, b.psrc)
    beta = b.p.get("beta") if b.p.get("beta") is not None else b.f.get("beta_reported")
    b.comp(comps, "beta", "Beta to market", beta, [(0.5, 90), (1.0, 70), (1.5, 45), (2.2, 15)], b.psrc)
    return comps


def _equity(b: _Builder, w: dict[str, float], missing: float) -> dict[str, CategoryScore]:
    f, cats = b.f, {}
    g: list[Component] = []
    b.comp(g, "revenue_growth_1y_pct", "Revenue growth, last year (%)", f.get("revenue_growth_1y_pct"), PCT_GROWTH, b.fsrc)
    b.comp(g, "revenue_cagr_3y_pct", "Revenue CAGR, 3 years (%)", f.get("revenue_cagr_3y_pct"), PCT_GROWTH, b.fsrc)
    b.comp(g, "eps_cagr_3y_pct", "EPS CAGR, 3 years (%)", f.get("eps_cagr_3y_pct"),
           [(-10, 10), (0, 30), (15, 70), (30, 100)], b.fsrc)
    b.comp(g, "fcf_cagr_3y_pct", "Free cash flow CAGR, 3 years (%)", f.get("fcf_cagr_3y_pct"),
           [(-10, 10), (0, 30), (15, 70), (30, 100)], b.fsrc)
    cats["growth"] = _category("growth", w["growth"], g, missing)

    s: list[Component] = []
    b.comp(s, "debt_to_equity", "Debt / equity", f.get("debt_to_equity"), [(0, 100), (0.5, 85), (1, 65), (2, 35), (4, 0)], b.fsrc)
    b.comp(s, "net_debt_to_ebitda", "Net debt / EBITDA", f.get("net_debt_to_ebitda"),
           [(-1, 100), (0, 90), (1, 80), (3, 45), (5, 10)], b.fsrc)
    b.comp(s, "current_ratio", "Current ratio", f.get("current_ratio"), [(0.5, 10), (1, 45), (1.5, 75), (2.5, 100)], b.fsrc)
    b.comp(s, "interest_coverage", "Interest coverage (x)", f.get("interest_coverage"),
           [(1, 0), (3, 40), (8, 80), (20, 100)], b.fsrc)
    b.comp(s, "fcf_margin_pct", "Free cash flow margin (%)", f.get("fcf_margin_pct"),
           [(-20, 0), (0, 35), (10, 70), (25, 100)], b.fsrc)
    cats["financial_strength"] = _category("financial_strength", w["financial_strength"], s, missing)

    v: list[Component] = []
    fcf_yield = f.get("fcf_yield_pct")
    b.comp(v, "fcf_yield_pct", "Free cash flow yield (%)", fcf_yield, [(-2, 0), (0, 15), (2, 45), (4, 65), (6, 80), (10, 100)], b.fsrc)
    b.comp(v, "peg", "PEG ratio", f.get("peg"), [(0.5, 100), (1, 85), (1.5, 65), (2.5, 35), (4, 10)], b.fsrc)
    b.comp(v, "pe", "Price / earnings", f.get("pe"), [(10, 90), (15, 80), (25, 60), (40, 35), (80, 10)], b.fsrc)
    b.comp(v, "ev_ebitda", "EV / EBITDA", f.get("ev_ebitda"), [(6, 95), (10, 80), (15, 60), (25, 35), (40, 10)], b.fsrc)
    cats["valuation"] = _category("valuation", w["valuation"], v, missing)

    m: list[Component] = []
    b.comp(m, "gross_margin_pct", "Gross margin (%)", f.get("gross_margin_pct"), [(20, 20), (40, 55), (60, 80), (75, 95)], b.fsrc)
    b.comp(m, "gross_margin_stability_pp", "Gross margin variability (pp)", f.get("gross_margin_stability_pp"),
           [(1, 100), (3, 75), (6, 45), (10, 20)], b.fsrc)
    b.comp(m, "roic_pct", "Return on invested capital (%)", f.get("roic_pct"), [(0, 10), (8, 45), (15, 75), (25, 100)], b.fsrc)
    b.comp(m, "operating_margin_pct", "Operating margin (%)", f.get("operating_margin_pct"),
           [(0, 20), (10, 50), (20, 75), (35, 100)], b.fsrc)
    cats["competitive_advantage"] = _ai_category("competitive_advantage", w["competitive_advantage"], b.facts, m, missing)

    cats["industry_trends"] = _ai_category("industry_trends", w["industry_trends"], b.facts, [], missing)
    cats["catalysts_news"] = _news_category(b, w["catalysts_news"], missing)

    r = _risk_components(b)
    b.comp(r, "avg_dollar_volume_m", "Average daily traded value (millions)", b.p.get("avg_dollar_volume_m"),
           [(0.5, 10), (2, 40), (10, 70), (50, 100)], b.psrc)
    cats["risk"] = _category("risk", w["risk"], r, missing)
    return cats


def _news_category(b: _Builder, weight: float, missing: float) -> CategoryScore:
    ns = b.facts.news_signal
    if not ns or not ns.get("collected"):
        return CategoryScore("catalysts_news", weight, missing, False, [], "news was not collected for this cycle")
    net = float(ns.get("net", 0.0))
    count = int(ns.get("count", 0))
    comp = Component("news_net_impact", f"Net assessed news impact ({count} items, 30 days)", round(net, 3),
                     round(scale(net, [(-1, 5), (-0.3, 30), (0, 50), (0.3, 70), (1, 95)]), 2), "news_assessments")
    note = "no material company-specific news; neutral" if count == 0 else None
    return CategoryScore("catalysts_news", weight, comp.subscore, True, [comp], note)


def _etf_equity(b: _Builder, w: dict[str, float], missing: float) -> dict[str, CategoryScore]:
    f, e, cats = b.f, b.e, {}
    mer = b.facts.instrument.mer_pct if b.facts.instrument.mer_pct is not None else f.get("expense_ratio_pct")
    c: list[Component] = []
    b.comp(c, "mer_pct", "Management expense ratio (%)", mer, COST_MER, "instrument/fundamentals")
    cats["cost"] = _category("cost", w["cost"], c, missing)

    d: list[Component] = []
    hc = e.get("holdings_count") if e.get("holdings_count") is not None else f.get("holdings_count")
    b.comp(d, "holdings_count", "Number of holdings", hc, [(20, 20), (100, 60), (500, 85), (2000, 100)], "etf_holdings")
    b.comp(d, "top10_pct", "Top-10 holdings weight (%)", e.get("top10_pct"), [(15, 95), (30, 70), (50, 35), (70, 10)], "etf_holdings")
    b.comp(d, "effective_holdings", "Effective number of holdings", e.get("effective_n"),
           [(10, 15), (30, 45), (100, 75), (300, 100)], "etf_holdings")
    cats["diversification"] = _category("diversification", w["diversification"], d, missing)

    lt: list[Component] = []
    b.comp(lt, "return_5y_ann_pct", "5-year annualised total return (%)", b.p.get("return_5y_ann_pct"),
           [(-5, 5), (0, 20), (5, 45), (8, 60), (12, 80), (18, 100)], b.psrc)
    b.comp(lt, "sharpe_3y", "3-year Sharpe ratio", b.p.get("sharpe_3y"), [(0, 20), (0.5, 50), (1.0, 80), (1.5, 100)], b.psrc)
    cats["long_term_return"] = _category("long_term_return", w["long_term_return"], lt, missing,
                                         "long-horizon and risk-adjusted; short-term performance is not used")

    ge: list[Component] = []
    b.comp(ge, "weighted_revenue_growth_pct", "Holdings-weighted revenue growth (%)",
           e.get("weighted_revenue_growth_pct", f.get("weighted_revenue_growth_pct")), PCT_GROWTH, "etf_holdings")
    cats["growth_exposure"] = _category("growth_exposure", w["growth_exposure"], ge, missing)

    v: list[Component] = []
    b.comp(v, "weighted_pe", "Holdings-weighted P/E", e.get("weighted_pe", f.get("weighted_pe")),
           [(10, 90), (15, 80), (22, 60), (35, 30), (50, 10)], "etf_holdings")
    cats["valuation"] = _category("valuation", w["valuation"], v, missing)

    cats["risk"] = _category("risk", w["risk"], _risk_components(b), missing)
    cats["structure_liquidity"] = _structure(b, w["structure_liquidity"], missing)
    return cats


def _structure(b: _Builder, weight: float, missing: float) -> CategoryScore:
    inst, comps = b.facts.instrument, []
    b.comp(comps, "aum_m", "Assets under management (millions)", (b.f.get("aum") or 0) / 1e6 if b.f.get("aum") else None,
           [(50, 20), (500, 60), (5000, 90), (20000, 100)], b.fsrc)
    b.comp(comps, "avg_dollar_volume_m", "Average daily traded value (millions)", b.p.get("avg_dollar_volume_m"),
           [(0.2, 15), (1, 45), (10, 80), (50, 100)], b.psrc)
    if inst.is_leveraged or inst.is_inverse:
        comps.append(Component("leverage", "Leveraged or inverse structure", "yes", 0.0, "instrument"))
    return _category("structure_liquidity", weight, comps, missing)


def _fixed_income(b: _Builder, w: dict[str, float], missing: float) -> dict[str, CategoryScore]:
    f, cats = b.f, {}
    y: list[Component] = []
    ytm = f.get("yield_to_maturity_pct") if f.get("yield_to_maturity_pct") is not None else f.get("distribution_yield_pct")
    b.comp(y, "yield_pct", "Yield to maturity / distribution yield (%)", ytm, [(0, 0), (2, 35), (3.5, 60), (5, 80), (7, 95)], b.fsrc)
    cats["yield"] = _category("yield", w["yield"], y, missing)
    cq = f.get("credit_quality")
    cq_map = {"government": 95.0, "investment_grade": 75.0, "mixed": 55.0, "high_yield": 30.0}
    cats["credit_quality"] = (
        CategoryScore("credit_quality", w["credit_quality"], cq_map[cq], True,
                      [Component("credit_quality", "Average credit quality", cq, cq_map[cq], b.fsrc)])
        if cq in cq_map else CategoryScore("credit_quality", w["credit_quality"], missing, False, [], "no data available")
    )
    dr: list[Component] = []
    b.comp(dr, "avg_duration_years", "Average duration (years)", f.get("avg_duration_years"),
           [(0.5, 100), (3, 80), (7, 55), (12, 35), (20, 15)], b.fsrc)
    cats["duration_risk"] = _category("duration_risk", w["duration_risk"], dr, missing)
    c: list[Component] = []
    mer = b.facts.instrument.mer_pct if b.facts.instrument.mer_pct is not None else f.get("expense_ratio_pct")
    b.comp(c, "mer_pct", "Management expense ratio (%)", mer, COST_MER, "instrument/fundamentals")
    cats["cost"] = _category("cost", w["cost"], c, missing)
    r: list[Component] = []
    b.comp(r, "volatility_1y_pct", "1-year annualised volatility (%)", b.p.get("volatility_1y_pct"),
           [(2, 100), (5, 80), (9, 55), (15, 25)], b.psrc)
    b.comp(r, "max_drawdown_3y_pct", "3-year maximum drawdown (%)", b.p.get("max_drawdown_3y_pct"),
           [(-30, 5), (-20, 30), (-10, 65), (-3, 100)], b.psrc)
    cats["risk"] = _category("risk", w["risk"], r, missing)
    cats["structure_liquidity"] = _structure(b, w["structure_liquidity"], missing)
    return cats


def _commodity(b: _Builder, w: dict[str, float], missing: float) -> dict[str, CategoryScore]:
    f, p, cats = b.f, b.p, {}
    inst = b.facts.instrument
    structure = f.get("structure")
    s_map = {"physical": 90.0, "equity_holdings": 65.0, "futures": 55.0, "synthetic": 40.0}
    if inst.is_leveraged or inst.is_inverse:
        cats["structure"] = CategoryScore("structure", w["structure"], 0.0, True,
                                          [Component("structure", "Leveraged or inverse product", "leveraged", 0.0, "instrument")])
    elif structure in s_map:
        cats["structure"] = CategoryScore("structure", w["structure"], s_map[structure], True,
                                          [Component("structure", "Fund structure", structure, s_map[structure], b.fsrc)])
    else:
        cats["structure"] = CategoryScore("structure", w["structure"], missing, False, [], "no data available")
    c: list[Component] = []
    mer = inst.mer_pct if inst.mer_pct is not None else f.get("expense_ratio_pct")
    b.comp(c, "mer_pct", "Management expense ratio (%)", mer, COST_MER, "instrument/fundamentals")
    cats["cost"] = _category("cost", w["cost"], c, missing)
    db: list[Component] = []
    b.comp(db, "corr_to_equities", "Correlation to global equities (3y daily)", p.get("corr_to_equities"),
           [(-0.3, 100), (0, 85), (0.3, 60), (0.7, 25), (0.9, 10)], b.psrc)
    cats["diversification_benefit"] = _category("diversification_benefit", w["diversification_benefit"], db, missing)
    lt: list[Component] = []
    b.comp(lt, "return_5y_ann_pct", "5-year annualised total return (%)", p.get("return_5y_ann_pct"),
           [(-5, 10), (0, 30), (5, 60), (10, 85), (15, 100)], b.psrc)
    cats["long_term_return"] = _category("long_term_return", w["long_term_return"], lt, missing)
    t: list[Component] = []
    # Trend is rewarded moderately and penalised when extended: avoids chasing recent performance.
    b.comp(t, "price_vs_sma200_pct", "Price vs 200-day average (%)", p.get("price_vs_sma200_pct"),
           [(-25, 25), (-10, 45), (0, 60), (10, 70), (25, 55), (40, 35)], b.psrc)
    cats["trend"] = _category("trend", w["trend"], t, missing)
    cats["risk"] = _category("risk", w["risk"], _risk_components(b), missing)
    return cats


def _cash(b: _Builder, w: dict[str, float], missing: float) -> dict[str, CategoryScore]:
    f, cats = b.f, {}
    y: list[Component] = []
    b.comp(y, "yield_pct", "Current yield (%)", f.get("distribution_yield_pct") or f.get("yield_to_maturity_pct"),
           [(0, 0), (1.5, 40), (3, 70), (4.5, 90), (6, 100)], b.fsrc)
    cats["yield"] = _category("yield", w["yield"], y, missing)
    cq = f.get("credit_quality")
    safety = {"government": 95.0, "investment_grade": 75.0, "mixed": 55.0, "high_yield": 20.0}.get(cq or "")
    cats["safety"] = (CategoryScore("safety", w["safety"], safety, True,
                                    [Component("credit_quality", "Underlying credit quality", cq, safety, b.fsrc)])
                      if safety is not None else CategoryScore("safety", w["safety"], missing, False, [], "no data available"))
    c: list[Component] = []
    mer = b.facts.instrument.mer_pct if b.facts.instrument.mer_pct is not None else f.get("expense_ratio_pct")
    b.comp(c, "mer_pct", "Management expense ratio (%)", mer, [(0.05, 100), (0.15, 85), (0.3, 60), (0.6, 20)],
           "instrument/fundamentals")
    cats["cost"] = _category("cost", w["cost"], c, missing)
    cats["structure_liquidity"] = _structure(b, w["structure_liquidity"], missing)
    return cats


MODEL_BUILDERS = {
    "equity": _equity,
    "etf_equity": _etf_equity,
    "fixed_income": _fixed_income,
    "commodity": _commodity,
    "cash_equivalent": _cash,
}


def model_for(inst: InstrumentInfo) -> str:
    if inst.asset_class == "cash_equivalent":
        return "cash_equivalent"
    if inst.asset_class == "bond":
        return "fixed_income"
    if inst.asset_class in ("commodity", "precious_metal"):
        return "commodity"
    if inst.security_type in ("etf", "mutual_fund"):
        return "etf_equity"
    return "equity"


# --------------------------------------------------------------------------------------------
# Main entry point
# --------------------------------------------------------------------------------------------


def score(facts: Facts, config: dict[str, Any]) -> ScoreResult:
    model = model_for(facts.instrument)
    weights = config["models"][model]["weights"]
    missing = float(config.get("missing_category_score", 50.0))
    builder = _Builder(facts)
    cats = MODEL_BUILDERS[model](builder, weights, missing)

    total_w = sum(weights.values())
    overall = sum(c.score * c.weight for c in cats.values()) / total_w
    coverage = sum(c.weight for c in cats.values() if c.available) / total_w

    quality_penalty = min(0.3, 0.1 * len(facts.quality_issues))
    stale_penalty = 0.0
    if facts.fundamentals_as_of and (facts.as_of - facts.fundamentals_as_of).days > 200:
        stale_penalty = 0.1
    confidence = max(0.0, min(1.0, 0.25 + 0.75 * coverage - quality_penalty - stale_penalty))

    positives, negatives = _explain(cats)
    risks, avoid = _risks_and_avoid(facts, cats, coverage)
    overall = round(max(0.0, min(100.0, overall)), 2)
    evidence = [
        {"category": c.name, "metric": comp.metric, "label": comp.label, "value": comp.value,
         "subscore": comp.subscore, "source": comp.source}
        for c in cats.values() for comp in c.components
    ]
    horizon = "3-5 years" if model in ("equity", "etf_equity") else "1-3 years"
    return ScoreResult(model=model, overall=overall, grade=grade_for(overall), confidence=round(confidence, 3),
                       coverage=round(coverage, 3), categories=cats, positives=positives, negatives=negatives,
                       risks=risks, avoid_reasons=avoid, horizon=horizon, evidence=evidence)


def _explain(cats: dict[str, CategoryScore]) -> tuple[list[str], list[str]]:
    pos: list[str] = []
    neg: list[str] = []
    for c in cats.values():
        for comp in c.components:
            val = comp.value if isinstance(comp.value, str) else f"{comp.value:,.2f}"
            if comp.subscore >= 80:
                pos.append(f"{comp.label}: {val} (strong)")
            elif comp.subscore <= 30:
                neg.append(f"{comp.label}: {val} (weak)")
    return pos[:8], neg[:8]


def _risks_and_avoid(facts: Facts, cats: dict[str, CategoryScore], coverage: float) -> tuple[list[str], list[str]]:
    inst, f, p = facts.instrument, facts.fundamentals or {}, facts.price_stats or {}
    risks: list[str] = []
    avoid: list[str] = []
    if inst.is_leveraged or inst.is_inverse:
        avoid.append("Leveraged/inverse products reset daily and are unsuitable as long-term holdings.")
    if inst.is_speculative:
        risks.append("Speculative position: size small (guideline 1-3% of portfolio).")
    vol = p.get("volatility_1y_pct")
    if vol is not None and vol > 45:
        risks.append(f"High volatility ({vol:.0f}% annualised).")
    mdd = p.get("max_drawdown_3y_pct")
    if mdd is not None and mdd < -40:
        risks.append(f"Deep historical drawdown ({mdd:.0f}% within 3 years).")
    de = f.get("debt_to_equity")
    fcfm = f.get("fcf_margin_pct")
    if de is not None and de > 2:
        risks.append(f"High leverage (debt/equity {de:.1f}).")
    if fcfm is not None and fcfm < 0 and de is not None and de > 1.5:
        avoid.append("Negative free cash flow combined with high debt.")
    pe = f.get("pe")
    if pe is not None and pe > 60:
        risks.append(f"Rich valuation (P/E {pe:.0f}) leaves little margin of safety.")
    if inst.currency != "CAD" or inst.currency_hedged is False:
        if inst.currency_hedged is not True:
            risks.append("Returns in CAD are exposed to currency movements (not currency-hedged).")
    if inst.is_reit:
        risks.append("REIT: excluded from default recommendations unless enabled by the owner.")
    if coverage < 0.5:
        avoid.append(f"Insufficient data: only {coverage:.0%} of the scoring weight is backed by data.")
    for issue in facts.quality_issues:
        risks.append(f"Data quality: {issue}")
    if cats.get("catalysts_news") and cats["catalysts_news"].available and cats["catalysts_news"].score < 30:
        risks.append("Recent news flow assessed as materially negative.")
    return risks, avoid
