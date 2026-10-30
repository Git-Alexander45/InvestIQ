"""Walk-forward historical backtest of a strategy version against a baseline.

Bias controls:
* Look-ahead: at each rebalance date only fundamentals with as_of <= date and bars <= date are used;
  positions are entered at the first close AFTER the decision date.
* Survivorship: the universe at each date is every instrument listed then, including instruments
  that were later delisted (``delisted_on``); a delisted holding exits at its last available price.
* Overfitting / selective reporting: the in-sample/out-of-sample split is fixed up front, the
  number of variants tested is recorded with every run, and every run is stored (pass or fail).
* AI and news inputs are excluded: they are not reproducible point-in-time, so the backtest
  measures the quantitative scoring only.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from investiq.data import repository as repo
from investiq.data.stats import price_stats
from investiq.finance.fundamentals import derive
from investiq.finance.returns import annualized_volatility, cagr, max_drawdown, sharpe_ratio
from investiq.models import BacktestRun, FundamentalsSnapshot, Instrument, PriceBar, StrategyVersion
from investiq.research.facts import info
from investiq.scoring.engine import Facts, score

MIN_OOS_DAYS = 180


@dataclass
class Series:
    dates: list[date]
    closes: list[float]
    bars: list[PriceBar]

    def idx_at(self, d: date) -> int:
        """Index of the last bar on or before d (-1 if none)."""
        return bisect.bisect_right(self.dates, d) - 1

    def idx_after(self, d: date) -> int | None:
        i = bisect.bisect_right(self.dates, d)
        return i if i < len(self.dates) else None


def _load(session: Session, instruments: list[Instrument], end: date) -> dict[int, Series]:
    out = {}
    for inst in instruments:
        bars = repo.daily_bars(session, inst.id, datetime.combine(end, time.max, UTC), lookback_days=365 * 30)
        if bars:
            out[inst.id] = Series([b.ts.date() for b in bars], [b.adj_close or b.close for b in bars], bars)
    return out


def _fundamentals(session: Session, inst_ids: list[int]) -> dict[int, list[FundamentalsSnapshot]]:
    rows = session.execute(select(FundamentalsSnapshot).where(FundamentalsSnapshot.instrument_id.in_(inst_ids))
                           .order_by(FundamentalsSnapshot.as_of)).scalars()
    out: dict[int, list[FundamentalsSnapshot]] = {}
    for r in rows:
        out.setdefault(r.instrument_id, []).append(r)
    return out


def _select(session: Session, config: dict[str, Any], universe: list[Instrument], series: dict[int, Series],
            funds: dict[int, list[FundamentalsSnapshot]], d: date, top_n: int) -> list[int]:
    as_of = datetime.combine(d, time.max, UTC)
    ranked = []
    for inst in universe:
        s = series.get(inst.id)
        if s is None:
            continue
        i = s.idx_at(d)
        if i < 60:
            continue
        snaps = [f for f in funds.get(inst.id, []) if f.as_of <= as_of]
        fs = snaps[-1] if snaps else None
        facts = Facts(info(inst), as_of, fundamentals=derive(fs.metrics) if fs else None,
                      fundamentals_source=fs.source if fs else None, fundamentals_as_of=fs.as_of if fs else None,
                      price_stats=price_stats(s.bars[max(0, i - 1300): i + 1], as_of))
        r = score(facts, config)
        if r.avoid_reasons or r.coverage < 0.5 or r.overall < 70:
            continue
        ranked.append((r.overall, inst.id))
    ranked.sort(reverse=True)
    return [i for _, i in ranked[:top_n]]


def _simulate(session: Session, config: dict[str, Any], universe: list[Instrument], series: dict[int, Series],
              funds: dict[int, list[FundamentalsSnapshot]], dates: list[date], top_n: int, end: date
              ) -> tuple[list[tuple[date, float]], list[dict[str, Any]]]:
    equity = 1.0
    curve: list[tuple[date, float]] = []
    log: list[dict[str, Any]] = []
    for k, d in enumerate(dates):
        nxt = dates[k + 1] if k + 1 < len(dates) else end
        listed = [u for u in universe if (u.listed_on is None or u.listed_on <= d) and
                  (u.delisted_on is None or u.delisted_on > d)]
        picks = _select(session, config, listed, series, funds, d, top_n)
        period_rets = []
        for inst_id in picks:
            s = series[inst_id]
            i0 = s.idx_after(d)  # enter at the first close after the decision date
            i1 = s.idx_at(nxt)
            if i0 is None or i1 < i0:
                continue
            period_rets.append(s.closes[i1] / s.closes[i0] - 1)
        r = float(np.mean(period_rets)) if period_rets else 0.0  # no picks -> stay in cash
        equity *= 1 + r
        curve.append((nxt, equity))
        log.append({"date": d.isoformat(), "picks": picks, "period_return": r})
    return curve, log


def _metrics(curve: list[tuple[date, float]], start_value: float, start: date) -> dict[str, Any]:
    if not curve:
        return {"periods": 0}
    values = [start_value] + [v for _, v in curve]
    rets = np.diff(values) / np.asarray(values[:-1])
    end_d = curve[-1][0]
    a = cagr(values[0], values[-1], start, end_d)
    per_year = max(1, round(len(rets) / max((end_d - start).days / 365.25, 1e-9)))
    vol = annualized_volatility(rets, per_year) if len(rets) > 2 else None
    sh = sharpe_ratio(rets, 0.0, per_year) if len(rets) > 2 else None
    return {"periods": len(rets), "start": start.isoformat(), "end": end_d.isoformat(),
            "total_return_pct": round((values[-1] / values[0] - 1) * 100, 4),
            "cagr_pct": None if a is None else round(a * 100, 4),
            "volatility_pct": None if vol is None else round(vol * 100, 4),
            "sharpe": None if sh is None else round(sh, 4), "max_drawdown_pct": round(max_drawdown(values) * 100, 4)}


def _split(curve: list[tuple[date, float]], split: date, start: date) -> tuple[dict, dict]:
    ins = [(d, v) for d, v in curve if d <= split]
    oos = [(d, v) for d, v in curve if d > split]
    in_m = _metrics(ins, 1.0, start)
    base = ins[-1][1] if ins else 1.0
    oos_m = _metrics([(d, v / base) for d, v in oos], 1.0, split)
    return in_m, oos_m


def run(session: Session, strategy: StrategyVersion, baseline: StrategyVersion, start: date, end: date, split: date,
        rebalance_days: int = 30, top_n: int = 10) -> BacktestRun:
    if not start < split < end:
        raise ValueError("require start < split < end")
    universe = list(session.execute(select(Instrument)).scalars())
    series = _load(session, universe, end)
    funds = _fundamentals(session, [u.id for u in universe])
    dates, d = [], start
    while d < end:
        dates.append(d)
        d += timedelta(days=rebalance_days)
    strat_curve, strat_log = _simulate(session, strategy.config, universe, series, funds, dates, top_n, end)
    base_curve, _ = _simulate(session, baseline.config, universe, series, funds, dates, top_n, end)
    s_in, s_oos = _split(strat_curve, split, start)
    b_in, b_oos = _split(base_curve, split, start)
    for m, b in ((s_in, b_in), (s_oos, b_oos)):
        if m.get("total_return_pct") is not None and b.get("total_return_pct") is not None:
            m["excess_vs_baseline_pct"] = round(m["total_return_pct"] - b["total_return_pct"], 4)
        m["baseline"] = b
    variants = session.execute(select(func.count(StrategyVersion.id)).where(StrategyVersion.kind == "experimental")).scalar_one()
    notes: list[str] = []
    passed = True
    if (end - split).days < MIN_OOS_DAYS:
        passed = False
        notes.append(f"out-of-sample period shorter than {MIN_OOS_DAYS} days")
    if (s_oos.get("excess_vs_baseline_pct") or 0) <= 0:
        passed = False
        notes.append("did not beat the frozen baseline out of sample")
    if (s_in.get("excess_vs_baseline_pct") or 0) <= 0:
        passed = False
        notes.append("did not beat the baseline in sample either")
    if s_oos.get("sharpe") is not None and b_oos.get("sharpe") is not None and s_oos["sharpe"] < b_oos["sharpe"] - 0.1:
        passed = False
        notes.append("worse risk-adjusted return than baseline out of sample")
    if strategy.id == baseline.id:
        passed = False
        notes.append("strategy is the baseline itself")
    if variants > 5:
        notes.append(f"{variants} experimental variants exist: beware of multiple-testing / overfitting")
    if not funds:
        notes.append("no fundamentals history stored: scores rely on price data only")
    sources = sorted({s.bars[-1].source for s in series.values()})
    run_row = BacktestRun(strategy_version_id=strategy.id, baseline_strategy_version_id=baseline.id, start_date=start,
                          end_date=end, split_date=split,
                          parameters={"rebalance_days": rebalance_days, "top_n": top_n, "universe_size": len(universe),
                                      "selection": "top-N by overall score, coverage>=50%, grade>=C, equal weight",
                                      "log_tail": strat_log[-3:]},
                          in_sample=s_in, out_of_sample=s_oos, variants_tested=int(variants), passed_validation=passed,
                          validation_notes=notes, data_sources=sources)
    session.add(run_row)
    session.flush()
    return run_row
