"""Owner preferences: validated, versioned (each change inserts a new row), with defaults.

Defaults reflect the master specification. Changing a preference never edits history.
"""

from __future__ import annotations

from datetime import time
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from investiq.models import PreferenceVersion
from investiq.services.audit import audit


class ResearchSchedule(BaseModel):
    time_local: str = "18:00"
    timezone: str = "America/Toronto"
    enabled: bool = True
    catch_up_if_missed: bool = True

    @field_validator("time_local")
    @classmethod
    def _valid_time(cls, v: str) -> str:
        time.fromisoformat(v)
        return v

    @field_validator("timezone")
    @classmethod
    def _valid_tz(cls, v: str) -> str:
        from zoneinfo import ZoneInfo

        ZoneInfo(v)
        return v


class EmailPrefs(BaseModel):
    enabled: bool = True
    to_address: EmailStr | None = None
    provider: Literal["smtp", "resend", "outbox"] = "outbox"


class NotificationPrefs(BaseModel):
    desktop_enabled: bool = True
    kinds: dict[str, bool] = Field(default_factory=lambda: {
        "important_news": True,
        "watchlist": True,
        "grade_change": True,
        "new_opportunity": True,
        "portfolio_risk": True,
        "research_complete": True,
        "paper_milestone": True,
        "job_failed": True,
        "price_alert": True,
    })
    grade_change_min_steps: int = Field(1, ge=1, le=5)


class AiBudget(BaseModel):
    monthly_limit_cad: float = Field(5.0, ge=0, le=10_000)
    premium_reserve_pct: float = Field(0.0, ge=0, le=100)  # stop premium calls when this % remains
    usd_cad_fallback_rate: float = Field(1.45, gt=0)  # conservative, only if no BoC rate is stored


class AiModelRoute(BaseModel):
    provider: Literal["anthropic", "disabled"] = "anthropic"
    model: str
    effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    max_output_tokens: int = Field(4000, ge=256, le=64000)


class AiModels(BaseModel):
    low_cost: AiModelRoute = AiModelRoute(model="claude-haiku-5-5", effort="low", max_output_tokens=2000)
    premium: AiModelRoute = AiModelRoute(model="claude-opus-5-5", effort="medium", max_output_tokens=6000)
    reviewer: AiModelRoute = AiModelRoute(model="claude-sonnet-5-5", effort="medium", max_output_tokens=3000)
    reviewer_enabled: bool = True
    max_premium_candidates_per_cycle: int = Field(4, ge=0, le=50)
    max_news_items_for_ai: int = Field(30, ge=0, le=500)


class RiskLimits(BaseModel):
    max_stock_position_pct: float = Field(8.0, gt=0, le=100)
    target_stock_position_pct: float = Field(5.0, gt=0, le=100)
    max_speculative_position_pct: float = Field(3.0, gt=0, le=100)
    max_etf_position_pct: float = Field(30.0, gt=0, le=100)
    sector_flag_pct: float = Field(25.0, gt=0, le=100)
    sector_max_pct: float = Field(30.0, gt=0, le=100)
    country_flag_pct: float = Field(70.0, gt=0, le=100)
    single_company_lookthrough_flag_pct: float = Field(10.0, gt=0, le=100)
    etf_overlap_flag_pct: float = Field(50.0, gt=0, le=100)
    min_cash_pct: float = Field(0.0, ge=0, le=100)


class Universe(BaseModel):
    include_reits: bool = False
    include_leveraged_inverse: bool = False
    asset_classes: dict[str, bool] = Field(default_factory=lambda: {
        "equity": True, "bond": True, "commodity": True,
        "precious_metal": True, "cash_equivalent": True, "multi_asset": True,
    })
    regions: dict[str, bool] = Field(default_factory=lambda: {
        "canada": True, "united_states": True, "europe": True, "asia": True,
        "emerging_markets": True, "global": True,
    })
    extra_symbols: list[str] = Field(default_factory=list)


class BrokeragePrefs(BaseModel):
    require_both: bool = True
    reverify_after_days: int = Field(180, ge=1, le=3650)


class DisplayPrefs(BaseModel):
    primary_currency: Literal["CAD", "USD"] = "CAD"
    secondary_currency: Literal["CAD", "USD"] = "USD"


class MarketData(BaseModel):
    price_provider: Literal["fmp", "twelvedata", "synthetic", "none"] = "fmp"
    fundamentals_provider: Literal["fmp", "sec_edgar", "synthetic", "none"] = "fmp"
    etf_holdings_provider: Literal["fmp", "synthetic", "none"] = "fmp"
    fx_provider: Literal["bank_of_canada", "synthetic"] = "bank_of_canada"
    stale_after_days: int = Field(4, ge=1, le=30)
    discrepancy_tolerance_pct: float = Field(1.0, gt=0, le=50)
    # Protects free-tier provider quotas. The first run backfills history, so it may take a few
    # cycles to fill the whole universe; instruments not reached keep their stored data.
    max_provider_calls_per_cycle: int = Field(600, ge=10, le=20_000)


class PaperTrading(BaseModel):
    enabled: bool = True
    commission_per_trade_cad: float = Field(0.0, ge=0)
    fx_fee_pct: float = Field(1.5, ge=0, le=10)
    slippage_bps: float = Field(10.0, ge=0, le=500)
    require_brokerage_verification: bool = True
    reinvest_dividends: bool = True
    allow_fractional_shares: bool = False
    rebalance_band_pct: float = Field(5.0, ge=0, le=50)


PREFERENCE_MODELS: dict[str, type[BaseModel]] = {
    "research_schedule": ResearchSchedule,
    "email": EmailPrefs,
    "notifications": NotificationPrefs,
    "ai_budget": AiBudget,
    "ai_models": AiModels,
    "risk_limits": RiskLimits,
    "universe": Universe,
    "brokerage": BrokeragePrefs,
    "display": DisplayPrefs,
    "market_data": MarketData,
    "paper_trading": PaperTrading,
}


class UnknownPreference(KeyError):
    pass


def _model(key: str) -> type[BaseModel]:
    try:
        return PREFERENCE_MODELS[key]
    except KeyError as exc:
        raise UnknownPreference(key) from exc


def get_pref(session: Session, key: str) -> Any:
    model = _model(key)
    row = session.execute(
        select(PreferenceVersion).where(PreferenceVersion.key == key).order_by(PreferenceVersion.id.desc()).limit(1)
    ).scalar_one_or_none()
    if row is None:
        return model()
    return model.model_validate(row.value)


def set_pref(session: Session, key: str, value: dict[str, Any], *, actor: str = "owner",
             reason: str | None = None) -> BaseModel:
    model = _model(key)
    validated = model.model_validate(value)
    current = get_pref(session, key)
    if key == "ai_budget" and actor != "owner":
        # The budget is never raised automatically.
        if validated.monthly_limit_cad > current.monthly_limit_cad:  # type: ignore[attr-defined]
            raise PermissionError("Only the owner may increase the AI budget")
    session.add(PreferenceVersion(key=key, value=validated.model_dump(mode="json"), changed_by=actor,
                                  reason=reason))
    audit(session, "preference.changed", actor=actor, entity_type="preference", entity_id=key,
          before=current.model_dump(mode="json"), after=validated.model_dump(mode="json"))
    return validated


def all_prefs(session: Session) -> dict[str, Any]:
    return {k: get_pref(session, k).model_dump(mode="json") for k in PREFERENCE_MODELS}


def pref_history(session: Session, key: str) -> list[PreferenceVersion]:
    _model(key)
    return list(session.execute(
        select(PreferenceVersion).where(PreferenceVersion.key == key).order_by(PreferenceVersion.id.desc())
    ).scalars())


def count_versions(session: Session) -> int:
    return session.execute(select(func.count(PreferenceVersion.id))).scalar_one()
