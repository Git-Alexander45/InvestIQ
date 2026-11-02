"""Prediction tracking, strategy versions, backtests and (owner-only) promotion."""

from __future__ import annotations

import threading
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from investiq.api.deps import db, not_found, row
from investiq.db.session import get_session
from investiq.learning import backtest, predictions, strategies
from investiq.models import BacktestRun, Prediction, PredictionEvaluation, StrategyPromotion, StrategyVersion

router = APIRouter(tags=["learning"])
_bt: dict[str, Any] = {"thread": None, "result": None}


@router.get("/predictions/summary")
def summary(s: Session = Depends(db)) -> dict[str, Any]:
    return predictions.summary(s)


@router.get("/predictions")
def prediction_list(instrument_id: int | None = None, limit: int = Query(200, le=5000), s: Session = Depends(db)
                    ) -> list[dict[str, Any]]:
    q = select(Prediction).order_by(Prediction.id.desc()).limit(limit)
    if instrument_id:
        q = q.where(Prediction.instrument_id == instrument_id)
    out = []
    for p in s.execute(q).scalars():
        evs = s.execute(select(PredictionEvaluation).where(PredictionEvaluation.prediction_id == p.id)
                        .order_by(PredictionEvaluation.checkpoint_days)).scalars()
        out.append({**row(p), "evaluations": [row(e) for e in evs]})
    return out


@router.get("/strategies")
def strategy_list(s: Session = Depends(db)) -> dict[str, Any]:
    prod = strategies.production(s)
    return {"production_id": prod.id, "frozen_id": strategies.frozen(s).id,
            "versions": [row(v) for v in s.execute(select(StrategyVersion).order_by(StrategyVersion.id)).scalars()],
            "promotions": [row(p) for p in s.execute(select(StrategyPromotion).order_by(StrategyPromotion.id)).scalars()]}


class ExperimentalIn(BaseModel):
    config: dict[str, Any]
    notes: str = Field(min_length=3, max_length=2000)


@router.post("/strategies/experimental")
def create_experimental(body: ExperimentalIn, s: Session = Depends(db)) -> dict[str, Any]:
    try:
        return row(strategies.create_experimental(s, body.config, body.notes, actor="owner"))
    except strategies.StrategyError as exc:
        raise HTTPException(422, str(exc)) from exc


class BacktestIn(BaseModel):
    strategy_version_id: int
    start: date
    end: date
    split: date
    rebalance_days: int = Field(30, ge=5, le=365)
    top_n: int = Field(10, ge=1, le=50)


@router.post("/backtests", status_code=202)
def start_backtest(body: BacktestIn, s: Session = Depends(db)) -> dict[str, Any]:
    if not body.start < body.split < body.end:
        raise HTTPException(422, "require start < split < end")
    if s.get(StrategyVersion, body.strategy_version_id) is None:
        raise not_found("strategy version")
    t = _bt["thread"]
    if t is not None and t.is_alive():
        raise HTTPException(409, "a backtest is already running")

    def work() -> None:
        session = get_session()
        try:
            sv = session.get(StrategyVersion, body.strategy_version_id)
            run = backtest.run(session, sv, strategies.frozen(session), body.start, body.end, body.split,
                               rebalance_days=body.rebalance_days, top_n=body.top_n)
            session.commit()
            _bt["result"] = {"run_id": run.id, "passed_validation": run.passed_validation}
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            _bt["result"] = {"error": f"{type(exc).__name__}: {exc}"[:300]}
        finally:
            session.close()

    _bt["result"] = None
    _bt["thread"] = threading.Thread(target=work, name="investiq-backtest", daemon=True)
    _bt["thread"].start()
    return {"started": True}


@router.get("/backtests")
def backtests(s: Session = Depends(db)) -> dict[str, Any]:
    t = _bt["thread"]
    runs = s.execute(select(BacktestRun).order_by(BacktestRun.id.desc()).limit(100)).scalars()
    return {"running": bool(t and t.is_alive()), "last_result": _bt["result"], "runs": [row(r) for r in runs]}


class PromoteIn(BaseModel):
    backtest_run_id: int
    reason: str = Field(min_length=10, max_length=2000)
    confirm: bool = Field(description="must be true: promotion changes production recommendations")


@router.post("/strategies/{strategy_version_id}/promote")
def promote(strategy_version_id: int, body: PromoteIn, s: Session = Depends(db)) -> dict[str, Any]:
    if not body.confirm:
        raise HTTPException(422, "Set confirm=true to promote. This changes which strategy production research uses.")
    try:
        return row(strategies.promote(s, strategy_version_id, body.backtest_run_id, body.reason, actor="owner"))
    except strategies.StrategyError as exc:
        raise HTTPException(422, str(exc)) from exc
