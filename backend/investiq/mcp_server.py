"""Read-only MCP server exposing InvestIQ research to Claude (``investiq mcp``, stdio transport).

Read-only by construction:
* every tool is annotated readOnlyHint and only calls query functions;
* each call runs in a database transaction set to READ ONLY (PostgreSQL) or ``query_only``
  (SQLite), which is always rolled back, so even a bug cannot write;
* there are no tools that trade, edit holdings, change settings or spend AI budget.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from sqlalchemy import text
from sqlalchemy.orm import Session

from investiq import __version__
from investiq.db.session import get_session

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
DISCLAIMER = ("InvestIQ research output: research opinions, not instructions to trade. InvestIQ never places "
              "real trades. Prices are end-of-day or delayed unless stated.")

mcp = MCPServer(name="investiq", version=__version__,
                instructions="Read-only access to the owner's InvestIQ research: market overview, scores, "
                             "recommendations, news, paper portfolios and watchlists. Nothing here can trade, "
                             "change holdings or change settings. Always mention data dates and sources.")


@contextmanager
def read_only_session() -> Iterator[Session]:
    s = get_session()
    try:
        if s.bind.dialect.name == "postgresql":
            s.execute(text("SET TRANSACTION READ ONLY"))
        elif s.bind.dialect.name == "sqlite":
            s.execute(text("PRAGMA query_only = ON"))
        yield s
    finally:
        s.rollback()
        if s.bind.dialect.name == "sqlite":
            s.execute(text("PRAGMA query_only = OFF"))
            s.rollback()
        s.close()


def _run(fn: Callable[[Session], Any]) -> dict[str, Any]:
    with read_only_session() as s:
        return {"data": fn(s), "generated_at": datetime.now(UTC).isoformat(), "disclaimer": DISCLAIMER}


@mcp.tool(annotations=READ_ONLY)
def get_market_overview() -> dict[str, Any]:
    """Major market proxies (Canada, US, international, emerging, bonds, gold, commodities) with daily and
    one-year moves, plus the latest USD/CAD reference rate."""
    from investiq.api.routes.research import market_overview

    return _run(market_overview)


@mcp.tool(annotations=READ_ONLY)
def search_investments(query: str, limit: int = 20) -> dict[str, Any]:
    """Search the research universe by ticker or name. Returns latest grade and score for each match."""
    from investiq.api.routes.instruments import search

    return _run(lambda s: search(q=query[:64], asset_class=None, security_type=None, limit=max(1, min(limit, 100)), s=s))


def _analysis(symbol: str, exchange: str | None, want_fund: bool | None) -> Callable[[Session], Any]:
    from investiq.api.routes.instruments import detail, history
    from investiq.data import repository as repo

    def fn(s: Session) -> Any:
        inst = repo.instrument_by_symbol(s, symbol, exchange)
        if inst is None:
            return {"error": f"{symbol} is not in the InvestIQ universe"}
        is_fund = inst.security_type in ("etf", "mutual_fund")
        if want_fund is not None and is_fund != want_fund:
            return {"error": f"{symbol} is {'a fund' if is_fund else 'not a fund'}; use the other analysis tool"}
        d = detail(inst.id, s)
        d["history"] = {k: v[:10] for k, v in history(inst.id, limit=10, s=s).items()}
        return d

    return fn


@mcp.tool(annotations=READ_ONLY)
def get_stock_analysis(symbol: str, exchange: str | None = None) -> dict[str, Any]:
    """Latest scores (with category evidence), assessment, AI analyses, fundamentals, brokerage
    availability and recent history for a stock. Exchange examples: TSX, NASDAQ, NYSE."""
    return _run(_analysis(symbol, exchange, want_fund=False))


@mcp.tool(annotations=READ_ONLY)
def get_etf_analysis(symbol: str, exchange: str | None = None) -> dict[str, Any]:
    """Latest analysis of an ETF or fund, including MER, look-through top holdings, country exposure,
    scores and brokerage availability."""
    return _run(_analysis(symbol, exchange, want_fund=True))


@mcp.tool(annotations=READ_ONLY)
def get_latest_news(days: int = 2, topic: str | None = None, symbol: str | None = None) -> dict[str, Any]:
    """Recent collected news with InvestIQ's assessment (impact, confirmation, affected securities)."""
    from investiq.api.routes.news import news

    return _run(lambda s: news(days=max(1, min(days, 30)), topic=topic, symbol=symbol, official_only=False,
                               min_importance=0.0, s=s)[:100])


@mcp.tool(annotations=READ_ONLY)
def get_portfolio_overview() -> dict[str, Any]:
    """The owner's manually entered holdings with current values in CAD. Never assumed or inferred."""
    from investiq.api.routes.holdings import holdings

    return _run(holdings)


@mcp.tool(annotations=READ_ONLY)
def get_diversification_report() -> dict[str, Any]:
    """Diversification of the owner's entered holdings: asset class, sector, country, currency, ETF
    look-through overlap, concentration and correlation flags."""
    from investiq.services import portfolio_view

    return _run(lambda s: portfolio_view.owner_report(s, datetime.now(UTC)))


@mcp.tool(annotations=READ_ONLY)
def get_daily_recommendations(assessment: str | None = None) -> dict[str, Any]:
    """The latest completed research cycle's assessments (BUY/WATCH/HOLD/SELL/AVOID) and leaderboards."""
    from investiq.api.routes.research import leaderboards, recommendations

    if assessment and assessment.upper() not in ("BUY", "WATCH", "HOLD", "SELL", "AVOID"):
        return {"error": "assessment must be BUY, WATCH, HOLD, SELL or AVOID"}

    def fn(s: Session) -> Any:
        recs = recommendations(assessment=assessment.upper() if assessment else None, cycle_id=None, s=s)
        recs["items"] = recs["items"][:60]
        return {"recommendations": recs, "leaderboards": leaderboards(None, s)["boards"]}

    return _run(fn)


@mcp.tool(annotations=READ_ONLY)
def get_paper_trading_results() -> dict[str, Any]:
    """Simulated portfolios A-D versus benchmarks: value, returns, drawdown, costs (virtual money only)."""
    from investiq.paper import performance

    def fn(s: Session) -> Any:
        c = performance.comparison(s)
        c.pop("curves", None)
        return c

    return _run(fn)


@mcp.tool(annotations=READ_ONLY)
def get_watchlist() -> dict[str, Any]:
    """The owner's watchlists with each saved investment's latest grade and score."""
    from investiq.api.routes.watchlists import watchlists

    return _run(lambda s: watchlists(include_archived=False, s=s))


@mcp.tool(annotations=READ_ONLY)
def get_ai_performance() -> dict[str, Any]:
    """How past recommendations performed at 7/30/90/180/365-day checkpoints (hit rates and excess return
    vs benchmark, AI-reviewed vs quant-only), plus this month's AI spending against the budget."""
    from investiq.ai import budget
    from investiq.learning import predictions

    return _run(lambda s: {"predictions": predictions.summary(s), "ai_budget": budget.status(s).as_dict()})


TOOL_NAMES = ("get_market_overview", "search_investments", "get_stock_analysis", "get_etf_analysis", "get_latest_news",
              "get_portfolio_overview", "get_diversification_report", "get_daily_recommendations",
              "get_paper_trading_results", "get_watchlist", "get_ai_performance")


def main() -> None:
    mcp.run("stdio")

