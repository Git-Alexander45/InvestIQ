from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from investiq.data import ingest, repository
from investiq.data.providers.base import (
    BarDTO,
    BarsResult,
    FundamentalsDTO,
    HoldingDTO,
    HoldingsDTO,
    InstrumentRef,
)
from investiq.data.providers.synthetic import SyntheticProvider
from investiq.data.stats import price_stats
from investiq.data.validation import discrepancy, staleness, validate_bars
from investiq.db.base import AppendOnlyViolation
from investiq.models import DataQualityIssue, FundamentalsSnapshot, Instrument, PriceBar, Score
from investiq.services.bootstrap import bootstrap


def bar(d, o, h, low, c, v=100):
    return BarDTO(datetime(2026, 1, d, tzinfo=UTC), o, h, low, c, v)


def test_validate_bars_drops_invalid_and_flags_outliers():
    bars = [bar(2, 10, 11, 9, 10), bar(2, 10, 11, 9, 10), bar(5, 10, 9, 11, 10), bar(6, -1, 1, -2, 0.5),
            bar(7, 10, 16, 10, 15.5)]
    clean, issues = validate_bars(bars)
    assert len(clean) == 2
    kinds = sorted(i.issue_type for i in issues)
    assert kinds.count("invalid") == 3 and "outlier" in kinds


def test_staleness_and_discrepancy():
    assert staleness(None, date(2026, 1, 9), 3).issue_type == "missing"
    assert staleness(date(2026, 1, 2), date(2026, 1, 9), 3).issue_type == "stale"
    assert staleness(date(2026, 1, 8), date(2026, 1, 9), 3) is None
    assert discrepancy(100, 103, "fmp", "twelvedata", 1.0).issue_type == "discrepancy"
    assert discrepancy(100, 100.5, "fmp", "twelvedata", 1.0) is None


def test_bootstrap_is_idempotent(session):
    first = bootstrap(session)
    session.commit()
    assert first["instruments_added"] > 100
    second = bootstrap(session)
    assert second["instruments_added"] == 0
    codes = {p.code for p in session.execute(select(investiq_models().Portfolio)).scalars()}
    assert {"OWNER", "A", "B", "C", "D", "BM_GLOBAL"} <= codes


def investiq_models():
    import investiq.models as m

    return m


def _instrument(session, symbol="TST", exchange="TSX", currency="CAD"):
    inst = Instrument(symbol=symbol, exchange=exchange, name=symbol, asset_class="equity",
                      security_type="common_stock", currency=currency)
    session.add(inst)
    session.flush()
    return inst


def test_store_bars_never_overwrites(session):
    inst = _instrument(session)
    r1 = BarsResult([bar(2, 10, 11, 9, 10), bar(5, 10, 11, 9, 10.5)], "1d", "CAD", "fmp", "end_of_day")
    assert ingest.store_bars(session, inst, r1) == 2
    r2 = BarsResult([bar(5, 99, 100, 98, 99), bar(6, 10, 11, 9, 10.2)], "1d", "CAD", "fmp", "end_of_day")
    assert ingest.store_bars(session, inst, r2) == 1
    session.flush()
    jan5 = session.get(PriceBar, (inst.id, "1d", datetime(2026, 1, 5, tzinfo=UTC), "fmp"))
    assert jan5.close == 10.5


def test_fundamentals_versioning_and_point_in_time(session):
    inst = _instrument(session)
    dto = FundamentalsDTO({"pe_ttm": 20}, "CAD", date(2025, 12, 31), datetime(2026, 2, 1, tzinfo=UTC), "fmp")
    assert ingest.store_fundamentals(session, inst, dto) is not None
    assert ingest.store_fundamentals(session, inst, dto) is None  # unchanged -> no duplicate
    dto2 = FundamentalsDTO({"pe_ttm": 25}, "CAD", date(2026, 3, 31), datetime(2026, 5, 1, tzinfo=UTC), "fmp")
    ingest.store_fundamentals(session, inst, dto2)
    session.flush()
    early = repository.latest_fundamentals(session, inst.id, datetime(2026, 3, 1, tzinfo=UTC))
    late = repository.latest_fundamentals(session, inst.id, datetime(2026, 6, 1, tzinfo=UTC))
    assert early.metrics["pe_ttm"] == 20 and late.metrics["pe_ttm"] == 25
    assert repository.latest_fundamentals(session, inst.id, datetime(2026, 1, 1, tzinfo=UTC)) is None


def test_append_only_guard(session):
    inst = _instrument(session)
    snap = FundamentalsSnapshot(instrument_id=inst.id, as_of=datetime.now(UTC), source="fmp", metrics={"a": 1})
    session.add(snap)
    session.flush()
    snap.metrics = {"a": 2}
    with pytest.raises(AppendOnlyViolation):
        session.flush()
    session.rollback()
    inst = _instrument(session, "TS2")
    snap = FundamentalsSnapshot(instrument_id=inst.id, as_of=datetime.now(UTC), source="fmp", metrics={"a": 1})
    session.add(snap)
    session.flush()
    session.delete(snap)
    with pytest.raises(AppendOnlyViolation):
        session.flush()


def test_naive_datetimes_rejected(session):
    inst = _instrument(session)
    session.add(Score(instrument_id=inst.id, strategy_version_id=1, model="equity", overall=1, grade="F",
                      confidence=0, coverage=0, as_of=datetime(2026, 1, 1)))
    with pytest.raises(Exception, match="naive"):
        session.flush()


def test_holdings_and_issue_recording(session):
    etf = _instrument(session, "ETF1")
    dto = HoldingsDTO([HoldingDTO("Apple", 7.0, "AAPL"), HoldingDTO("Microsoft", 6.0, "MSFT")], date(2026, 1, 1), "fmp")
    snap = ingest.store_holdings(session, etf, dto)
    assert snap.coverage_pct == 13.0
    assert ingest.store_holdings(session, etf, dto) is None
    ingest.store_bars(session, etf, BarsResult([bar(2, 1, 1, 1, 1), bar(5, 0, 0, 0, 0)], "1d", "CAD", "fmp", "end_of_day"))
    session.flush()
    assert session.execute(select(DataQualityIssue)).scalars().first() is not None


def test_price_stats_from_synthetic_history(session):
    inst = _instrument(session, "SYN")
    prov = SyntheticProvider()
    ref = InstrumentRef("SYN", "TSX", "CAD")
    res = prov.bars(ref, "1d", date(2019, 1, 1), date(2026, 9, 30))
    ingest.store_bars(session, inst, res)
    session.flush()
    as_of = datetime(2026, 9, 30, 23, tzinfo=UTC)
    bars = repository.daily_bars(session, inst.id, as_of)
    stats = price_stats(bars, as_of)
    assert stats["volatility_1y_pct"] > 0
    assert stats["max_drawdown_3y_pct"] <= 0
    assert stats["return_5y_ann_pct"] is not None
    assert stats["data_status"] == "synthetic"
    assert stats["return_basis"] == "price_only"
    # point-in-time: nothing after as_of
    assert all(b.ts <= as_of for b in bars)
    earlier = repository.daily_bars(session, inst.id, as_of - timedelta(days=400))
    assert earlier[-1].ts < bars[-1].ts
