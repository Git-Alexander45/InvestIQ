"""Request dependencies: database session and local API token check."""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from datetime import date, datetime
from typing import Any

from fastapi import Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from investiq.config import get_settings
from investiq.db.session import get_session


def db() -> Iterator[Session]:
    s = get_session()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def require_token(request: Request, authorization: str | None = Header(default=None),
                  x_investiq_token: str | None = Header(default=None)) -> None:
    """Every API call needs the local token (the dashboard's server-side proxy adds it), so other
    programs or web pages on this computer cannot read or change InvestIQ data."""
    expected = get_settings().secret("api_token")
    if not expected:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "INVESTIQ_API_TOKEN is not configured")
    supplied = x_investiq_token
    if authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
    if not supplied or not secrets.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or missing API token")


def row(obj: Any, exclude: set[str] | None = None) -> dict[str, Any]:
    """ORM object -> plain dict of its columns."""
    if obj is None:
        return {}
    out = {}
    for col in obj.__table__.columns:
        if exclude and col.name in exclude:
            continue
        v = getattr(obj, col.key)
        out[col.name] = v.isoformat() if isinstance(v, datetime | date) else v
    return out


def not_found(what: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"{what} not found")
