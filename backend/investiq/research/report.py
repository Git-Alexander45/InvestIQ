"""Daily report and failure report generation (HTML email + plain text), saved permanently."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select
from sqlalchemy.orm import Session

from investiq.ai import budget as ai_budget
from investiq.data import repository as repo
from investiq.data.stats import price_stats
from investiq.models import DataQualityIssue, GradeChange, Instrument, Report, ResearchCycle, TfsaProfile
from investiq.news.service import latest_assessments
from investiq.paper.performance import comparison
from investiq.reports.pricing import format_price, price_block
from investiq.scoring.grades import GRADE_DISCLAIMER
from investiq.scoring.leaderboards import BOARD_TITLES

TEMPLATES = Path(__file__).resolve().parents[1] / "reports" / "templates"
_env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html", "j2"]))

MARKETS = [("Canada equity", "XIC", "TSX"), ("US equity (S&P 500, CAD)", "VFV", "TSX"),
           ("Developed ex-NA", "XEF", "TSX"), ("Emerging markets", "XEC", "TSX"), ("Canadian bonds", "ZAG", "TSX"),
           ("US long Treasuries", "TLT", "NASDAQ"), ("Gold", "GLD", "NYSEARCA"), ("Commodities", "PDBC", "NASDAQ")]
FINANCIAL = {"earnings", "corporate_action", "insider", "institutional", "technology", "supply_chain", "general"}
POLITICAL = {"elections_politics", "geopolitics", "tariffs_trade", "regulation"}
ECONOMIC = {"central_bank", "inflation", "employment", "economic_reports", "energy", "commodities"}
DISCLAIMER = ("InvestIQ is a private research tool. Assessments (BUY/WATCH/HOLD/SELL/AVOID) are research opinions, "
              "not instructions to trade, and no real trades are ever placed. " + GRADE_DISCLAIMER +
              " Past performance does not guarantee future results. Verify availability, tickers and tax treatment "
              "before investing.")


def _markets(session: Session, now: datetime) -> list[dict[str, Any]]:
    fx = repo.fx_table(session, now.date())
    out = []
    for label, sym, ex in MARKETS:
        inst = repo.instrument_by_symbol(session, sym, ex)
        if inst is None:
            continue
        bars = repo.daily_bars(session, inst.id, now, lookback_days=400)
        if len(bars) < 2:
            out.append({"label": label, "symbol": sym, "day_change": "—", "one_year": "—", "price_text": "no data"})
            continue
        st = price_stats(bars, now) or {}
        day = (bars[-1].close / bars[-2].close - 1) * 100
        pb = price_block(bars[-1].close, bars[-1].currency, bars[-1].ts.date().isoformat(), bars[-1].source,
                         bars[-1].data_status, fx)
        out.append({"label": label, "symbol": sym, "day_change": f"{day:+.2f}% (1d)",
                    "one_year": f"{st['return_1y_pct']:+.1f}% (1y)" if st.get("return_1y_pct") is not None else "—",
                    "price_text": format_price(pb), "text": f"{label} ({sym}): {day:+.2f}% on the day",
                    "source": bars[-1].source, "as_of": bars[-1].ts.date().isoformat()})
    return out


def _news(session: Session, now: datetime, cycle_id: int | None) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list] = {"financial": [], "political": [], "economic": []}
    pairs = latest_assessments(session, now - timedelta(days=1, hours=6))
    pairs.sort(key=lambda p: -(p[1].importance * p[1].confidence))
    for item, a in pairs:
        row = {"title": item.title, "url": item.url, "source": item.source_key,
               "published_at": item.published_at.isoformat(timespec="minutes") if item.published_at else None,
               "collected_at": item.collected_at.isoformat(timespec="minutes"), "impact": a.impact,
               "horizon": a.horizon, "confirmation": a.confirmation, "affected": a.affected_symbols[:6],
               "method": a.method.split(":")[0], "topic": a.topic}
        key = "political" if a.topic in POLITICAL else "economic" if a.topic in ECONOMIC else "financial"
        if len(groups[key]) < 10:
            groups[key].append(row)
    return groups


def chief_facts(session: Session, ctx) -> dict[str, Any]:
    news = _news(session, ctx.now, ctx.cycle.id)
    top = []
    for row in (ctx.results.get("boards") or {}).get("best_overall", [])[:12]:
        rec = ctx.results["recs"].get(row["instrument_id"])
        d = ctx.scored[row["instrument_id"]]
        top.append({"symbol": row["symbol"], "grade": d["score"].grade, "overall": d["score"].overall,
                    "assessment": rec.assessment if rec else row["assessment"], "why_not_now": rec.why_not_now if rec else None})
    flags = [f["message"] for f in (ctx.results.get("owner_diversification") or {}).get("flags", [])]
    return {"news": [n for g in news.values() for n in g], "markets": _markets(session, ctx.now), "top": top,
            "risk_flags": flags}


def _board_rows(session: Session, ctx, rows: list[dict[str, Any]], fx) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        d = ctx.scored[row["instrument_id"]]
        rec = ctx.results["recs"].get(row["instrument_id"])
        inst: Instrument = d["inst"]
        last = d["extras"]["last_bar"]
        pb = price_block(last.close, last.currency, last.ts.date().isoformat(), last.source, last.data_status, fx) if last else None
        out.append({"rank": row["rank"], "symbol": inst.symbol, "exchange": inst.exchange, "name": inst.name,
                    "grade": d["score"].grade, "overall": d["score"].overall, "confidence": d["score"].confidence,
                    "assessment": rec.assessment if rec else row["assessment"], "primary": bool(rec and rec.primary_eligible),
                    "why_not_now": rec.why_not_now if rec else None, "price_text": format_price(pb),
                    "method": row["method"]})
    return out


def _changes(session: Session, cycle: ResearchCycle) -> list[str]:
    out = []
    for gc, inst in session.execute(select(GradeChange, Instrument).join(Instrument, Instrument.id == GradeChange.instrument_id)
                                    .where(GradeChange.created_at >= cycle.started_at)).all():
        out.append(f"{inst.symbol}: grade {gc.old_grade} → {gc.new_grade} ({gc.old_overall:.1f} → {gc.new_overall:.1f}). {gc.reason}")
    return out[:30]


def build_daily(session: Session, ctx) -> Report:
    now, cycle = ctx.now, ctx.cycle
    fx = repo.fx_table(session, now.date())
    boards = {k: _board_rows(session, ctx, v, fx) for k, v in (ctx.results.get("boards") or {}).items()}
    div = ctx.results.get("owner_diversification")
    div_view = None
    if div:
        div_view = {"asset_classes": ", ".join(f"{k} {v:.1f}%" for k, v in div["by_asset_class"].items()),
                    "regions": ", ".join(f"{k} {v:.1f}%" for k, v in list(div["by_region"].items())[:6]),
                    "sectors": ", ".join(f"{k} {v:.1f}%" for k, v in list(div["by_sector"].items())[:6]),
                    "flags": [f["message"] for f in div["flags"]]}
    picks = ctx.results.get("tfsa_picks") or {}
    profile = session.execute(select(TfsaProfile).order_by(TfsaProfile.id.desc()).limit(1)).scalar_one_or_none()
    room = (f"{profile.contribution_room_cad:,.0f} CAD as of {profile.room_as_of} (entered by you)"
            if profile and profile.contribution_room_cad is not None else "not provided (InvestIQ never estimates it)")
    risks = list(ctx.degraded)
    rr = ctx.results.get("risk_review")
    if rr:
        risks += [c.text for c in rr.portfolio_risks][:5]
    dq = session.execute(select(DataQualityIssue).where(DataQualityIssue.cycle_id == cycle.id,
                                                        DataQualityIssue.severity != "info").limit(8)).scalars()
    risks += [f"Data quality: {i.message}" for i in dq]
    comp = comparison(session)
    paper_rows = []
    for _code, m in comp["portfolios"].items():
        paper_rows.append({"name": m["name"], "value": f"{m.get('value_cad', 0):,.0f}" if m.get("value_cad") else "—",
                           "total_return": f"{m['total_return_pct']:+.2f}%" if m.get("total_return_pct") is not None else "—",
                           "max_dd": f"{m['max_drawdown_pct']:.2f}%" if m.get("max_drawdown_pct") is not None else "—",
                           "dividends": f"{m.get('dividends_net_cad', 0):,.0f}",
                           "costs": f"{(m.get('trading_costs_cad') or {}).get('total', 0):,.0f}"})
    st = ai_budget.status(session)
    from sqlalchemy import func

    from investiq.models import AiRequest

    cycle_cost = session.execute(select(func.coalesce(func.sum(AiRequest.cost_cad), 0.0))
                                 .where(AiRequest.cycle_id == cycle.id)).scalar_one()
    providers = ctx.providers
    sources = []
    if providers is not None:
        used = {getattr(providers.prices, "name", None), getattr(providers.fundamentals, "name", None),
                getattr(providers.holdings, "name", None)} - {None}
        sources.append("Market data providers: " + (", ".join(sorted(used)) or "none configured"))
        if providers.unavailable:
            sources.append("Not configured: " + "; ".join(f"{k} ({v})" for k, v in providers.unavailable.items()))
    try:
        q = fx.get("USD", "CAD")
        fx_line = (f"USD/CAD {q.rate:.4f} — {q.source}, {q.as_of}. Daily reference rate, not a live trading rate.")
        sources.append(fx_line)
    except Exception:
        fx_line = "No USD/CAD reference rate available."
    sources.append("News: official feeds and licensed provider headlines; only headlines, links and short excerpts are stored.")
    sources.append("Price status labels: live / delayed / end_of_day / synthetic as reported by each source.")
    sources.append(f"Report generated {datetime.now(UTC).isoformat(timespec='seconds')} for research day {cycle.cycle_date}.")
    chief = ctx.results.get("chief")
    synthetic = bool(providers and providers.synthetic)
    data = {
        "subject": ("[SYNTHETIC TEST DATA] " if synthetic else "") + f"InvestIQ daily research — {cycle.cycle_date}",
        "synthetic": synthetic, "cycle_date": cycle.cycle_date.isoformat(), "status": "completed" +
        (" with warnings" if ctx.degraded else ""), "generated_at": datetime.now(UTC).isoformat(timespec="minutes"),
        "strategy": f"{ctx.production.name} v{ctx.production.version}" if ctx.production else "—",
        "degraded": ctx.degraded, "markets": _markets(session, now), "fx_line": fx_line,
        "news": _news(session, now, cycle.id), "boards": {k: boards.get(k, []) for k in BOARD_TITLES},
        "diversification": div_view,
        "tfsa": {"picks": [("Best overall TFSA candidate", picks.get("best_overall")),
                           ("Best growth TFSA candidate", picks.get("best_growth")),
                           ("Best dividend TFSA candidate", picks.get("best_dividend"))], "room": room},
        "risks": risks[:15], "watchlist": ctx.results.get("watchlist_updates", []), "paper": paper_rows,
        "changes": _changes(session, cycle),
        "ai": {"cycle_cost": f"{float(cycle_cost):.4f}", "month": st.month, "spent": f"{st.spent_cad:.4f}",
               "limit": f"{st.limit_cad:.2f}", "remaining": f"{st.remaining_cad:.4f}", "requests": st.requests,
               "paused": ctx.results.get("ai_paused")},
        "sources": sources, "disclaimer": DISCLAIMER,
        "chief": chief.model_dump() if chief is not None else None,
    }
    html = _env.get_template("daily.html.j2").render(**data)
    text = render_text(data)
    rep = Report(cycle_id=cycle.id, kind="daily", subject=data["subject"], html=html, text=text,
                 data=_json(data))
    session.add(rep)
    session.flush()
    return rep


def render_text(d: dict[str, Any]) -> str:
    lines = [d["subject"], "=" * len(d["subject"])]
    if d["synthetic"]:
        lines.append("!!! SYNTHETIC DEVELOPMENT DATA - NOT REAL MARKET INFORMATION !!!")
    if d["degraded"]:
        lines.append("Degraded run: " + "; ".join(d["degraded"]))
    lines.append("\n1. Global market overview")
    if d["chief"]:
        lines.append(d["chief"]["market_overview"])
    lines += [f"  {m['label']} ({m['symbol']}): {m['day_change']}, {m['one_year']}" for m in d["markets"]]
    lines.append("  " + d["fx_line"])
    for n, (title, key) in enumerate((("Major financial news", "financial"), ("Important political developments", "political"),
                                      ("Economic developments", "economic")), start=2):
        lines.append(f"\n{n}. {title}")
        lines += [f"  - {x['title']} [{x['impact']}, {x['confirmation']}] {x['url']}" for x in d["news"][key]] or ["  none"]
    for n, (title, key) in enumerate((("Top investment opportunities", "best_overall"), ("Best growth stocks", "aggressive_growth_stocks"),
                                      ("Best growth ETFs", "diversified_growth_etfs"), ("Best undervalued opportunities", "undervalued"),
                                      ("Best dividend opportunities", "dividend_growth"), ("International opportunities", "international")),
                                     start=5):
        lines.append(f"\n{n}. {title}")
        rows = d["boards"].get(key) or []
        lines += [f"  {r['rank']}. {r['symbol']}:{r['exchange']} {r['grade']} ({r['overall']:.1f}) {r['assessment']}"
                  + (f" — not now: {r['why_not_now']}" if r["why_not_now"] else "") + f"\n     {r['price_text']}" for r in rows] \
            or ["  No qualifying investments today. Waiting is a valid outcome."]
    lines.append("\n11. Diversification findings")
    lines += [f"  - {f}" for f in (d["diversification"] or {}).get("flags", [])] or ["  No holdings entered or no flags."]
    lines.append("\n12. Canadian TFSA opportunities")
    for label, p in d["tfsa"]["picks"]:
        lines.append(f"  {label}: " + (f"{p['symbol']} (TFSA score {p['tfsa_score']:.1f})" if p else "none qualified"))
    lines.append(f"  Contribution room: {d['tfsa']['room']}")
    lines.append("\n13. Important risks")
    lines += [f"  - {r}" for r in d["risks"]] or ["  none flagged"]
    lines.append("\n14. Saved watchlist updates")
    lines += [f"  {w['symbol']}: grade {w['grade']}, {w['assessment']}, {w['news_count']} news" for w in d["watchlist"]] or ["  none"]
    lines.append("\n15. Paper trading performance")
    lines += [f"  {p['name']}: {p['value']} CAD, {p['total_return']}, max DD {p['max_dd']}" for p in d["paper"]]
    lines.append("\n16. Changes from the previous report")
    lines += [f"  - {c}" for c in d["changes"]] or ["  none"]
    a = d["ai"]
    lines.append(f"\n17. AI spending: cycle {a['cycle_cost']} CAD; month {a['spent']}/{a['limit']} CAD"
                 + (f"; AI PAUSED: {a['paused']}" if a["paused"] else ""))
    lines.append("\n18. Sources and timestamps")
    lines += [f"  - {s}" for s in d["sources"]]
    lines.append("\n" + d["disclaimer"])
    return "\n".join(lines)


def _json(d: Any) -> Any:
    import json

    return json.loads(json.dumps(d, default=str))


def build_failure(session: Session, cycle: ResearchCycle) -> Report:
    from investiq.models import CycleStep

    steps = list(session.execute(select(CycleStep).where(CycleStep.cycle_id == cycle.id).order_by(CycleStep.step_no)).scalars())
    failed = [s for s in steps if s.status == "failed"]
    subject = f"InvestIQ research FAILED — {cycle.cycle_date}"
    text = "\n".join([subject, "", f"Error: {cycle.error}", "", "Steps:"] +
                     [f"  {s.step_no}. {s.name}: {s.status}" + (f" — {(s.error or '').splitlines()[0]}" if s.error else "")
                      for s in steps] +
                     ["", "No research results were reported for this cycle. InvestIQ will retry automatically "
                          "(up to 3 attempts per day) and you can run it manually from Settings."])
    from html import escape

    html = ("<html><body style='font-family:Segoe UI,Arial;background:#0b1118;color:#d7e0ea;padding:20px'>"
            f"<h2 style='color:#f07a7a'>{escape(subject)}</h2><pre style='white-space:pre-wrap'>{escape(text)}</pre></body></html>")
    rep = Report(cycle_id=cycle.id, kind="failure", subject=subject, html=html, text=text,
                 data={"failed_steps": [s.name for s in failed], "error": cycle.error})
    session.add(rep)
    session.flush()
    return rep
