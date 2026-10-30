"""Currency conversion with provenance. Rates are daily reference rates unless stated."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class FxQuote:
    base: str
    quote: str
    rate: float  # 1 base = rate quote
    as_of: date
    source: str
    rate_type: str = "daily_reference"

    def inverse(self) -> FxQuote:
        return FxQuote(self.quote, self.base, 1.0 / self.rate, self.as_of, self.source, self.rate_type)


class MissingFxRate(LookupError):
    pass


class FxTable:
    """Holds the latest known rate per currency pair, converting via CAD when needed."""

    def __init__(self, quotes: list[FxQuote] | None = None) -> None:
        self._rates: dict[tuple[str, str], FxQuote] = {}
        for q in quotes or []:
            self.add(q)

    def add(self, q: FxQuote) -> None:
        if q.rate <= 0:
            raise ValueError("FX rate must be positive")
        key = (q.base, q.quote)
        existing = self._rates.get(key)
        if existing is None or q.as_of >= existing.as_of:
            self._rates[key] = q
            self._rates[(q.quote, q.base)] = q.inverse()

    def get(self, base: str, quote: str) -> FxQuote:
        base, quote = base.upper(), quote.upper()
        if base == quote:
            return FxQuote(base, quote, 1.0, date.min, "identity", "identity")
        if (base, quote) in self._rates:
            return self._rates[(base, quote)]
        # Cross via CAD (Bank of Canada publishes everything against CAD).
        if (base, "CAD") in self._rates and ("CAD", quote) in self._rates:
            a, b = self._rates[(base, "CAD")], self._rates[("CAD", quote)]
            return FxQuote(base, quote, a.rate * b.rate, min(a.as_of, b.as_of), f"{a.source} (cross via CAD)",
                           a.rate_type)
        raise MissingFxRate(f"No FX rate for {base}/{quote}")

    def convert(self, amount: float, from_ccy: str, to_ccy: str) -> tuple[float, FxQuote]:
        q = self.get(from_ccy, to_ccy)
        return amount * q.rate, q
