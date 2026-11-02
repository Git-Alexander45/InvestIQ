"""Financial Modeling Prep adapter (https://site.financialmodelingprep.com/developer/docs).

Requires INVESTIQ_FMP_API_KEY. Plan entitlements (real-time vs delayed/end-of-day quotes,
international coverage, ETF holdings) vary by subscription; InvestIQ labels quotes as
"delayed" unless INVESTIQ_FMP_REALTIME=true is explicitly configured by the owner.
Field names are mapped defensively because FMP has evolved its API ("stable" vs v3).
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime, time
from typing import Any

from investiq.data.providers.base import (
    BarDTO,
    BarsResult,
    DividendDTO,
    FundamentalsDTO,
    HoldingDTO,
    HoldingsDTO,
    InstrumentRef,
    NewsDTO,
    ProviderError,
    ProviderNotConfigured,
    ProviderUnsupported,
    QuoteDTO,
    SplitDTO,
)
from investiq.data.providers.http import HttpClient
from investiq.data.providers.symbols import suffixed

BASE = "https://financialmodelingprep.com/stable"
INTRADAY = {"1min": "1min", "5min": "5min", "15min": "15min", "1h": "1hour"}


def _first(d: dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None


def _f(v: Any) -> float | None:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _d(v: Any) -> date | None:
    if not v:
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def _list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [p for p in payload if isinstance(p, dict)]
    if isinstance(payload, dict):
        if "Error Message" in payload or "error" in payload:
            raise ProviderError(f"FMP error: {payload.get('Error Message') or payload.get('error')}")
        for key in ("historical", "data", "results"):
            if isinstance(payload.get(key), list):
                return payload[key]
        return [payload]
    return []


class FmpProvider:
    name = "fmp"
    supported_intervals = ("1min", "5min", "15min", "1h", "1d")

    def __init__(self, api_key: str | None, http: HttpClient | None = None, realtime: bool | None = None) -> None:
        if not api_key:
            raise ProviderNotConfigured("Financial Modeling Prep needs INVESTIQ_FMP_API_KEY")
        self._key = api_key
        self._http = http or HttpClient(min_interval_s=0.25)
        self._realtime = realtime if realtime is not None else os.environ.get("INVESTIQ_FMP_REALTIME") == "true"

    def _get(self, path: str, **params: Any) -> list[dict[str, Any]]:
        params["apikey"] = self._key
        return _list(self._http.get_json(f"{BASE}/{path}", params))

    # ---- prices -------------------------------------------------------------------------
    def bars(self, ref: InstrumentRef, interval: str, start: date, end: date) -> BarsResult:
        sym = suffixed(ref, "fmp")
        if interval == "1d":
            rows = self._get("historical-price-eod/full", symbol=sym, **{"from": start.isoformat(), "to": end.isoformat()})
            bars = []
            for r in rows:
                d = _d(r.get("date"))
                o, h, lo, c = (_f(r.get(k)) for k in ("open", "high", "low", "close"))
                if d is None or None in (o, h, lo, c):
                    continue
                bars.append(BarDTO(datetime.combine(d, time(0), UTC), o, h, lo, c, _f(r.get("volume")),
                                   _f(_first(r, "adjClose", "adjustedClose"))))
            status = "end_of_day"
        elif interval in INTRADAY:
            rows = self._get(f"historical-chart/{INTRADAY[interval]}", symbol=sym,
                             **{"from": start.isoformat(), "to": end.isoformat()})
            bars = []
            for r in rows:
                try:
                    ts = datetime.fromisoformat(str(r["date"])).replace(tzinfo=UTC)  # FMP intraday is exchange time
                except (KeyError, ValueError):
                    continue
                o, h, lo, c = (_f(r.get(k)) for k in ("open", "high", "low", "close"))
                if None in (o, h, lo, c):
                    continue
                bars.append(BarDTO(ts, o, h, lo, c, _f(r.get("volume"))))
            status = "live" if self._realtime else "delayed"
        else:
            raise ProviderUnsupported(f"FMP interval {interval} not supported")
        bars.sort(key=lambda b: b.ts)
        return BarsResult(bars, interval, ref.currency, self.name, status)

    def quote(self, ref: InstrumentRef) -> QuoteDTO:
        rows = self._get("quote", symbol=suffixed(ref, "fmp"))
        if not rows or _f(rows[0].get("price")) is None:
            raise ProviderError(f"FMP returned no quote for {ref.symbol}")
        r = rows[0]
        ts = r.get("timestamp")
        as_of = datetime.fromtimestamp(int(ts), UTC) if ts else datetime.now(UTC)
        return QuoteDTO(float(r["price"]), ref.currency, as_of, self.name, "live" if self._realtime else "delayed")

    # ---- fundamentals -------------------------------------------------------------------
    def fundamentals(self, ref: InstrumentRef) -> FundamentalsDTO:
        sym = suffixed(ref, "fmp")
        profile = (self._get("profile", symbol=sym) or [{}])[0]
        income = sorted(self._get("income-statement", symbol=sym, period="annual", limit=6), key=lambda r: r.get("date", ""))
        balance = sorted(self._get("balance-sheet-statement", symbol=sym, period="annual", limit=2),
                         key=lambda r: r.get("date", ""))
        cash = sorted(self._get("cash-flow-statement", symbol=sym, period="annual", limit=6), key=lambda r: r.get("date", ""))
        ratios = (self._get("ratios-ttm", symbol=sym) or [{}])[0]
        km = (self._get("key-metrics-ttm", symbol=sym) or [{}])[0]

        def hist(rows: list[dict[str, Any]], *keys: str) -> list[dict[str, Any]]:
            out = []
            for r in rows:
                v = _f(_first(r, *keys))
                y = _first(r, "fiscalYear", "calendarYear") or str(r.get("date", ""))[:4]
                if v is not None and y:
                    out.append({"year": int(y), "value": v})
            return out

        bal = balance[-1] if balance else {}
        inc = income[-1] if income else {}
        metrics: dict[str, Any] = {
            "revenue_history": hist(income, "revenue"),
            "eps_history": hist(income, "epsDiluted", "epsdiluted", "eps"),
            "gross_profit_history": hist(income, "grossProfit"),
            "operating_income_history": hist(income, "operatingIncome"),
            "fcf_history": hist(cash, "freeCashFlow"),
            "net_income": _f(inc.get("netIncome")),
            "ebitda": _f(inc.get("ebitda")),
            "interest_expense": _f(inc.get("interestExpense")),
            "shares_outstanding": _f(_first(inc, "weightedAverageShsOutDil", "weightedAverageShsOut")),
            "total_debt": _f(bal.get("totalDebt")),
            "cash": _f(_first(bal, "cashAndCashEquivalents", "cashAndShortTermInvestments")),
            "total_equity": _f(_first(bal, "totalStockholdersEquity", "totalEquity")),
            "current_assets": _f(bal.get("totalCurrentAssets")),
            "current_liabilities": _f(bal.get("totalCurrentLiabilities")),
            "market_cap": _f(_first(profile, "marketCap", "mktCap")) or _f(km.get("marketCap")),
            "beta": _f(profile.get("beta")),
            "pe_ttm": _f(_first(ratios, "priceToEarningsRatioTTM", "peRatioTTM")),
            "ev_ebitda": _f(_first(ratios, "enterpriseValueMultipleTTM")) or _f(km.get("evToEBITDATTM")),
        }
        roic = _f(_first(km, "returnOnInvestedCapitalTTM", "roicTTM"))
        if roic is not None:
            metrics["roic_pct"] = roic * 100 if abs(roic) < 5 else roic
        dy = _f(_first(ratios, "dividendYieldTTM", "dividendYielTTM"))
        if dy is not None:
            metrics["dividend_yield_pct"] = dy * 100 if dy < 1 else dy
        payout = _f(_first(ratios, "dividendPayoutRatioTTM", "payoutRatioTTM"))
        if payout is not None:
            metrics["payout_ratio_pct"] = payout * 100 if payout < 5 else payout
        filing = max((_d(_first(r, "filingDate", "acceptedDate", "fillingDate")) or date.min for r in income + balance),
                     default=date.min)
        as_of = datetime.combine(filing, time(0), UTC) if filing != date.min else datetime.now(UTC)
        if profile.get("isEtf") or profile.get("isFund"):
            metrics.update(self._etf_info(sym))
        return FundamentalsDTO(
            metrics={k: v for k, v in metrics.items() if v not in (None, [])},
            currency=_first(inc, "reportedCurrency") or profile.get("currency"),
            period_end=_d(inc.get("date")), as_of=as_of, source=self.name,
            profile={"name": profile.get("companyName"), "sector": profile.get("sector"),
                     "industry": profile.get("industry"), "country": profile.get("country"),
                     "currency": profile.get("currency"), "is_etf": bool(profile.get("isEtf"))},
        )

    def _etf_info(self, sym: str) -> dict[str, Any]:
        info = (self._get("etf/info", symbol=sym) or [{}])[0]
        er = _f(_first(info, "expenseRatio"))
        return {k: v for k, v in {
            "expense_ratio_pct": er,
            "aum": _f(_first(info, "assetsUnderManagement", "aum")),
            "holdings_count": _f(_first(info, "holdingsCount")),
        }.items() if v is not None}

    # ---- ETF holdings -----------------------------------------------------------------------
    def holdings(self, ref: InstrumentRef) -> HoldingsDTO:
        rows = self._get("etf/holdings", symbol=suffixed(ref, "fmp"))
        holdings = []
        as_of = None
        for r in rows:
            w = _f(_first(r, "weightPercentage", "weight"))
            name = _first(r, "name", "asset")
            if w is None or not name:
                continue
            holdings.append(HoldingDTO(name=str(name), weight_pct=w, symbol=_first(r, "asset", "symbolHolding")))
            as_of = as_of or _d(_first(r, "updatedAt", "updated", "date"))
        if not holdings:
            raise ProviderError(f"FMP returned no holdings for {ref.symbol}")
        return HoldingsDTO(holdings, as_of or date.today(), self.name)

    # ---- corporate actions ------------------------------------------------------------------
    def dividends(self, ref: InstrumentRef, start: date, end: date) -> list[DividendDTO]:
        out = []
        for r in self._get("dividends", symbol=suffixed(ref, "fmp")):
            ex = _d(_first(r, "date", "exDividendDate"))
            amt = _f(_first(r, "dividend", "adjDividend"))
            if ex and amt and start <= ex <= end:
                out.append(DividendDTO(ex, amt, ref.currency, _d(r.get("paymentDate"))))
        return out

    def splits(self, ref: InstrumentRef, start: date, end: date) -> list[SplitDTO]:
        out = []
        for r in self._get("splits", symbol=suffixed(ref, "fmp")):
            d = _d(r.get("date"))
            num, den = _f(r.get("numerator")), _f(r.get("denominator"))
            if d and num and den and start <= d <= end:
                out.append(SplitDTO(d, num / den))
        return out

    # ---- company news (licensed provider feed) -------------------------------------------------
    def company_news(self, symbols: list[str], limit: int = 50) -> list[NewsDTO]:
        if not symbols:
            return []
        rows = self._get("news/stock", symbols=",".join(symbols[:50]), limit=limit)
        out = []
        for r in rows:
            url, title = r.get("url"), r.get("title")
            if not url or not title:
                continue
            published = None
            if r.get("publishedDate"):
                try:
                    published = datetime.fromisoformat(str(r["publishedDate"]).replace("Z", "+00:00"))
                    if published.tzinfo is None:
                        published = published.replace(tzinfo=UTC)
                except ValueError:
                    published = None
            text = (r.get("text") or "")[:400] or None
            out.append(NewsDTO(url=url, title=title, summary=text, published_at=published,
                               source_key=f"fmp:{r.get('site') or r.get('publisher') or 'news'}",
                               category="company", official=False,
                               symbols=[s for s in [r.get("symbol")] if s]))
        return out
