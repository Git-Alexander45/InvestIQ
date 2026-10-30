"""Assemble point-in-time scoring inputs for an instrument from the database."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from investiq.data import repository as repo
from investiq.data.stats import price_stats
from investiq.finance import overlap as ov
from investiq.finance.fundamentals import derive
from investiq.models import DataQualityIssue, Instrument, PriceBar
from investiq.scoring.engine import Facts, InstrumentInfo


def info(inst: Instrument) -> InstrumentInfo:
    return InstrumentInfo(symbol=inst.symbol, exchange=inst.exchange, name=inst.name, asset_class=inst.asset_class,
                          security_type=inst.security_type, currency=inst.currency, country=inst.country,
                          region=inst.region, sector=inst.sector, themes=list(inst.themes or []), is_reit=inst.is_reit,
                          is_leveraged=inst.is_leveraged, is_inverse=inst.is_inverse,
                          is_speculative=inst.is_speculative, currency_hedged=inst.currency_hedged, mer_pct=inst.mer_pct)


def etf_stats(session: Session, inst: Instrument, as_of: datetime) -> tuple[dict[str, Any] | None, list[ov.Constituent] | None,
                                                                          dict[str, Any] | None]:
    snap = repo.latest_holdings(session, inst.id, as_of.date())
    if snap is None or not snap.holdings:
        return None, None, None
    cons = [ov.Constituent(ov.normalise_key(h.symbol, h.name), h.name, h.weight_pct, h.sector, h.country, h.currency,
                           h.asset_class) for h in snap.holdings]
    weights = [c.weight_pct for c in cons]
    stats = {"holdings_count": len(cons), "top10_pct": round(ov.top_n_concentration(weights, 10), 3),
             "effective_n": round(ov.effective_number(weights), 2), "coverage_pct": snap.coverage_pct,
             "as_of": snap.as_of.isoformat(), "source": snap.source}
    countries: dict[str, float] = {}
    for c in cons:
        countries[c.country or "Unknown"] = countries.get(c.country or "Unknown", 0) + c.weight_pct
    return stats, cons, countries


def build(session: Session, inst: Instrument, as_of: datetime, *, market_bars: list[PriceBar] | None = None,
          news_signal: dict[str, Any] | None = None, ai_inputs: dict[str, Any] | None = None,
          bars: list[PriceBar] | None = None, cycle_id: int | None = None) -> tuple[Facts, dict[str, Any]]:
    fs = repo.latest_fundamentals(session, inst.id, as_of)
    bars = bars if bars is not None else repo.daily_bars(session, inst.id, as_of)
    ps = price_stats(bars, as_of, market_bars) if bars else None
    est, cons, countries = (etf_stats(session, inst, as_of) if inst.security_type in ("etf", "mutual_fund")
                            else (None, None, None))
    issues: list[str] = []
    if cycle_id is not None:
        q = session.query(DataQualityIssue).filter(DataQualityIssue.instrument_id == inst.id,
                                                   DataQualityIssue.cycle_id == cycle_id,
                                                   DataQualityIssue.severity != "info")
        issues = [i.message for i in q.limit(3)]
    if ps and ps.get("data_status") == "synthetic":
        issues.append("synthetic development data")
    facts = Facts(instrument=info(inst), as_of=as_of, fundamentals=derive(fs.metrics) if fs else None,
                  fundamentals_source=fs.source if fs else None, fundamentals_as_of=fs.as_of if fs else None,
                  price_stats=ps, price_source=bars[-1].source if bars else None, etf_stats=est,
                  news_signal=news_signal, ai_inputs=ai_inputs, quality_issues=issues)
    extras = {"constituents": cons, "country_exposure": countries,
              "last_bar": bars[-1] if bars else None, "fundamentals_snapshot_id": fs.id if fs else None}
    return facts, extras
