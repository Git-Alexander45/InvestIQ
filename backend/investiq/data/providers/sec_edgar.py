"""SEC EDGAR XBRL "company facts" (https://www.sec.gov/edgar/sec-api-documentation).

Free and official, US filers only. Requires INVESTIQ_SEC_USER_AGENT ("Name email@example.com")
per SEC fair-access policy (max 10 requests/second). Values are taken from annual (10-K)
filings and stamped with their *filing date*, which makes them point-in-time for backtests.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, time
from typing import Any

from investiq.data.providers.base import FundamentalsDTO, InstrumentRef, ProviderError, ProviderNotConfigured
from investiq.data.providers.http import HttpClient

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"

TAGS = {
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"],
    "eps": ["EarningsPerShareDiluted"],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss"],
    "ocf": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment"],
    "debt": ["LongTermDebt", "LongTermDebtNoncurrent"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue"],
    "equity": ["StockholdersEquity"],
    "current_assets": ["AssetsCurrent"],
    "current_liabilities": ["LiabilitiesCurrent"],
    "interest": ["InterestExpense"],
    "shares": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
}


class SecEdgarFundamentals:
    name = "sec_edgar"

    def __init__(self, user_agent: str | None, http: HttpClient | None = None) -> None:
        if not user_agent:
            raise ProviderNotConfigured("SEC EDGAR needs INVESTIQ_SEC_USER_AGENT ('Name email')")
        self._http = http or HttpClient(user_agent=user_agent, min_interval_s=0.15)
        self._ciks: dict[str, int] | None = None

    def _cik(self, symbol: str) -> int:
        if self._ciks is None:
            data = self._http.get_json(TICKERS_URL)
            self._ciks = {row["ticker"].upper(): int(row["cik_str"]) for row in data.values()}
        cik = self._ciks.get(symbol.upper().replace(".", "-"))
        if cik is None:
            raise ProviderError(f"{symbol} is not an SEC registrant")
        return cik

    def fundamentals(self, ref: InstrumentRef, as_of: date | None = None) -> FundamentalsDTO:
        facts = self._http.get_json(FACTS_URL.format(cik=self._cik(ref.symbol)))
        return parse_company_facts(facts, as_of=as_of)


def _annual(facts: dict[str, Any], tags: list[str], as_of: date | None) -> list[tuple[int, float, date]]:
    gaap = facts.get("facts", {}).get("us-gaap", {})
    for tag in tags:
        units = gaap.get(tag, {}).get("units", {})
        values = units.get("USD") or units.get("USD/shares") or units.get("shares")
        if not values:
            continue
        by_year: dict[int, tuple[float, date]] = {}
        for v in values:
            if v.get("form") != "10-K" or v.get("fp") != "FY" or "fy" not in v:
                continue
            filed = date.fromisoformat(v["filed"])
            if as_of and filed > as_of:
                continue  # not yet public at as_of: excluded to prevent look-ahead bias
            end = date.fromisoformat(v["end"])
            start = date.fromisoformat(v["start"]) if v.get("start") else None
            if start and (end - start).days < 300:
                continue  # quarterly figure inside a 10-K
            year = end.year
            prev = by_year.get(year)
            if prev is None or filed >= prev[1]:
                by_year[year] = (float(v["val"]), filed)
        if by_year:
            return [(y, val, filed) for y, (val, filed) in sorted(by_year.items())]
    return []


def parse_company_facts(facts: dict[str, Any], as_of: date | None = None) -> FundamentalsDTO:
    series = {k: _annual(facts, tags, as_of) for k, tags in TAGS.items()}
    hist = defaultdict(list)
    for key in ("revenue", "eps", "gross_profit", "operating_income"):
        hist[key] = [{"year": y, "value": v} for y, v, _ in series[key][-6:]]
    ocf = {y: v for y, v, _ in series["ocf"]}
    capex = {y: v for y, v, _ in series["capex"]}
    fcf = [{"year": y, "value": ocf[y] - capex.get(y, 0.0)} for y in sorted(ocf)][-6:]

    def latest(key: str) -> float | None:
        return series[key][-1][1] if series[key] else None

    filed_dates = [f for s in series.values() for _, _, f in s[-1:]]
    last_filed = max(filed_dates) if filed_dates else None
    metrics = {
        "revenue_history": hist["revenue"], "eps_history": hist["eps"],
        "gross_profit_history": hist["gross_profit"], "operating_income_history": hist["operating_income"],
        "fcf_history": fcf, "net_income": latest("net_income"), "total_debt": latest("debt"),
        "cash": latest("cash"), "total_equity": latest("equity"), "current_assets": latest("current_assets"),
        "current_liabilities": latest("current_liabilities"), "interest_expense": latest("interest"),
        "shares_outstanding": latest("shares"),
    }
    period_end = None
    if series["revenue"]:
        period_end = date(series["revenue"][-1][0], 12, 31)
    return FundamentalsDTO(
        metrics={k: v for k, v in metrics.items() if v not in (None, [])},
        currency="USD", period_end=period_end,
        as_of=datetime.combine(last_filed, time(0), UTC) if last_filed else datetime.now(UTC),
        source="sec_edgar", profile={"name": facts.get("entityName"), "country": "US"},
    )
