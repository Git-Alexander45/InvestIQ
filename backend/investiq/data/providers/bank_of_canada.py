"""Bank of Canada Valet API (https://www.bankofcanada.ca/valet/docs): daily reference FX rates.

No API key. These are indicative daily averages published once per business day, NOT live
trading rates; every converted amount carries that label.
"""

from __future__ import annotations

from datetime import date

from investiq.data.providers.base import ProviderError
from investiq.data.providers.http import HttpClient
from investiq.finance.fx import FxQuote

BASE = "https://www.bankofcanada.ca/valet/observations"
SUPPORTED = ("USD", "EUR", "GBP", "JPY", "CHF", "AUD", "HKD", "CNY", "INR", "MXN", "SEK", "NOK", "SGD", "KRW",
             "TWD", "ZAR", "BRL", "NZD")
SOURCE = "Bank of Canada daily exchange rate"


class BankOfCanadaFx:
    name = "bank_of_canada"

    def __init__(self, http: HttpClient | None = None) -> None:
        self._http = http or HttpClient(min_interval_s=0.5)

    def rates(self, currencies: list[str], start: date, end: date) -> list[FxQuote]:
        wanted = [c for c in currencies if c in SUPPORTED]
        if not wanted:
            return []
        series = ",".join(f"FX{c}CAD" for c in wanted)
        data = self._http.get_json(f"{BASE}/{series}/json",
                                   {"start_date": start.isoformat(), "end_date": end.isoformat()})
        if not isinstance(data, dict) or "observations" not in data:
            raise ProviderError("Bank of Canada response missing observations")
        out: list[FxQuote] = []
        for obs in data["observations"]:
            d = date.fromisoformat(obs["d"])
            for c in wanted:
                cell = obs.get(f"FX{c}CAD")
                if cell and cell.get("v") not in (None, ""):
                    out.append(FxQuote(c, "CAD", float(cell["v"]), d, SOURCE, "daily_reference"))
        return out
