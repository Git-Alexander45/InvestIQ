"""The daily research cycle: 20 recorded steps from data collection to the emailed report.

Rules:
* Each step is recorded (status, timing, detail). Required steps that fail make the cycle fail;
  optional steps (AI, extra news) degrade it. A degraded cycle says exactly what was missing.
* The cycle never reports success when required analysis failed (e.g. nothing could be scored).
* AI is used only for a filtered shortlist; everything else is deterministic Python.
"""

from __future__ import annotations

import logging
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from investiq.ai import agents
from investiq.ai import budget as ai_budget
from investiq.ai.router import ModelRouter
from investiq.config import get_settings
from investiq.data import ingest, registry
from investiq.data import repository as repo
from investiq.data.providers.base import (
    InstrumentRef,
    ProviderError,
    ProviderNotConfigured,
    ProviderUnsupported,
)
from investiq.data.validation import staleness
from investiq.diversification.engine import Position, analyse, what_if
from investiq.learning import predictions, strategies
from investiq.models import (
    CycleStep,
    GradeChange,
    Instrument,
    LeaderboardEntry,
    NewsItem,
    Portfolio,
    Prediction,
    Recommendation,
    ResearchCycle,
    SavedInvestment,
    Score,
    StrategyVersion,
    Watchlist,
)
from investiq.news import service as news_service
from investiq.notify import email as email_mod
from investiq.notify.service import notify
from investiq.paper import engine as paper
from investiq.paper import ledger
from investiq.research import facts as facts_mod
from investiq.research import locking, report
from investiq.scoring import assessment as asm
from investiq.scoring.engine import ScoreResult, score
from investiq.scoring.grades import grade_steps
from investiq.scoring.leaderboards import Candidate, build_boards
from investiq.services import portfolio_view
from investiq.services.preferences import get_pref
from investiq.tfsa import rules as tfsa

log = logging.getLogger(__name__)
MARKET_PROXY = ("XEQT", "TSX")
FX_CURRENCIES = ["USD", "EUR", "GBP", "JPY", "CHF", "AUD", "HKD"]


class StepFailed(RuntimeError):
    pass


@dataclass
class Ctx:
    session: Session
    cycle: ResearchCycle
    now: datetime
    providers: registry.Providers | None = None
    router: ModelRouter | None = None
    universe: list[Instrument] = field(default_factory=list)
    production: StrategyVersion | None = None
    experimental: StrategyVersion | None = None
    results: dict[str, Any] = field(default_factory=dict)
    degraded: list[str] = field(default_factory=list)
    calls: int = 0
    scored: dict[int, dict[str, Any]] = field(default_factory=dict)  # instrument_id -> details (production)
    scored_exp: dict[int, dict[str, Any]] = field(default_factory=dict)
    held_ids: set[int] = field(default_factory=set)


# ------------------------------------------------------------------------------------------------
# Step runner
# ------------------------------------------------------------------------------------------------


def _run_step(ctx: Ctx, no: int, name: str, fn: Callable[[Ctx], dict[str, Any] | None], required: bool,
              retries: int = 1) -> bool:
    step = CycleStep(cycle_id=ctx.cycle.id, step_no=no, name=name, required=required, status="running")
    ctx.session.add(step)
    ctx.session.commit()
    for attempt in range(1, retries + 1):
        step.attempts = attempt
        try:
            noted = len(ctx.degraded)
            detail = fn(ctx) or {}
            step.status = "degraded" if detail.pop("_degraded", False) else "ok"
            if step.status == "degraded" and len(ctx.degraded) == noted:
                why = detail.get("note") or "; ".join(str(e) for e in (detail.get("errors") or [])[:2]) or "partial"
                ctx.degraded.append(f"{name}: {why}"[:300])
            step.detail = _jsonable(detail)
            step.finished_at = datetime.now(UTC)
            ctx.session.commit()
            locking.heartbeat(ctx.session, ctx.cycle)
            return True
        except ProviderError as exc:
            ctx.session.rollback()
            step.error = f"{type(exc).__name__}: {exc}"
            if attempt < retries:
                continue
        except Exception as exc:  # noqa: BLE001 - every failure is recorded, then classified
            ctx.session.rollback()
            step.error = f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=4)}"[:4000]
            break
    step.status = "failed" if required else "degraded"
    step.finished_at = datetime.now(UTC)
    ctx.session.add(step)
    ctx.session.commit()
    if required:
        raise StepFailed(f"step {no} ({name}) failed: {step.error.splitlines()[0] if step.error else ''}")
    ctx.degraded.append(f"{name}: {step.error.splitlines()[0] if step.error else 'failed'}")
    return False


def _jsonable(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple | set):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, datetime | date):
        return obj.isoformat()
    if isinstance(obj, float | int | str | bool) or obj is None:
        return obj
    return str(obj)


# ------------------------------------------------------------------------------------------------
# Steps 1-3: collection
# ------------------------------------------------------------------------------------------------


def _universe(session: Session) -> list[Instrument]:
    u = get_pref(session, "universe")
    out = []
    for inst in session.execute(select(Instrument).where(Instrument.active.is_(True)).order_by(Instrument.id)).scalars():
        if not u.asset_classes.get(inst.asset_class, True):
            continue
        out.append(inst)
    return out


def _ref(inst: Instrument) -> InstrumentRef:
    return InstrumentRef(inst.symbol, inst.exchange, inst.currency, dict(inst.provider_symbols or {}))


def step_market_data(ctx: Ctx) -> dict[str, Any]:
    s = ctx.session
    mprefs = get_pref(s, "market_data")
    ctx.providers = registry.build(get_settings(), mprefs, today=ctx.now.date())
    ctx.universe = _universe(s)
    p = ctx.providers
    out: dict[str, Any] = {"universe": len(ctx.universe), "unavailable": p.unavailable, "synthetic": p.synthetic,
                           "bars_added": 0, "fundamentals_updated": 0, "holdings_updated": 0, "dividends": 0,
                           "errors": []}
    today = ctx.now.date()
    # FX first: everything is converted to CAD.
    try:
        last_fx = s.execute(select(ingest.FxRate.as_of).order_by(ingest.FxRate.as_of.desc()).limit(1)).scalar_one_or_none()
        start = (last_fx - timedelta(days=3)) if last_fx else today - timedelta(days=365 * 6)
        out["fx_added"] = ingest.store_fx(s, p.fx.rates(FX_CURRENCIES, start, today))
    except (ProviderError, Exception) as exc:  # FX outage: keep last stored rates
        out["errors"].append(f"fx: {exc}")
    if p.prices is None:
        out["_degraded"] = True
        out["note"] = "No price provider configured: using stored data only."
        return out
    max_calls = 10**9 if p.synthetic else mprefs.max_provider_calls_per_cycle
    for inst in ctx.universe:
        if ctx.calls >= max_calls:
            out["errors"].append("provider call budget for this cycle reached; remaining instruments use stored data")
            break
        ref = _ref(inst)
        try:
            last = s.execute(select(ingest.PriceBar.ts).where(ingest.PriceBar.instrument_id == inst.id,
                                                              ingest.PriceBar.interval == "1d")
                             .order_by(ingest.PriceBar.ts.desc()).limit(1)).scalar_one_or_none()
            start = (last.date() - timedelta(days=5)) if last else today - timedelta(days=365 * 6)
            ctx.calls += 1
            res = p.prices.bars(ref, "1d", start, today)
            out["bars_added"] += ingest.store_bars(s, inst, res, ctx.cycle.id)
            snap = repo.latest_fundamentals(s, inst.id, ctx.now)
            if p.fundamentals is not None and (snap is None or (ctx.now - snap.collected_at).days >= 7):
                fund_provider = p.fundamentals
                if inst.security_type == "common_stock" and inst.country == "US" and p.sec is not None and \
                        getattr(fund_provider, "name", "") != "fmp":
                    fund_provider = p.sec
                ctx.calls += 1
                if ingest.store_fundamentals(s, inst, fund_provider.fundamentals(ref)):
                    out["fundamentals_updated"] += 1
            if inst.security_type in ("etf", "mutual_fund") and p.holdings is not None:
                hs = repo.latest_holdings(s, inst.id, today)
                if hs is None or (today - hs.as_of).days >= 30:
                    ctx.calls += 1
                    if ingest.store_holdings(s, inst, p.holdings.holdings(ref)):
                        out["holdings_updated"] += 1
            if p.actions is not None and (last is None or today.day == 1 or today.weekday() == 5):
                ctx.calls += 2
                out["dividends"] += ingest.store_dividends(s, inst, p.actions.dividends(ref, start, today),
                                                           getattr(p.actions, "name", "provider"))
                ingest.store_splits(s, inst, p.actions.splits(ref, start, today), getattr(p.actions, "name", "provider"))
            s.commit()
        except (ProviderError, ProviderUnsupported, ProviderNotConfigured) as exc:
            s.rollback()
            out["errors"].append(f"{inst.symbol}: {exc}")
    if out["errors"]:
        out["_degraded"] = True
        out["errors"] = out["errors"][:50]
    return out


def step_company_news(ctx: Ctx) -> dict[str, Any]:
    s = ctx.session
    if ctx.providers is None or ctx.providers.company_news is None:
        return {"_degraded": True, "note": "no licensed company-news provider configured"}
    symbols = _focus_symbols(ctx)
    items = ctx.providers.company_news.company_news([_fmp_symbol(i) for i in symbols][:50])
    stats = news_service.store(s, items, ctx.cycle.id, news_service.entity_index(s))
    ctx.results["company_news"] = stats
    return stats


def _fmp_symbol(inst: Instrument) -> str:
    from investiq.data.providers.symbols import suffixed

    return suffixed(_ref(inst), "fmp")


def _focus_symbols(ctx: Ctx) -> list[Instrument]:
    """Owner holdings and watchlist first, then everything else in the universe."""
    s = ctx.session
    held = {h.instrument_id for h in portfolio_view.owner_holdings(s)}
    watched = {r.instrument_id for r in s.execute(select(SavedInvestment).where(SavedInvestment.archived.is_(False))).scalars()}
    first = [i for i in ctx.universe if i.id in held | watched]
    rest = [i for i in ctx.universe if i.id not in held | watched and i.security_type != "etf"]
    return first + rest


def step_official_news(ctx: Ctx) -> dict[str, Any]:
    s = ctx.session
    rss = ctx.providers.rss if ctx.providers else None
    if rss is None:
        return {"_degraded": True, "note": "RSS provider unavailable"}
    items, errors = news_service.collect(s, rss, None, [])
    stats = news_service.store(s, items, ctx.cycle.id, news_service.entity_index(s))
    stats["feed_errors"] = errors
    if errors and not items:
        stats["_degraded"] = True
        stats["note"] = f"no official feed could be read ({len(errors)} failed)"
    ctx.results["official_news"] = stats
    return stats


# ------------------------------------------------------------------------------------------------
# Steps 4-8: quality, dedupe, classification, affected securities, ETF holdings
# ------------------------------------------------------------------------------------------------


def step_quality(ctx: Ctx) -> dict[str, Any]:
    s = ctx.session
    stale_days = get_pref(s, "market_data").stale_after_days
    stale, missing = [], []
    for inst in ctx.universe:
        last = repo.last_bar(s, inst.id, ctx.now)
        issue = staleness(last.ts.date() if last else None, ctx.now.date(), stale_days)
        if issue is not None:
            (missing if issue.issue_type == "missing" else stale).append(inst.symbol)
            ingest.record_issues(s, [issue], inst.id, ctx.cycle.id)
    fx_ok = True
    try:
        repo.fx_table(s, ctx.now.date()).get("USD", "CAD")
    except Exception:
        fx_ok = False
    out = {"stale": stale[:60], "missing": missing[:60], "stale_count": len(stale), "missing_count": len(missing),
           "usd_cad_available": fx_ok}
    if not fx_ok:
        out["_degraded"] = True
        ctx.degraded.append("No recent USD/CAD rate: CAD conversions of USD prices unavailable")
    return out


def step_dedupe(ctx: Ctx) -> dict[str, Any]:
    a = ctx.results.get("official_news", {})
    b = ctx.results.get("company_news", {})
    return {k: a.get(k, 0) + b.get(k, 0) for k in ("received", "new", "duplicates", "related", "skipped_known")}


def step_classify(ctx: Ctx) -> dict[str, Any]:
    """Rules classification already ran on ingestion. Upgrade the most important new items with the
    low-cost model when the budget allows (filtered first: never the whole feed)."""
    s = ctx.session
    models = get_pref(s, "ai_models")
    items = list(s.execute(select(NewsItem).where(NewsItem.cycle_id == ctx.cycle.id, NewsItem.duplicate_of_id.is_(None))
                           ).scalars())
    pairs = news_service.latest_assessments(s, ctx.now - timedelta(days=2))
    importance = {it.id: a.importance for it, a in pairs}
    items.sort(key=lambda i: -importance.get(i.id, 0))
    chosen = items[: models.max_news_items_for_ai]
    ctx.router = ctx.router or ModelRouter(s, cycle_id=ctx.cycle.id)
    ok, why = ctx.router.available("low_cost")
    if not chosen:
        return {"rules_classified": len(items), "ai_classified": 0}
    if not ok:
        return {"rules_classified": len(items), "ai_classified": 0, "ai_status": why, "_degraded": True}
    universe = [i.symbol for i in ctx.universe]
    total = 0
    for k in range(0, len(chosen), 10):
        res = agents.assess_news(ctx.router, s, chosen[k:k + 10], universe, ctx.cycle.id)
        total += res.get("assessed", 0)
        if res["status"] != "ok":
            ctx.degraded.append(f"AI news classification: {res.get('error') or res['status']}")
            break
    return {"rules_classified": len(items), "ai_classified": total}


def step_affected(ctx: Ctx) -> dict[str, Any]:
    signals = news_service.news_signals(ctx.session, ctx.now)
    ctx.results["news_signals"] = signals
    top = sorted(signals.items(), key=lambda kv: -abs(kv[1]["net"]) * kv[1]["count"])[:15]
    return {"symbols_with_news": len(signals),
            "top": [{"symbol": k, "net": round(v["net"], 3), "count": v["count"]} for k, v in top]}


def step_etf_holdings(ctx: Ctx) -> dict[str, Any]:
    s = ctx.session
    covered, missing = [], []
    for inst in ctx.universe:
        if inst.security_type not in ("etf", "mutual_fund"):
            continue
        (covered if repo.latest_holdings(s, inst.id, ctx.now.date()) else missing).append(inst.symbol)
    out = {"etfs_with_holdings": len(covered), "etfs_without_holdings": missing[:50]}
    if missing:
        out["note"] = "Funds without holdings data are analysed without look-through (flagged in reports)."
    return out


# ------------------------------------------------------------------------------------------------
# Steps 9-14: screening, AI, fit, recommendations
# ------------------------------------------------------------------------------------------------


def _excluded(inst: Instrument, uprefs) -> str | None:
    if inst.is_reit and not uprefs.include_reits:
        return "REITs are excluded from recommendations unless enabled in Settings."
    if (inst.is_leveraged or inst.is_inverse) and not uprefs.include_leveraged_inverse:
        return "Leveraged/inverse products are excluded from the long-term universe."
    region = inst.region or {"CA": "canada", "US": "united_states"}.get(inst.country or "", "global")
    if region in uprefs.regions and not uprefs.regions[region]:
        return f"Region '{region}' is disabled in Settings."
    return None


def _score_all(ctx: Ctx, sv: StrategyVersion, target: dict[int, dict[str, Any]], persist: bool) -> int:
    s = ctx.session
    signals = ctx.results.get("news_signals", {})
    news_ok = any(k in ctx.results for k in ("official_news", "company_news"))
    proxy = repo.instrument_by_symbol(s, *MARKET_PROXY)
    market_bars = repo.daily_bars(s, proxy.id, ctx.now) if proxy else None
    uprefs = get_pref(s, "universe")
    n = 0
    for inst in ctx.universe:
        sig = signals.get(inst.symbol) or ({"net": 0.0, "count": 0, "items": [], "collected": True} if news_ok else None)
        f, extras = facts_mod.build(s, inst, ctx.now, market_bars=market_bars, news_signal=sig, cycle_id=ctx.cycle.id)
        if f.price_stats is None and f.fundamentals is None:
            continue
        r = score(f, sv.config)
        tf = tfsa.evaluate(f, r, country_exposure=extras["country_exposure"],
                           top10_pct=(f.etf_stats or {}).get("top10_pct"))
        row = None
        if persist:
            row = _persist_score(ctx, inst, sv, r, f)
        target[inst.id] = {"inst": inst, "facts": f, "extras": extras, "score": r, "score_row": row, "tfsa": tf,
                           "excluded": _excluded(inst, uprefs)}
        n += 1
    return n


def _persist_score(ctx: Ctx, inst: Instrument, sv: StrategyVersion, r: ScoreResult, f, ai_analysis_id: int | None = None
                   ) -> Score:
    s = ctx.session
    prev = s.execute(select(Score).where(Score.instrument_id == inst.id, Score.strategy_version_id == sv.id)
                     .order_by(Score.id.desc()).limit(1)).scalar_one_or_none()
    metrics = {k: v for k, v in (f.price_stats or {}).items() if k not in ("daily_returns", "daily_dates")}
    row = Score(instrument_id=inst.id, cycle_id=ctx.cycle.id, strategy_version_id=sv.id, model=r.model, overall=r.overall,
                grade=r.grade, confidence=r.confidence, coverage=r.coverage, category_scores=_jsonable(r.category_dict()),
                evidence=_jsonable(r.evidence), positives=r.positives, negatives=r.negatives, risks=r.risks,
                avoid_reasons=r.avoid_reasons, horizon=r.horizon,
                metrics=_jsonable({"price": metrics, "fundamentals": f.fundamentals or {}, "etf": f.etf_stats or {},
                                   "ai_analysis_id": ai_analysis_id}), as_of=ctx.now)
    s.add(row)
    s.flush()
    if prev is not None and prev.grade != r.grade:
        deltas = {k: round(v["score"] - prev.category_scores.get(k, {}).get("score", v["score"]), 2)
                  for k, v in row.category_scores.items()}
        movers = sorted(deltas.items(), key=lambda kv: -abs(kv[1]))[:3]
        reason = "Largest category changes: " + ", ".join(f"{k} {v:+.1f}" for k, v in movers if v)
        if ai_analysis_id:
            reason += f" (includes AI analysis #{ai_analysis_id})"
        s.add(GradeChange(instrument_id=inst.id, strategy_version_id=sv.id, previous_score_id=prev.id,
                          new_score_id=row.id, old_grade=prev.grade, new_grade=r.grade, old_overall=prev.overall,
                          new_overall=r.overall, reason=reason, category_deltas=deltas))
        steps = abs(grade_steps(prev.grade, r.grade))
        if steps >= get_pref(s, "notifications").grade_change_min_steps and (
                inst.id in ctx.held_ids or _is_watched(s, inst.id)):
            notify(s, "grade_change", f"{inst.symbol} grade {prev.grade} → {r.grade}", reason,
                   severity="warning" if grade_steps(prev.grade, r.grade) < 0 else "info", entity_type="instrument",
                   entity_id=inst.id, dedupe_key=f"grade:{inst.id}:{r.grade}:{ctx.cycle.cycle_date}")
    return row


def _is_watched(s: Session, instrument_id: int) -> bool:
    return s.execute(select(SavedInvestment.id).where(SavedInvestment.instrument_id == instrument_id,
                                                      SavedInvestment.archived.is_(False)).limit(1)).first() is not None


def step_screening(ctx: Ctx) -> dict[str, Any]:
    s = ctx.session
    ctx.production = strategies.production(s)
    exp = strategies.latest_experimental(s)
    ctx.cycle.strategy_version_id = ctx.production.id
    ctx.held_ids = {h.instrument_id for h in portfolio_view.owner_holdings(s)}
    n = _score_all(ctx, ctx.production, ctx.scored, persist=True)
    if n == 0:
        raise StepFailed("No instrument could be scored: there is no stored price or fundamentals data. "
                         "Configure a market-data provider (see docs/DATA_SOURCES.md).")
    if exp.config_hash != ctx.production.config_hash:
        ctx.experimental = exp
        _score_all(ctx, exp, ctx.scored_exp, persist=True)
    else:
        ctx.experimental = exp
        ctx.scored_exp = ctx.scored
    grades: dict[str, int] = {}
    for d in ctx.scored.values():
        grades[d["score"].grade] = grades.get(d["score"].grade, 0) + 1
    return {"scored": n, "grades": grades, "strategy": f"{ctx.production.name} v{ctx.production.version}",
            "experimental_scored_separately": ctx.scored_exp is not ctx.scored}


def step_shortlist(ctx: Ctx) -> dict[str, Any]:
    s = ctx.session
    models = get_pref(s, "ai_models")
    watched = {r.instrument_id for r in s.execute(select(SavedInvestment).where(SavedInvestment.archived.is_(False))).scalars()}
    pool = []
    for iid, d in ctx.scored.items():
        r: ScoreResult = d["score"]
        if d["excluded"] or r.avoid_reasons:
            continue
        if (r.overall >= 80 and r.coverage >= 0.6) or (iid in watched | ctx.held_ids and r.overall >= 70):
            pool.append((iid in ctx.held_ids, iid in watched, r.overall, iid))
    pool.sort(reverse=True)
    n = models.max_premium_candidates_per_cycle
    st = ai_budget.status(s)
    # Scale AI volume to the remaining budget: assume a worst-case premium call costs ~0.20 CAD.
    affordable = int(max(st.remaining_cad, 0) // 0.20)
    n = min(n, affordable)
    ctx.results["shortlist"] = [p[3] for p in pool[:n]]
    return {"eligible": len(pool), "selected": [ctx.scored[i]["inst"].symbol for i in ctx.results["shortlist"]],
            "budget_remaining_cad": st.remaining_cad, "limited_by_budget": affordable < models.max_premium_candidates_per_cycle}


def _fit_for(ctx: Ctx, d: dict[str, Any]) -> asm.FitResult:
    positions = ctx.results.get("owner_positions")
    if positions is None:
        return asm.FitResult(True, [], {"note": "portfolio fit not yet evaluated"})
    inst = d["inst"]
    cache = ctx.results.setdefault("fit_cache", {})
    if inst.id in cache:
        return cache[inst.id]
    cash = ctx.results.get("owner_cash", 0.0)
    if not positions:
        positions, cash = [], 100_000.0  # notional portfolio when the owner has not entered holdings
    weight = 5.0 if inst.security_type not in ("etf", "mutual_fund") else 10.0
    if inst.is_speculative:
        weight = 2.0
    cand = Position(inst.id, inst.symbol, inst.exchange, inst.name, inst.asset_class, inst.security_type, 0.0,
                    inst.currency, inst.country, inst.sector, inst.is_speculative, inst.currency_hedged,
                    d["extras"]["constituents"], None)
    fit, _, _ = what_if(positions, cash, cand, weight, get_pref(ctx.session, "risk_limits").model_dump())
    cache[inst.id] = fit
    return fit


def _brokerage(ctx: Ctx, inst_id: int) -> dict[str, dict]:
    days = get_pref(ctx.session, "brokerage").reverify_after_days
    return repo.brokerage_status(ctx.session, inst_id, ctx.now, days)


def _context(ctx: Ctx, d: dict[str, Any], quant_assessment: str) -> dict[str, Any]:
    s = ctx.session
    inst = d["inst"]
    sig = (ctx.results.get("news_signals") or {}).get(inst.symbol, {})
    holdings = []
    for c in (d["extras"]["constituents"] or [])[:10]:
        holdings.append({"name": c.name, "symbol": c.key, "weight_pct": c.weight_pct, "source": "ETF holdings"})
    from investiq.models import PersonalNote

    notes = [{"kind": n.kind, "body": n.body, "created_at": n.created_at.date().isoformat()}
             for n in s.execute(select(PersonalNote).where(PersonalNote.instrument_id == inst.id)
                                .order_by(PersonalNote.id.desc()).limit(5)).scalars()]
    return {"instrument": inst, "facts": d["facts"], "score": d["score"], "quant_assessment": quant_assessment,
            "brokerage": _brokerage(ctx, inst.id), "fit": _fit_for(ctx, d), "news_items": sig.get("items", []),
            "holdings_top": holdings, "owner_notes": notes, "prior_analyses": agents.prior_analyses(s, inst.id)}


def step_ai_analysis(ctx: Ctx) -> dict[str, Any]:
    s = ctx.session
    ctx.router = ctx.router or ModelRouter(s, cycle_id=ctx.cycle.id)
    shortlist = ctx.results.get("shortlist", [])
    # Portfolio context is needed by the analysts, so compute it before AI runs.
    _ensure_owner_positions(ctx)
    ok, why = ctx.router.available("premium")
    if not shortlist:
        return {"analysed": 0, "note": "no candidate met the shortlist criteria"}
    if not ok:
        ctx.results["ai_paused"] = why
        return {"analysed": 0, "ai_status": why, "_degraded": True}
    done, failed = [], []
    ctx.results["ai"] = {}
    for iid in shortlist:
        d = ctx.scored[iid]
        quant = _assess(ctx, d, d["score"]).assessment
        context = _context(ctx, d, quant)
        analysis_row, out, pack = agents.analyze_candidate(ctx.router, s, context, ctx.cycle.id)
        if out is None:
            failed.append(f"{d['inst'].symbol}: {analysis_row.status}")
            if analysis_row.status == "budget_blocked":
                ctx.results["ai_paused"] = "monthly AI budget reached during the cycle"
                break
            continue
        ai_inputs = {
            "competitive_advantage": {"score": out.competitive_advantage.score, "evidence": out.competitive_advantage.evidence,
                                      "model": analysis_row.model, "analysis_id": analysis_row.id},
            "industry_trends": {"score": out.industry_trends.score, "evidence": out.industry_trends.evidence,
                                "model": analysis_row.model, "analysis_id": analysis_row.id},
        }
        f = d["facts"]
        f.ai_inputs = ai_inputs
        r2 = score(f, ctx.production.config)
        row2 = _persist_score(ctx, d["inst"], ctx.production, r2, f, ai_analysis_id=analysis_row.id)
        ctx.results["ai"][iid] = {"analysis": analysis_row, "out": out, "pack": pack, "quant_score": d["score"],
                                  "quant_score_row": d["score_row"]}
        d["score"], d["score_row"] = r2, row2
        done.append(d["inst"].symbol)
        s.commit()
    out_d: dict[str, Any] = {"analysed": done, "failed": failed}
    if failed:
        out_d["_degraded"] = True
        ctx.degraded.append(f"AI analysis failed for {len(failed)} candidate(s)")
    return out_d


def step_challenge(ctx: Ctx) -> dict[str, Any]:
    s = ctx.session
    if not ctx.results.get("ai"):
        return {"reviewed": 0, "note": "no AI analyses to challenge"}
    ok, why = ctx.router.available("reviewer")
    if not ok:
        return {"reviewed": 0, "ai_status": why}
    reviewed = []
    for iid, a in ctx.results["ai"].items():
        if a["out"].recommendation not in ("BUY", "HOLD") and _assess(ctx, ctx.scored[iid], ctx.scored[iid]["score"]
                                                                       ).assessment != "BUY":
            continue  # only challenge the strongest theses
        row, rev = agents.review_candidate(ctx.router, s, ctx.scored[iid]["inst"], a["pack"], a["out"], ctx.cycle.id)
        a["review"], a["review_row"] = rev, row
        reviewed.append(ctx.scored[iid]["inst"].symbol)
        s.commit()
    return {"reviewed": reviewed}


def _ensure_owner_positions(ctx: Ctx) -> None:
    if "owner_positions" in ctx.results:
        return
    s = ctx.session
    holdings = portfolio_view.owner_holdings(s)
    items = [(s.get(Instrument, h.instrument_id), h.quantity) for h in holdings]
    positions, problems = portfolio_view.build_positions(s, items, ctx.now)
    ctx.results["owner_positions"] = positions
    ctx.results["owner_cash"] = 0.0
    ctx.results["owner_position_problems"] = problems


def step_portfolio_fit(ctx: Ctx) -> dict[str, Any]:
    s = ctx.session
    _ensure_owner_positions(ctx)
    positions = ctx.results["owner_positions"]
    limits = get_pref(s, "risk_limits").model_dump()
    report_d = analyse(positions, 0.0, limits).as_dict() if positions else None
    ctx.results["owner_diversification"] = report_d
    out: dict[str, Any] = {"owner_positions": len(positions), "problems": ctx.results["owner_position_problems"]}
    if report_d:
        out["flags"] = [f["message"] for f in report_d["flags"]][:15]
        for f in report_d["flags"]:
            if f["severity"] == "warning":
                notify(s, "portfolio_risk", "Portfolio risk", f["message"], severity="warning",
                       dedupe_key=f"risk:{f['type']}:{f.get('sector') or f.get('company') or f.get('symbol')}")
    else:
        out["note"] = "No owner holdings entered; fit is evaluated against a notional all-cash portfolio."
    if ctx.router and ctx.results.get("shortlist") and report_d:
        ok, _ = ctx.router.available("low_cost")
        if ok:
            _, rr = agents.risk_review(ctx.router, s, report_d, [ctx.scored[i]["inst"].symbol for i in ctx.results["shortlist"]],
                                       ctx.cycle.id)
            if rr:
                ctx.results["risk_review"] = rr
                out["ai_risk_summary"] = rr.summary
    return out


def _assess(ctx: Ctx, d: dict[str, Any], r: ScoreResult, cfg: dict | None = None) -> asm.AssessmentResult:
    statuses = {b: v["status"] for b, v in _brokerage(ctx, d["inst"].id).items()}
    fit = _fit_for(ctx, d) if r.overall >= (cfg or ctx.production.config)["assessment"]["buy_min_overall"] - 5 else asm.FitResult()
    return asm.assess(r, cfg or ctx.production.config, brokerage=statuses, fit=fit, held=d["inst"].id in ctx.held_ids,
                      excluded_reason=d["excluded"])


def step_recommend(ctx: Ctx) -> dict[str, Any]:
    s = ctx.session
    counts: dict[str, int] = {}
    candidates: list[Candidate] = []
    proxy = repo.instrument_by_symbol(s, *MARKET_PROXY)
    downgrade = set(ctx.results.get("risk_review").candidates_to_downgrade if ctx.results.get("risk_review") else [])
    ctx.results["recs"] = {}
    new_buys = []
    for iid, d in ctx.scored.items():
        r: ScoreResult = d["score"]
        res = _assess(ctx, d, r)
        final, source = res.assessment, "quant_only"
        ai = (ctx.results.get("ai") or {}).get(iid)
        quant_assessment = _assess(ctx, d, ai["quant_score"]).assessment if ai else res.assessment
        rationale, why, thesis, analysis_id = res.rationale, res.why_not_now, None, None
        if ai:
            source, analysis_id, thesis = "ai_reviewed", ai["analysis"].id, ai["out"].thesis
            final = asm.more_cautious(final, ai["out"].recommendation)
            if ai.get("review") is not None:
                final = asm.more_cautious(final, ai["review"].recommended_assessment)
            if final != res.assessment:
                why = (why + "; " if why else "") + f"AI review lowered conviction to {final}"
        if d["inst"].symbol in downgrade and final == "BUY":
            final, why = "WATCH", (why + "; " if why else "") + "risk manager: would concentrate the portfolio"
        last = d["extras"]["last_bar"]
        rec = Recommendation(cycle_id=ctx.cycle.id, instrument_id=iid, strategy_version_id=ctx.production.id,
                             score_id=d["score_row"].id, analysis_id=analysis_id, assessment=final,
                             quant_assessment=quant_assessment, source=source,
                             primary_eligible=res.primary_eligible and final == "BUY", rationale=rationale,
                             why_not_now=why, thesis=thesis, portfolio_fit=_jsonable(_fit_for(ctx, d).__dict__),
                             brokerage_status=_jsonable(_brokerage(ctx, iid)),
                             price=last.close if last else None, price_currency=last.currency if last else None,
                             price_as_of=last.ts if last else None, price_source=last.source if last else None,
                             horizon=r.horizon)
        s.add(rec)
        s.flush()
        ctx.results["recs"][iid] = rec
        counts[final] = counts.get(final, 0) + 1
        _maybe_predict(s, rec, d["score_row"], proxy.id if proxy else None)
        if final == "BUY":
            new_buys.append(d["inst"].symbol)
        candidates.append(Candidate(iid, d["facts"], r, d["score_row"].id, final, rec.primary_eligible,
                                    d["tfsa"].as_dict() | {"score": d["tfsa"].score} if d["tfsa"].eligible else None,
                                    _intl_pct(d["extras"]["country_exposure"])))
    boards = build_boards(candidates, ctx.production.config["leaderboards"]["size"])
    for key, rows in boards.items():
        for row in rows:
            s.add(LeaderboardEntry(cycle_id=ctx.cycle.id, board=key, rank=row["rank"], instrument_id=row["instrument_id"],
                                   score_id=row["score_id"], board_score=row["board_score"], method=row["method"],
                                   details=_jsonable(row)))
    ctx.results["boards"] = boards
    ctx.results["tfsa_picks"] = tfsa.pick_candidates([
        {"symbol": c.facts.instrument.symbol, "instrument_id": c.instrument_id, "tfsa_score": (c.tfsa or {}).get("score"),
         "growth": c.score.score_of("growth") if c.tfsa else None,
         "dividend": (c.facts.fundamentals or {}).get("dividend_yield_pct") if c.tfsa else None,
         "primary_eligible": c.primary_eligible, "assessment": c.assessment, "grade": c.score.grade,
         "withholding_drag_pct": (c.tfsa or {}).get("withholding_drag_pct"), "notes": (c.tfsa or {}).get("notes")}
        for c in candidates if c.tfsa])
    prev_buys = _previous_buys(s, ctx.cycle)
    for sym in sorted(set(new_buys) - prev_buys):
        notify(s, "new_opportunity", f"New BUY research assessment: {sym}",
               "Verified at both brokerages, with acceptable valuation, risk and portfolio fit. Research only — "
               "not an instruction to trade.", dedupe_key=f"buy:{sym}:{ctx.cycle.cycle_date}")
    # Experimental strategy assessments feed Portfolio D only (no recommendations are published for it).
    if ctx.scored_exp is not ctx.scored:
        ctx.results["exp_assessments"] = {iid: _assess(ctx, d, d["score"], ctx.experimental.config).assessment
                                          for iid, d in ctx.scored_exp.items()}
    return {"assessments": counts, "boards": {k: len(v) for k, v in boards.items()}, "new_buys": new_buys}


def _intl_pct(countries: dict[str, float] | None) -> float | None:
    if not countries:
        return None
    total = sum(countries.values()) or 1
    return sum(v for k, v in countries.items() if k not in ("CA", "US", "Unknown")) / total * 100


def _previous_buys(s: Session, cycle: ResearchCycle) -> set[str]:
    prev = s.execute(select(ResearchCycle).where(ResearchCycle.id < cycle.id, ResearchCycle.status.in_(locking.DONE))
                     .order_by(ResearchCycle.id.desc()).limit(1)).scalar_one_or_none()
    if prev is None:
        return set()
    rows = s.execute(select(Instrument.symbol).join(Recommendation, Recommendation.instrument_id == Instrument.id)
                     .where(Recommendation.cycle_id == prev.id, Recommendation.assessment == "BUY")).all()
    return {r[0] for r in rows}


def _maybe_predict(s: Session, rec: Recommendation, score_row: Score, benchmark_id: int | None) -> None:
    """Record a new prediction when the call changes (or is first made / older than 90 days)."""
    last = s.execute(select(Prediction).where(Prediction.instrument_id == rec.instrument_id,
                                              Prediction.strategy_version_id == rec.strategy_version_id,
                                              Prediction.source == rec.source)
                     .order_by(Prediction.id.desc()).limit(1)).scalar_one_or_none()
    if last is not None and last.assessment == rec.assessment and rec.price_as_of and \
            (rec.price_as_of - last.made_at).days < 90:
        return
    predictions.create(s, rec, score_row, benchmark_id)


# ------------------------------------------------------------------------------------------------
# Steps 15-20: watchlists, paper trading, save, report, email, completion
# ------------------------------------------------------------------------------------------------


def step_watchlists(ctx: Ctx) -> dict[str, Any]:
    s = ctx.session
    updates = []
    for si, wl in s.execute(select(SavedInvestment, Watchlist).join(Watchlist, Watchlist.id == SavedInvestment.watchlist_id)
                            .where(SavedInvestment.archived.is_(False))).all():
        d = ctx.scored.get(si.instrument_id)
        rec = (ctx.results.get("recs") or {}).get(si.instrument_id)
        inst = s.get(Instrument, si.instrument_id)
        sig = (ctx.results.get("news_signals") or {}).get(inst.symbol, {})
        u = {"watchlist": wl.name, "symbol": inst.symbol, "grade": d["score"].grade if d else None,
             "assessment": rec.assessment if rec else None, "news_count": sig.get("count", 0)}
        updates.append(u)
        if sig.get("count"):
            notify(s, "watchlist", f"{inst.symbol}: {sig['count']} new development(s)",
                   "; ".join(i["title"] for i in sig.get("items", [])[:3]), entity_type="instrument", entity_id=inst.id,
                   dedupe_key=f"wl-news:{inst.id}:{ctx.cycle.cycle_date}")
    from investiq.services.alerts import check_alerts

    fired = check_alerts(s, ctx.now)
    ctx.results["watchlist_updates"] = updates
    return {"saved_investments": len(updates), "alerts_fired": fired}


def _paper_candidates(ctx: Ctx, scored: dict[int, dict[str, Any]], assessments: dict[int, str] | None) -> list[dict]:
    rows = []
    for iid, d in scored.items():
        rec = (ctx.results.get("recs") or {}).get(iid)
        a = (assessments or {}).get(iid) or (rec.assessment if rec else None)
        if a is None:
            continue
        inst = d["inst"]
        rows.append({"instrument_id": iid, "assessment": a, "overall": d["score"].overall, "grade": d["score"].grade,
                     "model": d["score"].model, "primary_eligible": bool(rec and rec.primary_eligible) if assessments is None
                     else all(v["status"] == "VERIFIED" for v in _brokerage(ctx, iid).values()),
                     "sector": inst.sector, "region": inst.region, "country": inst.country,
                     "is_speculative": inst.is_speculative, "security_type": inst.security_type,
                     "recommendation_id": rec.id if rec and assessments is None else None})
    return rows


def step_paper(ctx: Ctx) -> dict[str, Any]:
    s = ctx.session
    prefs = get_pref(s, "paper_trading")
    if not prefs.enabled:
        return {"note": "paper trading disabled in Settings"}
    prod = _paper_candidates(ctx, ctx.scored, None)
    exp = _paper_candidates(ctx, ctx.scored_exp, ctx.results.get("exp_assessments")) if ctx.results.get(
        "exp_assessments") else prod
    out = {}
    for p in s.execute(select(Portfolio).where(Portfolio.kind.in_(("paper", "benchmark")), Portfolio.active.is_(True))
                       .order_by(Portfolio.code)).scalars():
        cands = exp if p.code == "D" else prod
        before = ledger.value(s, p, ctx.now.date()).total_cad if p.inception_date else p.initial_cash
        out[p.code] = paper.run_day(s, p, ctx.now, prefs, cands)
        _milestones(s, p, before, out[p.code].get("value_cad"))
    evaluated = predictions.evaluate_due(s, ctx.now)
    out["prediction_evaluations"] = evaluated
    return out


def _milestones(s: Session, p: Portfolio, before: float | None, after: float | None) -> None:
    from investiq.models import PortfolioMilestone

    if not after or not p.initial_cash or p.kind != "paper":
        return
    change = (after / p.initial_cash - 1) * 100
    for threshold in (-20, -10, 10, 25, 50, 100):
        crossed = change >= threshold if threshold > 0 else change <= threshold
        if not crossed:
            continue
        if s.execute(select(PortfolioMilestone.id).where(PortfolioMilestone.portfolio_id == p.id,
                                                         PortfolioMilestone.kind == "total_return",
                                                         PortfolioMilestone.threshold == threshold)).first():
            continue
        s.add(PortfolioMilestone(portfolio_id=p.id, kind="total_return", threshold=threshold,
                                 detail={"value_cad": after, "total_return_pct": round(change, 2)}))
        notify(s, "paper_milestone", f"{p.name}: {threshold:+d}% total return",
               f"Simulated value {after:,.0f} CAD ({change:+.1f}% since inception). Paper trading only.",
               severity="warning" if threshold < 0 else "info", dedupe_key=f"ms:{p.id}:{threshold}")


def step_save(ctx: Ctx) -> dict[str, Any]:
    s = ctx.session
    s.commit()
    return {"scores": s.query(Score).filter(Score.cycle_id == ctx.cycle.id).count(),
            "recommendations": s.query(Recommendation).filter(Recommendation.cycle_id == ctx.cycle.id).count(),
            "leaderboard_entries": s.query(LeaderboardEntry).filter(LeaderboardEntry.cycle_id == ctx.cycle.id).count()}


def step_report(ctx: Ctx) -> dict[str, Any]:
    s = ctx.session
    if ctx.router is not None and ctx.router.available("premium")[0]:
        cf = report.chief_facts(s, ctx)
        _, chief = agents.chief_analyst(ctx.router, s, cf, ctx.cycle.id)
        ctx.results["chief"] = chief
    rep = report.build_daily(s, ctx)
    ctx.results["report"] = rep
    return {"report_id": rep.id, "subject": rep.subject}


def step_email(ctx: Ctx) -> dict[str, Any]:
    s = ctx.session
    prefs = get_pref(s, "email")
    rep = ctx.results["report"]
    if not prefs.enabled:
        return {"status": "disabled in Settings"}
    d = email_mod.deliver(s, kind="daily_report", to=prefs.to_address, provider=prefs.provider, subject=rep.subject,
                          html=rep.html, text=rep.text, report_id=rep.id, cycle_id=ctx.cycle.id)
    out = {"status": d.status, "provider": d.provider, "error": d.error}
    if d.status != "sent":
        out["_degraded"] = True
        ctx.degraded.append(f"Daily email not sent ({d.status}): {d.error}")
        notify(s, "job_failed", "Daily report email not sent", d.error or d.status, severity="warning",
               dedupe_key=f"email:{ctx.cycle.cycle_date}")
    return out


STEPS: list[tuple[int, str, Callable[[Ctx], dict[str, Any] | None], bool, int]] = [
    (1, "collect_market_data", step_market_data, True, 2),
    (2, "collect_company_news", step_company_news, False, 2),
    (3, "collect_economic_political_news", step_official_news, False, 2),
    (4, "check_data_quality", step_quality, True, 1),
    (5, "deduplicate_news", step_dedupe, True, 1),
    (6, "classify_developments", step_classify, False, 1),
    (7, "identify_affected_securities", step_affected, True, 1),
    (8, "analyse_etf_holdings", step_etf_holdings, True, 1),
    (9, "quantitative_screening", step_screening, True, 1),
    (10, "shortlist_candidates", step_shortlist, True, 1),
    (11, "ai_deep_analysis", step_ai_analysis, False, 1),
    (12, "challenge_theses", step_challenge, False, 1),
    (13, "portfolio_fit", step_portfolio_fit, True, 1),
    (14, "rank_and_recommend", step_recommend, True, 1),
    (15, "update_watchlists", step_watchlists, True, 1),
    (16, "update_paper_trading", step_paper, True, 1),
    (17, "save_results", step_save, True, 1),
    (18, "generate_report", step_report, True, 1),
    (19, "send_email", step_email, False, 1),
]


def run_cycle(session: Session, *, triggered_by: str = "manual", now: datetime | None = None,
              cycle_date: date | None = None, force: bool = False, router: ModelRouter | None = None) -> ResearchCycle:
    now = now or datetime.now(UTC)
    if cycle_date is None:
        sched = get_pref(session, "research_schedule")
        cycle_date, _ = locking.latest_occurrence(now, sched.time_local, sched.timezone)
    cycle = locking.acquire(session, cycle_date, triggered_by, now, force=force)
    if router is not None:
        router.cycle_id = cycle.id
    ctx = Ctx(session=session, cycle=cycle, now=now, router=router)
    try:
        for no, name, fn, required, retries in STEPS:
            _run_step(ctx, no, name, fn, required, retries)
        if ctx.results.get("ai_paused"):
            ctx.degraded.append(f"AI analysis paused: {ctx.results['ai_paused']}")
        _complete(ctx, "succeeded_degraded" if ctx.degraded else "succeeded")
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        cycle.error = str(exc)[:4000]
        _complete(ctx, "failed")
    return cycle


def _complete(ctx: Ctx, status: str) -> None:
    s = ctx.session
    c = ctx.cycle
    from sqlalchemy import func

    from investiq.models import AiRequest

    cost = s.execute(select(func.coalesce(func.sum(AiRequest.cost_cad), 0.0)).where(AiRequest.cycle_id == c.id,
                                                                                   AiRequest.status != "reserved")).scalar_one()
    step = CycleStep(cycle_id=c.id, step_no=20, name="record_completion", required=True, status="ok",
                     detail={"status": status, "ai_cost_cad": float(cost), "degraded": ctx.degraded},
                     finished_at=datetime.now(UTC))
    s.add(step)
    c.status = status
    c.finished_at = datetime.now(UTC)
    c.ai_cost_cad = round(float(cost), 6)
    c.degraded_reasons = ctx.degraded[:30]
    c.summary = _jsonable({k: v for k, v in ctx.results.items() if k in ("company_news", "official_news", "tfsa_picks")})
    s.commit()
    if status == "failed":
        notify(s, "job_failed", f"Research cycle {c.cycle_date} failed", c.error or "unknown error", severity="error",
               dedupe_key=f"cycle-fail:{c.id}")
        rep = report.build_failure(s, c)
        prefs = get_pref(s, "email")
        if prefs.enabled:
            email_mod.deliver(s, kind="failure", to=prefs.to_address, provider=prefs.provider, subject=rep.subject,
                              html=rep.html, text=rep.text, report_id=rep.id, cycle_id=c.id)
    else:
        notify(s, "research_complete", f"Research for {c.cycle_date} complete" + (" (degraded)" if ctx.degraded else ""),
               "; ".join(ctx.degraded[:3]) or "All steps completed.", dedupe_key=f"cycle-done:{c.id}")
    s.commit()
