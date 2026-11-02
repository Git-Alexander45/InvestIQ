"""Owner settings. Every change is a new version (history kept) and is audit-logged."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from investiq.api.deps import db, row
from investiq.config import get_settings
from investiq.services.health import _configured
from investiq.services.preferences import PREFERENCE_MODELS, all_prefs, get_pref, pref_history, set_pref

router = APIRouter(tags=["settings"])


@router.get("/settings")
def settings(s: Session = Depends(db)) -> dict[str, Any]:
    cfg = get_settings()
    return {"preferences": all_prefs(s),
            "schema": {k: m.model_json_schema() for k, m in PREFERENCE_MODELS.items()},
            "system": {"env": cfg.env, "api_host": cfg.api_host, "api_port": cfg.api_port,
                       "database": cfg.database_url.split("://")[0], "configured": _configured(),
                       "synthetic_allowed": cfg.allow_synthetic_data and not cfg.is_production,
                       "note": "API keys and passwords are set in the .env file, never through the dashboard."}}


class PrefIn(BaseModel):
    value: dict[str, Any]
    reason: str | None = Field(None, max_length=500)
    confirm_budget_increase: bool = False


@router.put("/settings/{key}")
def update(key: str, body: PrefIn, s: Session = Depends(db)) -> dict[str, Any]:
    if key not in PREFERENCE_MODELS:
        raise HTTPException(404, "unknown setting")
    current = get_pref(s, key)
    merged = {**current.model_dump(mode="json"), **body.value}
    if key == "ai_budget":
        new_limit = float(merged.get("monthly_limit_cad", current.monthly_limit_cad))
        if new_limit > current.monthly_limit_cad and not body.confirm_budget_increase:
            raise HTTPException(409, f"Raising the AI budget from {current.monthly_limit_cad:.2f} to {new_limit:.2f} CAD "
                                     "needs explicit confirmation (confirm_budget_increase=true).")
    if key == "market_data":
        cfg = get_settings()
        wants_synth = any(v == "synthetic" for v in merged.values())
        if wants_synth and (cfg.is_production or not cfg.allow_synthetic_data):
            raise HTTPException(422, "Synthetic data is disabled. It is allowed only in development.")
    try:
        v = set_pref(s, key, merged, actor="owner", reason=body.reason)
    except ValidationError as exc:
        raise HTTPException(422, exc.errors(include_url=False, include_context=False)) from exc
    return {"key": key, "value": v.model_dump(mode="json")}


@router.get("/settings/{key}/history")
def history(key: str, s: Session = Depends(db)) -> list[dict[str, Any]]:
    if key not in PREFERENCE_MODELS:
        raise HTTPException(404, "unknown setting")
    return [row(v) for v in pref_history(s, key)]
