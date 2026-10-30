import json
from datetime import date

import httpx
import pytest

from investiq.data.providers.bank_of_canada import BankOfCanadaFx
from investiq.data.providers.base import InstrumentRef, ProviderError, ProviderNotConfigured
from investiq.data.providers.fmp import FmpProvider
from investiq.data.providers.http import HttpClient
from investiq.data.providers.rss import parse_feed
from investiq.data.providers.sec_edgar import parse_company_facts
from investiq.data.providers.symbols import suffixed
from investiq.data.providers.twelvedata import TwelveDataProvider


def client(handler):
    return HttpClient(transport=httpx.MockTransport(handler), sleep=lambda s: None)


def test_symbol_suffixes():
    assert suffixed(InstrumentRef("RY", "TSX", "CAD"), "fmp") == "RY.TO"
    assert suffixed(InstrumentRef("BRK.B", "NYSE", "USD"), "fmp") == "BRK-B"
    assert suffixed(InstrumentRef("X", "TSX", "CAD", {"fmp": "CUSTOM"}), "fmp") == "CUSTOM"


def test_http_retries_then_fails():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(503)

    with pytest.raises(ProviderError):
        client(handler).get("https://example.test/x")
    assert len(calls) == 3


def test_http_no_retry_on_client_error():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(403)

    with pytest.raises(ProviderError, match="403"):
        client(handler).get("https://example.test/x")
    assert len(calls) == 1


def test_fmp_requires_key():
    with pytest.raises(ProviderNotConfigured):
        FmpProvider(None)


def test_fmp_bars_and_quote_parsing():
    def handler(req):
        assert req.url.params["apikey"] == "k"
        if req.url.path.endswith("historical-price-eod/full"):
            assert req.url.params["symbol"] == "RY.TO"
            return httpx.Response(200, json=[
                {"date": "2026-01-03", "open": 2, "high": 3, "low": 1, "close": 2.5, "volume": 10},
                {"date": "2026-01-02", "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 5},
                {"date": "bad"},
            ])
        if req.url.path.endswith("quote"):
            return httpx.Response(200, json=[{"symbol": "RY.TO", "price": 150.1, "timestamp": 1767312000}])
        return httpx.Response(404)

    p = FmpProvider("k", http=client(handler))
    ref = InstrumentRef("RY", "TSX", "CAD")
    res = p.bars(ref, "1d", date(2026, 1, 1), date(2026, 1, 5))
    assert [b.close for b in res.bars] == [1.5, 2.5]
    assert res.data_status == "end_of_day" and res.source == "fmp"
    q = p.quote(ref)
    assert q.price == 150.1 and q.data_status == "delayed"  # never labelled live unless configured


def test_fmp_error_payload_raises():
    p = FmpProvider("k", http=client(lambda r: httpx.Response(200, json={"Error Message": "Invalid API KEY"})))
    with pytest.raises(ProviderError, match="Invalid"):
        p.quote(InstrumentRef("AAPL", "NASDAQ", "USD"))


def test_fmp_fundamentals_mapping():
    payloads = {
        "profile": [{"companyName": "X", "sector": "Technology", "country": "US", "marketCap": 1000, "beta": 1.2,
                     "currency": "USD"}],
        "income-statement": [
            {"date": "2025-12-31", "fiscalYear": "2025", "revenue": 120, "epsDiluted": 1.2, "grossProfit": 60,
             "operatingIncome": 30, "netIncome": 20, "ebitda": 40, "interestExpense": 2, "filingDate": "2026-02-10",
             "reportedCurrency": "USD"},
            {"date": "2024-12-31", "fiscalYear": "2024", "revenue": 100, "epsDiluted": 1.0, "grossProfit": 50,
             "operatingIncome": 25, "filingDate": "2025-02-10"}],
        "balance-sheet-statement": [{"date": "2025-12-31", "totalDebt": 50, "cashAndCashEquivalents": 10,
                                     "totalStockholdersEquity": 100, "totalCurrentAssets": 60,
                                     "totalCurrentLiabilities": 30}],
        "cash-flow-statement": [{"date": "2025-12-31", "fiscalYear": "2025", "freeCashFlow": 25}],
        "ratios-ttm": [{"priceToEarningsRatioTTM": 30, "dividendYieldTTM": 0.012}],
        "key-metrics-ttm": [{"returnOnInvestedCapitalTTM": 0.18}],
    }

    def handler(req):
        key = req.url.path.split("/stable/")[1]
        return httpx.Response(200, json=payloads.get(key, []))

    dto = FmpProvider("k", http=client(handler)).fundamentals(InstrumentRef("X", "NASDAQ", "USD"))
    m = dto.metrics
    assert [r["value"] for r in m["revenue_history"]] == [100, 120]
    assert m["roic_pct"] == pytest.approx(18)
    assert m["dividend_yield_pct"] == pytest.approx(1.2)
    assert dto.as_of.date() == date(2026, 2, 10)  # point-in-time: filing date
    assert dto.profile["sector"] == "Technology"


def test_twelvedata_parsing_and_error():
    def handler(req):
        if req.url.params.get("symbol") == "BAD":
            return httpx.Response(200, json={"status": "error", "message": "symbol not found"})
        return httpx.Response(200, json={"meta": {"currency": "CAD"}, "values": [
            {"datetime": "2026-01-02", "open": "1", "high": "2", "low": "0.5", "close": "1.5", "volume": "100"}]})

    p = TwelveDataProvider("k", http=client(handler))
    res = p.bars(InstrumentRef("RY", "TSX", "CAD"), "1d", date(2026, 1, 1), date(2026, 1, 3))
    assert res.bars[0].close == 1.5 and res.currency == "CAD"
    with pytest.raises(ProviderError):
        p.bars(InstrumentRef("BAD", "TSX", "CAD"), "1d", date(2026, 1, 1), date(2026, 1, 3))


def test_bank_of_canada_parsing():
    def handler(req):
        assert "FXUSDCAD,FXEURCAD" in req.url.path
        return httpx.Response(200, json={"observations": [
            {"d": "2026-01-02", "FXUSDCAD": {"v": "1.3700"}, "FXEURCAD": {"v": "1.5000"}},
            {"d": "2026-01-05", "FXUSDCAD": {"v": "1.3650"}}]})

    rates = BankOfCanadaFx(http=client(handler)).rates(["USD", "EUR", "XXX"], date(2026, 1, 1), date(2026, 1, 5))
    assert len(rates) == 3
    assert rates[0].rate_type == "daily_reference" and "Bank of Canada" in rates[0].source


def test_rss_parsing_rss_and_atom_and_xxe_safe():
    rss = """<?xml version="1.0"?><rss><channel>
      <item><title>Bank of Canada maintains policy rate</title><link>https://x.test/a</link>
        <description>&lt;p&gt;The Bank held its &lt;b&gt;policy rate&lt;/b&gt; at 2.25%.&lt;/p&gt;</description>
        <pubDate>Wed, 29 Oct 2026 13:45:00 GMT</pubDate></item>
      <item><title>No link</title></item></channel></rss>"""
    items = parse_feed(rss, "boc", "central_bank", True)
    assert len(items) == 1
    assert items[0].summary == "The Bank held its policy rate at 2.25%."
    assert items[0].published_at.year == 2026
    atom = """<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>T</title><link href="https://x.test/b"/>
      <updated>2026-10-29T10:00:00Z</updated><summary>S</summary></entry></feed>"""
    assert parse_feed(atom, "a", None, False)[0].url == "https://x.test/b"
    evil = """<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]><rss><channel>
      <item><title>&x;</title><link>https://x.test</link></item></channel></rss>"""
    from defusedxml.common import DTDForbidden, EntitiesForbidden, ExternalReferenceForbidden

    with pytest.raises((DTDForbidden, EntitiesForbidden, ExternalReferenceForbidden)):
        parse_feed(evil, "e", None, False)


def test_rss_summary_is_truncated():
    long = "word " * 400
    rss = f"<rss><channel><item><title>T</title><link>https://x.test/l</link><description>{long}</description></item></channel></rss>"
    assert len(parse_feed(rss, "k", None, False)[0].summary) <= 400


def test_sec_company_facts_point_in_time():
    def fact(val, fy, end, filed, start=None):
        return {"val": val, "fy": fy, "fp": "FY", "form": "10-K", "end": end, "filed": filed,
                "start": start or f"{int(end[:4])}-01-01"}

    facts = {"entityName": "Test Corp", "facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [fact(100, 2023, "2023-12-31", "2024-02-15"),
                                       fact(120, 2024, "2024-12-31", "2025-02-14"),
                                       fact(30, 2024, "2024-12-31", "2025-02-14", start="2024-10-01")]}},
        "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [fact(40, 2024, "2024-12-31", "2025-02-14")]}},
        "PaymentsToAcquirePropertyPlantAndEquipment": {"units": {"USD": [fact(10, 2024, "2024-12-31", "2025-02-14")]}},
    }}}
    dto = parse_company_facts(facts)
    assert [r["value"] for r in dto.metrics["revenue_history"]] == [100, 120]  # quarterly value ignored
    assert dto.metrics["fcf_history"] == [{"year": 2024, "value": 30}]
    early = parse_company_facts(facts, as_of=date(2024, 6, 1))
    assert [r["value"] for r in early.metrics["revenue_history"]] == [100]  # 2024 10-K not yet filed
    assert json.dumps(early.metrics)
