"""Provider-neutral data transfer objects and interfaces.

Every value carries its source, timestamp, currency and live/delayed status. Providers return
what they actually received and never fill gaps with invented numbers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Protocol

INTERVALS = ("1min", "5min", "15min", "1h", "1d", "1wk", "1mo")


class ProviderError(RuntimeError):
    """A provider call failed (network, HTTP status, malformed payload)."""


class ProviderNotConfigured(ProviderError):
    """The provider needs configuration (e.g. an API key) that is not present."""


class ProviderUnsupported(ProviderError):
    """The provider does not offer this dataset / interval / market."""


@dataclass(frozen=True)
class InstrumentRef:
    symbol: str
    exchange: str
    currency: str
    provider_symbols: dict[str, str] = field(default_factory=dict)


@dataclass
class BarDTO:
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None
    adj_close: float | None = None


@dataclass
class BarsResult:
    bars: list[BarDTO]
    interval: str
    currency: str
    source: str
    data_status: str  # live, delayed, end_of_day, synthetic


@dataclass
class QuoteDTO:
    price: float
    currency: str
    as_of: datetime
    source: str
    data_status: str


@dataclass
class FundamentalsDTO:
    metrics: dict[str, Any]
    currency: str | None
    period_end: date | None
    as_of: datetime  # when the information was published/available (filing date when known)
    source: str
    profile: dict[str, Any] = field(default_factory=dict)  # sector, industry, country, name


@dataclass
class HoldingDTO:
    name: str
    weight_pct: float
    symbol: str | None = None
    sector: str | None = None
    country: str | None = None
    currency: str | None = None
    asset_class: str | None = None


@dataclass
class HoldingsDTO:
    holdings: list[HoldingDTO]
    as_of: date
    source: str


@dataclass
class DividendDTO:
    ex_date: date
    amount: float
    currency: str
    pay_date: date | None = None


@dataclass
class SplitDTO:
    effective_date: date
    ratio: float  # new shares per old share


@dataclass
class NewsDTO:
    url: str
    title: str
    summary: str | None
    published_at: datetime | None
    source_key: str
    category: str | None
    official: bool
    symbols: list[str] = field(default_factory=list)


class PriceProvider(Protocol):
    name: str
    supported_intervals: tuple[str, ...]

    def bars(self, ref: InstrumentRef, interval: str, start: date, end: date) -> BarsResult: ...
    def quote(self, ref: InstrumentRef) -> QuoteDTO: ...


class FundamentalsProvider(Protocol):
    name: str

    def fundamentals(self, ref: InstrumentRef) -> FundamentalsDTO: ...


class HoldingsProvider(Protocol):
    name: str

    def holdings(self, ref: InstrumentRef) -> HoldingsDTO: ...


class CorporateActionsProvider(Protocol):
    name: str

    def dividends(self, ref: InstrumentRef, start: date, end: date) -> list[DividendDTO]: ...
    def splits(self, ref: InstrumentRef, start: date, end: date) -> list[SplitDTO]: ...


class NewsProvider(Protocol):
    name: str

    def fetch(self, since: datetime | None) -> list[NewsDTO]: ...
