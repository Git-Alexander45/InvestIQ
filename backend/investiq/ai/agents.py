"""AI roles used by the research cycle. Each function builds an evidence pack from the database,
calls the router and persists the result as an append-only Analysis (even when AI is unavailable)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from investiq.ai.evidence import EvidencePack
from investiq.ai.router import AiResult, ModelRouter
from investiq.ai.schemas import ChiefAnalystOut, InvestmentAnalysisOut, NewsBatchOut, ReviewOut, RiskReviewOut
from investiq.models import Analysis, Instrument, NewsAssessment, NewsItem
from investiq.news.service import affected_etfs


def _save(session: Session, res: AiResult, *, role: str, pack: EvidencePack, instrument_id: int | None,
          cycle_id: int | None) -> Analysis:
    status = {"ok": "ok", "blocked_budget": "budget_blocked", "unavailable": "skipped"}.get(res.status, res.status)
    a = Analysis(instrument_id=instrument_id, cycle_id=cycle_id, role=role, model=res.model,
                 prompt_version=res.prompt_version, status=status, evidence_pack=pack.as_dict(),
                 output=res.output.model_dump(mode="json") if res.output else {"error": res.error},
                 unsupported_claims=(res.citations.unsupported if res.citations else []),
                 ai_request_id=res.request_id)
    session.add(a)
    session.flush()
    return a


# ------------------------------------------------------------------------------------------------
# News researcher (low-cost)
# ------------------------------------------------------------------------------------------------


def assess_news(router: ModelRouter, session: Session, items: list[NewsItem], universe: list[str],
                cycle_id: int | None) -> dict[str, Any]:
    if not items:
        return {"status": "skipped", "assessed": 0}
    pack = EvidencePack(subject="news batch")
    id_map: dict[str, NewsItem] = {}
    for it in items:
        fid = pack.add("news", f"{it.title}" + (f" — {it.summary}" if it.summary else ""),
                       f"{it.source_key} {it.url}", it.published_at.isoformat() if it.published_at else None)
        id_map[fid] = it
    pack.context = {"universe_symbols": universe[:400], "official_sources": sorted({i.source_key for i in items if i.official})}
    res = router.run(task="news_classification", role="news_researcher", tier="low_cost", pack=pack, schema=NewsBatchOut)
    _save(session, res, role="news_researcher", pack=pack, instrument_id=None, cycle_id=cycle_id)
    if res.output is None:
        return {"status": res.status, "assessed": 0, "error": res.error}
    known = set(universe)
    n = 0
    for a in res.output.items:  # type: ignore[attr-defined]
        item = id_map.get(a.news_id)
        if item is None:
            continue
        symbols = sorted({s.upper() for s in a.affected_symbols if s.upper() in known})
        session.add(NewsAssessment(
            news_item_id=item.id, method=f"ai:{res.model}:{res.prompt_version}", topic=a.topic[:48],
            what_happened=a.what_happened, event_time=None,
            confirmation="confirmed" if item.official and a.confirmation == "reported" else a.confirmation,
            impact=a.impact, horizon=a.horizon, confidence=a.confidence, importance=a.importance,
            affected_symbols=symbols, affected_sectors=a.affected_sectors[:10],
            affected_etfs=affected_etfs(session, symbols), evidence=[a.news_id, f"url:{item.url}", a.reasoning[:500]],
        ))
        n += 1
    return {"status": "ok", "assessed": n}


# ------------------------------------------------------------------------------------------------
# Analysts (premium), reviewer, risk manager, chief analyst
# ------------------------------------------------------------------------------------------------

FUND_LABELS = {
    "revenue_growth_1y_pct": "Revenue growth last year (%)", "revenue_cagr_3y_pct": "Revenue CAGR 3y (%)",
    "eps_cagr_3y_pct": "EPS CAGR 3y (%)", "fcf_margin_pct": "Free cash flow margin (%)",
    "gross_margin_pct": "Gross margin (%)", "operating_margin_pct": "Operating margin (%)",
    "debt_to_equity": "Debt/equity", "net_debt_to_ebitda": "Net debt/EBITDA", "current_ratio": "Current ratio",
    "fcf_yield_pct": "FCF yield (%)", "pe": "P/E", "peg": "PEG", "ev_ebitda": "EV/EBITDA", "roic_pct": "ROIC (%)",
    "dividend_yield_pct": "Dividend yield (%)", "dividend_cagr_5y_pct": "Dividend CAGR 5y (%)",
    "expense_ratio_pct": "Expense ratio (%)", "holdings_count": "Holdings count",
}
PRICE_LABELS = {
    "return_1y_pct": "1y price return (%)", "return_3y_ann_pct": "3y annualised return (%)",
    "return_5y_ann_pct": "5y annualised return (%)", "volatility_1y_pct": "1y volatility (%)",
    "max_drawdown_3y_pct": "3y max drawdown (%)", "beta": "Beta", "sharpe_3y": "3y Sharpe",
    "price_vs_sma200_pct": "Price vs 200-day average (%)",
}


def candidate_pack(ctx: dict[str, Any]) -> EvidencePack:
    """ctx keys: instrument, facts (scoring Facts), score (ScoreResult), quant_assessment, brokerage, fit,
    news_items, holdings_top, owner_notes, prior_analyses."""
    inst: Instrument = ctx["instrument"]
    facts, score = ctx["facts"], ctx["score"]
    pack = EvidencePack(subject=f"{inst.name} ({inst.symbol}:{inst.exchange}), {inst.security_type}, "
                                f"{inst.asset_class}, trades in {inst.currency}")
    f = facts.fundamentals or {}
    for k, label in FUND_LABELS.items():
        if f.get(k) is not None:
            pack.add("fundamentals", f"{label}: {f[k]:.4g}" if isinstance(f[k], int | float) else f"{label}: {f[k]}",
                     facts.fundamentals_source or "fundamentals",
                     facts.fundamentals_as_of.date().isoformat() if facts.fundamentals_as_of else None)
    p = facts.price_stats or {}
    for k, label in PRICE_LABELS.items():
        if p.get(k) is not None:
            pack.add("price", f"{label}: {p[k]:.4g}", f"{facts.price_source or 'prices'} ({p.get('return_basis')})",
                     p.get("last_date"))
    pack.add("score", f"Quantitative grade {score.grade} ({score.overall:.1f}/100, model {score.model}, coverage "
                      f"{score.coverage:.0%}, confidence {score.confidence:.2f}); rule-based assessment "
                      f"{ctx['quant_assessment']}", "InvestIQ scoring engine")
    for name, cat in score.categories.items():
        pack.add("score", f"Category {name}: {cat.score:.0f}/100" + ("" if cat.available else " (no data, neutral)"),
                 "InvestIQ scoring engine")
    for b, v in ctx.get("brokerage", {}).items():
        pack.add("brokerage", f"{b}: {v.get('status')} — {v.get('evidence_note', '')}", "brokerage verification records",
                 v.get("verified_at"))
    fit = ctx.get("fit")
    if fit is not None:
        pack.add("portfolio", "Portfolio fit acceptable" if fit.acceptable else
                 "Portfolio fit concerns: " + "; ".join(fit.flags), "InvestIQ diversification engine")
    for h in ctx.get("holdings_top", [])[:10]:
        pack.add("holdings", f"Holding {h['name']} ({h.get('symbol') or '-'}) {h['weight_pct']:.2f}%",
                 h.get("source", "ETF holdings"), h.get("as_of"))
    for n in ctx.get("news_items", [])[:8]:
        pack.add("news", f"{n['title']} (assessed {n['impact']} via {n['method']})", n["url"], n.get("published_at"))
    for note in ctx.get("owner_notes", [])[:5]:
        pack.add("owner_note", f"Owner note ({note['kind']}): {note['body'][:300]}", "owner (preference, not evidence)",
                 note.get("created_at"))
    for a in ctx.get("prior_analyses", [])[:2]:
        pack.add("prior_analysis", f"Previous analysis {a['created_at']}: {a['summary'][:300]}", f"analysis #{a['id']}")
    return pack


def analyze_candidate(router: ModelRouter, session: Session, ctx: dict[str, Any], cycle_id: int | None
                      ) -> tuple[Analysis, InvestmentAnalysisOut | None, EvidencePack]:
    inst: Instrument = ctx["instrument"]
    pack = candidate_pack(ctx)
    role = "etf_analyst" if inst.security_type in ("etf", "mutual_fund") else "stock_analyst"
    res = router.run(task=f"{role}_analysis", role=role, tier="premium", pack=pack, schema=InvestmentAnalysisOut)
    a = _save(session, res, role=role, pack=pack, instrument_id=inst.id, cycle_id=cycle_id)
    return a, res.output, pack  # type: ignore[return-value]


def review_candidate(router: ModelRouter, session: Session, inst: Instrument, pack: EvidencePack,
                     analysis: InvestmentAnalysisOut, cycle_id: int | None) -> tuple[Analysis, ReviewOut | None]:
    review_pack = EvidencePack(subject=pack.subject, facts=list(pack.facts), _counters=dict(pack._counters))
    review_pack.context = {"analyst_conclusion": analysis.model_dump(mode="json")}
    res = router.run(task="independent_review", role="reviewer", tier="reviewer", pack=review_pack, schema=ReviewOut)
    a = _save(session, res, role="reviewer", pack=review_pack, instrument_id=inst.id, cycle_id=cycle_id)
    return a, res.output  # type: ignore[return-value]


def risk_review(router: ModelRouter, session: Session, report: dict[str, Any], shortlist: list[str],
                cycle_id: int | None) -> tuple[Analysis, RiskReviewOut | None]:
    pack = EvidencePack(subject="portfolio risk review")
    for k in ("by_asset_class", "by_region", "by_sector", "by_underlying_currency"):
        if report.get(k):
            pack.add("portfolio", f"{k}: " + ", ".join(f"{a} {b:.1f}%" for a, b in list(report[k].items())[:8]),
                     "InvestIQ diversification engine")
    for flag in report.get("flags", [])[:15]:
        pack.add("portfolio", f"Flag: {flag['message']}", "InvestIQ diversification engine")
    pack.add("portfolio", f"Shortlisted candidates: {', '.join(shortlist) or 'none'}", "InvestIQ research cycle")
    res = router.run(task="risk_review", role="risk_manager", tier="low_cost", pack=pack, schema=RiskReviewOut)
    a = _save(session, res, role="risk_manager", pack=pack, instrument_id=None, cycle_id=cycle_id)
    return a, res.output  # type: ignore[return-value]


def chief_analyst(router: ModelRouter, session: Session, cycle_facts: dict[str, Any], cycle_id: int | None
                  ) -> tuple[Analysis, ChiefAnalystOut | None]:
    pack = EvidencePack(subject="daily research conclusions")
    for n in cycle_facts.get("news", [])[:25]:
        pack.add("news", f"[{n['topic']}] {n['title']} — impact {n['impact']}, {n['confirmation']}", n["url"],
                 n.get("published_at"))
    for m in cycle_facts.get("markets", [])[:15]:
        pack.add("macro", m["text"], m["source"], m.get("as_of"))
    for r in cycle_facts.get("top", [])[:12]:
        pack.add("score", f"{r['symbol']}: grade {r['grade']} ({r['overall']:.1f}), assessment {r['assessment']}"
                          + (f"; not buying now because {r['why_not_now']}" if r.get("why_not_now") else ""),
                 "InvestIQ scoring engine")
    for flag in cycle_facts.get("risk_flags", [])[:10]:
        pack.add("portfolio", flag, "InvestIQ diversification engine")
    res = router.run(task="chief_analyst", role="chief_analyst", tier="premium", pack=pack, schema=ChiefAnalystOut)
    a = _save(session, res, role="chief_analyst", pack=pack, instrument_id=None, cycle_id=cycle_id)
    return a, res.output  # type: ignore[return-value]


def prior_analyses(session: Session, instrument_id: int, limit: int = 2) -> list[dict[str, Any]]:
    rows = session.execute(select(Analysis).where(Analysis.instrument_id == instrument_id, Analysis.status == "ok")
                           .order_by(Analysis.id.desc()).limit(limit)).scalars()
    return [{"id": a.id, "created_at": a.created_at.date().isoformat(),
             "summary": f"{a.output.get('recommendation', '')}: {a.output.get('thesis', '')}"} for a in rows]
