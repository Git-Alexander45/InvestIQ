"""Strategy versions: a frozen control that never changes, and experimental versions.

Production recommendations follow the latest *promoted* version (the frozen baseline until the
owner promotes something). Promotion is never automatic and requires a backtest that passed
out-of-sample validation.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from investiq.models import BacktestRun, StrategyPromotion, StrategyVersion
from investiq.scoring.strategy_config import config_hash, validate_config
from investiq.services.audit import audit
from investiq.services.bootstrap import EXPERIMENTAL_NAME, FROZEN_NAME, ensure_strategies


class StrategyError(ValueError):
    pass


def frozen(session: Session) -> StrategyVersion:
    return ensure_strategies(session)[FROZEN_NAME]


def latest_experimental(session: Session) -> StrategyVersion:
    return ensure_strategies(session)[EXPERIMENTAL_NAME]


def production(session: Session) -> StrategyVersion:
    promo = session.execute(select(StrategyPromotion).order_by(StrategyPromotion.id.desc()).limit(1)).scalar_one_or_none()
    if promo is not None:
        return session.get(StrategyVersion, promo.strategy_version_id)
    return frozen(session)


def create_experimental(session: Session, config: dict[str, Any], notes: str, actor: str = "owner") -> StrategyVersion:
    problems = validate_config(config)
    if problems:
        raise StrategyError("; ".join(problems))
    parent = latest_experimental(session)
    if config_hash(config) == parent.config_hash:
        raise StrategyError("configuration is identical to the current experimental version")
    version = (session.execute(select(func.max(StrategyVersion.version)).where(StrategyVersion.name == EXPERIMENTAL_NAME))
               .scalar_one() or 0) + 1
    sv = StrategyVersion(name=EXPERIMENTAL_NAME, version=version, kind="experimental", parent_id=parent.id, config=config,
                         config_hash=config_hash(config), notes=notes)
    session.add(sv)
    session.flush()
    audit(session, "strategy.version_created", actor=actor, entity_type="strategy_version", entity_id=sv.id,
          version=version, notes=notes)
    return sv


def promote(session: Session, strategy_version_id: int, backtest_run_id: int, reason: str, actor: str = "owner"
            ) -> StrategyPromotion:
    if actor != "owner":
        raise PermissionError("Only the owner can change the production strategy")
    sv = session.get(StrategyVersion, strategy_version_id)
    run = session.get(BacktestRun, backtest_run_id)
    if sv is None or run is None:
        raise StrategyError("unknown strategy version or backtest run")
    if run.strategy_version_id != sv.id:
        raise StrategyError("backtest run does not belong to this strategy version")
    if not run.passed_validation:
        raise StrategyError("backtest did not pass out-of-sample validation: " + "; ".join(run.validation_notes))
    promo = StrategyPromotion(strategy_version_id=sv.id, backtest_run_id=run.id, reason=reason, actor=actor)
    session.add(promo)
    audit(session, "strategy.promoted", actor=actor, entity_type="strategy_version", entity_id=sv.id,
          backtest_run_id=run.id, reason=reason)
    return promo
