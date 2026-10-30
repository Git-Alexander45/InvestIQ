"""Research cycles, strategy versions, scores, analyses, recommendations and predictions."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, Date, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from investiq.db.base import Base, utcnow


class StrategyVersion(Base):
    """Scoring weights + parameters. Never edited: every change is a new version."""

    __tablename__ = "strategy_versions"
    __append_only__ = True
    __table_args__ = (UniqueConstraint("name", "version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64))  # e.g. "frozen-baseline", "experimental"
    version: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))  # frozen, experimental
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("strategy_versions.id"))
    config: Mapped[dict[str, Any]] = mapped_column(default=dict)  # weights per model + parameters
    config_hash: Mapped[str] = mapped_column(String(64))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class StrategyPromotion(Base):
    """Audit trail for which strategy version drives production recommendations."""

    __tablename__ = "strategy_promotions"
    __append_only__ = True

    id: Mapped[int] = mapped_column(primary_key=True)
    strategy_version_id: Mapped[int] = mapped_column(ForeignKey("strategy_versions.id"))
    backtest_run_id: Mapped[int | None] = mapped_column(ForeignKey("backtest_runs.id"))
    reason: Mapped[str] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(String(64), default="owner")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class ResearchCycle(Base):
    __tablename__ = "research_cycles"
    __append_only__ = True
    __mutable_columns__ = frozenset(
        {"status", "finished_at", "heartbeat_at", "error", "summary", "ai_cost_cad", "degraded_reasons",
         "strategy_version_id"}
    )
    __table_args__ = (UniqueConstraint("cycle_date", "kind", "attempt"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    cycle_date: Mapped[date] = mapped_column(Date, index=True)  # the research day (Eastern)
    kind: Mapped[str] = mapped_column(String(16), default="daily")
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(24), default="running")
    # running, succeeded, succeeded_degraded, failed, abandoned
    triggered_by: Mapped[str] = mapped_column(String(32))  # scheduler, task_scheduler, manual, catch_up
    strategy_version_id: Mapped[int | None] = mapped_column(ForeignKey("strategy_versions.id"))
    started_at: Mapped[datetime] = mapped_column(default=utcnow)
    heartbeat_at: Mapped[datetime] = mapped_column(default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column()
    lock_owner: Mapped[str] = mapped_column(String(128))
    error: Mapped[str | None] = mapped_column(Text)
    degraded_reasons: Mapped[list[Any]] = mapped_column(default=list)
    summary: Mapped[dict[str, Any]] = mapped_column(default=dict)
    ai_cost_cad: Mapped[float] = mapped_column(Float, default=0.0)


class CycleStep(Base):
    __tablename__ = "cycle_steps"
    __append_only__ = True
    __mutable_columns__ = frozenset({"status", "finished_at", "detail", "error", "attempts"})

    id: Mapped[int] = mapped_column(primary_key=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("research_cycles.id"), index=True)
    step_no: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(64))
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(16), default="running")  # running, ok, skipped, degraded, failed
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    started_at: Mapped[datetime] = mapped_column(default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column()
    detail: Mapped[dict[str, Any]] = mapped_column(default=dict)
    error: Mapped[str | None] = mapped_column(Text)


class Score(Base):
    """A graded evaluation of one instrument under one strategy version. Never overwritten."""

    __tablename__ = "scores"
    __append_only__ = True

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    cycle_id: Mapped[int | None] = mapped_column(ForeignKey("research_cycles.id"), index=True)
    strategy_version_id: Mapped[int] = mapped_column(ForeignKey("strategy_versions.id"))
    model: Mapped[str] = mapped_column(String(32))  # equity, etf_equity, etf_fixed_income, commodity, cash
    overall: Mapped[float] = mapped_column(Float)
    grade: Mapped[str] = mapped_column(String(3))
    confidence: Mapped[float] = mapped_column(Float)
    coverage: Mapped[float] = mapped_column(Float)  # share of category weight backed by data
    category_scores: Mapped[dict[str, Any]] = mapped_column(default=dict)
    evidence: Mapped[list[Any]] = mapped_column(default=list)
    positives: Mapped[list[Any]] = mapped_column(default=list)
    negatives: Mapped[list[Any]] = mapped_column(default=list)
    risks: Mapped[list[Any]] = mapped_column(default=list)
    avoid_reasons: Mapped[list[Any]] = mapped_column(default=list)
    horizon: Mapped[str] = mapped_column(String(32), default="3-5 years")
    metrics: Mapped[dict[str, Any]] = mapped_column(default=dict)  # derived inputs (point in time)
    as_of: Mapped[datetime] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class GradeChange(Base):
    __tablename__ = "grade_changes"
    __append_only__ = True

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    strategy_version_id: Mapped[int] = mapped_column(ForeignKey("strategy_versions.id"))
    previous_score_id: Mapped[int] = mapped_column(ForeignKey("scores.id"))
    new_score_id: Mapped[int] = mapped_column(ForeignKey("scores.id"))
    old_grade: Mapped[str] = mapped_column(String(3))
    new_grade: Mapped[str] = mapped_column(String(3))
    old_overall: Mapped[float] = mapped_column(Float)
    new_overall: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(Text)
    category_deltas: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Analysis(Base):
    """An AI reasoning report (or a recorded skip), with citations into the evidence pack."""

    __tablename__ = "analyses"
    __append_only__ = True

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int | None] = mapped_column(ForeignKey("instruments.id"), index=True)
    cycle_id: Mapped[int | None] = mapped_column(ForeignKey("research_cycles.id"), index=True)
    role: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))  # ok, invalid, failed, budget_blocked
    evidence_pack: Mapped[dict[str, Any]] = mapped_column(default=dict)
    output: Mapped[dict[str, Any]] = mapped_column(default=dict)
    unsupported_claims: Mapped[list[Any]] = mapped_column(default=list)
    ai_request_id: Mapped[int | None] = mapped_column(ForeignKey("ai_requests.id"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Recommendation(Base):
    __tablename__ = "recommendations"
    __append_only__ = True

    id: Mapped[int] = mapped_column(primary_key=True)
    cycle_id: Mapped[int | None] = mapped_column(ForeignKey("research_cycles.id"), index=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    strategy_version_id: Mapped[int] = mapped_column(ForeignKey("strategy_versions.id"))
    score_id: Mapped[int] = mapped_column(ForeignKey("scores.id"))
    analysis_id: Mapped[int | None] = mapped_column(ForeignKey("analyses.id"))
    assessment: Mapped[str] = mapped_column(String(8))  # BUY, WATCH, HOLD, SELL, AVOID
    quant_assessment: Mapped[str] = mapped_column(String(8))  # what rules alone concluded
    source: Mapped[str] = mapped_column(String(16))  # quant_only, ai_reviewed
    primary_eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    rationale: Mapped[str] = mapped_column(Text)
    why_not_now: Mapped[str | None] = mapped_column(Text)
    thesis: Mapped[str | None] = mapped_column(Text)
    portfolio_fit: Mapped[dict[str, Any]] = mapped_column(default=dict)
    brokerage_status: Mapped[dict[str, Any]] = mapped_column(default=dict)
    price: Mapped[float | None] = mapped_column(Float)
    price_currency: Mapped[str | None] = mapped_column(String(3))
    price_as_of: Mapped[datetime | None] = mapped_column()
    price_source: Mapped[str | None] = mapped_column(String(32))
    horizon: Mapped[str] = mapped_column(String(32), default="3-5 years")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class LeaderboardEntry(Base):
    __tablename__ = "leaderboard_entries"
    __append_only__ = True

    id: Mapped[int] = mapped_column(primary_key=True)
    cycle_id: Mapped[int | None] = mapped_column(ForeignKey("research_cycles.id"), index=True)
    board: Mapped[str] = mapped_column(String(48), index=True)
    rank: Mapped[int] = mapped_column(Integer)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"))
    score_id: Mapped[int] = mapped_column(ForeignKey("scores.id"))
    board_score: Mapped[float] = mapped_column(Float)
    method: Mapped[str] = mapped_column(String(255))
    details: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Prediction(Base):
    """Every recommendation becomes a prediction so outcomes are tracked without selection."""

    __tablename__ = "predictions"
    __append_only__ = True

    id: Mapped[int] = mapped_column(primary_key=True)
    recommendation_id: Mapped[int] = mapped_column(ForeignKey("recommendations.id"), unique=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    strategy_version_id: Mapped[int] = mapped_column(ForeignKey("strategy_versions.id"))
    source: Mapped[str] = mapped_column(String(16))  # quant_only, ai_reviewed
    assessment: Mapped[str] = mapped_column(String(8))
    grade: Mapped[str] = mapped_column(String(3))
    overall: Mapped[float] = mapped_column(Float)
    thesis: Mapped[str | None] = mapped_column(Text)
    horizon_days: Mapped[int] = mapped_column(Integer, default=365)
    made_at: Mapped[datetime] = mapped_column()
    price_at: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(3))
    benchmark_instrument_id: Mapped[int | None] = mapped_column(ForeignKey("instruments.id"))
    benchmark_price_at: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class PredictionEvaluation(Base):
    __tablename__ = "prediction_evaluations"
    __append_only__ = True
    __table_args__ = (UniqueConstraint("prediction_id", "checkpoint_days"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    prediction_id: Mapped[int] = mapped_column(ForeignKey("predictions.id"), index=True)
    checkpoint_days: Mapped[int] = mapped_column(Integer)
    evaluated_at: Mapped[datetime] = mapped_column(default=utcnow)
    price: Mapped[float] = mapped_column(Float)
    price_date: Mapped[date] = mapped_column(Date)
    price_return_pct: Mapped[float] = mapped_column(Float)
    dividends_per_share: Mapped[float] = mapped_column(Float, default=0.0)
    total_return_pct: Mapped[float] = mapped_column(Float)
    benchmark_return_pct: Mapped[float | None] = mapped_column(Float)
    excess_return_pct: Mapped[float | None] = mapped_column(Float)
    success: Mapped[bool | None] = mapped_column(Boolean)
    thesis_valid: Mapped[bool | None] = mapped_column(Boolean)  # None = not assessed
    notes: Mapped[str | None] = mapped_column(Text)


class BacktestRun(Base):
    __tablename__ = "backtest_runs"
    __append_only__ = True

    id: Mapped[int] = mapped_column(primary_key=True)
    strategy_version_id: Mapped[int] = mapped_column(ForeignKey("strategy_versions.id"))
    baseline_strategy_version_id: Mapped[int | None] = mapped_column(ForeignKey("strategy_versions.id"))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    split_date: Mapped[date] = mapped_column(Date)  # in-sample before, out-of-sample after
    parameters: Mapped[dict[str, Any]] = mapped_column(default=dict)
    in_sample: Mapped[dict[str, Any]] = mapped_column(default=dict)
    out_of_sample: Mapped[dict[str, Any]] = mapped_column(default=dict)
    variants_tested: Mapped[int] = mapped_column(Integer, default=1)
    passed_validation: Mapped[bool] = mapped_column(Boolean, default=False)
    validation_notes: Mapped[list[Any]] = mapped_column(default=list)
    data_sources: Mapped[list[Any]] = mapped_column(default=list)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
