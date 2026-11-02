import asyncio
from datetime import UTC, datetime, timedelta

import pytest
import yaml
from sqlalchemy import text

from investiq import mcp_server
from investiq.data.providers.rss import RssProvider
from investiq.research.cycle import run_cycle
from investiq.services.bootstrap import bootstrap
from investiq.services.preferences import set_pref
from tests.test_cycle import SMALL_UNIVERSE, fake_feed


def test_exactly_the_specified_read_only_tools():
    tools = asyncio.run(mcp_server.mcp.list_tools())
    assert sorted(t.name for t in tools) == sorted(mcp_server.TOOL_NAMES)
    assert all(t.annotations and t.annotations.read_only_hint and not t.annotations.destructive_hint for t in tools)
    forbidden = ("trade", "order", "buy", "sell", "set_", "update", "delete", "create", "add_")
    assert not any(t.name.startswith(forbidden) for t in tools)


def test_read_only_session_rejects_writes(session):
    bootstrap(session)
    session.commit()
    with mcp_server.read_only_session() as s, pytest.raises(Exception):  # noqa: B017 - driver-specific error type
        s.execute(text("UPDATE instruments SET name = 'x'"))
    assert session.execute(text("SELECT count(*) FROM instruments WHERE name = 'x'")).scalar() == 0


def test_tools_return_research_after_a_cycle(session, tmp_path, monkeypatch):
    path = tmp_path / "u.yaml"
    path.write_text(yaml.safe_dump(SMALL_UNIVERSE), encoding="utf-8")
    monkeypatch.setattr(RssProvider, "fetch_feed", fake_feed)
    bootstrap(session, universe_path=path)
    set_pref(session, "market_data", {"price_provider": "synthetic", "fundamentals_provider": "synthetic",
                                      "etf_holdings_provider": "synthetic", "fx_provider": "synthetic"}, actor="test")
    set_pref(session, "notifications", {"desktop_enabled": False}, actor="test")
    session.commit()
    now = datetime.now(UTC) - timedelta(hours=1)
    run_cycle(session, triggered_by="test", now=now, cycle_date=now.date())

    def call(name, args=None):
        return asyncio.run(mcp_server.mcp.call_tool(name, args or {}))

    for name in mcp_server.TOOL_NAMES:
        args = {"query": "RY"} if name == "search_investments" else {}
        if name == "get_stock_analysis":
            args = {"symbol": "RY", "exchange": "TSX"}
        if name == "get_etf_analysis":
            args = {"symbol": "XEQT"}
        result = call(name, args)
        assert not getattr(result, "is_error", False), (name, result)
    stock = mcp_server.get_stock_analysis("RY", "TSX")
    assert stock["data"]["instrument"]["symbol"] == "RY" and "never places real trades" in stock["disclaimer"]
    assert "error" in mcp_server.get_etf_analysis("RY", "TSX")["data"]
    assert "error" in mcp_server.get_stock_analysis("NOPE")["data"]
    recs = mcp_server.get_daily_recommendations()
    assert recs["data"]["recommendations"]["items"]
