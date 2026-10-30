"""News ingestion pipeline: collect -> dedupe/cluster -> rules assessment -> affected ETFs."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from investiq.data.providers.base import NewsDTO, ProviderError
from investiq.models import EtfHolding, EtfHoldingsSnapshot, Instrument, NewsAssessment, NewsCluster, NewsItem, NewsSource
from investiq.news import classify, dedupe

log = logging.getLogger(__name__)
RULES_METHOD = "rules:v1"


def entity_index(session: Session) -> classify.EntityIndex:
    rows = session.execute(select(Instrument.symbol, Instrument.name).where(Instrument.active.is_(True))).all()
    return classify.EntityIndex.build([(s, n) for s, n in rows])


def collect(session: Session, rss, company_news, symbols: list[str]) -> tuple[list[NewsDTO], list[str]]:
    items: list[NewsDTO] = []
    errors: list[str] = []
    for src in session.execute(select(NewsSource).where(NewsSource.enabled.is_(True))).scalars():
        try:
            items.extend(rss.fetch_feed(src.url, src.key, src.category, src.official))
        except (ProviderError, Exception) as exc:  # one bad feed must not stop collection
            errors.append(f"{src.key}: {exc}")
    if company_news is not None and symbols:
        try:
            items.extend(company_news.company_news(symbols))
        except Exception as exc:
            errors.append(f"company_news: {exc}")
    return items, errors


def store(session: Session, items: list[NewsDTO], cycle_id: int | None, entities: classify.EntityIndex,
          window_hours: int = 72) -> dict[str, Any]:
    known_urls = {u for (u,) in session.execute(select(NewsItem.url).where(NewsItem.url.in_([i.url for i in items])))}
    since = datetime.now(UTC) - timedelta(hours=window_hours)
    recent = list(session.execute(select(NewsItem).where(NewsItem.collected_at >= since)).scalars())
    stats = {"received": len(items), "new": 0, "duplicates": 0, "related": 0, "skipped_known": 0}
    for dto in sorted(items, key=lambda i: i.published_at or datetime.now(UTC)):
        if dto.url in known_urls:
            stats["skipped_known"] += 1
            continue
        known_urls.add(dto.url)
        fp = dedupe.fingerprint(dto.title)
        dup = next((r for r in recent if r.title_fingerprint == fp), None)
        related = None
        if dup is None:
            best = max(recent, key=lambda r: dedupe.similarity(r.title, dto.title), default=None)
            if best is not None and dedupe.similarity(best.title, dto.title) >= dedupe.RELATED_THRESHOLD:
                related = best
        item = NewsItem(source_key=dto.source_key, url=dto.url[:1024], title=dto.title[:512], summary=dto.summary,
                        published_at=dto.published_at, title_fingerprint=fp, category=dto.category,
                        official=dto.official, cycle_id=cycle_id)
        anchor = dup or related
        if anchor is not None:
            cluster = session.get(NewsCluster, anchor.cluster_id) if anchor.cluster_id else None
            if cluster is None:
                cluster = NewsCluster(title=anchor.title[:512])
                session.add(cluster)
                session.flush()
                anchor.cluster_id = cluster.id
            cluster.item_count += 1
            cluster.last_seen_at = datetime.now(UTC)
            item.cluster_id = cluster.id
            if dup is not None:
                item.duplicate_of_id = dup.id
                stats["duplicates"] += 1
            else:
                stats["related"] += 1
        session.add(item)
        session.flush()
        recent.append(item)
        stats["new"] += 1
        if item.duplicate_of_id is None:
            ra = classify.assess(dto.title, dto.summary, official=dto.official, entities=entities)
            symbols = sorted(set(ra.affected_symbols) | {s.upper() for s in dto.symbols if s.upper() in entities.by_symbol})
            session.add(NewsAssessment(
                news_item_id=item.id, method=RULES_METHOD, topic=ra.topic, what_happened=ra.what_happened,
                event_time=dto.published_at, confirmation=ra.confirmation, impact=ra.impact, horizon=ra.horizon,
                confidence=ra.confidence, importance=ra.importance, affected_symbols=symbols,
                affected_sectors=ra.affected_sectors, affected_etfs=affected_etfs(session, symbols),
                evidence=ra.evidence + [f"source:{dto.source_key}", f"url:{dto.url}"],
            ))
    return stats


def affected_etfs(session: Session, symbols: list[str], min_weight: float = 1.0) -> list[dict[str, Any]]:
    """ETFs in the universe whose latest holdings contain any affected company (>= min_weight%)."""
    if not symbols:
        return []
    rows = session.execute(
        select(Instrument.symbol, EtfHolding.symbol, EtfHolding.weight_pct, EtfHoldingsSnapshot.id)
        .join(EtfHoldingsSnapshot, EtfHoldingsSnapshot.etf_id == Instrument.id)
        .join(EtfHolding, EtfHolding.snapshot_id == EtfHoldingsSnapshot.id)
        .where(EtfHolding.symbol.in_(symbols), EtfHolding.weight_pct >= min_weight)
    ).all()
    latest: dict[str, int] = {}
    for etf, _, _, snap_id in rows:
        latest[etf] = max(latest.get(etf, 0), snap_id)
    out = [{"etf": etf, "holding": h, "weight_pct": round(w, 3)} for etf, h, w, snap in rows if latest[etf] == snap]
    return sorted(out, key=lambda r: -r["weight_pct"])[:20]


def latest_assessments(session: Session, since: datetime) -> list[tuple[NewsItem, NewsAssessment]]:
    """Latest assessment per news item (AI assessments supersede rules when both exist)."""
    rows = session.execute(
        select(NewsItem, NewsAssessment).join(NewsAssessment, NewsAssessment.news_item_id == NewsItem.id)
        .where(NewsItem.collected_at >= since, NewsItem.duplicate_of_id.is_(None))
        .order_by(NewsAssessment.id)
    ).all()
    best: dict[int, tuple[NewsItem, NewsAssessment]] = {}
    for item, a in rows:
        current = best.get(item.id)
        if current is None or a.method.startswith("ai:") or not current[1].method.startswith("ai:"):
            best[item.id] = (item, a)
    return list(best.values())


def news_signals(session: Session, as_of: datetime, days: int = 30) -> dict[str, dict[str, Any]]:
    """Per-symbol net impact in [-1, 1], weighted by confidence and importance."""
    sign = {"positive": 1.0, "negative": -1.0, "mixed": 0.0, "uncertain": 0.0}
    acc: dict[str, dict[str, Any]] = {}
    for item, a in latest_assessments(session, as_of - timedelta(days=days)):
        if item.collected_at > as_of:
            continue
        w = a.confidence * max(a.importance, 0.1)
        for sym in a.affected_symbols:
            s = acc.setdefault(sym, {"num": 0.0, "den": 0.0, "count": 0, "items": []})
            s["num"] += sign.get(a.impact, 0.0) * w
            s["den"] += w
            s["count"] += 1
            s["items"].append({"news_item_id": item.id, "assessment_id": a.id, "impact": a.impact,
                               "title": item.title, "url": item.url, "method": a.method})
    return {k: {"net": (v["num"] / v["den"]) if v["den"] else 0.0, "count": v["count"], "items": v["items"][:10],
                "collected": True} for k, v in acc.items()}
