"""Research cycles, leaderboards, recommendations, reports, TFSA view and diversification."""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from investiq.api.deps import db, not_found, row
from investiq.data import repository as repo
from investiq.db.session import get_session
from investiq.diversification.engine import Position, what_if
from investiq.models import (
    CycleStep,
    Instrument,
    LeaderboardEntry,
    PriceBar,
    Recommendation,
    Report,
    ResearchCycle,
    Score,
    TfsaProfile,
)
from investiq.reports.pricing import price_block
from investiq.research import locking
from investiq.research.report import _markets
from investiq.services import portfolio_view
from investiq.services.audit import audit
from investiq.services.preferences import get_pref

router = APIRouter(tags=["research"])
_manual_run: dict[str, Any] = {"thread": None, "result": None}


@router.get("/cycles")
def cycles(limit: int = Query(30, le=365), s: Session = Depends(db)) -> list[dict[str, Any]]:
    rows = s.execute(select(ResearchCycle).order_by(ResearchCycle.id.desc()).limit(limit)).scalars()
    return [row(c) for c in rows]


@router.get("/cycles/{cycle_id}")
def cycle_detail(cycle_id: int, s: Session = Depends(db)) -> dict[str, Any]:
    c = s.get(ResearchCycle, cycle_id)
    if c is None:
        raise not_found("cycle")
    steps = s.execute(select(CycleStep).where(CycleStep.cycle_id == c.id).order_by(CycleStep.step_no)).scalars()
    return {"cycle": row(c), "steps": [row(x) for x in steps]}


class RunRequest(BaseModel):
    force: bool = False


@router.post("/cycles/run", status_code=202)
def run_now(body: RunRequest, s: Session = Depends(db)) -> dict[str, Any]:
    """Start a research cycle in the background. Duplicate runs are refused by the cycle lock."""
    t = _manual_run["thread"]
    if t is not None and t.is_alive():
        raise HTTPException(409, "a manually started cycle is already running")
    audit(s, "cycle.manual_run", actor="owner", force=body.force)

    def work() -> None:
        from investiq.research.cycle import run_cycle

        session = get_session()
        try:
            c = run_cycle(session, triggered_by="manual", force=body.force)
            _manual_run["result"] = {"cycle_id": c.id, "status": c.status}
        except locking.CycleNotDue as exc:
            _manual_run["result"] = {"status": "not_run", "reason": str(exc)}
        except Exception as exc:  # noqa: BLE001 - surfaced through the status endpoint
            _manual_run["result"] = {"status": "error", "reason": type(exc).__name__}
        finally:
            session.close()

    _manual_run["result"] = None
    _manual_run["thread"] = threading.Thread(target=work, name="investiq-manual-cycle", daemon=True)
    _manual_run["thread"].start()
    return {"started": True, "note": "Progress appears under Research cycles; a completed day is not re-run "
                                     "unless 'force' is set."}


@router.get("/cycles-manual-status")
def manual_status() -> dict[str, Any]:
    t = _manual_run["thread"]
    return {"running": bool(t and t.is_alive()), "result": _manual_run["result"]}


def _latest_cycle(s: Session) -> ResearchCycle | None:
    return s.execute(select(ResearchCycle).where(ResearchCycle.status.in_(locking.DONE))
                     .order_by(ResearchCycle.id.desc()).limit(1)).scalar_one_or_none()


@router.get("/leaderboards")
def leaderboards(cycle_id: int | None = None, s: Session = Depends(db)) -> dict[str, Any]:
    c = s.get(ResearchCycle, cycle_id) if cycle_id else _latest_cycle(s)
    if c is None:
        return {"cycle": None, "boards": {}}
    fx = repo.fx_table(s, c.cycle_date)
    boards: dict[str, list] = {}
    for e in s.execute(select(LeaderboardEntry).where(LeaderboardEntry.cycle_id == c.id)
                       .order_by(LeaderboardEntry.board, LeaderboardEntry.rank)).scalars():
        inst = s.get(Instrument, e.instrument_id)
        rec = s.execute(select(Recommendation).where(Recommendation.cycle_id == c.id,
                                                     Recommendation.instrument_id == e.instrument_id)).scalar_one_or_none()
        sc = s.get(Score, e.score_id)
        boards.setdefault(e.board, []).append({
            "rank": e.rank, "instrument_id": inst.id, "symbol": inst.symbol, "exchange": inst.exchange,
            "name": inst.name, "asset_class": inst.asset_class, "security_type": inst.security_type,
            "board_score": e.board_score, "method": e.method, "overall": sc.overall, "grade": sc.grade,
            "confidence": sc.confidence, "coverage": sc.coverage,
            "assessment": rec.assessment if rec else None, "why_not_now": rec.why_not_now if rec else None,
            "brokerage": rec.brokerage_status if rec else None,
            "price": None if rec is None else price_block(
                rec.price, rec.price_currency, rec.price_as_of.date().isoformat() if rec.price_as_of else None,
                rec.price_source, _bar_status(s, rec), fx),
        })
    return {"cycle": row(c), "boards": boards}


def _bar_status(s: Session, rec: Recommendation) -> str | None:
    """Live/delayed/end-of-day status of the exact bar the recommendation was priced from."""
    if rec.price_as_of is None or rec.price_source is None:
        return None
    bar = s.get(PriceBar, (rec.instrument_id, "1d", rec.price_as_of, rec.price_source))
    return bar.data_status if bar else None


@router.get("/recommendations")
def recommendations(assessment: str | None = Query(None, pattern="^(BUY|WATCH|HOLD|SELL|AVOID)$"),
                    cycle_id: int | None = None, s: Session = Depends(db)) -> dict[str, Any]:
    c = s.get(ResearchCycle, cycle_id) if cycle_id else _latest_cycle(s)
    if c is None:
        return {"cycle": None, "items": []}
    q = select(Recommendation, Score, Instrument).join(Score, Score.id == Recommendation.score_id).join(
        Instrument, Instrument.id == Recommendation.instrument_id).where(Recommendation.cycle_id == c.id)
    if assessment:
        q = q.where(Recommendation.assessment == assessment)
    items = [{"recommendation": row(r), "score": {"overall": sc.overall, "grade": sc.grade, "confidence": sc.confidence,
                                                   "coverage": sc.coverage, "category_scores": sc.category_scores,
                                                   "positives": sc.positives, "negatives": sc.negatives,
                                                   "risks": sc.risks},
              "instrument": row(i, {"provider_symbols"})}
             for r, sc, i in s.execute(q.order_by(Score.overall.desc())).all()]
    return {"cycle": row(c), "items": items}


@router.get("/reports")
def reports(limit: int = Query(60, le=1000), s: Session = Depends(db)) -> list[dict[str, Any]]:
    rows = s.execute(select(Report).order_by(Report.id.desc()).limit(limit)).scalars()
    return [{"id": r.id, "cycle_id": r.cycle_id, "kind": r.kind, "subject": r.subject,
             "created_at": r.created_at.isoformat()} for r in rows]


@router.get("/reports/{report_id}")
def report(report_id: int, s: Session = Depends(db)) -> dict[str, Any]:
    r = s.get(Report, report_id)
    if r is None:
        raise not_found("report")
    return row(r, {"html"})


@router.get("/reports/{report_id}/html", response_class=HTMLResponse)
def report_html(report_id: int, s: Session = Depends(db)) -> HTMLResponse:
    r = s.get(Report, report_id)
    if r is None:
        raise not_found("report")
    # Shown inside a sandboxed iframe; the CSP blocks scripts even if content were ever injected.
    return HTMLResponse(r.html, headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; "
                                                                    "img-src data:; sandbox"})


@router.get("/market/overview")
def market_overview(s: Session = Depends(db)) -> dict[str, Any]:
    now = datetime.now(UTC)
    fx = repo.fx_table(s, now.date())
    try:
        q = fx.get("USD", "CAD")
        fx_d = {"pair": "USD/CAD", "rate": q.rate, "as_of": q.as_of.isoformat(), "source": q.source,
                "note": "Daily reference rate, not a live trading rate."}
    except Exception:  # noqa: BLE001
        fx_d = None
    return {"markets": _markets(s, now), "usd_cad": fx_d}


@router.get("/tfsa")
def tfsa_view(s: Session = Depends(db)) -> dict[str, Any]:
    c = _latest_cycle(s)
    prof = s.execute(select(TfsaProfile).order_by(TfsaProfile.id.desc()).limit(1)).scalar_one_or_none()
    return {"profile": row(prof) if prof else None, "picks": (c.summary or {}).get("tfsa_picks") if c else None,
            "cycle": row(c) if c else None,
            "rules": ["TFSA eligibility depends on the security being listed on a designated stock exchange.",
                      "US dividends in a TFSA lose 15% withholding tax that cannot be recovered.",
                      "Over-contributions are taxed at 1% per month; InvestIQ only tracks room you enter.",
                      "Frequent trading in a TFSA can be treated as carrying on a business."]}


class TfsaIn(BaseModel):
    contribution_room_cad: float | None = Field(None, ge=0, le=10_000_000)
    room_as_of: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    source_note: str | None = Field(None, max_length=500)


@router.post("/tfsa/profile")
def tfsa_profile(body: TfsaIn, s: Session = Depends(db)) -> dict[str, Any]:
    from datetime import date

    p = TfsaProfile(contribution_room_cad=body.contribution_room_cad,
                    room_as_of=date.fromisoformat(body.room_as_of) if body.room_as_of else None,
                    source_note=body.source_note)
    s.add(p)
    s.flush()
    audit(s, "tfsa.profile_entered", actor="owner", entity_type="tfsa_profile", entity_id=p.id)
    return row(p)


@router.get("/diversification")
def diversification(s: Session = Depends(db)) -> dict[str, Any]:
    return portfolio_view.owner_report(s, datetime.now(UTC))


class WhatIfIn(BaseModel):
    instrument_id: int
    amount_cad: float = Field(gt=0, le=100_000_000)
    cash_cad: float = Field(0.0, ge=0, le=100_000_000)


@router.post("/diversification/what-if")
def diversification_what_if(body: WhatIfIn, s: Session = Depends(db)) -> dict[str, Any]:
    now = datetime.now(UTC)
    inst = s.get(Instrument, body.instrument_id)
    if inst is None:
        raise not_found("instrument")
    holdings = portfolio_view.owner_holdings(s)
    positions, problems = portfolio_view.build_positions(s, [(s.get(Instrument, h.instrument_id), h.quantity)
                                                             for h in holdings], now)
    cand, cproblems = portfolio_view.build_positions(s, [(inst, 1.0)], now)
    if not cand:
        raise HTTPException(422, f"cannot evaluate {inst.symbol}: {'; '.join(cproblems)}")
    total = sum(p.value_cad for p in positions) + body.cash_cad + body.amount_cad
    weight = body.amount_cad / total * 100
    limits = get_pref(s, "risk_limits").model_dump()
    fit, before, after = what_if(positions, body.cash_cad + body.amount_cad, Position(**cand[0].__dict__), weight, limits)
    return {"instrument": inst.symbol, "weight_pct": round(weight, 3), "acceptable": fit.acceptable,
            "new_warnings": fit.flags, "detail": fit.detail, "before": before.as_dict(), "after": after.as_dict(),
            "data_problems": problems,
            "note": "Hypothetical only. Nothing is bought; your holdings are unchanged."}


@router.get("/screener")
def screener(kind: str = Query("all", pattern="^(all|stocks|funds)$"), s: Session = Depends(db)) -> dict[str, Any]:
    """Every instrument scored in the latest completed cycle, with the inputs a screener filters on."""
    c = _latest_cycle(s)
    if c is None:
        return {"cycle": None, "rows": []}
    now = datetime.now(UTC)
    fx = repo.fx_table(s, now.date())
    q = (select(Score, Recommendation, Instrument).join(Recommendation, Recommendation.score_id == Score.id)
         .join(Instrument, Instrument.id == Score.instrument_id).where(Score.cycle_id == c.id))
    rows = []
    for sc, rec, inst in s.execute(q).all():
        fund = inst.security_type in ("etf", "mutual_fund")
        if (kind == "stocks" and fund) or (kind == "funds" and not fund):
            continue
        bars = repo.daily_bars(s, inst.id, now, lookback_days=10)
        day = (bars[-1].close / bars[-2].close - 1) * 100 if len(bars) >= 2 else None
        price = (sc.metrics or {}).get("price", {})
        fnd = (sc.metrics or {}).get("fundamentals", {})
        etf = (sc.metrics or {}).get("etf", {})
        rows.append({
            "instrument_id": inst.id, "symbol": inst.symbol, "exchange": inst.exchange, "name": inst.name,
            "asset_class": inst.asset_class, "security_type": inst.security_type, "sector": inst.sector,
            "country": inst.country, "region": inst.region, "currency": inst.currency, "themes": inst.themes,
            "overall": sc.overall, "grade": sc.grade, "confidence": sc.confidence, "coverage": sc.coverage,
            "model": sc.model, "assessment": rec.assessment, "primary_eligible": rec.primary_eligible,
            "categories": {k: v.get("score") for k, v in (sc.category_scores or {}).items()},
            "change_1d_pct": None if day is None else round(day, 3),
            "return_1y_pct": price.get("return_1y_pct"), "return_5y_ann_pct": price.get("return_5y_ann_pct"),
            "volatility_1y_pct": price.get("volatility_1y_pct"), "max_drawdown_3y_pct": price.get("max_drawdown_3y_pct"),
            "pe": fnd.get("pe"), "dividend_yield_pct": fnd.get("dividend_yield_pct"),
            "revenue_growth_1y_pct": fnd.get("revenue_growth_1y_pct"), "mer_pct": inst.mer_pct or fnd.get("expense_ratio_pct"),
            "holdings_count": etf.get("holdings_count"),
            "price": None if not bars else price_block(bars[-1].close, bars[-1].currency, bars[-1].ts.date().isoformat(),
                                                       bars[-1].source, bars[-1].data_status, fx),
        })
    rows.sort(key=lambda r: -r["overall"])
    return {"cycle": row(c), "rows": rows}
