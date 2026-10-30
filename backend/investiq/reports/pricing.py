"""Price display with full provenance: trading currency, CAD and USD equivalents, FX, source, status."""

from __future__ import annotations

from datetime import date
from typing import Any

from investiq.finance.fx import FxTable, MissingFxRate


def price_block(price: float | None, currency: str | None, as_of: str | None, source: str | None,
                status: str | None, fx: FxTable) -> dict[str, Any] | None:
    if price is None or currency is None:
        return None
    out: dict[str, Any] = {"price": round(price, 4), "currency": currency, "as_of": as_of, "source": source,
                           "status": status or "unknown"}
    for target in ("CAD", "USD"):
        try:
            v, q = fx.convert(price, currency, target)
            out[target.lower()] = round(v, 4)
            if currency != target:
                out[f"fx_{currency.lower()}_{target.lower()}"] = {
                    "rate": round(q.rate, 6), "as_of": q.as_of.isoformat() if q.as_of != date.min else None,
                    "source": q.source, "type": q.rate_type}
        except MissingFxRate:
            out[target.lower()] = None
    return out


def format_price(p: dict[str, Any] | None) -> str:
    if not p:
        return "no price data"
    parts = [f"{p['price']:,.2f} {p['currency']}"]
    if p["currency"] != "CAD" and p.get("cad") is not None:
        parts.append(f"≈ {p['cad']:,.2f} CAD")
    if p["currency"] != "USD" and p.get("usd") is not None:
        parts.append(f"≈ {p['usd']:,.2f} USD")
    fx = next((v for k, v in p.items() if k.startswith("fx_")), None)
    meta = f"{p['status']}, {p['source']}, {p['as_of']}"
    if fx:
        meta += f"; FX {fx['rate']} ({fx['source']}, {fx['as_of']}, daily reference rate)"
    return " / ".join(parts) + f" [{meta}]"
