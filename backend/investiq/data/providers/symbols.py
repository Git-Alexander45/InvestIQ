"""Exchange-specific ticker formats used by data providers."""

from __future__ import annotations

from investiq.data.providers.base import InstrumentRef

# Yahoo/FMP-style suffixes for non-US listings.
SUFFIX = {
    "TSX": ".TO", "TSXV": ".V", "NEO": ".NE", "CBOE_CA": ".NE", "CSE": ".CN", "LSE": ".L", "XETRA": ".DE",
    "FWB": ".F", "EURONEXT": ".PA", "SIX": ".SW", "TSE": ".T", "HKEX": ".HK", "ASX": ".AX", "SGX": ".SI",
}
US_EXCHANGES = {"NYSE", "NASDAQ", "NYSEARCA", "NYSEAMERICAN", "CBOE_US", "BATS"}
# Twelve Data exchange names / MIC-like codes.
TWELVEDATA_EXCHANGE = {"TSX": "TSX", "TSXV": "TSXV", "NEO": "NEO", "CBOE_CA": "NEO", "NYSE": "NYSE",
                       "NASDAQ": "NASDAQ", "NYSEARCA": "NYSE", "LSE": "LSE", "XETRA": "XETR", "TSE": "JPX"}


def suffixed(ref: InstrumentRef, provider: str) -> str:
    if provider in ref.provider_symbols:
        return ref.provider_symbols[provider]
    base = ref.symbol.replace(".", "-") if ref.exchange in US_EXCHANGES else ref.symbol.replace(".", "-")
    if ref.exchange in US_EXCHANGES:
        return base
    return base + SUFFIX.get(ref.exchange, "")
