"""Every recommendation becomes a tracked prediction, evaluated at fixed checkpoints.

Checkpoints (7/30/90/180/365 days) are evaluation points, not sell signals. Returns include
dividends (ex-date within the window) and are compared with a benchmark over the same window.
All predictions are evaluated, so results cannot be cherry-picked.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from investiq.data import repository as repo
from investiq.models import Prediction, PredictionEvaluation, Recommendation, Score

CHECKPOINTS = (7, 30, 90, 180, 365)
HORIZON_DAYS = {"3-5 years": 365 * 3, "1-3 years": 365}
MIN_SAMPLE = 30


def create(session: Session, rec: Recommendation, score: Score, benchmark_id: int | None) -> Prediction | None:
    if rec.price is None or rec.price_as_of is None:
        return None
    bench_px = None
    if benchmark_id:
        b = repo.last_bar(session, benchmark_id, rec.price_as_of)
        bench_px = b.close if b else None
    p = Prediction(recommendation_id=rec.id, instrument_id=rec.instrument_id, strategy_version_id=rec.strategy_version_id,
                   source=rec.source, assessment=rec.assessment, grade=score.grade, overall=score.overall, thesis=rec.thesis,
                   horizon_days=HORIZON_DAYS.get(rec.horizon, 365 * 3), made_at=rec.price_as_of, price_at=rec.price,
                   currency=rec.price_currency or "CAD", benchmark_instrument_id=benchmark_id if bench_px else None,
                   benchmark_price_at=bench_px)
    session.add(p)
    return p


def _total_return(session: Session, instrument_id: int, start: datetime, start_px: float, target: datetime,
                  now: datetime) -> tuple[float, float, Any] | None:
    bar = repo.bar_on_or_after(session, instrument_id, target, max_days=10)
    if bar is None or bar.ts > now:
        return None
    divs = sum(d.amount for d in repo.dividends_between(session, instrument_id, start.date(), bar.ts.date()))
    return (bar.close + divs) / start_px - 1, divs, bar


def evaluate_due(session: Session, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    done = {(e.prediction_id, e.checkpoint_days) for e in session.execute(select(PredictionEvaluation)).scalars()}
    n = 0
    for p in session.execute(select(Prediction)).scalars():
        for days in CHECKPOINTS:
            if (p.id, days) in done:
                continue
            target = p.made_at + timedelta(days=days)
            if target > now:
                break
            res = _total_return(session, p.instrument_id, p.made_at, p.price_at, target, now)
            if res is None:
                continue
            total, divs, bar = res
            bench = None
            if p.benchmark_instrument_id and p.benchmark_price_at:
                b = _total_return(session, p.benchmark_instrument_id, p.made_at, p.benchmark_price_at, target, now)
                bench = b[0] if b else None
            excess = None if bench is None else total - bench
            success = None
            if excess is not None:
                if p.assessment in ("BUY", "HOLD"):
                    success = excess > 0
                elif p.assessment in ("SELL", "AVOID"):
                    success = excess < 0
            session.add(PredictionEvaluation(
                prediction_id=p.id, checkpoint_days=days, price=bar.close, price_date=bar.ts.date(),
                price_return_pct=round((bar.close / p.price_at - 1) * 100, 4), dividends_per_share=divs,
                total_return_pct=round(total * 100, 4), benchmark_return_pct=None if bench is None else round(bench * 100, 4),
                excess_return_pct=None if excess is None else round(excess * 100, 4), success=success,
                notes="WATCH is tracked, not scored" if p.assessment == "WATCH" else None))
            n += 1
    session.flush()
    return n


def summary(session: Session) -> dict[str, Any]:
    """Hit rates and average excess return by assessment, by source (quant vs AI-reviewed) and by
    strategy version, per checkpoint. Small samples are flagged explicitly."""
    rows = session.execute(select(Prediction, PredictionEvaluation)
                           .join(PredictionEvaluation, PredictionEvaluation.prediction_id == Prediction.id)).all()
    groups: dict[tuple[str, str, int], list[PredictionEvaluation]] = defaultdict(list)
    for p, e in rows:
        groups[("assessment", p.assessment, e.checkpoint_days)].append(e)
        groups[("source", p.source, e.checkpoint_days)].append(e)
        groups[("strategy", str(p.strategy_version_id), e.checkpoint_days)].append(e)
    out: dict[str, Any] = defaultdict(dict)
    for (dim, key, cp), evs in groups.items():
        scored = [e for e in evs if e.success is not None]
        ex = [e.excess_return_pct for e in evs if e.excess_return_pct is not None]
        out[dim].setdefault(key, {})[str(cp)] = {
            "n": len(evs), "scored": len(scored),
            "hit_rate_pct": round(sum(e.success for e in scored) / len(scored) * 100, 2) if scored else None,
            "avg_excess_return_pct": round(sum(ex) / len(ex), 4) if ex else None,
            "small_sample": len(evs) < MIN_SAMPLE,
        }
    total = session.execute(select(Prediction.id)).all()
    ai_vs_quant = _ai_vs_quant(out.get("source", {}))
    return {"total_predictions": len(total), "evaluations": len(rows), **out, "ai_vs_quant": ai_vs_quant,
            "note": "Checkpoints are evaluation points, not sell signals. Results under "
                    f"{MIN_SAMPLE} observations are not statistically meaningful."}


def _ai_vs_quant(by_source: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for cp in map(str, CHECKPOINTS):
        ai = by_source.get("ai_reviewed", {}).get(cp)
        q = by_source.get("quant_only", {}).get(cp)
        if ai and q and ai["avg_excess_return_pct"] is not None and q["avg_excess_return_pct"] is not None:
            out[cp] = {"ai_minus_quant_excess_pct": round(ai["avg_excess_return_pct"] - q["avg_excess_return_pct"], 4),
                       "conclusive": not (ai["small_sample"] or q["small_sample"])}
    return out


def score_for(session: Session, score_id: int) -> Score | None:
    return session.get(Score, score_id)
