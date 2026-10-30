import io
from datetime import UTC, datetime, timedelta

import pytest
import yaml
from fastapi.testclient import TestClient

from investiq.config import reset_settings_cache
from investiq.data.providers.rss import RssProvider
from investiq.models import AuditLog, BrokerageVerification, Instrument, OwnerHoldingEntry, PreferenceVersion
from investiq.research.cycle import run_cycle
from investiq.services.bootstrap import bootstrap
from investiq.services.preferences import set_pref
from tests.test_cycle import SMALL_UNIVERSE, fake_feed

TOKEN = "test-token-123456789"


@pytest.fixture()
def client(engine, session, tmp_path, monkeypatch):
    monkeypatch.setenv("INVESTIQ_API_TOKEN", TOKEN)
    reset_settings_cache()
    path = tmp_path / "u.yaml"
    path.write_text(yaml.safe_dump(SMALL_UNIVERSE), encoding="utf-8")
    monkeypatch.setattr(RssProvider, "fetch_feed", fake_feed)
    bootstrap(session, universe_path=path)
    session.commit()
    from investiq.api.app import create_app

    with TestClient(create_app(start_scheduler=False)) as c:
        c.headers["Authorization"] = f"Bearer {TOKEN}"
        yield c
    reset_settings_cache()


@pytest.fixture()
def researched(client, session):
    set_pref(session, "market_data", {"price_provider": "synthetic", "fundamentals_provider": "synthetic",
                                      "etf_holdings_provider": "synthetic", "fx_provider": "synthetic"}, actor="test")
    set_pref(session, "notifications", {"desktop_enabled": False}, actor="test")
    session.commit()
    now = datetime.now(UTC) - timedelta(hours=1)
    run_cycle(session, triggered_by="test", now=now, cycle_date=now.date())
    return client


def inst_id(session, symbol):
    return session.query(Instrument).filter_by(symbol=symbol).one().id


def test_token_required_and_health_is_public(client):
    raw = TestClient(client.app)
    assert raw.get("/api/health").json()["ok"] is True
    assert raw.get("/api/status").status_code == 401
    assert raw.get("/api/status", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert raw.get("/api/status", headers={"X-InvestIQ-Token": TOKEN}).status_code == 200


def test_untrusted_host_rejected(client):
    r = client.get("/api/health", headers={"Host": "evil.example.com"})
    assert r.status_code == 400


def test_security_headers_and_safe_errors(client, monkeypatch):
    r = client.get("/api/status")
    assert r.headers["X-Content-Type-Options"] == "nosniff" and r.headers["X-Frame-Options"] == "DENY"
    import investiq.api.routes.system as system

    monkeypatch.setattr(system, "health", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("secret detail sk-ant-xyz")))
    raw = TestClient(client.app, raise_server_exceptions=False)
    r = raw.get("/api/status", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 500 and "secret" not in r.text and "error_id" in r.json()


def test_status_reports_configuration_without_secrets(client):
    body = client.get("/api/status").json()
    assert body["database"]["ok"] and body["configured"]["api_token"] is True
    assert TOKEN not in str(body)
    assert any("Anthropic" in w for w in body["warnings"])


def test_research_endpoints_after_a_cycle(researched, session):
    c = researched
    cycles = c.get("/api/cycles").json()
    assert cycles and cycles[0]["status"].startswith("succeeded")
    detail = c.get(f"/api/cycles/{cycles[0]['id']}").json()
    assert len(detail["steps"]) == 20
    boards = c.get("/api/leaderboards").json()["boards"]
    assert "best_overall" in boards and boards["best_overall"][0]["grade"]
    recs = c.get("/api/recommendations").json()["items"]
    assert len(recs) == 9
    assert c.get("/api/recommendations?assessment=NOPE").status_code == 422
    reports = c.get("/api/reports").json()
    html = c.get(f"/api/reports/{reports[0]['id']}/html")
    assert "sandbox" in html.headers["Content-Security-Policy"] and "SYNTHETIC" in html.text
    dash = c.get("/api/dashboard").json()
    assert dash["last_cycle"] and dash["ai_budget"]["limit_cad"] == 5.0
    assert c.get("/api/paper").json()["notice"].startswith("Simulation only")
    assert c.get("/api/paper/BM_GLOBAL").json()["orders"]
    assert c.get("/api/market/overview").json()["usd_cad"]["note"].startswith("Daily reference")
    assert isinstance(c.get("/api/news?days=7").json(), list)


def test_instrument_detail_and_chart(researched, session):
    c = researched
    rid = inst_id(session, "RY")
    d = c.get(f"/api/instruments/{rid}").json()
    assert d["instrument"]["symbol"] == "RY" and d["score"]["grade"]
    assert d["brokerage"]["wealthsimple"]["status"] == "UNVERIFIED"
    assert d["price"]["cad"] is not None and d["price"]["source"] == "synthetic"
    ch = c.get(f"/api/instruments/{rid}/bars?range=1Y&indicators=sma50,sma200,rsi,macd,bb").json()
    assert len(ch["bars"]) > 200 and len(ch["indicators"]["sma200"]) == len(ch["bars"])
    assert ch["indicators"]["sma200"][0] is not None  # warm-up data: no blank left edge
    assert set(ch["indicators"]["macd"]) == {"macd", "signal", "histogram"}
    wk = c.get(f"/api/instruments/{rid}/bars?interval=1wk&range=3Y").json()
    assert 140 < len(wk["bars"]) < 170
    assert c.get(f"/api/instruments/{rid}/bars?interval=5min").status_code == 422  # synthetic has no intraday
    assert c.get(f"/api/instruments/{rid}/bars?indicators=evil").status_code == 422
    assert "1d" in ch["supported_intervals"]
    hist = c.get(f"/api/instruments/{rid}/history").json()
    assert hist["scores"] and hist["recommendations"]
    assert c.get("/api/instruments?q=roy").json()[0]["symbol"] == "RY"


def test_add_instrument_validates(client):
    r = client.post("/api/instruments", json={"symbol": "BN", "exchange": "TSX", "name": "Brookfield Corp",
                                              "asset_class": "equity", "security_type": "common_stock",
                                              "currency": "CAD", "country": "ca"})
    assert r.status_code == 201 and r.json()["country"] == "CA"
    assert client.post("/api/instruments", json={**r.json(), "exchange": "TSX"}).status_code in (409, 422)
    bad = client.post("/api/instruments", json={"symbol": "X;DROP", "exchange": "TSX", "name": "x",
                                                "asset_class": "equity", "security_type": "etf", "currency": "CAD"})
    assert bad.status_code == 422


def test_watchlists_notes_alerts_never_delete(client, session):
    rid = inst_id(session, "RY")
    w = client.get("/api/watchlists").json()[0]
    item = client.post(f"/api/watchlists/{w['id']}/items", json={"instrument_id": rid, "saved_from": "leaderboard"}).json()
    assert client.get("/api/watchlists").json()[0]["items"][0]["symbol"] == "RY"
    client.patch(f"/api/saved/{item['id']}", json={"archived": True})
    assert client.get("/api/watchlists").json()[0]["items"] == []
    assert client.get("/api/watchlists?include_archived=true").json()[0]["items"][0]["archived"] is True
    n1 = client.post("/api/notes", json={"instrument_id": rid, "kind": "thesis", "body": "Strong capital ratios"}).json()
    client.post("/api/notes", json={"instrument_id": rid, "kind": "thesis", "body": "Revised", "supersedes_id": n1["id"]})
    assert len(client.get(f"/api/notes?instrument_id={rid}").json()) == 2  # history kept
    a = client.post("/api/alerts", json={"instrument_id": rid, "kind": "price_above", "threshold": 150}).json()
    assert client.patch(f"/api/alerts/{a['id']}", json={"active": False}).json()["active"] is False
    assert client.delete(f"/api/alerts/{a['id']}").status_code == 405


def test_settings_versioned_and_budget_increase_needs_confirmation(client, session):
    r = client.put("/api/settings/research_schedule", json={"value": {"time_local": "17:30"}, "reason": "earlier"})
    assert r.status_code == 200 and r.json()["value"]["time_local"] == "17:30"
    assert client.put("/api/settings/research_schedule", json={"value": {"time_local": "25:99"}}).status_code == 422
    assert client.put("/api/settings/ai_budget", json={"value": {"monthly_limit_cad": 3}}).status_code == 200
    up = client.put("/api/settings/ai_budget", json={"value": {"monthly_limit_cad": 20}})
    assert up.status_code == 409 and "confirmation" in up.json()["detail"]
    ok = client.put("/api/settings/ai_budget", json={"value": {"monthly_limit_cad": 20}, "confirm_budget_increase": True})
    assert ok.status_code == 200
    hist = client.get("/api/settings/ai_budget/history").json()
    assert [h["value"]["monthly_limit_cad"] for h in hist][:2] == [20.0, 3.0]
    assert session.query(PreferenceVersion).count() >= 3
    assert client.put("/api/settings/nope", json={"value": {}}).status_code == 404
    s = client.get("/api/settings").json()
    assert "preferences" in s and "sk-" not in str(s)


def test_synthetic_refused_in_production(client, monkeypatch):
    monkeypatch.setenv("INVESTIQ_ENV", "production")
    reset_settings_cache()
    r = client.put("/api/settings/market_data", json={"value": {"price_provider": "synthetic"}})
    assert r.status_code == 422


def test_owner_holdings_append_only(researched, session):
    c = researched
    rid = inst_id(session, "RY")
    c.post("/api/holdings", json={"instrument_id": rid, "quantity": 10, "average_cost": 50, "cost_currency": "CAD"})
    c.post("/api/holdings", json={"instrument_id": rid, "quantity": 15, "average_cost": 55, "cost_currency": "CAD"})
    h = c.get("/api/holdings").json()
    assert len(h["holdings"]) == 1 and h["holdings"][0]["quantity"] == 15 and h["holdings"][0]["value_cad"] > 0
    assert session.query(OwnerHoldingEntry).count() == 2
    c.post("/api/holdings", json={"instrument_id": rid, "quantity": 0, "average_cost": 0, "cost_currency": "CAD"})
    assert c.get("/api/holdings").json()["holdings"] == []
    assert len(c.get("/api/holdings/history").json()) == 3
    assert c.post("/api/holdings", json={"instrument_id": rid, "quantity": 5, "average_cost": 0,
                                         "cost_currency": "CAD"}).status_code == 422
    d = c.get("/api/diversification").json()
    assert d["holdings_entered"] == 0
    w = c.post("/api/diversification/what-if", json={"instrument_id": rid, "amount_cad": 1000}).json()
    assert w["weight_pct"] == 100.0 and "Hypothetical" in w["note"]


def test_brokerage_manual_and_csv(client, session):
    rid = inst_id(session, "RY")
    r = client.post("/api/brokerage/verify", json={"instrument_id": rid, "brokerage": "wealthsimple", "status": "VERIFIED",
                                                   "ticker": "ry", "exchange": "tsx", "trading_currency": "CAD",
                                                   "tfsa_eligible": True, "evidence_note": "Seen in WS app"})
    assert r.status_code == 200 and r.json()["ticker"] == "RY"
    assert client.post("/api/brokerage/verify", json={"instrument_id": rid, "brokerage": "robinhood", "status": "VERIFIED",
                                                      "ticker": "RY", "exchange": "TSX",
                                                      "evidence_note": "x x x"}).status_code == 422
    csv_text = ("symbol,exchange,brokerage,status,ticker,trading_currency,tfsa_eligible,evidence_note,checked_on\n"
                "RY,TSX,questrade,VERIFIED,RY.TO,CAD,yes,Questrade web 2026-10-29,2026-10-29\n"
                "ZZZ,TSX,questrade,VERIFIED,ZZZ,CAD,yes,unknown symbol,2026-10-29\n"
                "SHOP,TSX,questrade,MAYBE,SHOP,CAD,yes,bad status,2026-10-29\n")
    res = client.post("/api/brokerage/import", files={"file": ("v.csv", io.BytesIO(csv_text.encode()), "text/csv")}).json()
    assert res["imported"] == 1 and [r["ok"] for r in res["rows"]] == [True, False, False]
    st = client.get(f"/api/brokerage/{rid}").json()
    assert st["current"]["wealthsimple"]["status"] == "VERIFIED" and st["current"]["questrade"]["status"] == "VERIFIED"
    assert session.query(BrokerageVerification).count() == 2
    assert session.query(AuditLog).filter(AuditLog.action == "brokerage.verified").count() == 2


def test_learning_endpoints(client):
    st = client.get("/api/strategies").json()
    assert st["production_id"] == st["frozen_id"]
    r = client.post(f"/api/strategies/{st['frozen_id']}/promote",
                    json={"backtest_run_id": 1, "reason": "because I said so", "confirm": False})
    assert r.status_code == 422
    assert client.post("/api/backtests", json={"strategy_version_id": st["frozen_id"], "start": "2024-01-01",
                                               "end": "2023-01-01", "split": "2023-06-01"}).status_code == 422
    assert client.get("/api/predictions/summary").json()["total_predictions"] == 0


def test_costs_and_notifications(client):
    c = client.get("/api/ai/costs").json()
    assert c["status"]["limit_cad"] == 5.0 and "never raised automatically" in c["policy"]
    r = client.post("/api/external-costs", json={"service": "FMP Starter", "category": "market_data", "amount": 22,
                                                 "currency": "USD", "period": "monthly"})
    assert r.status_code == 200
    assert client.get("/api/external-costs").json()[0]["service"] == "FMP Starter"
    assert client.post("/api/notifications/read", json={"ids": []}).json()["marked"] == 0


def test_export_download_blocks_traversal(client):
    assert client.get("/api/export/..%2F..%2Fetc%2Fpasswd").status_code == 404
    assert client.get("/api/export/investiq-export-nope.zip").status_code == 404
