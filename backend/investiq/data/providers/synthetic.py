"""Deterministic synthetic data for development and automated tests ONLY.

Every record produced here is labelled data_status/quality "synthetic". The application refuses
to use this provider when INVESTIQ_ENV=production, and reports built from synthetic data carry a
prominent "SYNTHETIC DATA - NOT REAL MARKET INFORMATION" banner.
"""

from __future__ import annotations

import hashlib
import math
import random
from datetime import UTC, date, datetime, time, timedelta

from investiq.data.providers.base import (
    BarDTO,
    BarsResult,
    DividendDTO,
    FundamentalsDTO,
    HoldingDTO,
    HoldingsDTO,
    InstrumentRef,
    QuoteDTO,
    SplitDTO,
)
from investiq.finance.fx import FxQuote

SOURCE = "synthetic"


def _rng(*parts: str) -> random.Random:
    seed = int(hashlib.sha256("|".join(parts).encode()).hexdigest()[:16], 16)
    return random.Random(seed)  # noqa: S311 - not used for security


def _business_days(start: date, end: date) -> list[date]:
    days, d = [], start
    while d <= end:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


class SyntheticProvider:
    name = SOURCE
    supported_intervals = ("1d",)

    def __init__(self, anchor: date = date(2018, 1, 1), today: date | None = None) -> None:
        self.anchor = anchor
        self._today = today  # lets tests replay a past day without data "from the future"

    @property
    def today(self) -> date:
        return self._today or date.today()

    def _path(self, ref: InstrumentRef, end: date) -> list[tuple[date, float, float]]:
        rng = _rng("path", ref.symbol, ref.exchange)
        price = 20 + rng.random() * 180
        drift = (rng.random() * 0.18 - 0.03) / 252
        vol = (0.12 + rng.random() * 0.35) / math.sqrt(252)
        out = []
        for d in _business_days(self.anchor, end):
            shock = rng.gauss(0, 1)
            price = max(0.5, price * math.exp(drift - 0.5 * vol * vol + vol * shock))
            out.append((d, price, vol))
        return out

    def bars(self, ref: InstrumentRef, interval: str, start: date, end: date) -> BarsResult:
        bars = []
        rng = _rng("ohlc", ref.symbol)
        for d, close, vol in self._path(ref, end):
            if d < start:
                continue
            spread = close * vol * (0.5 + rng.random())
            open_ = close * (1 + rng.gauss(0, vol / 2))
            high = max(open_, close) + spread / 2
            low = max(0.01, min(open_, close) - spread / 2)
            bars.append(BarDTO(datetime.combine(d, time(21), UTC), open_, high, low, close,
                               float(int(1e5 + rng.random() * 5e6))))
        return BarsResult(bars, interval, ref.currency, SOURCE, "synthetic")

    def quote(self, ref: InstrumentRef) -> QuoteDTO:
        path = self._path(ref, self.today)
        d, close, _ = path[-1]
        return QuoteDTO(close, ref.currency, datetime.combine(d, time(21), UTC), SOURCE, "synthetic")

    def fundamentals(self, ref: InstrumentRef) -> FundamentalsDTO:
        rng = _rng("fund", ref.symbol)
        rev = 1e9 * (0.5 + rng.random() * 50)
        g = rng.uniform(-0.05, 0.35)
        years = list(range(self.today.year - 5, self.today.year))
        revenue = [{"year": y, "value": rev * (1 + g) ** i} for i, y in enumerate(years)]
        margin = rng.uniform(0.25, 0.75)
        op_margin = rng.uniform(-0.05, 0.35)
        fcf_margin = op_margin * rng.uniform(0.5, 1.1)
        shares = 1e8 * (1 + rng.random() * 20)
        eps = [{"year": r["year"], "value": r["value"] * op_margin * 0.8 / shares} for r in revenue]
        metrics = {
            "revenue_history": revenue,
            "eps_history": eps,
            "gross_profit_history": [{"year": r["year"], "value": r["value"] * (margin + rng.uniform(-0.02, 0.02))}
                                     for r in revenue],
            "operating_income_history": [{"year": r["year"], "value": r["value"] * op_margin} for r in revenue],
            "fcf_history": [{"year": r["year"], "value": r["value"] * fcf_margin} for r in revenue],
            "total_debt": revenue[-1]["value"] * rng.uniform(0, 1.2),
            "cash": revenue[-1]["value"] * rng.uniform(0.05, 0.5),
            "total_equity": revenue[-1]["value"] * rng.uniform(0.3, 1.5),
            "current_assets": revenue[-1]["value"] * rng.uniform(0.3, 0.9),
            "current_liabilities": revenue[-1]["value"] * rng.uniform(0.2, 0.6),
            "interest_expense": revenue[-1]["value"] * rng.uniform(0.001, 0.03),
            "ebitda": revenue[-1]["value"] * (op_margin + 0.05),
            "net_income": revenue[-1]["value"] * op_margin * 0.8,
            "shares_outstanding": shares,
            "market_cap": revenue[-1]["value"] * rng.uniform(1, 12),
            "pe_ttm": rng.uniform(8, 60),
            "ev_ebitda": rng.uniform(5, 35),
            "roic_pct": rng.uniform(-5, 35),
            "dividend_yield_pct": max(0.0, rng.uniform(-1.5, 4.5)),
            "dividend_per_share_history": [{"year": y, "value": 1 + 0.07 * i} for i, y in enumerate(years)],
        }
        if ref.symbol.startswith(("X", "V", "Z")):
            metrics.update({"expense_ratio_pct": round(rng.uniform(0.05, 0.6), 2), "aum": rng.uniform(1e8, 2e10),
                            "holdings_count": float(int(rng.uniform(25, 9000)))})
        return FundamentalsDTO(metrics, ref.currency, date(years[-1], 12, 31),
                               datetime.combine(min(date(years[-1] + 1, 2, 15), self.today), time(0), UTC), SOURCE,
                               profile={"country": "CA" if ref.exchange == "TSX" else "US"})

    def holdings(self, ref: InstrumentRef) -> HoldingsDTO:
        rng = _rng("hold", ref.symbol)
        pool = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "RY", "TD", "SHOP", "ENB", "ASML", "NESN", "TSM",
                "JPM", "LLY", "XOM", "BRK.B", "CNR", "SAP", "TM"]
        picks = rng.sample(pool, 12)
        raw = [rng.random() ** 2 for _ in picks]
        scale = rng.uniform(40, 95) / sum(raw)
        sectors = ["Technology", "Financials", "Energy", "Health Care", "Industrials"]
        countries = ["US", "CA", "NL", "JP", "CH", "TW"]
        hs = [HoldingDTO(name=p, symbol=p, weight_pct=round(w * scale, 3), sector=rng.choice(sectors),
                         country=rng.choice(countries)) for p, w in zip(picks, raw, strict=True)]
        return HoldingsDTO(hs, self.today, SOURCE)

    def dividends(self, ref: InstrumentRef, start: date, end: date) -> list[DividendDTO]:
        rng = _rng("div", ref.symbol)
        if rng.random() < 0.3:
            return []
        out, d = [], date(start.year, 3, 15)
        amt = 0.1 + rng.random()
        while d <= end:
            if d >= start:
                out.append(DividendDTO(d, round(amt, 4), ref.currency, d + timedelta(days=14)))
            d = date(d.year + (d.month + 3 > 12), (d.month + 3 - 1) % 12 + 1, 15)
        return out

    def splits(self, ref: InstrumentRef, start: date, end: date) -> list[SplitDTO]:
        return []

    def rates(self, currencies: list[str], start: date, end: date) -> list[FxQuote]:
        out = []
        for c in currencies:
            rng = _rng("fx", c)
            base = {"USD": 1.36, "EUR": 1.48, "GBP": 1.72, "JPY": 0.0092}.get(c, 0.5 + rng.random())
            for i, d in enumerate(_business_days(start, end)):
                out.append(FxQuote(c, "CAD", round(base * (1 + 0.02 * math.sin(i / 40)), 6), d, SOURCE, "synthetic"))
        return out
