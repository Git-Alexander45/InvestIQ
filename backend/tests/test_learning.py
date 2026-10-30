from datetime import UTC, date, datetime, timedelta

import pytest

from investiq.data import ingest
from investiq.data.providers.base import InstrumentRef
from investiq.data.providers.synthetic import SyntheticProvider
from investiq.learning import backtest, predictions, strategies
from investiq.models import (
    Dividend,
    Instrument,
    Prediction,
    PredictionEvaluation,
    PriceBar,
    Recommendation,
    Score,
    StrategyPromotion,
)
from investiq.scoring.strategy_config import baseline
from investiq.services.bootstrap import ensure_strategies

T0 = datetime(2026, 1, 5, 21, tzinfo=UTC)


def inst(session, symbol, **kw):
    i = Instrument(symbol=symbol, exchange="TSX", name=symbol, asset_class="equity",
                   security_type=kw.pop("security_type", "common_stock"), currency="CAD", country="CA", **kw)
    session.add(i)
    session.flush()
    return i


def daily(session, i, start: datetime, closes):
    for k, c in enumerate(closes):
        session.add(PriceBar(instrument_id=i.id, interval="1d", ts=start + timedelta(days=k), source="test", open=c,
                             high=c, low=c, close=c, currency="CAD"))
    session.flush()


def prediction(session, i, bench, assessment="BUY"):
    sv = ensure_strategies(session)["frozen-baseline"]
    sc = Score(instrument_id=i.id, strategy_version_id=sv.id, model="equity", overall=85, grade="A", confidence=0.8,
               coverage=0.9, as_of=T0)
    session.add(sc)
    session.flush()
    rec = Recommendation(instrument_id=i.id, strategy_version_id=sv.id, score_id=sc.id, assessment=assessment,
                         quant_assessment=assessment, source="quant_only", rationale="test", price=100.0,
                         price_currency="CAD", price_as_of=T0)
    session.add(rec)
    session.flush()
    p = Prediction(recommendation_id=rec.id, instrument_id=i.id, strategy_version_id=sv.id, source="quant_only",
                   assessment=assessment, grade="A", overall=85, horizon_days=1095, made_at=T0, price_at=100.0,
                   currency="CAD", benchmark_instrument_id=bench.id, benchmark_price_at=100.0)
    session.add(p)
    session.flush()
    return p


def test_predictions_evaluated_at_checkpoints_with_dividends_and_benchmark(session):
    a, b = inst(session, "AAA"), inst(session, "BMK", security_type="etf")
    daily(session, a, T0, [100 + k * 0.5 for k in range(40)])
    daily(session, b, T0, [100 + k * 0.1 for k in range(40)])
    session.add(Dividend(instrument_id=a.id, ex_date=(T0 + timedelta(days=3)).date(), amount=2.0, currency="CAD",
                         source="test"))
    p = prediction(session, a, b)
    assert predictions.evaluate_due(session, T0 + timedelta(days=6)) == 0  # 7-day checkpoint not reached
    assert predictions.evaluate_due(session, T0 + timedelta(days=8)) == 1
    assert predictions.evaluate_due(session, T0 + timedelta(days=8)) == 0  # idempotent
    e7 = session.query(PredictionEvaluation).filter_by(prediction_id=p.id, checkpoint_days=7).one()
    assert e7.price == 103.5 and e7.dividends_per_share == 2.0
    assert e7.total_return_pct == pytest.approx(5.5)
    assert e7.benchmark_return_pct == pytest.approx(0.7)
    assert e7.success is True
    assert predictions.evaluate_due(session, T0 + timedelta(days=39)) == 1  # 30-day checkpoint
    summ = predictions.summary(session)
    assert summ["assessment"]["BUY"]["7"]["hit_rate_pct"] == 100.0
    assert summ["assessment"]["BUY"]["7"]["small_sample"] is True


def test_avoid_prediction_succeeds_when_it_underperforms(session):
    a, b = inst(session, "AAA"), inst(session, "BMK", security_type="etf")
    daily(session, a, T0, [100 - k for k in range(10)])
    daily(session, b, T0, [100] * 10)
    p = prediction(session, a, b, assessment="AVOID")
    predictions.evaluate_due(session, T0 + timedelta(days=8))
    assert session.query(PredictionEvaluation).filter_by(prediction_id=p.id).one().success is True


def test_experimental_versions_and_promotion_rules(session):
    sv = ensure_strategies(session)
    assert strategies.production(session).id == sv["frozen-baseline"].id
    cfg = baseline()
    with pytest.raises(strategies.StrategyError):
        strategies.create_experimental(session, cfg, "same as before")
    cfg2 = baseline()
    model = next(iter(cfg2["models"]))
    cats = cfg2["models"][model]["weights"]
    k1, k2 = list(cats)[:2]
    cats[k1], cats[k2] = cats[k1] + 5, cats[k2] - 5
    exp = strategies.create_experimental(session, cfg2, "shift weight")
    assert exp.version == 2 and exp.parent_id == sv["experimental"].id
    run = backtest.BacktestRun(strategy_version_id=exp.id, baseline_strategy_version_id=sv["frozen-baseline"].id,
                               start_date=date(2020, 1, 1), end_date=date(2025, 1, 1), split_date=date(2023, 1, 1),
                               parameters={}, in_sample={}, out_of_sample={}, variants_tested=1,
                               passed_validation=False, validation_notes=["did not beat the baseline"], data_sources=[])
    session.add(run)
    session.flush()
    with pytest.raises(PermissionError):
        strategies.promote(session, exp.id, run.id, "try", actor="ai")
    with pytest.raises(strategies.StrategyError):
        strategies.promote(session, exp.id, run.id, "try")
    run2 = backtest.BacktestRun(strategy_version_id=exp.id, baseline_strategy_version_id=sv["frozen-baseline"].id,
                                start_date=date(2020, 1, 1), end_date=date(2025, 1, 1), split_date=date(2023, 1, 1),
                                parameters={}, in_sample={}, out_of_sample={}, variants_tested=1,
                                passed_validation=True, validation_notes=[], data_sources=[])
    session.add(run2)
    session.flush()
    strategies.promote(session, exp.id, run2.id, "beat baseline out of sample")
    assert strategies.production(session).id == exp.id
    assert session.query(StrategyPromotion).count() == 1
    assert strategies.frozen(session).config_hash == sv["frozen-baseline"].config_hash  # control never changes


def test_backtest_runs_without_lookahead_and_records_everything(session):
    sv = ensure_strategies(session)
    synth = SyntheticProvider(today=date(2025, 12, 31))
    universe = [inst(session, s) for s in ("AAA", "BBB", "CCC", "DDD")]
    gone = inst(session, "EEE", delisted_on=date(2024, 6, 28))
    for i in universe + [gone]:
        end = i.delisted_on or date(2025, 12, 31)
        ingest.store_bars(session, i, synth.bars(InstrumentRef(i.symbol, "TSX", "CAD"), "1d", date(2019, 1, 1), end))
    session.flush()
    run = backtest.run(session, sv["experimental"], sv["frozen-baseline"], date(2021, 1, 1), date(2025, 12, 1),
                       date(2024, 1, 1), rebalance_days=60, top_n=3)
    assert run.id is not None
    assert run.passed_validation is False  # identical configs cannot beat each other
    assert any("baseline" in n for n in run.validation_notes)
    assert run.out_of_sample.get("periods", 0) > 0 and run.in_sample.get("periods", 0) > 0
    assert run.data_sources == ["synthetic"]
    # The delisted instrument is in the universe before its delisting (no survivorship bias).
    assert run.parameters["universe_size"] == 5
    with pytest.raises(ValueError):
        backtest.run(session, sv["experimental"], sv["frozen-baseline"], date(2024, 1, 1), date(2023, 1, 1),
                     date(2023, 6, 1))


def test_backtest_entry_is_after_decision_date():
    dates = [date(2024, 1, d) for d in (2, 3, 4)]
    s = backtest.Series(dates, [1.0, 2.0, 3.0], [])
    assert s.idx_at(date(2024, 1, 3)) == 1
    assert s.idx_after(date(2024, 1, 3)) == 2  # decision on the 3rd enters on the 4th
    assert s.idx_after(date(2024, 1, 4)) is None


