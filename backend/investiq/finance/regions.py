"""Country -> region and currency reference mapping (ISO-3166 alpha-2)."""

from __future__ import annotations

EUROPE = {"GB", "DE", "FR", "NL", "CH", "SE", "DK", "NO", "FI", "IT", "ES", "BE", "IE", "AT", "PT", "LU", "IS"}
ASIA_DEVELOPED = {"JP", "HK", "SG", "AU", "NZ", "IL"}
EMERGING = {"CN", "IN", "TW", "KR", "BR", "MX", "ZA", "SA", "ID", "TH", "MY", "PH", "CL", "PE", "CO", "TR",
            "PL", "AE", "QA", "KW", "EG", "GR", "HU", "CZ", "VN", "AR"}

COUNTRY_CURRENCY = {
    "CA": "CAD", "US": "USD", "GB": "GBP", "CH": "CHF", "SE": "SEK", "DK": "DKK", "NO": "NOK", "JP": "JPY",
    "HK": "HKD", "SG": "SGD", "AU": "AUD", "NZ": "NZD", "IL": "ILS", "CN": "CNY", "IN": "INR", "TW": "TWD",
    "KR": "KRW", "BR": "BRL", "MX": "MXN", "ZA": "ZAR", "SA": "SAR",
}
EURO = {"DE", "FR", "NL", "IT", "ES", "BE", "IE", "AT", "PT", "LU", "FI", "GR"}


def region_of(country: str | None) -> str:
    if not country or country == "Unknown":
        return "unknown"
    c = country.upper()
    if c == "CA":
        return "canada"
    if c == "US":
        return "united_states"
    if c in EUROPE:
        return "europe"
    if c in ASIA_DEVELOPED:
        return "asia_pacific"
    if c in EMERGING:
        return "emerging_markets"
    return "other"


def currency_of(country: str | None) -> str | None:
    if not country:
        return None
    c = country.upper()
    if c in EURO:
        return "EUR"
    return COUNTRY_CURRENCY.get(c)
