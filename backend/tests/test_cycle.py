"""End-to-end daily research cycle on synthetic data, plus scheduling/locking rules."""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from sqlalchemy import select

from investiq.data.providers.base import NewsDTO
from investiq.data.providers.rss import RssProvider
from investiq.models import (
    AiRequest,
    CycleStep,
    EmailDelivery,
    LeaderboardEntry,
    Notification,
    PaperOrder,
    Prediction,
    Recommendation,
    Report,
    ResearchCycle,
    Score,
)
from investiq.research import locking
from investiq.research.cycle import run_cycle
from investiq.services.bootstrap import bootstrap
from investiq.services.preferences import set_pref

SMALL_UNIVERSE = {
    "defaults": {"metadata_source": "test"},
    "instruments": [
        {"symbol": s, "exchange": "TSX", "name": n, "asset_class": ac, "security_type": "etf", "currency": "CAD",
         "country": "CA", "region": r}
        for s, n, ac, r in [("XEQT", "All equity", "equity", "global"), ("VFV", "S&P 500", "equity", "united_states"),
                            ("XIC", "TSX composite", "equity", "canada"), ("XGRO", "Growth", "multi_asset", "global"),
                            ("ZAG", "Aggregate bond", "bond", "canada")]
    ] + [
        {"symbol": "RY", "exchange": "TSX", "name": "Royal Bank of Canada", "asset_class": "equity",
         "security_type": "common_stock", "currency": "CAD", "country": "CA", "sector": "Financials"},
        {"symbol": "SHOP", "exchange": "TSX", "name": "Shopify Inc", "asset_class": "equity",
         "security_type": "common_stock", "currency": "CAD", "country": "CA", "sector": "Technology"},
        {"symbol": "AAPL", "exchange": "NASDAQ", "name": "Apple Inc", "asset_class": "equity",
         "security_type": "common_stock", "currency": "USD", "country": "US", "sector": "Technology"},
        {"symbol": "MSFT", "exchange": "NASDAQ", "name": "Microsoft Corp", "asset_class": "equity",
         "security_type": "common_stock", "currency": "USD", "country": "US", "sector": "Technology"},
    ],
}
DAY1 = datetime(2026, 10, 29, 23, 30, tzinfo=UTC)  # 19:30 Eastern, after the 18:00 run time


def fake_feed(self, url, source_key, category, official):
    return [NewsDTO(url=f"https://example.test/{source_key}/1", title="Bank of Canada holds policy rate at 2.25%",
                    summary="The central bank kept its key rate unchanged.", published_at=DAY1 - timedelta(hours=3),
                    source_key=source_key, category=category, official=official),
            NewsDTO(url=f"https://example.test/{source_key}/2", title="Royal Bank of Canada raises dividend",
                    summary="RY lifted its quarterly dividend.", published_at=DAY1 - timedelta(hours=2),
                    source_key=source_key, category=category, official=official)]


@pytest.fixture()
def world(session, tmp_path, monkeypatch):
    path = tmp_path / "universe.yaml"
    path.write_text(yaml.safe_dump(SMALL_UNIVERSE), encoding="utf-8")
    monkeypatch.setattr(RssProvider, "fetch_feed", fake_feed)  # never touch the network in tests
    bootstrap(session, universe_path=path)
    session.commit()
    set_pref(session, "market_data", {"price_provider": "synthetic", "fundamentals_provider": "synthetic",
                                      "etf_holdings_provider": "synthetic", "fx_provider": "synthetic"}, actor="test")
    set_pref(session, "email", {"enabled": True, "to_address": "owner@example.com", "provider": "outbox"}, actor="test")
    set_pref(session, "notifications", {"desktop_enabled": False}, actor="test")
    session.commit()
    return session


def steps(session, cycle):
    return {s.name: s for s in session.execute(select(CycleStep).where(CycleStep.cycle_id == cycle.id)).scalars()}


def test_full_cycle_on_synthetic_data(world, tmp_path):
    s = world
    c = run_cycle(s, triggered_by="test", now=DAY1)
    st = steps(s, c)
    assert c.status == "succeeded_degraded", c.error
    assert len(st) == 20 and all(x.status in ("ok", "degraded") for x in st.values())
    # Degradations are named, never hidden: no licensed company-news feed and no AI key.
    assert any("company_news" in r for r in c.degraded_reasons)
    assert st["quantitative_screening"].detail["scored"] == 9
    assert s.query(Score).filter(Score.cycle_id == c.id).count() == 9
    assert s.query(Recommendation).filter(Recommendation.cycle_id == c.id).count() == 9
    assert s.query(LeaderboardEntry).filter(LeaderboardEntry.cycle_id == c.id).count() > 0
    # Nothing is recommended as BUY without verified availability at both brokerages.
    assert not s.query(Recommendation).filter(Recommendation.cycle_id == c.id,
                                              Recommendation.assessment == "BUY").count()
    # News was stored and the RY headline linked to RY.
    assert st["collect_economic_political_news"].detail["new"] >= 2
    # Report: synthetic data is labelled loudly everywhere.
    rep = s.query(Report).filter(Report.cycle_id == c.id).one()
    assert rep.subject.startswith("[SYNTHETIC TEST DATA]")
    assert "SYNTHETIC" in rep.text and "SYNTHETIC" in rep.html
    for section in ("Global market overview", "Top investment opportunities", "Paper trading performance", "AI spending",
                    "Canadian TFSA opportunities", "Sources and timestamps"):
        assert section.lower() in rep.text.lower(), section
    assert "no real trades are ever placed" in rep.text.lower()
    # Email went to the local outbox.
    d = s.query(EmailDelivery).filter(EmailDelivery.cycle_id == c.id).one()
    assert d.status == "sent" and d.provider == "outbox" and Path(d.provider_message_id).exists()
    # Benchmarks placed their one-time orders; no AI spend without a key.
    assert s.query(PaperOrder).count() >= 4
    assert s.query(AiRequest).count() == 0 and c.ai_cost_cad == 0
    assert s.query(Prediction).count() == 9  # first assessment of each instrument is tracked
    assert s.query(Notification).filter(Notification.kind == "research_complete").count() == 1


def test_same_day_never_runs_twice_and_next_day_continues(world):
    s = world
    run_cycle(s, triggered_by="test", now=DAY1)
    with pytest.raises(locking.CycleNotDue):
        run_cycle(s, triggered_by="test", now=DAY1 + timedelta(minutes=5))
    assert locking.due_cycle_date(s, DAY1 + timedelta(hours=1)) is None
    day2 = DAY1 + timedelta(days=1)
    assert locking.due_cycle_date(s, day2) == date(2026, 10, 30)
    c2 = run_cycle(s, triggered_by="test", now=day2)
    assert c2.status.startswith("succeeded")
    detail = steps(s, c2)["update_paper_trading"].detail
    assert detail["BM_GLOBAL"]["fills"] == 1  # yesterday's benchmark order filled at today's open
    # Predictions are only re-issued when an assessment changes.
    assert s.query(Prediction).count() < 18


def test_cycle_fails_honestly_without_any_data(session, tmp_path, monkeypatch):
    path = tmp_path / "universe.yaml"
    path.write_text(yaml.safe_dump(SMALL_UNIVERSE), encoding="utf-8")
    monkeypatch.setattr(RssProvider, "fetch_feed", fake_feed)
    bootstrap(session, universe_path=path)
    set_pref(session, "market_data", {"price_provider": "none", "fundamentals_provider": "none",
                                      "etf_holdings_provider": "none", "fx_provider": "synthetic"}, actor="test")
    set_pref(session, "email", {"enabled": True, "to_address": "owner@example.com", "provider": "outbox"}, actor="test")
    set_pref(session, "notifications", {"desktop_enabled": False}, actor="test")
    session.commit()
    c = run_cycle(session, triggered_by="test", now=DAY1)
    assert c.status == "failed"
    assert "quantitative_screening" in c.error
    rep = session.query(Report).filter(Report.cycle_id == c.id, Report.kind == "failure").one()
    assert "failed" in rep.subject.lower()
    assert session.query(EmailDelivery).filter(EmailDelivery.kind == "failure").one().status == "sent"
    assert session.query(Notification).filter(Notification.kind == "job_failed").count() == 1
    # A failed day may be retried (it is due again), up to the attempt limit.
    assert locking.due_cycle_date(session, DAY1 + timedelta(minutes=30)) == date(2026, 10, 29)


# ------------------------------------------------------------------------------------------------
# Scheduling and locking
# ------------------------------------------------------------------------------------------------


def test_latest_occurrence_respects_eastern_time_and_dst():
    tz = "America/Toronto"
    # 17:59 EDT on Oct 29 -> still the previous research day.
    d, _ = locking.latest_occurrence(datetime(2026, 10, 29, 21, 59, tzinfo=UTC), "18:00", tz)
    assert d == date(2026, 10, 28)
    d, run_at = locking.latest_occurrence(datetime(2026, 10, 29, 22, 0, tzinfo=UTC), "18:00", tz)
    assert d == date(2026, 10, 29) and run_at == datetime(2026, 10, 29, 22, 0, tzinfo=UTC)
    # After DST ends (Nov 1), 18:00 Eastern is 23:00 UTC.
    d, run_at = locking.latest_occurrence(datetime(2026, 11, 2, 23, 30, tzinfo=UTC), "18:00", tz)
    assert d == date(2026, 11, 2) and run_at == datetime(2026, 11, 2, 23, 0, tzinfo=UTC)


def test_missed_run_is_caught_up_after_sleep(session):
    bootstrap(session)
    session.commit()
    # Computer was asleep at 18:00; it wakes at 07:00 the next morning.
    morning = datetime(2026, 10, 30, 11, 0, tzinfo=UTC)
    assert locking.due_cycle_date(session, morning) == date(2026, 10, 29)


def test_concurrent_and_stale_runs(session):
    bootstrap(session)
    session.commit()
    t0 = datetime(2026, 10, 29, 22, 5, tzinfo=UTC)
    c1 = locking.acquire(session, date(2026, 10, 29), "scheduler", t0)
    with pytest.raises(locking.CycleNotDue):
        locking.acquire(session, date(2026, 10, 29), "manual", t0 + timedelta(minutes=10))
    assert locking.due_cycle_date(session, t0 + timedelta(minutes=10)) is None
    # The first process died (no heartbeat for 45+ minutes): it is marked abandoned and a new attempt starts.
    later = t0 + timedelta(minutes=50)
    c2 = locking.acquire(session, date(2026, 10, 29), "scheduler", later)
    session.refresh(c1)
    assert c1.status == "abandoned" and "Abandoned" in c1.error
    assert c2.attempt == 2 and c2.status == "running"


def test_attempt_limit(session):
    bootstrap(session)
    session.commit()
    t = datetime(2026, 10, 29, 22, 5, tzinfo=UTC)
    for i in range(locking.MAX_ATTEMPTS_PER_DAY):
        c = locking.acquire(session, date(2026, 10, 29), "scheduler", t + timedelta(minutes=i))
        c.status = "failed"
        session.commit()
    assert locking.due_cycle_date(session, t + timedelta(hours=1)) is None
    with pytest.raises(locking.CycleNotDue):
        locking.acquire(session, date(2026, 10, 29), "scheduler", t + timedelta(hours=1))
    # The owner can still force a manual re-run.
    forced = locking.acquire(session, date(2026, 10, 29), "manual", t + timedelta(hours=1), force=True)
    assert forced.attempt == locking.MAX_ATTEMPTS_PER_DAY + 1


def test_disabled_schedule_is_never_due(session):
    bootstrap(session)
    set_pref(session, "research_schedule", {"enabled": False}, actor="test")
    session.commit()
    assert locking.due_cycle_date(session, datetime(2026, 10, 29, 23, 0, tzinfo=UTC)) is None


def test_research_cycle_rows_are_unique_per_attempt(session):
    bootstrap(session)
    session.commit()
    t = datetime(2026, 10, 29, 22, 5, tzinfo=UTC)
    locking.acquire(session, date(2026, 10, 29), "scheduler", t)
    rows = session.execute(select(ResearchCycle)).scalars().all()
    assert [(r.cycle_date, r.attempt) for r in rows] == [(date(2026, 10, 29), 1)]
