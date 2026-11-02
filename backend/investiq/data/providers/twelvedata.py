"""Twelve Data adapter (https://twelvedata.com/docs) for prices.

Requires INVESTIQ_TWELVEDATA_API_KEY. Free plans are rate limited (credits per minute/day) and
market coverage/real-time entitlements depend on the plan; quotes are labelled "delayed" unless
INVESTIQ_TWELVEDATA_REALTIME=true is explicitly configured.
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime

from investiq.data.providers.base import (
    BarDTO,
    BarsResult,
    InstrumentRef,
    ProviderError,
    ProviderNotConfigured,
    ProviderUnsupported,
    QuoteDTO,
)
from investiq.data.providers.http import HttpClient
from investiq.data.providers.symbols import TWELVEDATA_EXCHANGE

BASE = "https://api.twelvedata.com"
INTERVALS = {"1min": "1min", "5min": "5min", "15min": "15min", "1h": "1h", "1d": "1day", "1wk": "1week",
             "1mo": "1month"}


class TwelveDataProvider:
    name = "twelvedata"
    supported_intervals = tuple(INTERVALS)

    def __init__(self, api_key: str | None, http: HttpClient | None = None, realtime: bool | None = None) -> None:
        if not api_key:
            raise ProviderNotConfigured("Twelve Data needs INVESTIQ_TWELVEDATA_API_KEY")
        self._key = api_key
        self._http = http or HttpClient(min_interval_s=8.0)  # free tier: 8 requests/minute
        self._realtime = realtime if realtime is not None else os.environ.get("INVESTIQ_TWELVEDATA_REALTIME") == "true"

    def _params(self, ref: InstrumentRef, **extra) -> dict:
        params = {"symbol": ref.provider_symbols.get("twelvedata", ref.symbol), "apikey": self._key, **extra}
        ex = TWELVEDATA_EXCHANGE.get(ref.exchange)
        if ex:
            params["exchange"] = ex
        return params

    def bars(self, ref: InstrumentRef, interval: str, start: date, end: date) -> BarsResult:
        if interval not in INTERVALS:
            raise ProviderUnsupported(interval)
        data = self._http.get_json(f"{BASE}/time_series", self._params(
            ref, interval=INTERVALS[interval], start_date=start.isoformat(), end_date=end.isoformat(),
            outputsize=5000, order="ASC", timezone="UTC"))
        if not isinstance(data, dict) or data.get("status") == "error":
            raise ProviderError(f"Twelve Data error: {data.get('message') if isinstance(data, dict) else data}")
        bars = []
        for v in data.get("values", []):
            try:
                ts = datetime.fromisoformat(v["datetime"])
                ts = ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts
                bars.append(BarDTO(ts, float(v["open"]), float(v["high"]), float(v["low"]), float(v["close"]),
                                   float(v["volume"]) if v.get("volume") not in (None, "") else None))
            except (KeyError, ValueError):
                continue
        currency = (data.get("meta") or {}).get("currency") or ref.currency
        status = "end_of_day" if interval in ("1d", "1wk", "1mo") else ("live" if self._realtime else "delayed")
        return BarsResult(bars, interval, currency, self.name, status)

    def quote(self, ref: InstrumentRef) -> QuoteDTO:
        data = self._http.get_json(f"{BASE}/quote", self._params(ref))
        if not isinstance(data, dict) or data.get("status") == "error" or "close" not in data:
            raise ProviderError("Twelve Data returned no quote")
        ts = data.get("last_quote_at") or data.get("timestamp")
        as_of = datetime.fromtimestamp(int(ts), UTC) if ts else datetime.now(UTC)
        return QuoteDTO(float(data["close"]), data.get("currency") or ref.currency, as_of, self.name,
                        "live" if self._realtime else "delayed")
